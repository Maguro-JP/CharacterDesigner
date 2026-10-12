"""質感: 絵の一部（身体・服・持ち物）をレイヤーに切り出し、透明感・金属感などの質感を掛ける。

  python3 tools/gen/materials.py cut <絵> <出力.png> (--region skin | --color "#7ab8ff" [--tol 60])
  python3 tools/gen/materials.py apply <レイヤー.png> <出力.png> --kind slime [--strength 0.6]

描く板（app/web の「描く」）で使う前提で、入力も出力も透明な地のレイヤー（RGBA）。
切り出しは2通り: 部位分け（顔・腕・脚・髪・服、tools/gen/edit.py の parts）と、色で選ぶ（スポイトの色に近い所）。
スライムのように肌の色が人と違う絵は部位分けが肌と取らないことがあるので、色で選ぶ方を使う。

質感（kind）。どれも strength 0〜1 で効き方を変える。0 は何もしない:
- slime（透明感）: 内側ほど透かし、縁は残す（縁が濃く見える透明な物の見え方）。縁の光と、光の当たる側の照り返しを足す
- metal（金属感）: 明暗の段差を強め、映り込みの帯を入れ、色を抜いて冷たく寄せる。強い照り返しを足す
- heavy（重厚感）: 暗く重く、明暗の差を上げ、縁の内側に影（物の厚み）を入れる
- gem（宝石感）: 彩度を上げ、面の分かれ（ファセット）の明暗と、内側の透けと、きらめきの点を足す
- inorganic（無機質感）: 細かい描き込みをならし、色を抜いて平らにする（陶器・樹脂・機械の面）
- dirt（汚れ）: 下と縁に溜まる汚れのむらを重ねる
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))

KINDS = ("slime", "metal", "heavy", "gem", "inorganic", "dirt")


# ---------- 切り出し ----------

def mask_parts(src: str, region: str) -> np.ndarray:
    """部位分けで選ぶ。region は edit.REGIONS の名前（skin・hair・clothes など）か、部位の名前"""
    import edit
    if region == "person":
        return mask_person(src, grow=0)
    lab = np.asarray(edit.parts(src))
    ids = edit.REGIONS.get(region) or ([edit.LABELS[region]] if region in edit.LABELS else None)
    if ids is None:
        raise ValueError(f"部位「{region}」は無い（{', '.join(list(edit.REGIONS) + list(edit.LABELS))}）")
    return np.isin(lab, ids)


def mask_person(src: str, grow: int = 6) -> np.ndarray:
    """人物の範囲（部位分けで背景でない所）。部位の名前は読み違えることがあっても、人物と背景の境目は合う。
    水色の肌のスライム娘で、肌は 8861 画素しか取れず脚を「ズボン」と読んだが、人物の外形は正しかった"""
    import edit
    from scipy.ndimage import binary_dilation
    m = np.asarray(edit.parts(src)) > 0
    # iterations=0 は「変わらなくなるまで広げる」の意味になり、絵全体を選んだ。0 のときは広げない
    return binary_dilation(m, iterations=grow) if grow > 0 else m


def mask_color(img: Image.Image, color: str, tol: float = 60.0, at: tuple[int, int] | None = None,
               within: np.ndarray | None = None) -> np.ndarray:
    """スポイトの色に近い所を選ぶ（ペイントソフトの自動選択）。色の差は明るさより色みを重く見る。tol は 0〜255 の目安。
    at（x, y）を渡すと、その点とつながった範囲だけ。渡さなければ一番大きいつながり。
    within を渡すと、その範囲の中だけで選ぶ（人物の範囲を渡すと、背景に漏れずに幅を広く取れる）。
    色だけで選ぶと、背景の似た色（白っぽい水色の地）まで斑に拾った"""
    rgb = np.asarray(img.convert("RGB")).astype(float)
    m = np.zeros(rgb.shape[:2], bool)
    # 色はカンマで区切って複数渡せる（同じ物の光の当たる所と陰の所、顔と体のように色が離れているとき）
    for col in [c.strip() for c in color.split(",") if c.strip()]:
        c = np.array([int(col[i:i + 2], 16) for i in (1, 3, 5)], float)
        d = rgb - c
        # 明るさの差は半分に数える（同じ色の陰と光を同じ物として選ぶため）
        luma = d @ np.array([0.299, 0.587, 0.114])
        chroma = d - luma[..., None]
        m |= np.sqrt((luma * 0.5) ** 2 + (chroma ** 2).sum(-1)) < tol
    if within is not None:
        m &= within
    # 小さな点は落とし、穴は埋める（選んだ所を1つの面にする）
    from scipy.ndimage import binary_closing, binary_opening, label
    m = binary_closing(binary_opening(m, iterations=1), iterations=2)
    lab, n = label(m)
    if n == 0:
        return m
    if at is not None and 0 <= at[1] < m.shape[0] and 0 <= at[0] < m.shape[1] and lab[at[1], at[0]]:
        return lab == lab[at[1], at[0]]
    # 点を渡さないときは、小さな破片だけを落として残りを全部選ぶ（襟で切れた顔と体のように、同じ色の面が分かれていることがある）
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep = np.nonzero(sizes >= max(200, sizes.max() * 0.01))[0]
    return np.isin(lab, keep)


def cutout(img: Image.Image, mask: np.ndarray, feather: float = 1.0) -> Image.Image:
    """選んだ所だけを残したレイヤー（RGBA）。縁は少しぼかしてなじませる"""
    a = Image.fromarray((mask * 255).astype("uint8"))
    if feather > 0:
        a = a.filter(ImageFilter.GaussianBlur(feather))
    out = img.convert("RGBA").copy()
    base_a = np.asarray(out.getchannel("A")).astype(float) / 255
    out.putalpha(Image.fromarray((np.asarray(a).astype(float) * base_a).astype("uint8")))
    return out


# ---------- 質感 ----------

def _inside(alpha: np.ndarray) -> np.ndarray:
    """縁からの近さ（縁 0 〜 内側 1）。縁の太さは形の大きさに合わせる"""
    from scipy.ndimage import distance_transform_edt
    m = alpha > 0.5
    if not m.any():
        return np.zeros_like(alpha)
    d = distance_transform_edt(m)
    scale = max(np.percentile(d[m], 90), 1.0)
    return np.clip(d / scale, 0, 1)


def _blur(a: np.ndarray, r: float) -> np.ndarray:
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype("uint8"))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(float(r)))).astype(float) / 255


def _lit_side(alpha: np.ndarray, r: float, dx: int = -1, dy: int = -1) -> np.ndarray:
    """光の当たる縁（既定は左上から光）。形を光の向きへずらした差で取る"""
    m = (alpha > 0.5).astype(float)
    shift = np.roll(np.roll(m, int(r) * -dy, axis=0), int(r) * -dx, axis=1)
    return np.clip(m - shift, 0, 1)


def _noise(h: int, w: int, seed: int, octaves: int = 4) -> np.ndarray:
    """むら（大きさの違うぼかした乱数を重ねる）。0〜1"""
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w))
    for k in range(octaves):
        r = 2 ** (octaves - k + 1)
        acc += _blur(rng.random((h, w)), r) * (0.5 ** k)
    acc -= acc.min()
    return acc / max(acc.max(), 1e-6)


def apply(layer: Image.Image, kind: str, strength: float = 0.6, seed: int = 0) -> Image.Image:
    if kind not in KINDS:
        raise ValueError(f"質感「{kind}」は無い（{', '.join(KINDS)}）")
    s = float(np.clip(strength, 0, 1))
    arr = np.asarray(layer.convert("RGBA")).astype(float) / 255
    rgb, alpha = arr[..., :3], arr[..., 3]
    if s == 0 or not (alpha > 0).any():
        return layer.convert("RGBA")
    h, w = alpha.shape
    inside = _inside(alpha)
    luma = rgb @ np.array([0.299, 0.587, 0.114])
    # 形の大きさに合わせた縁の太さ（画素）。大きな面を選んだときに効きすぎないよう上限を付ける
    size = float(np.clip(np.sqrt((alpha > 0.5).sum()) / 30, 2.0, 10.0))

    if kind == "slime":
        # 内側ほど透かす（縁は残す）。透明な物は縁で光の通る道が長く、縁ほど濃く見える
        a = alpha * (1 - s * 0.75 * inside ** 0.7)
        # 透けても体の色が付いて見えるよう、内側の色みを濃くする（色ガラス）。薄い地の上で白く抜けて見えた
        mean = rgb.mean(-1, keepdims=True)
        rich = np.clip(mean + (rgb - mean) * 1.6, 0, 1) * 0.85
        rgb = rgb * (1 - s * inside[..., None]) + rich * s * inside[..., None]
        rim = _blur(np.clip(1 - inside, 0, 1) * (alpha > 0.5), size * 0.4)
        lit = _blur(_lit_side(alpha, size * 0.8), size * 0.6)
        rgb = np.clip(rgb + s * (0.25 * rim[..., None] + 0.6 * lit[..., None]), 0, 1)
        a = np.clip(a + s * 0.5 * lit, 0, 1) * (alpha > 0)
        alpha = np.maximum(a, alpha * (1 - s * 0.75))
    elif kind == "metal":
        # 明暗の段差を強め、映り込みの帯（明るさを波で折り返す）を入れ、色を抜いて冷たくする
        band = 0.5 + 0.5 * np.sin(luma * np.pi * 3 + inside * 2.0)
        L = np.clip((luma - 0.5) * (1 + 1.5 * s) + 0.5, 0, 1)
        L = L * (1 - 0.5 * s) + band * 0.5 * s
        gray = np.stack([L * 0.95, L * 0.98, L * 1.05], -1)
        rgb = rgb * (1 - 0.75 * s) + gray * 0.75 * s
        spec = _blur(_lit_side(alpha, size * 0.5), size * 0.3) + np.clip((luma - 0.8) * 5, 0, 1)
        rgb = np.clip(rgb + s * 0.6 * spec[..., None], 0, 1)
    elif kind == "heavy":
        # 暗く・明暗の差を上げ・縁の内側に厚みの影
        rgb = np.clip((rgb - 0.5) * (1 + 0.6 * s) + 0.5 - 0.15 * s, 0, 1)
        ao = np.clip(1 - inside * 3, 0, 1) * (alpha > 0.5)
        rgb = rgb * (1 - 0.45 * s * _blur(ao, size * 0.5))[..., None]
    elif kind == "gem":
        # 面の分かれ: 粗い升目ごとに明るさを変える。彩度を上げ、内側を少し透かし、きらめきの点を足す
        rng = np.random.default_rng(seed)
        # 面の分かれ: 種の点に一番近い所を同じ面にする（ボロノイ）。升目にすると四角いモザイクに見えた
        from scipy.spatial import cKDTree
        ys0, xs0 = np.nonzero(alpha > 0.5)
        n_seeds = int(np.clip(len(ys0) / (size * size * 40), 8, 400))
        pick = rng.choice(len(ys0), size=min(n_seeds, len(ys0)), replace=False)
        tree = cKDTree(np.c_[ys0[pick], xs0[pick]])
        yy, xx = np.mgrid[0:h, 0:w]
        _, idx = tree.query(np.c_[yy.ravel(), xx.ravel()])
        f = rng.random(len(pick))[idx].reshape(h, w)
        mean = rgb.mean(-1, keepdims=True)
        rgb = np.clip(mean + (rgb - mean) * (1 + 1.2 * s), 0, 1)
        rgb = np.clip(rgb * (1 + s * 0.35 * (f[..., None] - 0.5)), 0, 1)
        alpha = alpha * (1 - s * 0.3 * inside)
        bright = (alpha > 0.5) & (luma > np.percentile(luma[alpha > 0.5], 97) if (alpha > 0.5).any() else False)
        stars = np.zeros((h, w))
        ys, xs = np.nonzero(bright)
        for k in rng.choice(len(ys), size=min(len(ys), 12), replace=False) if len(ys) else []:
            y, x = ys[k], xs[k]
            L = int(size * 2)
            stars[max(0, y - L):y + L, x] = 1
            stars[y, max(0, x - L):x + L] = 1
        rgb = np.clip(rgb + s * _blur(stars, 0.8)[..., None] * 1.5, 0, 1)
    elif kind == "inorganic":
        # 細かい描き込みをならす（明るさの大きな変化は残す）。色を抜き、明暗を平らにする
        sm = np.stack([_blur(rgb[..., i], min(size * 0.3, 3.0) * s + 0.1) for i in range(3)], -1)
        rgb = rgb * (1 - s) + sm * s
        mean = rgb.mean(-1, keepdims=True)
        rgb = mean + (rgb - mean) * (1 - 0.6 * s)
        rgb = (rgb - 0.5) * (1 - 0.3 * s) + 0.5
    elif kind == "dirt":
        # 下ほど・縁ほど溜まる汚れ。むらを掛けて焦げ茶へ寄せる
        n = _noise(h, w, seed)
        ys = np.linspace(0, 1, h)[:, None]
        where = np.clip(0.4 * ys + 0.6 * (1 - inside) + 0.5 * (n - 0.5), 0, 1)
        grime = np.array([0.30, 0.22, 0.14])
        amt = (s * 0.8 * where * (n > 0.35))[..., None]
        rgb = rgb * (1 - amt) + grime * amt

    out = np.dstack([np.clip(rgb, 0, 1), np.clip(alpha, 0, 1)])
    return Image.fromarray((out * 255).astype("uint8"), "RGBA")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut")
    c.add_argument("src")
    c.add_argument("out")
    c.add_argument("--region", default="")
    c.add_argument("--color", default="")
    c.add_argument("--tol", type=float, default=60.0)
    c.add_argument("--at", default="", help="選ぶ点 x,y（その点とつながった範囲だけ）")
    c.add_argument("--person", action="store_true", help="人物の範囲の中だけで色を選ぶ")
    a = sub.add_parser("apply")
    a.add_argument("src")
    a.add_argument("out")
    a.add_argument("--kind", choices=KINDS, required=True)
    a.add_argument("--strength", type=float, default=0.6)
    x = ap.parse_args()
    if x.cmd == "cut":
        img = Image.open(x.src)
        at = tuple(int(v) for v in x.at.split(",")) if x.at else None
        within = mask_person(x.src) if x.person else None
        m = mask_color(img, x.color, x.tol, at, within) if x.color else mask_parts(x.src, x.region or "skin")
        cutout(img, m).save(x.out)
        print(json.dumps({"pixels": int(m.sum())}))
    else:
        apply(Image.open(x.src), x.kind, x.strength).save(x.out)
        print(json.dumps({"kind": x.kind}))


if __name__ == "__main__":
    main()
