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
    m = mask[..., None]
    return np.clip((src * (1 - m) + new * m) * 255, 0, 255).astype(np.uint8)


def white_outside(im: Image.Image) -> Image.Image:
    """人物の輪郭の外（四辺から塗り広げて届く背景）だけを白にする"""
    import design
    alpha = design.cut_background(im).getchannel("A").filter(ImageFilter.GaussianBlur(1))
    out = Image.new("RGB", im.size, "white")
    out.paste(im, (0, 0), alpha)
    return out


def part_mask(src: str, part: str) -> np.ndarray:
    import edit
    seg = np.asarray(edit.parts(src))
    m = Image.fromarray(((seg == edit.LABELS[part]) * 255).astype(np.uint8))
    return np.asarray(m.filter(ImageFilter.GaussianBlur(1.5))).astype(np.float32) / 255


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--part", default="pants"); ap.add_argument("--color", required=True)
    ap.add_argument("--white", action="store_true", help="人物の外の背景を白にする")
    a = ap.parse_args()
    im = Image.open(a.src).convert("RGB")
    mask = part_mask(a.src, a.part)
    res = Image.fromarray(recolor(np.asarray(im), mask, hexrgb(a.color)))
    if a.white:
        res = white_outside(res)
    res.save(a.out)
    print(f"{a.out}: 置き換えた画素 {int((mask > 0.5).sum())}")


if __name__ == "__main__":
    main()
