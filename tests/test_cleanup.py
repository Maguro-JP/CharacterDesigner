import sys
import unittest
from pathlib import Path

import importlib.util

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import cleanup  # noqa: E402


def picture(seed=0):
    """上着（部位 4）の塗り: 地と影の 2 段にまだらを足し、太い主線 1 本（途中 2 画素の途切れ）と小さな黒い粒を置く"""
    rng = np.random.default_rng(seed)
    rgb = np.full((300, 300, 3), 230.0)
    seg = np.zeros((300, 300), np.uint8)
    seg[40:260, 40:260] = 4
    rgb[40:260, 40:260] = (200, 120, 120)
    rgb[40:260, 150:260] = (150, 80, 80)
    rgb[40:260, 40:260] += rng.normal(0, 8, (220, 220, 1))
    rgb[60:240, 100:105] = 20
    rgb[150:152, 100:105] = (200, 120, 120)
    for y, x in rng.integers(50, 250, (30, 2)):
        rgb[y:y + 3, x:x + 3] = 25
    return np.clip(rgb, 0, 255), seg


HAS = all(importlib.util.find_spec(m) for m in ("scipy", "skimage"))


@unittest.skipUnless(HAS, "scipy と skimage が無い（sh tools/gen/setup.sh で入る）")
class Cleanup(unittest.TestCase):
    def test_lines_lose_specks_and_join_gap(self):
        rgb, seg = picture()
        before = cleanup.measure("", rgb, seg)
        out = cleanup.clean_lines(rgb, seg)
        after = cleanup.measure("", out, seg)
        self.assertGreater(before["specks"], 10)
        self.assertLess(after["specks"], before["specks"] // 3)
        self.assertLessEqual(after["ends"], before["ends"])
        # 主線は残る
        self.assertLess(out[100, 102].mean(), 60)

    def test_colors_get_flatter_and_keep_bands(self):
        rgb, seg = picture()
        out = cleanup.clean_colors(rgb, seg, 0.8)
        self.assertLess(cleanup.measure("", out, seg)["mottle"], cleanup.measure("", rgb, seg)["mottle"])
        # 地と影の差は残る（段を 1 つに潰さない）
        self.assertGreater(out[100, 60].mean() - out[100, 200].mean(), 30)

    def test_face_is_untouched(self):
        rgb, seg = picture()
        seg[40:260, 40:260] = cleanup.FACE
        self.assertTrue(np.array_equal(cleanup.clean_lines(rgb, seg), rgb))
        self.assertTrue(np.array_equal(cleanup.clean_colors(rgb, seg), rgb))


if __name__ == "__main__":
    unittest.main()
