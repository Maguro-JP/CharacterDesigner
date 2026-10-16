"""描き直しの跡（tools/gen/qc.py repaint_scars）の試験。絵は作らず、縞の画像をぼかして作る。"""
import sys
from pathlib import Path

import numpy as np
import unittest
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402

try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def stripes(w=256, h=256):
    a = np.full((h, w), 200, "uint8")
    for x in range(8, w, 24):
        a[:, x:x + 3] = 20          # 輪郭線のような鋭い縦線
    return Image.fromarray(a).convert("RGB")


def box_mask(w=256, h=256, box=(64, 64, 192, 192)):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle(box, fill=255)
    return m


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
def test_blurred_edge_is_found():
    before = stripes()
    m = box_mask()
    blurred = before.filter(ImageFilter.GaussianBlur(4))
    after = Image.composite(blurred, before, m)
    assert len(qc.repaint_scars(before, after, m)) > 0


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
def test_clean_repaint_is_not_found():
    before = stripes()
    assert qc.repaint_scars(before, before.copy(), box_mask()) == []


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
def test_image_border_is_not_an_edge():
    # 範囲が絵の右端に接していても、端の帯を縁と取り違えない
    before = stripes()
    m = box_mask(box=(128, 0, 255, 255))
    assert all(c["x"] < 200 for c in qc.repaint_scars(before, before.copy(), m))


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
def test_hole_opened_in_body_is_found():
    # 体（暗い四角）の中に、描き直しで背景色の穴が開いた
    im = Image.new("RGB", (200, 200), (216, 211, 207))
    ImageDraw.Draw(im).rectangle((40, 40, 160, 160), fill=(30, 30, 35))
    after = im.copy()
    ImageDraw.Draw(after).rectangle((90, 90, 110, 110), fill=(216, 211, 207))
    m = box_mask(200, 200, (70, 70, 130, 130))
    holes = qc.repaint_holes(im, after, m)
    assert len(holes) == 1 and holes[0]["pixels"] == 21 * 21


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
def test_no_hole_when_unchanged():
    im = Image.new("RGB", (200, 200), (216, 211, 207))
    ImageDraw.Draw(im).rectangle((40, 40, 160, 160), fill=(30, 30, 35))
    assert qc.repaint_holes(im, im.copy(), box_mask(200, 200, (70, 70, 130, 130))) == []
