"""頼んだ姿勢（腕を上げる・手を腰に・座る/しゃがむ）が関節の形に出ていない絵を数える。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402


def body(**over):
    # 立ち姿: 鼻 100、肩 200、腰 400、膝 580、手首は腰の横
    pts = {"nose": (100, 100), "left_shoulder": (130, 200), "right_shoulder": (70, 200), "left_hip": (120, 400),
           "right_hip": (80, 400), "left_knee": (120, 580), "right_knee": (80, 580), "left_wrist": (170, 420),
           "right_wrist": (30, 420)}
    pts.update(over)
    return [{"name": k, "x": x, "y": y, "score": 0.9} for k, (x, y) in pts.items()]


class PoseMissing(unittest.TestCase):
    def test_standing_when_crouch_asked(self):
        self.assertEqual(len(qc.pose_missing(body(), "full body, crouching")), 1)

    def test_crouching_passes(self):
        self.assertEqual(qc.pose_missing(body(left_knee=(140, 410), right_knee=(60, 410)), "full body, crouching"), [])

    def test_arms_up(self):
        self.assertEqual(len(qc.pose_missing(body(), "arms raised above head")), 1)
        self.assertEqual(qc.pose_missing(body(left_wrist=(150, 60)), "arms raised above head"), [])

    def test_hand_on_hip(self):
        self.assertEqual(qc.pose_missing(body(left_wrist=(125, 410)), "cowboy shot, hand on hip"), [])
        # 両手を前に組んだ（腰から離れた）形
        self.assertEqual(len(qc.pose_missing(body(left_wrist=(110, 300), right_wrist=(90, 300)), "cowboy shot, hand on hip")), 1)

    def test_not_asked(self):
        self.assertEqual(qc.pose_missing(body(), "full body, standing"), [])


if __name__ == "__main__":
    unittest.main()
