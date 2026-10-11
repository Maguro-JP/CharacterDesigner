"""人の順番の仕上げ（handdraw）の塗りの段の試験。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import handdraw  # noqa: E402


class Grisaille(unittest.TestCase):
    def test_value_from_grey_hue_from_flat(self):
        value = np.tile(np.linspace(0, 255, 100), (50, 1))
        flat = np.zeros((50, 100, 3), np.uint8)
        flat[:] = (200, 60, 60)
        person = np.ones((50, 100), bool)
        out = handdraw.grisaille(value, flat, person).astype(int)
        lum = out.sum(2)
        self.assertGreater(lum[:, 90].mean(), lum[:, 10].mean() + 150)   # 明暗は灰色から
        self.assertTrue((out[:, 30:70, 0] >= out[:, 30:70, 1]).all())     # 色相は下塗り（赤）から

    def test_outside_person_is_flat(self):
        flat = np.full((20, 20, 3), 90, np.uint8)
        person = np.zeros((20, 20), bool)
        person[5:15, 5:15] = True
        out = handdraw.grisaille(np.full((20, 20), 30.0), flat, person)
        self.assertTrue((out[~person] == 90).all())



if __name__ == "__main__":
    unittest.main()
