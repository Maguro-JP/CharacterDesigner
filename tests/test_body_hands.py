"""頭身（body.heads）と手の見え方（hands.shown）の測り方と基準。模型は使わず、骨格の点と部位分けを作って渡す"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402


def points(eye_y, ankle_y=950, wrist=(300, 500), score=0.9):
    p = {n: (500, 500) for n in ("nose", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                                  "left_hip", "right_hip", "left_knee", "right_knee")}
    p.update({"left_eye": (480, eye_y), "right_eye": (520, eye_y), "left_ankle": (480, ankle_y), "right_ankle": (520, ankle_y),
              "left_wrist": wrist, "right_wrist": wrist})
    return [{"name": n, "x": float(x), "y": float(y), "score": score} for n, (x, y) in p.items()]


def seg(hand=True):
    s = np.zeros((1000, 1000), np.uint8)
    s[0:1000, 400:600] = 4
    s[20:90, 470:530] = 11
    if hand:
        s[490:510, 290:310] = 14
    return s


class BodyHands(unittest.TestCase):
    def judged(self, m):
        return {b["path"] for b in measure.judge(m)}

    def test_child_heads_rejected_only_when_adult_asked(self):
        m = {"body": measure.proportion(points(eye_y=150), seg(), "1girl, adult woman")}
        self.assertLess(m["body"]["heads"], 4.5)
        self.assertIn("body.heads", self.judged(m))
        m = {"body": measure.proportion(points(eye_y=150), seg(), "1girl")}
        self.assertNotIn("body.heads", self.judged(m))

    def test_adult_heads_pass(self):
        m = {"body": measure.proportion(points(eye_y=70), seg(), "mature woman")}
        self.assertGreater(m["body"]["heads"], 6)
        self.assertNotIn("body.heads", self.judged(m))

    def test_unreadable_ankles_not_judged(self):
        self.assertIsNone(measure.proportion(points(70, score=0.1), seg(), "adult")["heads"])

    def test_hidden_hands_rejected(self):
        m = {"hands": measure.hands_seen(points(70), seg(hand=False), "")}
        self.assertIn("hands.shown", self.judged(m))
        m = {"hands": measure.hands_seen(points(70), seg(hand=True), "")}
        self.assertNotIn("hands.shown", self.judged(m))

    def test_hands_behind_back_excluded(self):
        self.assertIsNone(measure.hands_seen(points(70), seg(hand=False), "hands behind back")["shown"])


if __name__ == "__main__":
    unittest.main()
