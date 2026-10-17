"""頼んだ手の姿勢（tools/gen/measure.py hands_pose）の試験。骨格の点を直接作って渡す。
数字は hands behind back を頼んで手が横に出た絵（w-3101-3101）の骨格の点から取った。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

# 共通の基準だけで試す。利用者の判定から学んだ基準（config/norms.user.json）で結果が変わらないように
measure.USER_NORMS = Path(__file__).parent / "no-user-norms.json"

ASK = "1woman, standing, hands behind back"


def points(lw=(328, 381, 0.83), rw=(176, 362, 0.72)):
    xy = {"left_shoulder": (316, 172, 0.84), "right_shoulder": (220, 174, 0.85), "left_hip": (274, 370, 0.66),
          "right_hip": (212, 368, 0.69), "left_wrist": lw, "right_wrist": rw}
    return [{"name": k, "x": v[0], "y": v[1], "score": v[2]} for k, v in xy.items()]


def outlier(pose):
    return [b for b in measure.judge({"pose": pose}) if b["path"] == "pose.behind_out"]


class HandsBehindBackTest(unittest.TestCase):
    def test_hands_at_sides_fail(self):
        r = measure.hands_pose(points(), ASK)
        self.assertAlmostEqual(r["behind_out"], 0.562, places=2)
        self.assertTrue(outlier(r))

    def test_hidden_wrists_pass(self):
        # 胴に隠れた手首は確からしさが下がる。見えない手首は外に出ていると数えない
        r = measure.hands_pose(points(lw=(330, 380, 0.2), rw=(170, 360, 0.3)), ASK)
        self.assertEqual(r["behind_out"], 0.0)
        self.assertFalse(outlier(r))

    def test_wrists_inside_hips_pass(self):
        r = measure.hands_pose(points(lw=(265, 375, 0.8), rw=(220, 375, 0.8)), ASK)
        self.assertEqual(r["behind_out"], 0.0)

    def test_not_asked_is_not_judged(self):
        r = measure.hands_pose(points(), "1woman, standing")
        self.assertIsNone(r["behind_out"])
        self.assertFalse(outlier(r))

    def test_no_points_is_not_judged(self):
        self.assertIsNone(measure.hands_pose(None, ASK)["behind_out"])


if __name__ == "__main__":
    unittest.main()
