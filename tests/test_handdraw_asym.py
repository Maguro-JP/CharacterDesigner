"""左右対称の部位に差を付ける段（handdraw.asymmetry）の試験。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import handdraw  # noqa: E402


class Asymmetry(unittest.TestCase):
    def test_one_side_changes_slightly(self):
        img = np.zeros((40, 80, 3), np.uint8)
        img[15:25, 10:30] = 255   # 左の目
        img[15:25, 50:70] = 255   # 右の目（左と同じ形）
        out = handdraw.asymmetry(img, (0, 5, 80, 35), amount=0.1, seed=1)
        left = np.abs(out[:, :40].astype(int) - img[:, :40]).sum()
        right = np.abs(out[:, 40:].astype(int) - img[:, 40:]).sum()
        self.assertTrue((left == 0) != (right == 0))   # 片側だけが変わる
        self.assertLess(np.abs(out.astype(int) - img).mean(), 20)   # 変わり方は小さい

    def test_outside_box_untouched(self):
        img = np.random.default_rng(0).integers(0, 255, (40, 80, 3), dtype=np.uint8)
        out = handdraw.asymmetry(img, (10, 10, 70, 30), seed=2)
        self.assertTrue((out[:10] == img[:10]).all() and (out[30:] == img[30:]).all())


if __name__ == "__main__":
    unittest.main()
