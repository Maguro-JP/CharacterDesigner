import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402


def pose(la_x, ra_x):
    names = {"left_hip": (90, 200), "right_hip": (110, 200), "left_ankle": (la_x, 380), "right_ankle": (ra_x, 380)}
    return [{"name": n, "x": x, "y": y, "score": 0.9} for n, (x, y) in names.items()]


def legs(split: bool):
    s = np.zeros((400, 200), np.uint8)
    if split:
        s[200:390, 70:95] = 6
        s[200:390, 105:130] = 6
    else:
        s[200:390, 70:130] = 6
    return s


class LegsFused(unittest.TestCase):
    def test_apart_ankles_without_gap_is_fused(self):
        self.assertTrue(qc.legs_fused(pose(75, 125), legs(False), "full body, standing")["fused"])

    def test_two_legs_pass(self):
        self.assertFalse(qc.legs_fused(pose(75, 125), legs(True), "full body, standing")["fused"])

    def test_close_ankles_or_overlap_poses_are_not_judged(self):
        self.assertFalse(qc.legs_fused(pose(95, 105), legs(False), "full body, standing")["fused"])
        self.assertFalse(qc.legs_fused(pose(75, 125), legs(False), "full body, crouching")["readable"])


if __name__ == "__main__":
    unittest.main()
