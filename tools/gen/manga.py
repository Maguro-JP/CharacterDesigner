"""漫画の加工。主線・ベタ・スクリーントーンの 3 つで白黒の原稿にする。

線画（linestyle.py）は線だけで、塗りも影も持たない。漫画はその線に、ベタ（墨で塗りつぶした黒）と
トーン（tones.py の網点や線）を足したもの。ベタとトーンが無ければ漫画ではなく線画になる。

被写体の明るさの順位で段に分け、段ごとに「何で埋めるか」を決める（compose の bands）。
同じ元絵から、少年漫画・少女漫画・劇画のように、ベタの量とトーンの選び方だけで描き分ける。

  python3 tools/gen/manga.py 元.png 出力.png [型]   型: shonen shoujo gekiga flat
"""
from __future__ import annotations

import sys

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import tones
from stylize import _blur, _box, _drop_specks, _img, _subject, xdog


def _gray(im) -> np.ndarray:
    return np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0


def pen_line(im, weight: float = 1.0) -> np.ndarray:
    """ペンの主線 0/1。XDoG の線を 2 値にし、weight 倍に太らせる"""
    s = max(1, min(im.size) // 300)
    line = _drop_specks(xdog(im, sigma=0.7 * s), 3 * s, 7 * s)
    on = (line > 0.45).astype(np.float32)
    r = int(round(s * (weight - 1)))
    if r > 0:
        on = (_box(on, r) > 0).astype(np.float32)
    return on


def _rank(gs: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """明るさを、被写体の中での順位 0〜1 に直す（0.2 = 被写体の暗い方から 2 割）。
    明るさのままで段を切ると、茶色い動物は体の半分がベタになり、白い動物はトーンが 1 つも乗らなかった"""
    ref = np.sort(gs[inside] if inside.sum() > 100 else gs.ravel())
    return np.searchsorted(ref, gs).astype(np.float32) / max(1, len(ref))


def _majority(m: np.ndarray, r: int) -> np.ndarray:
    """周り (2r+1)^2 の過半数で 0/1 を決め直す。毛並みの細かい暗さがベタやトーンの斑になるのを防ぐ"""
    return (_box(m.astype(np.float32), r) > 0.5 * (2 * r + 1) ** 2).astype(np.float32)


def compose(im, bands, line_weight: float = 1.0, beta_level: float = 0.16, outline: float = 0.0,
            background: str | None = None, bg_value: float = 0.25):
    """原稿を組む。bands は (この順位未満, トーン名, 濃さ) を暗い順に並べたもの。順位は被写体の中での明るさの順位。
    ベタ → 段ごとのトーン → 主線 の順に墨を重ねる。ベタとトーンは被写体の中だけに置く。
    outline は被写体の外形だけを太らせる幅（画素）。background を渡すと、背景にそのトーンを敷く（渡さなければ白）"""
    g = _gray(im)
    h, w = g.shape
    s = max(1, min(h, w) // 300)
    subj = _subject(im)
    inside = subj > 0.5
    rk = _rank(_blur(g, 2.0 * s), inside)
    ink = _majority(rk < beta_level, 2 * s) * inside
    lo = beta_level
    for hi, name, v in bands:
        m = _majority((rk >= lo) & (rk < hi), 2 * s) * inside
        ink = np.maximum(ink, tones.render(name, v, h, w) * m)
        lo = hi
    if background:
        ink = np.where(inside, ink, tones.render(background, bg_value, h, w))
    ink = np.maximum(ink, pen_line(im, line_weight))
    if outline:
        nb = _box(subj, 1)
        edge = ((nb > 0.5) & (nb < 8.5)).astype(np.float32)
        ink = np.maximum(ink, (_box(edge, max(1, int(outline) // 2)) > 0).astype(np.float32))
    return _img(np.repeat((1 - ink)[..., None], 3, -1))


def shonen(im):
    """少年漫画。はっきりしたベタと、中くらいの網点 1 段の影"""
    return compose(im, [(0.5, "dot_mid", 0.35)], line_weight=1.3, beta_level=0.12, outline=4)


def shoujo(im):
    """少女漫画。細い線、ベタは少なく、細かい網点 2 段と、グラデーションの背景"""
    return compose(im, [(0.3, "dot_fine", 0.45), (0.65, "dot_fine", 0.2)], line_weight=0.8, beta_level=0.04,
                   background="gradation", bg_value=0.45)


def gekiga(im):
    """劇画。太い線、多いベタ、カケアミの影 2 段、砂目の背景"""
    return compose(im, [(0.5, "cross", 0.7), (0.75, "cross", 0.35)], line_weight=1.8, beta_level=0.25,
                   outline=6, background="sand", bg_value=0.12)


def flat(im):
    """トーンだけの原稿（ベタを使わない）。印刷の網点が目立つ絵柄"""
    return compose(im, [(0.3, "dot_coarse", 0.6), (0.65, "dot_coarse", 0.3)], beta_level=0.0)


STYLES = {"manga_shonen": shonen, "manga_shoujo": shoujo, "manga_gekiga": gekiga, "manga_flat": flat}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    kind = sys.argv[3] if len(sys.argv) > 3 else "shonen"
    STYLES["manga_" + kind](Image.open(sys.argv[1]).convert("RGB")).save(sys.argv[2])
