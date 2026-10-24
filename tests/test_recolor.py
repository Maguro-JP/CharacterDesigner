"""部位の色の置き換え（tools/gen/recolor.py）。模型は使わず、作った絵で確かめる。"""
import colorsys
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import recolor  # noqa: E402


class Recolor(unittest.TestCase):
    def test_hex(self):
        self.assertEqual(recolor.hexrgb("#835c41"), (131, 92, 65))

    def test_inside_takes_hue_and_keeps_shading(self):
        rgb = np.zeros((4, 4, 3), np.uint8)
        rgb[:, :2] = (230, 200, 90)   # 明るい辛子色
        rgb[:, 2:] = (150, 130, 60)   # 同じ色の影
        mask = np.ones((4, 4), np.float32)
        mask[0, 0] = 0
        out = recolor.recolor(rgb, mask, (131, 92, 65))
        want_h = colorsys.rgb_to_hsv(131 / 255, 92 / 255, 65 / 255)[0]
        h = colorsys.rgb_to_hsv(*(out[1, 1] / 255))[0]
        self.assertAlmostEqual(h, want_h, delta=0.02)
        # 影は明るい所より暗いまま
        self.assertLess(out[1, 3].max(), out[1, 1].max())
        # 範囲の外は変えない
        self.assertEqual(tuple(out[0, 0]), (230, 200, 90))


if __name__ == "__main__":
    unittest.main()


class Masks(unittest.TestCase):
    def test_delta_e(self):
        self.assertAlmostEqual(recolor.delta_e((10, 20, 30), (10, 20, 30)), 0.0)
        self.assertGreater(recolor.delta_e((255, 255, 255), (0, 0, 0)), 99)

    def test_belt_is_dark_band_on_pants_top(self):
        seg = np.zeros((60, 40), np.uint8)
        seg[30:60, 5:35] = 6                      # ズボン
        rgb = np.full((60, 40, 3), 230, np.uint8)
        rgb[28:32, 10:30] = (60, 40, 30)          # 上端の暗いベルト
        rgb[45, 15] = (60, 40, 30)                # 帯の外の暗い画素は入らない
        m = recolor.belt_mask(rgb, seg)
        self.assertTrue(m[29, 20] and m[31, 12])
        self.assertFalse(m[45, 15])
        self.assertFalse(m[20, 20])

    def test_hair_skips_dark_horn(self):
        seg = np.ones((10, 10), np.uint8)         # 髪と角がまとめて帽子の部位
        rgb = np.full((10, 10, 3), (245, 228, 170), np.uint8)
        rgb[:5] = (110, 80, 50)                   # 角
        m = recolor.hair_mask(rgb, seg)
        self.assertFalse(m[2, 2])
        self.assertTrue(m[7, 7])
