import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import numpy as np  # noqa: F401
    import qc
except ImportError:  # numpy が無い環境
    qc = None


def body(forearm=100):
    pts = {"left_shoulder": (300, 200), "right_shoulder": (200, 200), "left_hip": (290, 400), "right_hip": (210, 400),
           "left_elbow": (310, 320), "right_elbow": (190, 320), "left_wrist": (312, 320 + forearm),
           "right_wrist": (188, 320 + forearm), "left_knee": (290, 600), "right_knee": (210, 600),
           "left_ankle": (290, 800), "right_ankle": (210, 800)}
    return [{"name": k, "x": x, "y": y, "score": 0.9} for k, (x, y) in pts.items()]


@unittest.skipIf(qc is None, "numpy が無い")
class ProportionDriftTest(unittest.TestCase):
    def test_same_body_has_no_drift(self):
        p = qc.proportions(body())
        self.assertEqual(qc.proportion_drift(p, p)["off"], {})

    def test_long_forearm_is_found(self):
        d = qc.proportion_drift(qc.proportions(body()), qc.proportions(body(130)))
        self.assertEqual(set(d["off"]), {"forearm_l", "forearm_r"})

    def test_missing_torso_points(self):
        self.assertEqual(qc.proportions([p for p in body() if "hip" not in p["name"]]), {})


if __name__ == "__main__":
    unittest.main()


try:
    import scipy  # noqa: F401
except ImportError:  # scipy は .cache/gen/lib にだけある
    scipy = None


@unittest.skipIf(qc is None or scipy is None, "numpy か scipy が無い")
class BackgroundTest(unittest.TestCase):
    def test_clutter_and_part_color(self):
        import numpy as np
        rgb = np.full((300, 200, 3), 255, np.uint8)
        seg = np.zeros((300, 200), np.uint8)
        seg[100:250, 80:120] = 4
        rgb[100:250, 80:120] = (36, 48, 79)
        self.assertEqual(qc.background_clutter(rgb, seg), 0.0)
        for y in range(10, 290, 20):                                     # 点の模様（4 画素角の点）
            for x in range(5, 195, 20):
                rgb[y:y + 4, x:x + 4] = (250, 220, 0)
        self.assertGreater(qc.background_clutter(rgb, seg), 0.005)
        self.assertEqual(qc.part_color(rgb, seg, [4]), [36.0, 48.0, 79.0])
