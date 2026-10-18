"""顔の形の検品（faceform.fit）: 型を回して写した点は、その向きで当てはまり、ずれ（rms）が小さい。
1 点だけ動かした顔は、その点が一番ずれた点（worst）として出る"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
try:
    import scipy  # noqa: F401
    import faceform
except ImportError:
    faceform = None


def project(template, yaw_deg, scale=40.0, shift=(300.0, 200.0)):
    R = faceform._rot(np.radians(yaw_deg), 0.0, 0.0)
    return {n: list((np.array(p, float) @ R.T)[:2] * scale + shift) for n, p in template.items() if n in faceform.NAMES}


@unittest.skipIf(faceform is None, "scipy が無い")
class Fit(unittest.TestCase):
    def setUp(self):
        t = json.loads(faceform.TEMPLATE.read_text(encoding="utf-8"))
        self.t = t.get("points", t)

    def test_recovers_yaw(self):
        for yaw in (0, 20, -25):
            r = faceform.fit(project(self.t, yaw), self.t)
            self.assertLess(r["rms"], 0.02, yaw)
            self.assertAlmostEqual(r["yaw_deg"], yaw, delta=3, msg=yaw)

    def test_moved_point_is_worst(self):
        # 口を横にずらした顔は、左右の向き（yaw）が口のずれを吸い、worst が目の点に出ていた。目だけで向きを解き直して口と分かる
        for name, (dx, dy) in (("eyeL_out", (0, 10)), ("eyeR_top", (0, 8)), ("mouth", (0, 15)), ("mouth", (30, 0)), ("mouth", (-20, 0))):
            pts = project(self.t, 10)
            pts[name] = [pts[name][0] + dx, pts[name][1] + dy]
            r = faceform.fit(pts, self.t)
            self.assertEqual(r["worst"], name)
            self.assertGreater(r["rms"], 0.05)

    def test_too_few_points(self):
        self.assertIn("reason", faceform.fit({"mouth": [0, 0]}, self.t))


if __name__ == "__main__":
    unittest.main()
