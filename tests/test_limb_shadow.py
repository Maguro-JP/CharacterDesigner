"""手足の影（measure.limbs）: 軸に沿った形の影と、軸を横切る影、片脚だけ暗い影を見分けられるかを見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

try:
    import scipy  # noqa: F401  描く部品（.cache/gen/lib）に入っている
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

LABELS = {"left_leg": 12, "right_leg": 13, "left_arm": 14, "right_arm": 15}


def legs(shade):
    """縦長の脚を2本置いた部位分けと、shade(脚の中の x, y) で明るさを決めた絵"""
    h, w = 400, 320
    seg = np.zeros((h, w), dtype=np.uint8)
    rgb = np.ones((h, w, 3), dtype=np.float32)
    for lab, x0 in ((12, 40), (13, 200)):
        seg[40:380, x0:x0 + 100] = lab
        for y in range(40, 380):
            for x in range(x0, x0 + 100):
                rgb[y, x] = shade(lab, (x - x0) / 100, (y - 40) / 340)
    return rgb, seg


@unittest.skipUnless(HAS_SCIPY, "scipy が要る")
class LimbShadowTest(unittest.TestCase):
    def test_form_shadow_along_the_leg(self):
        # 左から光: 両脚とも右の 4 割が暗い。境は脚の長さに沿う
        rgb, seg = legs(lambda lab, u, v: 0.9 if u < 0.6 else 0.5)
        r = measure.limbs(rgb, seg, LABELS)
        self.assertLess(r["across_max"], 0.2)
        self.assertLess(r["leg_dark_gap"], 0.1)

    def test_shadow_edge_across_the_leg(self):
        # 影の境が脚を斜めに横切る（遮る物の無い所に出来る直線の影）
        rgb, seg = legs(lambda lab, u, v: 0.9 if v < 0.5 + 0.2 * (u - 0.5) else 0.5)
        self.assertGreater(measure.limbs(rgb, seg, LABELS)["across_max"], 0.6)

    def test_one_leg_dark(self):
        # 同じ光を受けるはずの脚の片方だけが大きく暗い
        rgb, seg = legs(lambda lab, u, v: (0.9 if u < 0.8 else 0.5) if lab == 12 else (0.9 if u < 0.2 else 0.5))
        self.assertGreater(measure.limbs(rgb, seg, LABELS)["leg_dark_gap"], 0.4)


if __name__ == "__main__":
    unittest.main()
