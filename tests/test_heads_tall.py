import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import numpy as np
    import qc
except ImportError:  # numpy が無い環境
    np = None


def figure(neck_wide: bool, chest_skin: bool, collar: bool):
    """高さ 1000 の人物: 頭のてっぺん 100、顔 140〜260（あご 260）、足 1100。頭身は (1100-100)/(260-100) = 6.25"""
    rgb = np.full((1200, 600, 3), 255, np.uint8)
    rgb[100:1100, 250:350] = 0
    seg = np.zeros((1200, 600), np.uint8)
    for y in range(140, 260):
        half = 40 if y < 220 else int(40 - (y - 220))     # あごへ向かって細る
        seg[y, 300 - half:300 + half] = 11
    if not collar:
        seg[260:300, 300 - (30 if neck_wide else 18):300 + (30 if neck_wide else 18)] = 11   # 首
    if chest_skin:
        seg[300:340, 240:360] = 11                         # 胸元の開いた服の肌
    return seg, rgb


@unittest.skipIf(np is None, "numpy が無い")
class HeadsTallTest(unittest.TestCase):
    def test_neck_chest_and_collar(self):
        for neck_wide in (False, True):
            for chest in (False, True):
                seg, rgb = figure(neck_wide, chest, collar=False)
                self.assertAlmostEqual(qc.heads_tall(seg, rgb), 6.25, delta=0.35, msg=(neck_wide, chest))
        seg, rgb = figure(False, False, collar=True)
        self.assertAlmostEqual(qc.heads_tall(seg, rgb), 6.25, delta=0.5)  # 襟で首が隠れると、あごの先を少し上に取る

    def test_no_face(self):
        seg, rgb = figure(False, False, False)
        seg[:] = 0
        self.assertIsNone(qc.heads_tall(seg, rgb))


if __name__ == "__main__":
    unittest.main()
