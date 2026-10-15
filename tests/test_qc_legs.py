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


class AutoCheckTest(unittest.TestCase):
    def test_check_failure_is_not_a_pass(self):
        # 検品が落ちても（読めない絵）、通ったことにしない
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            r = qc.auto_check(f"{d}/missing.png", "arachne")
        self.assertFalse(r["ok"])
        self.assertTrue(r["unreadable"])

    def test_plain_image_passes_and_writes_report(self):
        import json
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            Image.new("RGB", (64, 64), (255, 255, 255)).save(f"{d}/a.png")
            r = qc.auto_check(f"{d}/a.png", "1girl")
            saved = json.loads(Path(f"{d}/a.png.qc.json").read_text())
        self.assertEqual(r["problems"], [])
        self.assertEqual(saved["ok"], r["ok"])


class UnseenLegsTest(unittest.TestCase):
    def test_unseen_knees_are_unreadable_not_absent(self):
        # 蜘蛛の胴の上に立つ人の脚は、骨格の模型が膝と足首を見つけられず確からしさ 0.13 になった。「無い」と返さない
        r = qc.human_legs(points(shoulder=300, hip=500, knee=600, ankle=650, score=0.13), 1216)
        self.assertFalse(r["readable"])
        self.assertIsNone(r["legs"])


class EyeMismatchTest(unittest.TestCase):
    def test_front_face_with_big_difference_is_flagged(self):
        r = qc.eye_mismatch({"found": 2, "area_ratio": 2.52, "yaw_offset": -0.065})
        self.assertTrue(r["mismatch"])

    def test_turned_face_allows_smaller_far_eye(self):
        # 横を向いた顔（向き 0.238）の 2.89 は崩れではない
        r = qc.eye_mismatch({"found": 2, "area_ratio": 2.89, "yaw_offset": 0.238})
        self.assertFalse(r["mismatch"])

    def test_unread_eyes_are_not_a_pass(self):
        self.assertFalse(qc.eye_mismatch({"found": 1, "reason": "横に並ぶ2つの目が読めない"})["readable"])


class PersonFoundTest(unittest.TestCase):
    def pts(self, face, shoulders):
        names = {"nose": face, "left_eye": face, "right_eye": face, "left_shoulder": shoulders, "right_shoulder": shoulders}
        return [{"name": n, "x": 0, "y": 0, "score": v} for n, v in names.items()]

    def test_spider_only_picture_has_no_person(self):
        # 人を落として蜘蛛だけを描いた絵: 顔 0.25、肩 0.07
        self.assertFalse(qc.person_found(self.pts(0.25, 0.07))["found"])

    def test_person_is_found(self):
        self.assertTrue(qc.person_found(self.pts(0.64, 0.8))["found"])


@unittest.skipUnless(__import__("importlib").util.find_spec("scipy") is not None, "scipy が無い（.cache/gen/lib に入る）")
class EdgeCutBackgroundTest(unittest.TestCase):
    def test_gradient_background_is_not_reported_as_cut(self):
        import tempfile
        import numpy as np
        from PIL import Image
        a = np.zeros((200, 160, 3), "uint8")
        a[...] = np.linspace(40, 200, 200, dtype="uint8")[:, None, None]   # 上から下へ明るくなる背景
        with tempfile.TemporaryDirectory() as d:
            Image.fromarray(a).save(f"{d}/g.png")
            r = qc.auto_check(f"{d}/g.png", "1girl")
        # 辺に沿ってゆっくり変わる背景は、切れとも読めないとも言わない
        self.assertFalse(any("edge_cut" in x for x in r["problems"] + r["unreadable"]))


class LightHairTest(unittest.TestCase):
    def test_light_hair_words(self):
        # 銀髪を頼んだ絵では、髪の白飛びを崩れに数えない（言葉の一覧に入っていること）
        self.assertTrue(any(w in "1girl, long silver hair" for w in qc.LIGHT_HAIR))
        self.assertFalse(any(w in "1girl, short brown hair" for w in qc.LIGHT_HAIR))


try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
class EdgeCutTest(unittest.TestCase):
    def test_figure_touching_bottom_is_cut(self):
        import numpy as np
        a = np.zeros((200, 160, 3), "uint8")
        a[...] = np.linspace(40, 200, 200, dtype="uint8")[:, None, None]   # なだらかに変わる背景
        a[120:200, 60:100] = (20, 10, 60)                                     # 下の辺にかかった人物
        self.assertEqual(qc.edge_cut(a), ["下"])


class FixedRestrictionTest(unittest.TestCase):
    def test_minor_and_sexual_tags_are_caught(self):
        # 絵から読んだタグにも、言葉の判定と同じ固定の制限をかける（filters.fixed）
        import filters
        self.assertIsNotNone(filters.fixed("1girl, child, nude"))
        self.assertIsNone(filters.fixed("1girl, breasts, navel"))


class HoldTest(unittest.TestCase):
    def test_restricted_picture_is_moved_out(self):
        import tempfile
        from unittest import mock
        from PIL import Image
        import tagger
        with tempfile.TemporaryDirectory() as d:
            Image.new("RGB", (64, 64), (255, 255, 255)).save(f"{d}/a.png")
            with mock.patch.object(tagger, "read", return_value={"child": 0.9, "nude": 0.9}):
                r = qc.auto_check(f"{d}/a.png", "1girl")
            self.assertFalse(Path(f"{d}/a.png").exists())
            self.assertTrue(Path(f"{d}/held/a.png").exists())
            self.assertTrue(Path(f"{d}/held/a.png.qc.json").exists())
        self.assertFalse(r["ok"])
