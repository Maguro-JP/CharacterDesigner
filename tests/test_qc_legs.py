"""人の脚が残っているか（tools/gen/qc.py human_legs）の試験。骨格の点を直接作って渡す。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402

NAMES = ["left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def points(shoulder=200, hip=450, knee=650, ankle=850, score=0.8):
    ys = dict(shoulder=shoulder, hip=hip, knee=knee, ankle=ankle)
    return [{"name": n, "x": 0, "y": ys[n.split("_")[1]], "score": score} for n in NAMES]


class HumanLegsTest(unittest.TestCase):
    def test_standing_human_has_legs(self):
        r = qc.human_legs(points(), 1216)
        self.assertTrue(r["readable"])
        self.assertTrue(r["legs"])

    def test_short_low_confidence_legs_are_not_counted(self):
        # 人の脚の無いアラクネ: 足首は腰のすぐ下で、確からしさも低い（実際の絵で 0.41）
        r = qc.human_legs(points(shoulder=300, hip=460, knee=520, ankle=600, score=0.45), 1216)
        self.assertFalse(r["legs"])

    def test_whole_image_read_as_person_is_unreadable(self):
        # 胴が絵の高さの 4 割を超える: 骨格の模型が人以外を人と読んでいる。黙って「脚なし」にしない
        r = qc.human_legs(points(shoulder=100, hip=620), 1216)
        self.assertFalse(r["readable"])
        self.assertIsNone(r["legs"])
