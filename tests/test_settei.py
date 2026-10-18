"""設定画（settei）の、絵を描かない部分: 色指定の表と、足りない欄の数え方"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import settei  # noqa: E402


class ColorTable(unittest.TestCase):
    def test_base_shadow_light_by_brightness(self):
        rgb = np.zeros((60, 60, 3), np.uint8)
        seg = np.zeros((60, 60), int)
        seg[:, :] = 2                                   # 全部を髪とする
        rgb[:20] = (40, 20, 20)                         # 暗い帯
        rgb[20:58] = (160, 80, 60)                      # 地の色
        rgb[58:] = (250, 220, 210)                      # 光
        t = settei.color_table(rgb, seg, least=100)
        self.assertEqual(t[0]["part"], "髪")
        self.assertEqual(t[0]["shadow"], "#281414")
        self.assertEqual(t[0]["base"], "#a0503c")
        self.assertEqual(t[0]["light"], "#fadcd2")

    def test_small_parts_are_left_out(self):
        seg = np.zeros((40, 40), int)
        seg[:5, :5] = 1
        self.assertEqual(settei.color_table(np.zeros((40, 40, 3), np.uint8), seg), [])


class Missing(unittest.TestCase):
    def test_lists_what_a_sheet_needs(self):
        got = {"views": {"front": "a.png"}, "expressions": {"smile": "s.png"}, "details": {}}
        m = settei.missing(got)
        self.assertIn("横の全身", m)
        self.assertIn("背面の全身", m)
        self.assertTrue(any(x.startswith("表情") for x in m))
        full = {"views": {"front": 1, "side": 1, "back": 1}, "expressions": dict.fromkeys("abcd", 1), "details": dict.fromkeys("xyz", 1)}
        self.assertEqual(settei.missing(full), [])


if __name__ == "__main__":
    unittest.main()
