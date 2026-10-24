"""描いた絵の服の1部位だけを、明るさを保ったまま設定の色に置き換え、人物の外の背景を白にする。

描き直すと、ズボンの色の言葉が上着の色に引っ張られた（羊娘、4枚とも茶色にならず辛子色やクリーム色）。
形と陰影は描けているので、色相と彩度だけを差し替える。部位は部位分け（edit.parts）で取り、
髪・肌・靴は別の部位なので入らない。明るさは元の濃淡を、設定の色の明るさを中心に引き直す。

  python3 tools/gen/recolor.py IN.png OUT.png --part pants --color 835c41 [--white]
"""
from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))


def hexrgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def recolor(rgb: np.ndarray, mask: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    """mask の範囲を color の色相・彩度にする。明るさは元の濃淡の比を、color の明るさに掛けて保つ。
    mask は 0〜1 の小数（縁をぼかして継ぎ目を出さない）"""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in color))
    src = rgb.astype(np.float32) / 255
    lum = src.max(axis=2)
    inside = mask > 0.5
    mid = float(np.median(lum[inside])) if inside.any() else 1.0
    # 元の濃淡を、範囲の中ほどの明るさが設定の明るさになるよう引き直す
    nv = np.clip(lum / max(mid, 1e-3) * v, 0, 1)
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = nv * (1 - s), nv * (1 - s * f), nv * (1 - s * (1 - f))
    table = [(nv, t, p), (q, nv, p), (p, nv, t), (p, q, nv), (t, p, nv), (nv, p, q)][i]
    new = np.stack(table, axis=2)
    # 範囲の縁をぼかすと白い背景まで色が付き、ズボンの輪郭に橙の光の縁が出た。白に近い画素は変えない
    m = (mask * (src.min(axis=2) < 0.88))[..., None]
    return np.clip((src * (1 - m) + new * m) * 255, 0, 255).astype(np.uint8)


def white_outside(im: Image.Image) -> Image.Image:
    """人物の輪郭の外（四辺から塗り広げて届く背景）だけを白にする"""
    import design
    alpha = design.cut_background(im).getchannel("A").filter(ImageFilter.GaussianBlur(1))
    out = Image.new("RGB", im.size, "white")
    out.paste(im, (0, 0), alpha)
    return out


def eye_mask(rgb: np.ndarray, seg: np.ndarray) -> np.ndarray:
    """瞳の範囲: 顔の部位の中で、彩度が高く橙〜黄の色相の画素。部位分けには目の部位が無い"""
    hsv = np.asarray(Image.fromarray(rgb).convert("HSV")).astype(int)
    h, sat = hsv[..., 0] * 360 / 255, hsv[..., 1]
    return (seg == 11) & (sat > 90) & (h > 10) & (h < 70)


def hair_mask(rgb: np.ndarray, seg: np.ndarray) -> np.ndarray:
    """髪の範囲: 髪か帽子の部位で、明るい黄色の画素。羊娘の四面図では髪と角がまとめて帽子の部位に入った。
    暗い茶色の角と輪郭の線は明るさで外す"""
    hsv = np.asarray(Image.fromarray(rgb).convert("HSV")).astype(int)
    h = hsv[..., 0] * 360 / 255
    return np.isin(seg, (1, 2)) & (hsv[..., 2] > 170) & (h > 25) & (h < 70)


def belt_mask(rgb: np.ndarray, seg: np.ndarray) -> np.ndarray:
    """ベルトの範囲: 部位分けにベルトが出ないので、ズボンの上端から上下 14 画素の帯のうち、暗い画素（明るさ 150 未満）。
    帯の横幅はズボンの上端の幅にそろえる"""
    pants = seg == 6
    rows = np.nonzero(pants.sum(1) > 20)[0]
    out = np.zeros(seg.shape, bool)
    if not len(rows):
        return out
    top = rows.min()
    xs = np.nonzero(pants[top + 4])[0] if top + 4 < seg.shape[0] else np.nonzero(pants[top])[0]
    if not len(xs):
        return out
    band = np.zeros(seg.shape, bool)
    band[max(0, top - 14):top + 14, xs.min():xs.max() + 1] = True
    return band & (rgb.max(axis=2) < 150) & ~np.isin(seg, (2, 14, 15))


def raw_mask(rgb: np.ndarray, seg: np.ndarray, part: str) -> np.ndarray:
    import edit
    if part == "eyes":
        return eye_mask(rgb, seg)
    if part == "hair":
        return hair_mask(rgb, seg)
    if part == "belt":
        return belt_mask(rgb, seg)
    return seg == edit.LABELS[part]


def part_mask(src: str, part: str) -> np.ndarray:
    import edit
    seg = np.asarray(edit.parts(src))
    rgb = np.asarray(Image.open(src).convert("RGB"))
    m = Image.fromarray((raw_mask(rgb, seg, part) * 255).astype(np.uint8))
    return np.asarray(m.filter(ImageFilter.GaussianBlur(1.5 if part != "eyes" else 0.6))).astype(np.float32) / 255


def mean_color(src: str, part: str) -> tuple[int, int, int]:
    """部位の画素の色の中央値（輪郭の暗い線に引っ張られないよう平均でなく中央値）"""
    import edit
    seg = np.asarray(edit.parts(src))
    rgb = np.asarray(Image.open(src).convert("RGB"))
    m = raw_mask(rgb, seg, part)
    return tuple(int(v) for v in np.median(rgb[m], axis=0)) if m.any() else (0, 0, 0)


def lab(c) -> np.ndarray:
    """sRGB を CIE L*a*b*（D65）に。色の差は Lab の距離（ΔE76）で出す"""
    v = np.asarray(c, np.float64) / 255
    v = np.where(v > 0.04045, ((v + 0.055) / 1.055) ** 2.4, v / 12.92)
    x, y, z = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]) @ v
    f = lambda t: np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16 / 116)
    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return np.array([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)])


def delta_e(a, b) -> float:
    return float(np.linalg.norm(lab(a) - lab(b)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--part", default="pants", help="部位（hair, pants, belt, eyes など。カンマ区切りで複数）")
    ap.add_argument("--color", help="寄せる色（16 進）。--match と どちらか")
    ap.add_argument("--match", help="手本の絵。部位ごとに手本の同じ部位の色の中央値へ寄せる")
    ap.add_argument("--white", action="store_true", help="人物の外の背景を白にする")
    a = ap.parse_args()
    res = np.asarray(Image.open(a.src).convert("RGB"))
    for part in a.part.split(","):
        mask = part_mask(a.src, part)
        target = mean_color(a.match, part) if a.match else hexrgb(a.color)
        before = mean_color(a.src, part)
        res = recolor(res, mask, target)
        print(f"{part}: 置き換えた画素 {int((mask > 0.5).sum())}  手本 {target}  元 {before}  色の差 ΔE {delta_e(before, target):.1f}")
    res = Image.fromarray(res)
    if a.white:
        res = white_outside(res)
    res.save(a.out)


if __name__ == "__main__":
    main()
