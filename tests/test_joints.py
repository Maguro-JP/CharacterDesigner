"""関節の位置（tools/gen/joints.py）のうち、模型を使わない所の試験。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import joints  # noqa: E402


class CropBox(unittest.TestCase):
    def test_widens_and_keeps_ratio(self):
        x0, y0, x1, y1 = joints.crop_box((100, 100, 200, 500))
        self.assertAlmostEqual((x1 - x0) / (y1 - y0), 192 / 256)
        self.assertAlmostEqual(y1 - y0, 500)          # 縦長の人物は縦を 1.25 倍
        self.assertAlmostEqual((x0 + x1) / 2, 150)    # 中心は動かさない


class Decode(unittest.TestCase):
    def test_peak_maps_back_to_image(self):
        sx = np.zeros((17, 384)); sy = np.zeros((17, 512))
        sx[:, 192] = 1.0; sy[:, 128] = 0.8          # 切り出しの横の真ん中、縦の 1/4
        pts = joints.decode(sx, sy, (0, 0, 300, 400))
        self.assertAlmostEqual(pts[5]["x"], 150)
        self.assertAlmostEqual(pts[5]["y"], 100)
        self.assertAlmostEqual(pts[5]["score"], 0.8)
        self.assertEqual(pts[5]["name"], "left_shoulder")


if __name__ == "__main__":
    unittest.main()
