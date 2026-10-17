"""写実の明暗を段の影に落とす（toneshade.shade）: 段の数と、なめらかさの指定が効くかを見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))

try:
    import scipy  # noqa: F401
    import toneshade
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def cylinder():
    """左から光を受けた縦の円柱（左が明るく右へ暗くなる）"""
    h, w = 200, 200
    x = np.linspace(-1, 1, 120)
    lum = np.clip(0.2 + 0.8 * np.sqrt(np.clip(1 - x ** 2, 0, 1)) * (0.6 - 0.4 * x), 0, 1)
    rgb = np.ones((h, w, 3), dtype=np.float32)
    rgb[:, 40:160] = (lum[None, :, None] * np.array([1.0, 0.8, 0.7]))
    person = np.zeros((h, w), bool)
    person[:, 40:160] = True
    return rgb, person


@unittest.skipUnless(HAS_SCIPY, "scipy が要る")
class ToneShadeTest(unittest.TestCase):
    def test_hard_tones_are_few_and_follow_the_form(self):
        rgb, person = cylinder()
        out = toneshade.shade(rgb, person, tones=2, soft=0.0)
        row = out[100, 50:150].mean(-1)
        # 段の影: 明るい所と影の2つの値にまとまる（境のぼかし 1 画素ぶんを除く）
        self.assertLessEqual(len(np.unique(np.round(row, 2))), 8)
        # 影は光と反対（右）の側にある
        self.assertGreater(row[:30].mean(), row[-30:].mean())

    def test_soft_keeps_gradient(self):
        rgb, person = cylinder()
        hard = toneshade.shade(rgb, person, tones=2, soft=0.0)[100, 50:150].mean(-1)
        soft = toneshade.shade(rgb, person, tones=2, soft=1.0)[100, 50:150].mean(-1)
        self.assertGreater(len(np.unique(np.round(soft, 3))), len(np.unique(np.round(hard, 3))))


if __name__ == "__main__":
    unittest.main()
