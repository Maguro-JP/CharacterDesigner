"""線画の加工（描いた絵から線だけを取り出す）。塗り・ベタ・トーンは一切持たない（それを足したものは manga.py）。

最初から線画として描かせるのは lineart.py。こちらは描いた絵に後から掛ける加工で、塗りの下地、塗り絵、検品で形を見る用に使う。線の質だけを変えた型を持つ。

  python3 tools/gen/linestyle.py 元.png 出力.png [型]   型: clean bold pencil color
"""
from __future__ import annotations

import sys

import numpy as np
from PIL import Image

from stylize import _arr, _blur, _box, _drop_specks, _img, _paper, _subject, xdog


def _xline(im, sigma: float = 0.7) -> np.ndarray:
    s = max(1, min(im.size) // 300)
    return _drop_specks(xdog(im, sigma=sigma * s), 3 * s, 7 * s)


def clean(im):
    """清書の線画。白地に黒の 1 本線"""
    return _img(np.repeat((1 - _xline(im))[..., None], 3, -1))


def bold(im):
    """外形を太く、中の線を細くした線画。塗り絵やアイコン向け"""
    line = _xline(im)
    subj = _subject(im)
    s = max(2, min(im.size) // 150)
    nb = _box(subj, 1)
    edge = ((nb > 0.5) & (nb < 8.5)).astype(np.float32)  # 周りに被写体と背景が両方ある所が外形
    out = np.maximum(line * 0.9, (_box(edge, s) > 0).astype(np.float32))
    return _img(np.repeat((1 - out)[..., None], 3, -1))


def pencil(im):
    """鉛筆の線画。線を灰色にかすれさせ、紙の目を出す（陰は付けない）"""
    line = _xline(im, 0.9)
    h, w = line.shape
    rng = np.random.default_rng(3)
    grain = _blur(rng.random((h, w)).astype(np.float32), 0.7)
    lead = line * (0.55 + 0.45 * (grain > 0.45))
    return _img(np.repeat((1 - 0.85 * lead)[..., None], 3, -1) * _paper(h, w))


def color(im):
    """色線の線画。線の色を元の色の暗い側から取る（色トレス）"""
    line = _xline(im)[..., None]
    a = _arr(im)
    ink = np.clip(a * 0.55, 0, 1)
    return _img((1 - line) + line * ink)


STYLES = {"lineart": clean, "lineart_bold": bold, "lineart_pencil": pencil, "lineart_color": color}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    kind = sys.argv[3] if len(sys.argv) > 3 else "clean"
    STYLES["lineart" if kind == "clean" else "lineart_" + kind](Image.open(sys.argv[1]).convert("RGB")).save(sys.argv[2])
