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
