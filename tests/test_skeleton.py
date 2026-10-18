"""骨の長さの比（measure.skeleton）: 人の骨格の比なら外れず、あり得ない長さの前腕・脛は外れになるかを見る"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

measure.USER_NORMS = Path(__file__).parent / "no-user-norms.json"


def body(forearm=0.8, shin=0.95):
    """正面に立った体の関節の点。上腕 100 画素、太もも 200 画素を基準に、前腕と脛の長さを比で決める"""
    pts = {}
    for side, x in (("left", 300), ("right", 500)):
        pts[f"{side}_shoulder"] = (x, 200)
        pts[f"{side}_elbow"] = (x, 300)
        pts[f"{side}_wrist"] = (x, 300 + 100 * forearm)
        pts[f"{side}_hip"] = (x + (40 if side == "left" else -40), 500)
        pts[f"{side}_knee"] = (pts[f"{side}_hip"][0], 700)
        pts[f"{side}_ankle"] = (pts[f"{side}_hip"][0], 700 + 200 * shin)
    return [{"name": k, "x": v[0], "y": v[1], "score": 0.9} for k, v in pts.items()]


def flagged(points):
    return {c["path"] for c in measure.judge({"skeleton": measure.skeleton(points)}) if c["path"].startswith("skeleton.")}


class SkeletonTest(unittest.TestCase):
    def test_human_proportions_pass(self):
        self.assertEqual(flagged(body()), set())

    def test_long_forearm_is_flagged(self):
        self.assertIn("skeleton.forearm_upper_max", flagged(body(forearm=1.6)))

    def test_short_shin_is_flagged(self):
        self.assertIn("skeleton.shin_thigh_min", flagged(body(shin=0.4)))

    def test_unreadable_points_are_skipped(self):
        pts = body()
        for q in pts:
            q["score"] = 0.1
        self.assertEqual(measure.skeleton(pts)["left_right_max"], None)


if __name__ == "__main__":
    unittest.main()
