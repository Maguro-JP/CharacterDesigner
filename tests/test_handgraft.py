"""手の移植（tools/gen/handgraft.py）。模型は使わず、作った絵と部位分けで確かめる。"""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import handgraft  # noqa: E402


def scene(wrist, tip, color):
    """白地に、手首から指先へ向かう太い線の『手』を置いた絵と部位分け（腕 = 14）"""
    im = Image.new("RGB", (100, 100), "white")
    a = np.asarray(im).copy()
    seg = np.zeros((100, 100), np.uint8)
    for t in np.linspace(0, 1, 50):
        x = int(round(wrist[0] + (tip[0] - wrist[0]) * t))
        y = int(round(wrist[1] + (tip[1] - wrist[1]) * t))
        a[y - 2:y + 3, x - 2:x + 3] = color
        seg[y - 2:y + 3, x - 2:x + 3] = 14
    return Image.fromarray(a), seg


class HandGraft(unittest.TestCase):
    def test_moves_hand_to_new_wrist_and_direction(self):
        src, sseg = scene((20, 20), (20, 50), (200, 50, 50))     # 下向きの赤い手
        dst, dseg = scene((60, 40), (80, 40), (50, 50, 200))     # 右向きの青い手
        out, n = handgraft.graft(src, sseg, dst, dseg, (20, 20), (20, 50), (60, 40), (80, 40))
        a = np.asarray(out)
        self.assertGreater(n, 0)
        # 手首より先の元の青い手は消え、同じ場所に赤い手が来る
        tip_side = a[:, 61:]
        self.assertFalse(((tip_side[..., 2] > 150) & (tip_side[..., 0] < 100)).any())
        self.assertTrue((a[40, 70, 0] > 150) and (a[40, 70, 2] < 120))
        # 手首より手前（腕の側）には貼らない
        self.assertEqual(tuple(a[40, 50]), (255, 255, 255))

    def test_transform_maps_points(self):
        a, b, c, d, e, f = handgraft.transform((20, 20), (20, 50), (60, 40), (80, 40))
        # dst の指先は src の指先へ写る
        x, y = 80, 40
        self.assertAlmostEqual(a * x + b * y + c, 20, places=6)
        self.assertAlmostEqual(d * x + e * y + f, 50, places=6)


if __name__ == "__main__":
    unittest.main()


class PlaceDepth(unittest.TestCase):
    def test_hand_lands_on_wrist_and_is_brightened(self):
        d = Image.new("L", (40, 40), 0)
        a = np.asarray(d).copy()
        a[10:30, 18:22] = 90          # 下向きの手（暗い灰色）
        out = handgraft.place_depth(Image.fromarray(a), (20, 10), (20, 30), (200, 100), (100, 20), (100, 60))
        o = np.asarray(out)[..., 0]
        self.assertEqual(out.size, (200, 100))
        self.assertGreater(o[40, 100], 150)   # 手首と指先の間は明るい手
        self.assertEqual(o[40, 150], 0)       # 手の外は黒


class Outline(unittest.TestCase):
    def test_outline_is_edge_only(self):
        a = np.zeros((40, 40), np.uint8)
        a[10:30, 10:30] = 120
        o = np.asarray(handgraft.outline(Image.fromarray(a), 1))
        self.assertEqual(o[20, 20], 0)       # 中は塗らない
        self.assertEqual(o[0, 0], 0)         # 外も塗らない
        self.assertTrue((o[10:30, 9:12] == 255).any())   # 縁に線


class Restore(unittest.TestCase):
    def test_restores_only_inside_ellipse(self):
        good = Image.new("RGB", (50, 50), (255, 0, 0))
        img = Image.new("RGB", (50, 50), (0, 0, 255))
        out = np.asarray(handgraft.restore_regions(good, img, [(10, 10, 30, 30)], feather=1))
        self.assertEqual(tuple(out[20, 20]), (255, 0, 0))
        self.assertEqual(tuple(out[45, 45]), (0, 0, 255))
