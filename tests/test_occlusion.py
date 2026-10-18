import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import occlusion  # noqa: E402
import joints  # noqa: E402

H, W = 400, 200


def body(**low):
    """全部見えている立ち姿。low に名前と (x, y) を渡すと、その関節を見えない（確からしさ 0.1）にして位置を置く"""
    pos = {"nose": (100, 40), "left_eye": (95, 35), "right_eye": (105, 35), "left_ear": (90, 38), "right_ear": (110, 38),
           "left_shoulder": (80, 80), "right_shoulder": (120, 80), "left_elbow": (70, 140), "right_elbow": (130, 140),
           "left_wrist": (65, 190), "right_wrist": (135, 190), "left_hip": (90, 200), "right_hip": (110, 200),
           "left_knee": (88, 290), "right_knee": (112, 290), "left_ankle": (88, 370), "right_ankle": (112, 370)}
    out = []
    for n in joints.NAMES:
        x, y = low.get(n, pos[n])
        out.append({"name": n, "x": x, "y": y, "score": 0.1 if n in low else 0.9})
    return out


def seg_with(cover=None):
    s = np.zeros((H, W), np.uint8)
    s[60:220, 75:125] = 4   # 上着
    if cover:
        x, y = cover
        s[y - 10:y + 10, x - 10:x + 10] = 16   # 物（鞄）
    return s


def states(r):
    return {p["part"]: p["state"] for p in r["problems"]}


class Occlusion(unittest.TestCase):
    def test_all_visible_passes(self):
        self.assertEqual(occlusion.judge(body(), seg_with(), "full body")["problems"], [])

    def test_hand_ending_in_background_is_absent(self):
        r = occlusion.judge(body(left_wrist=(40, 200)), seg_with(), "standing")
        self.assertEqual(states(r), {"left_hand": "absent"})

    def test_hand_behind_object_passes_unless_needed(self):
        pts = body(left_wrist=(100, 150))   # 上着の前（体の陰）
        self.assertEqual(occlusion.judge(pts, seg_with(), "standing")["problems"], [])
        self.assertEqual(states(occlusion.judge(pts, seg_with(), "waving, peace sign")), {"left_hand": "must_see"})

    def test_hands_in_pockets_hides_both(self):
        pts = body(left_wrist=(40, 200), right_wrist=(160, 200))
        self.assertEqual(occlusion.judge(pts, seg_with(), "hands in pockets")["problems"], [])
        self.assertEqual(len(occlusion.judge(pts, seg_with(), "standing")["problems"]), 2)

    def test_cropped_feet_pass_but_full_body_needs_them(self):
        pts = body(left_ankle=(88, 399), right_ankle=(112, 399))
        self.assertEqual(occlusion.judge(pts, seg_with(), "cowboy shot")["problems"], [])
        self.assertEqual(states(occlusion.judge(pts, seg_with(), "full body")), {"left_foot": "must_see", "right_foot": "must_see"})

    def test_profile_allows_only_one_eye(self):
        one = body(right_eye=(150, 30))
        self.assertEqual(occlusion.judge(one, seg_with(), "profile")["problems"], [])
        both = body(left_eye=(50, 30), right_eye=(150, 30))
        self.assertEqual(len(occlusion.judge(both, seg_with(), "profile")["problems"]), 1)
        self.assertEqual(occlusion.judge(both, seg_with(), "from behind")["problems"], [])


if __name__ == "__main__":
    unittest.main()
