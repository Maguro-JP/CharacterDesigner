"""人の描き方の順番（ラフ → 線画 → 線の強弱 → 下塗り → 影 → 仕上げ）で絵を作る。docs/knowledge/drawing-process.md

  python3 tools/gen/handdraw.py run <元の絵> <出力フォルダ> [--guide <色を借りる絵>]

元の絵（ラフや模型の絵）から線を抜いて閉じ、強弱を付け、閉じた領域ごとに平らな色を置き、影を足して線を重ねる。
各段の絵を 1-lines.png … 5-final.png として残す（どの段で崩れたかを見るため）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))


def _grow(mask: np.ndarray, r: int) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype("uint8") * 255).filter(ImageFilter.MaxFilter(2 * r + 1))) > 127


def _shrink(mask: np.ndarray, r: int) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype("uint8") * 255).filter(ImageFilter.MinFilter(2 * r + 1))) > 127


def lines(src: str, gap: int = 2) -> np.ndarray:
    """線を抜いて閉じる。XDoG の線を gap 画素ぶん太らせてから細らせ（閉じる処理）、小さな切れ目を繋ぐ。
    線が閉じていないと、下塗りで隣の領域へ色が漏れる"""
    import imgproc
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        imgproc.lineart(src, f"{d}/l.png")
        line = np.asarray(Image.open(f"{d}/l.png")) < 128
    return _shrink(_grow(line, gap), max(gap - 1, 0)) | line


def person_mask(src: str) -> np.ndarray:
    import imgproc
    im = Image.open(src).convert("RGB")
    return imgproc._person_alpha(src, im)


def weight(line: np.ndarray, person: np.ndarray, light=(-1.0, -1.0)) -> np.ndarray:
    """線の強弱。外側の輪郭は太く（3画素）、内側の細部は細く（1画素）、影の側（光と反対）の輪郭はさらに太く（4画素）。
    人の描き手が「形の前後と重さ」を線で伝えるやり方を、外形からの距離と光の向きで近づける"""
    H, W = line.shape
    edge = person & ~_shrink(person, 3)            # 人物の外形の帯
    outer = line & _grow(edge, 2)
    inner = line & ~outer
    out = np.zeros_like(line)
    # 内側の線は細らせる（太いまま重ねると細部が黒く潰れた）。2画素以上の太さの所だけ1画素削る
    core = _shrink(inner, 1)                               # 3画素以上の太さの所の芯
    out |= core | (inner & ~_grow(core, 1))                 # 太い線は芯だけ、細い線はそのまま
    out |= _grow(outer, 1)                         # 外側は太く
    # 影の側: 外形の帯のうち、人物の重心から見て光と反対の向きにある所
    ys, xs = np.nonzero(person)
    if len(ys):
        cy, cx = ys.mean(), xs.mean()
        yy, xx = np.mgrid[0:H, 0:W]
        lx, ly = light
        dark_side = ((xx - cx) * -lx + (yy - cy) * -ly) > 0
        out |= _grow(outer & dark_side, 2)
    return out


def flats(line: np.ndarray, person: np.ndarray, guide: Image.Image, min_area: int = 30) -> np.ndarray:
    """閉じた領域ごとに平らな色を1つ置く（バケツ塗り）。色は guide の、その領域の中央値。
    人物の外は白。線の上は後で線を重ねるので、隣の色で埋める"""
    from collections import deque
    H, W = line.shape
    g = np.asarray(guide.convert("RGB").resize((W, H))).astype(int)
    out = np.full((H, W, 3), 255, dtype=np.uint8)
    seen = line.copy() | ~person
    labels = np.full((H, W), -1, dtype=np.int32)
    n = 0
    for y0 in range(H):
        for x0 in range(W):
            if seen[y0, x0]:
                continue
            comp, q = [], deque([(y0, x0)])
            seen[y0, x0] = True
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
            ys, xs = np.array(comp).T
            if len(comp) >= min_area:
                out[ys, xs] = np.median(g[ys, xs], axis=0).astype(np.uint8)
                labels[ys, xs] = n
                n += 1
            else:
                out[ys, xs] = g[ys, xs]   # 小さな隙間は元の色（ベタの点が浮かないように）
    # 線の下・小さな領域・人物の中の未塗りは、隣の大きな領域の色で埋める（細い領域が白く抜けた）。
    # 塗った所から外へ1画素ずつ色を広げる（最も近い塗った色で埋めるのと同じ）
    holes = person & (labels < 0)
    have = labels >= 0
    for _ in range(40):
        if not (holes & ~have).any():
            break
        grown = have.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(np.roll(have, dy, 0), dx, 1)
            col = np.roll(np.roll(out, dy, 0), dx, 1)
            take = holes & ~grown & src
            out[take] = col[take]
            grown |= take
        have = grown
    return out, n


def run(src: str, outdir: str, guide: str | None = None, style: str = "cel2", line_style: str = "default",
        brush: str | None = None, grain: float | None = None) -> dict:
    """line_style は線の作風（casts/brushes.json の styles。chibi はデフォルメで太い線）。brush で筆を指定できる"""
    import imgproc
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    person = person_mask(src)
    # 人物の外の線（ラフの効果線・背景の当たり線）は清書に入れない。外形の線を残すため、人物を少し太らせた範囲で切る
    line = lines(src) & _grow(person, 4)
    Image.fromarray(np.where(line, 0, 255).astype("uint8")).save(out / "1-lines.png")
    strong = weight(line, person)
    Image.fromarray(np.where(strong, 0, 255).astype("uint8")).save(out / "2-weight.png")
    flat, regions = flats(line, person, Image.open(guide or src))
    Image.fromarray(flat).save(out / "3-flats.png")
    # 影: 立体の計算（imgproc.shade）で暗くなった所だけを「影の面」として取り、下塗りの色ごとに1段暗い影色を平らに置く。
    # 計算の明暗をそのまま掛けると、下塗りとほぼ同じに見えた（段が無い）。人の影は面で置く
    imgproc.shade(str(out / "3-flats.png"), str(out / "4-calc.png"), style=style)
    calc = np.asarray(Image.open(out / "4-calc.png").convert("L")).astype(float)
    base = np.asarray(Image.fromarray(flat).convert("L")).astype(float)
    shadow = person & (calc < base * 0.93)
    shadow = _shrink(_grow(shadow, 2), 2)            # 細かい斑を面にまとめる
    shaded = flat.astype(float).copy()
    tint = np.array([0.62, 0.60, 0.80])              # 影は寒色寄りに落とす（黒を混ぜると濁る）
    # 影の境目だけ馴染ませる: 影の面の縁を細くぼかして掛ける（アニメ塗りは境目を残すので 1.5 画素だけ）
    soft = np.asarray(Image.fromarray(shadow.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(1.5))).astype(float)[..., None] / 255
    shaded = shaded * (1 - soft) + shaded * tint * soft
    Image.fromarray(shaded.clip(0, 255).astype(np.uint8)).save(out / "4-shade.png")
    # 色を重ねる（オーバーレイ）: 光源の側（左上）を暖かく、反対側を冷たく。人の描き手が最後に掛ける色味の層
    Hh, Ww = shadow.shape
    yy, xx = np.mgrid[0:Hh, 0:Ww]
    side = ((-(xx - Ww / 2) / Ww) + (-(yy - Hh / 2) / Hh))   # 左上ほど大きい
    warm = np.array([1.0, 0.55, 0.25]) * 255
    cool = np.array([0.25, 0.4, 1.0]) * 255
    tone = np.where(side[..., None] > 0, warm, cool)
    k = (np.abs(side)[..., None] * 0.18 * person[..., None])
    def overlay(a, b):
        a, b = a / 255, b / 255
        return np.where(a < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b)) * 255
    shaded = shaded * (1 - k) + overlay(shaded, tone) * k
    # ハイライト（加算）: 影でない所のうち、光源の側の外形の縁に細い光
    rim = person & ~_shrink(person, 3) & (side > 0.05) & ~shadow
    hl = np.asarray(Image.fromarray(rim.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(1))).astype(float)[..., None] / 255
    shaded = shaded + hl * 70
    shaded = shaded.clip(0, 255).astype(np.uint8)
    Image.fromarray(shaded).save(out / "4-light.png")
    # 線: 墨で重ねる。暗い面の上では墨が沈んで見えないので、下の色を明るくした色の線にする（色トレスの考え方）
    # 紙の目と筆ムラ: 人の絵は面の中に細かいざらつきがある（模型の絵の約4倍。docs/knowledge/painting-workflow.md）。
    # 細かい雑音と、ゆるく大きな濃淡の揺れ（筆ムラ）を人物の中にだけ掛ける
    # 量は線の作風で変える。人の絵でも、すっきりしたアニメ塗りは 2.75、筆の跡を残す塗りは 6 前後だった
    if grain is None:
        grain = {"sketch": 6.0, "manga": 3.0}.get(line_style, 3.0)
    rng = np.random.default_rng(7)
    H2, W2 = shaded.shape[:2]
    fine = rng.normal(0, 1, (H2, W2))
    blotch = np.asarray(Image.fromarray(((rng.normal(0, 1, (H2 // 24 + 1, W2 // 24 + 1)) * 40 + 128).clip(0, 255)).astype("uint8"))
                        .resize((W2, H2), Image.BICUBIC)).astype(float) - 128
    tex = (fine * grain + blotch * grain * 0.03)[..., None]
    shaded = np.where(person[..., None], shaded.astype(float) + tex, shaded.astype(float)).clip(0, 255).astype(np.uint8)
    Image.fromarray(shaded).save(out / "4-texture.png")
    lum = np.asarray(Image.fromarray(shaded).convert("L")).astype(float)
    # 線は筆跡としてブラシで引き直す（brushes.py）。外形の筆跡は太く。暗い面の上は下の色を明るくした線（色トレス）
    import brushes
    st = brushes.table()["styles"].get(line_style, brushes.table()["styles"]["default"])
    paths = brushes.strokes(strong)
    edge = _grow(person & ~_shrink(person, 3), 3)
    weights = [1.5 if np.mean([edge[y, x] for y, x in p]) > 0.5 else 1.0 for p in paths]
    layer = np.asarray(brushes.render(line.shape[::-1], paths, brush or st["brush"], st["line_scale"], weights)).astype(float)
    a = layer[..., 3:] / 255
    # 筆跡にならなかった短い線（目・口・まつ毛など顔の細い線）は、元の線を細いまま残す（ブラシで引き直すと抜け落ちた）
    left = strong & (a[..., 0] < 0.2)
    a = np.maximum(a, (left * 0.85)[..., None])
    ink = np.where((lum < 70)[..., None], (shaded.astype(float) * 1.9 + 50).clip(0, 255), np.array([40, 30, 40], dtype=float))
    shaded = (shaded.astype(float) * (1 - a) + ink * a).clip(0, 255).astype(np.uint8)
    # 目は人の描き手も最後に別に描く（講座でも「目の線画は後の工程で描く」）。顔の部位の中の目の周りだけ、元の絵の描き込みを戻す
    try:
        import edit
        lab = np.asarray(edit.parts(src).resize(shaded.shape[1::-1], Image.NEAREST))
        face = _shrink(lab == 11, 4)
        if face.any():
            ys, xs = np.nonzero(face)
            top, bot = ys.min(), ys.max()
            eyes = face & (np.arange(face.shape[0])[:, None] > top + (bot - top) * 0.30) & \
                (np.arange(face.shape[0])[:, None] < top + (bot - top) * 0.62)
            soft = np.asarray(Image.fromarray(eyes.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(3))).astype(float)[..., None] / 255
            orig = np.asarray(Image.open(src).convert("RGB")).astype(float)
            shaded = (shaded.astype(float) * (1 - soft) + orig * soft).clip(0, 255).astype(np.uint8)
    except Exception:
        pass   # 部位分けが使えないときは戻さない（線だけで描いた目のまま）
    Image.fromarray(shaded).save(out / "5-final.png")
    return {"regions": regions, "line_ratio": round(float(line.mean()), 4), "weighted_ratio": round(float(strong.mean()), 4)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("src"); r.add_argument("out"); r.add_argument("--guide", default=None); r.add_argument("--style", default="cel2")
    r.add_argument("--line-style", default="default"); r.add_argument("--brush", default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.src, a.out, a.guide, a.style, a.line_style, a.brush), ensure_ascii=False))
