"""しわを置く場所（tools/gen/folds.py）のうち、模型を使わない所の試験。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import folds  # noqa: E402

NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
         "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def body(right_wrist, score=0.9):
    """立った人の関節。右腕だけ手首の位置を変えて曲げる"""
    at = {"left_shoulder": (140, 100), "right_shoulder": (60, 100), "left_elbow": (150, 160), "right_elbow": (50, 160),
          "left_wrist": (155, 220), "right_wrist": right_wrist, "left_hip": (125, 220), "right_hip": (75, 220),
          "left_knee": (125, 300), "right_knee": (75, 300), "left_ankle": (125, 380), "right_ankle": (75, 380)}
    return [{"name": n, "x": at.get(n, (100, 50))[0], "y": at.get(n, (100, 50))[1], "score": score} for n in NAMES]


class Bend(unittest.TestCase):
    def test_straight_and_folded(self):
        self.assertAlmostEqual(folds.bend((0, 0), (0, 10), (0, 20)), 0, places=3)
        self.assertAlmostEqual(folds.bend((0, 0), (0, 10), (10, 10)), 90, places=3)

    def test_inner_points_to_the_hollow(self):
        n = folds.inner((0, 0), (0, 10), (10, 10))   # 下へ伸びて右へ曲がる。へこむ側は右上
        self.assertGreater(n[0], 0)
        self.assertLess(n[1], 0)


class Sites(unittest.TestCase):
    def setUp(self):
        self.lab = np.full((400, 200), 4)             # 全部が上着

    def test_bent_elbow_only(self):
        kinds = {(s["kind"], s["side"]) for s in folds.sites(body((110, 150)), self.lab)}
        self.assertIn(("elbow", "right"), kinds)       # 曲げた右肘にだけ置く
        self.assertNotIn(("elbow", "left"), kinds)     # まっすぐな左肘には置かない

    def test_nothing_without_joints(self):
        self.assertEqual(folds.sites(body((110, 150), score=0.1), self.lab), [])

    def test_not_on_bare_skin(self):
        self.assertEqual(folds.sites(body((110, 150)), np.full((400, 200), 14)), [])   # 腕の肌（部位 14）には置かない

    def test_belt_above_shoulders_is_ignored(self):
        lab = self.lab.copy()
        lab[60:80, 80:120] = 8                         # 肩（y 100）より上の「ベルト」は首元の結び目の取り違え
        self.assertNotIn("belt", {s["kind"] for s in folds.sites(body((50, 220)), lab)})


class Drop(unittest.TestCase):
    def test_long_skirt_hangs_from_hip(self):
        lab = np.zeros((400, 200), int)
        lab[90:220] = 4                                # 上着
        lab[220:360, 40:160] = 5                       # 腰から長く垂れるスカート
        drops = [s for s in folds.sites(body((50, 220)), lab) if s["kind"] == "drop"]
        self.assertEqual({s["side"] for s in drops}, {"left", "right"})
        self.assertTrue(all(s["hem"] > 340 for s in drops))

    def test_no_drop_for_trousers_or_short_hem(self):
        lab = np.zeros((400, 200), int)
        lab[90:220] = 4
        lab[220:380, 40:160] = 6                       # ズボンは脚に沿ってつっぱる
        self.assertFalse([s for s in folds.sites(body((50, 220)), lab) if s["kind"] == "drop"])
        lab[220:380] = 0
        lab[220:230, 40:160] = 5                       # 腰のすぐ下で終わる裾
        self.assertFalse([s for s in folds.sites(body((50, 220)), lab) if s["kind"] == "drop"])


if __name__ == "__main__":
    unittest.main()
