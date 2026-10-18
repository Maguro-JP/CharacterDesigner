"""髪の指定色の照合（measure.hair の spec_off）: 黒髪＋深紅のインナーカラーの指定で、光で桃色に染まった黒髪を外れと数える"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import scipy  # noqa: F401
    import measure
except ImportError:
    measure = None


def hair_of(colors):
    rgb = np.zeros((40, 40, 3), np.float32)
    seg = np.zeros((40, 40), int)
    seg[:, :] = 2
    for i, c in enumerate(colors):
        rgb[:, i * 40 // len(colors):(i + 1) * 40 // len(colors)] = np.array(c, np.float32) / 255
    return rgb, seg


@unittest.skipIf(measure is None, "scipy が無い")
class Spec(unittest.TestCase):
    SPEC = "#1e1a24,#a8203c"

    def off(self, colors):
        rgb, seg = hair_of(colors)
        return measure.hair(rgb, seg, {"hair": 2}, self.SPEC)["spec_off"]

    def test_asked_colors_pass(self):
        self.assertLess(self.off([(30, 26, 36), (168, 32, 60)]), 0.05)

    def test_pink_lit_black_hair_is_off(self):
        self.assertGreater(self.off([(30, 26, 36), (230, 150, 170)]), 0.4)


if __name__ == "__main__":
    unittest.main()
