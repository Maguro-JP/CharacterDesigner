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

    def test_light_hair_limit_between_judged(self):
        # 検品担当が通した銀髪 0.031 は許し、戻した銀髪 0.081 は崩れに数える上限であること
        self.assertTrue(0.031 <= qc.LIGHT_HAIR_BLOWN_MAX < 0.081)


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


class LegsMarginTest(unittest.TestCase):
    def test_score_just_above_line_is_unreadable(self):
        # 股のしわ（0.49）と本当の脚（0.54）は差が小さい。線のすぐ上は「ある」と言い切らない
        r = qc.human_legs(points(shoulder=300, hip=500, knee=600, ankle=722, score=0.45), 1216)
        self.assertGreaterEqual(r["score"], 0.45)
        self.assertLess(r["score"], 0.55)
        self.assertFalse(r["readable"])


class ScoreTest(unittest.TestCase):
    def test_lighter_defects_score_higher(self):
        bad = {"problems": [{"human_legs": {}}, {"edge_cut": ["下"]}], "unreadable": []}
        light = {"problems": [{"measure": {"path": "eyes.iris_delta"}}], "unreadable": []}
        clean = {"problems": [], "unreadable": []}
        self.assertLess(qc.score(bad), qc.score(light))
        self.assertEqual(qc.score(clean), 100)
        self.assertEqual(qc.score({"problems": [{"fixed_restriction": "x"}], "unreadable": []}), 0)


class EyesByTagsTest(unittest.TestCase):
    def test_colored_or_closed_eyes_count(self):
        self.assertTrue(qc.eyes_by_tags({"1girl": 1.0, "purple eyes": 0.49}))
        self.assertTrue(qc.eyes_by_tags({"closed eyes": 0.43}))

    def test_faceless_or_masked_do_not(self):
        # 顔の無い絵（目のタグが無い）、顔が黒く塗れた絵（mask）、目の色でない言葉、低い確からしさ
        self.assertFalse(qc.eyes_by_tags({"1girl": 0.97, "looking at viewer": 0.25}))
        self.assertFalse(qc.eyes_by_tags({"purple eyes": 0.52, "mask": 0.53}))
        self.assertFalse(qc.eyes_by_tags({"hair between eyes": 0.57, "extra eyes": 0.3}))
        self.assertFalse(qc.eyes_by_tags({"blue eyes": 0.2}))


class ExtraEyesTest(unittest.TestCase):
    def _check(self, value):
        import tempfile
        from unittest import mock
        from PIL import Image
        import tagger
        with tempfile.TemporaryDirectory() as d:
            Image.new("RGB", (64, 64), (255, 255, 255)).save(f"{d}/a.png")
            with mock.patch.object(tagger, "read", return_value={"1girl": 1.0, "extra eyes": value}):
                return qc.auto_check(f"{d}/a.png", "1girl")

    def test_high_extra_eyes_is_a_problem(self):
        # 瞳が消え光る線になった目（0.53）は崩れ。崩れの無い絵の 0.22〜0.30 は数えない
        self.assertIn({"extra_eyes": 0.53}, self._check(0.53)["problems"])
        self.assertNotIn("extra_eyes", [k for p in self._check(0.3)["problems"] for k in p])


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
class EyeHintTest(unittest.TestCase):
    """骨格の点の目の位置があれば、それに近い塊を目にする（顔の縁の髪の筋を目と取り違えない）"""

    def _face(self):
        import numpy as np
        import edit
        rgb = np.ones((200, 200, 3), np.float32)
        seg = np.zeros((200, 200), np.uint8)
        seg[20:180, 20:180] = edit.LABELS["face"]
        rgb[60:110, 22:30] = 0.05          # 顔の縁の髪の筋（縦長、大きい）
        rgb[90:96, 60:72] = 0.05           # 遠い側の小さな目
        rgb[85:93, 120:150] = 0.05         # 近い側の目
        return rgb, seg

    def test_hint_picks_eyes_not_hair(self):
        import measure
        import edit
        rgb, seg = self._face()
        e = measure.eyes(rgb, seg, edit.LABELS, hint=[(66, 93), (135, 89)])
        self.assertEqual(e["found"], 2)
        self.assertGreater(e["left"]["cx"], 50)

    def test_no_eye_near_hint_is_unreadable(self):
        import measure
        import edit
        rgb, seg = self._face()
        self.assertLess(measure.eyes(rgb, seg, edit.LABELS, hint=[(66, 160), (135, 160)])["found"], 2)


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
class SpiderLegsTest(unittest.TestCase):
    """体の下端の暗い塊で蜘蛛の脚の先を数える。地面の影（明るい灰）は数えない"""

    def _legs(self, n, shadow=False):
        import numpy as np
        rgb = np.ones((400, 400, 3), np.float32)
        alpha = np.zeros((400, 400), bool)
        rgb[50:300, 150:250] = 0.1                     # 胴
        alpha[50:300, 150:250] = True
        for i in range(n):
            x = 20 + i * 45
            rgb[200:380, x:x + 12] = 0.1               # 床まで届く脚
            alpha[200:380, x:x + 12] = True
        if shadow:
            rgb[370:390, 0:400] = 0.6                  # 脚の先をつなぐ地面の影
            alpha[370:390, 0:400] = True
            rgb[200:380, 20:380:45] = 0.1
        return qc.spider_legs(rgb, alpha)

    def test_counts_tips(self):
        self.assertEqual(self._legs(8)["count"], 8)
        self.assertEqual(self._legs(6)["count"], 6)

    def test_light_shadow_is_not_counted(self):
        self.assertEqual(self._legs(8, shadow=True)["count"], 8)


class HandBoxTest(unittest.TestCase):
    """手の枠と回す角度（qc.hand_boxes）。hands.measure は偽物に替え、手の模型を使わない"""

    def arm(self, elbow, wrist, score=0.9, side="left"):
        return [{"name": f"{side}_elbow", "x": elbow[0], "y": elbow[1], "score": 0.9},
                {"name": f"{side}_wrist", "x": wrist[0], "y": wrist[1], "score": score}]

    def test_hanging_arm_box_below_wrist_turned_upside_down(self):
        b = qc.hand_boxes(self.arm((100, 100), (100, 200)))[0]
        # 前腕 100、手の中心は手首から 35 下、枠は 60 四方。指先が下なので 180 度回す
        self.assertEqual(b["box"], (70, 205, 130, 265))
        self.assertEqual(b["angle"], 180)

    def test_arm_pointing_right_turns_left_90(self):
        b = qc.hand_boxes(self.arm((0, 0), (100, 0)))[0]
        self.assertEqual(b["box"], (105, -30, 165, 30))
        self.assertEqual(b["angle"], 90)

    def test_arm_pointing_left_and_up(self):
        self.assertEqual(qc.hand_boxes(self.arm((100, 0), (0, 0)))[0]["angle"], 270)
        self.assertEqual(qc.hand_boxes(self.arm((0, 100), (0, 0)))[0]["angle"], 0)

    def test_unsure_wrist_is_skipped(self):
        self.assertEqual(qc.hand_boxes(self.arm((0, 0), (0, 100), score=0.4)), [])

    def test_hands_auto_bad_and_unreadable(self):
        from unittest import mock
        from PIL import Image
        import hands
        im = Image.new("RGB", (300, 300), (255, 255, 255))
        seen = []

        def fake(crop):
            seen.append(crop.size)
            return {}, ["index の手の色 0.4（0.85〜1.01）"], None
        with mock.patch.object(hands, "measure", fake):
            r = qc.hands_auto(self.arm((100, 50), (100, 150)) + self.arm((200, 50), (200, 150), side="right"), im)
        self.assertEqual(seen, [(60, 60), (60, 60)])
        self.assertTrue(r["readable"] and r["bad"])
        self.assertFalse(qc.hands_auto([], im)["readable"])
