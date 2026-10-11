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


class Wear(unittest.TestCase):
    def test_only_cloth_changes_lightly(self):
        img = np.full((200, 200, 3), 150, np.uint8)
        cloth = np.zeros((200, 200), bool)
        cloth[40:180, 50:150] = True
        out = handdraw.wear(img, cloth, seed=3)
        diff = np.abs(out.astype(int) - img).sum(2)
        self.assertEqual(int(diff[~cloth].sum()), 0)      # 服の外は変えない
        self.assertGreater(int((diff > 0).sum()), 50)     # 服には描き込みが入る
        self.assertLess(float(diff[cloth].mean()), 15)    # 薄く（染みにしない）


try:
    import scipy  # noqa: F401
except ImportError:
    scipy = None


@unittest.skipIf(scipy is None, "scipy が無い（.cache/gen/lib に入る）")
class Metal(unittest.TestCase):
    def test_shiny_grey_is_metal_and_flat_red_is_cloth(self):
        rng = np.random.default_rng(0)
        img = np.zeros((120, 200, 3), np.uint8)
        img[:, :100] = rng.integers(60, 230, (120, 100, 1), dtype=np.uint8)   # 灰色でつやの散らばる板
        img[:, 100:] = (180, 40, 40)                                         # 平らな赤い布
        cloth = np.ones((120, 200), bool)
        m = handdraw.metal_mask(img, cloth)
        self.assertGreater(m[20:100, 20:80].mean(), 0.9)
        self.assertLess(m[20:100, 120:180].mean(), 0.1)


if __name__ == "__main__":
    unittest.main()
