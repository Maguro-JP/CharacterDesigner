"""手の枠の見当（tools/gen/hands.py の auto_boxes）のうち、模型を使わない所の試験。関節の読み取りは差し替える。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import hands  # noqa: E402
import joints  # noqa: E402


def pose(**over):
    base = {n: (0.0, 0.0, 0.0) for n in joints.NAMES}
    base.update(over)
    return [{"name": n, "x": x, "y": y, "score": s} for n, (x, y, s) in base.items()]


def parse(box):
    b, _, a = box.partition(":")
    return [int(v) for v in b.split(",")], float(a)


class AutoBoxes(unittest.TestCase):
    def test_hanging_arm_points_down(self):
        # 下へ垂れた腕: 枠は手首の下、指先を上へ回すので 180 度
        p = pose(nose=(100, 0, .9), left_ankle=(100, 1000, .9), left_elbow=(100, 300, .9), left_wrist=(100, 500, .9))
        with mock.patch.object(joints, "find", return_value=p):
            (box,) = hands.auto_boxes("x.png")
        (x0, y0, x1, y1), ang = parse(box)
        self.assertEqual(abs(ang), 180)
        self.assertEqual(((x0 + x1) // 2, (y0 + y1) // 2), (100, 600))  # 手首から前腕の 0.5 倍先
        self.assertEqual(x1 - x0, 220)                                     # 前腕の 1.1 倍

    def test_arm_to_the_right_rotates_90(self):
        p = pose(nose=(0, 0, .9), left_ankle=(0, 1000, .9), left_elbow=(100, 300, .9), left_wrist=(300, 300, .9))
        with mock.patch.object(joints, "find", return_value=p):
            (box,) = hands.auto_boxes("x.png")
        self.assertEqual(parse(box)[1], 90)

    def test_low_score_arm_is_skipped(self):
        p = pose(nose=(0, 0, .9), left_ankle=(0, 1000, .9), left_elbow=(100, 300, .1), left_wrist=(100, 500, .9))
        with mock.patch.object(joints, "find", return_value=p):
            self.assertEqual(hands.auto_boxes("x.png"), [])

    def test_upper_body_uses_shoulders_not_ankles(self):
        # 足首が読めない上半身の絵: 縮んだ前腕（20 画素）でも、肩幅 200×4 の 4.5% を半径の下限にする
        p = pose(nose=(200, 0, .9), left_shoulder=(300, 100, .9), right_shoulder=(100, 100, .9),
                 left_ankle=(200, 5000, .1), left_elbow=(300, 300, .9), left_wrist=(300, 320, .9))
        with mock.patch.object(joints, "find", return_value=p):
            (box,) = hands.auto_boxes("x.png")
        (x0, _, x1, _), _ = parse(box)
        self.assertEqual(x1 - x0, 72)


if __name__ == "__main__":
    unittest.main()
