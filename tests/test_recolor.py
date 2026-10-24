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
