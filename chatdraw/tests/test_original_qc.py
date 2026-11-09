"""CharacterDesigner 独自の作画監督（chatdraw/origqc.py）: 数字の外れを崩れと直す所にし、利用者の判定から基準を学び直して次の検品に効かせる"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chatdraw import omakase, origqc  # noqa: E402


class OutliersTest(unittest.TestCase):
    def test_every_outlier_gets_a_region(self):
        outs = [{"path": "face.rms", "value": 0.0912, "min": None, "max": 0.07, "means": "顔の点が1つの頭の向きで説明できない（説明）"},
                {"path": "hair.blown", "value": 0.2, "min": None, "max": 0.03, "means": "髪が白く飛んで形が消えている"},
                {"path": "light.inverted", "value": 1, "min": None, "max": 0, "means": "影が光より明るい"},
                {"path": "colors.mismatch", "value": 1, "min": None, "max": 0, "means": "頼んだ色と違う", "kind": "request"}]
        boxes = {"face": (10, 10, 50, 60), "hair": (5, 0, 60, 40), "body": (0, 0, 90, 100)}
        res = origqc.from_outliers(outs, boxes, (100, 100))
        self.assertEqual(len(res["bad"]), 3)                      # 指示との違いは崩れに数えない
        self.assertIn("face.rms = 0.091", res["bad"][0])
        # 見つけた崩れは全部、直す所として返す（描き直しに逃がさない）
        self.assertEqual(res["regions"], [((10, 10, 50, 60), "face"), ((5, 0, 60, 40), "hair"), ((0, 0, 90, 100), "body")])

    def test_unreadable_part_falls_back_to_whole(self):
        res = origqc.from_outliers([{"path": "eyes.found", "value": 1, "min": 2, "max": None, "means": "両目が読めない"}], {}, (64, 48))
        self.assertEqual(res["regions"], [((0, 0, 64, 48), "face")])

    def test_boxes_from_parts(self):
        parts = Image.new("L", (100, 100), 0)
        parts.paste(4, (20, 30, 80, 100))
        parts.paste(origqc.FACE_LABEL, (40, 20, 60, 50))
        b = origqc.boxes_from_parts(parts, (100, 100))
        x0, y0, x1, y1 = b["face"]
        self.assertTrue(x0 < 40 and y0 < 20 and x1 > 59 and y1 > 49)
        self.assertNotIn("hair", b)
        self.assertEqual(b["body"][3], 100)

    def test_missing_parts_is_reported_not_hidden(self):
        with mock.patch.object(origqc, "missing", lambda: ["scipy"]):
            res = origqc.check(Image.new("RGB", (64, 64)), "1girl")
        self.assertFalse(res["measured"])
        self.assertEqual(res["bad"], [])
        self.assertIn("scipy", res["notes"][0])                  # 測っていないことを隠さない

    def test_tiny_image_is_not_measured_and_says_so(self):
        with mock.patch.object(origqc, "missing", lambda: []), \
             mock.patch.object(origqc, "_setup", side_effect=AssertionError("測らない")):
            res = origqc.check(Image.new("RGB", (64, 64)), "1girl")
        self.assertFalse(res["measured"])
        self.assertIn("小さい", res["notes"][0])

    def test_unmeasurable_image_is_a_fault(self):
        fake = mock.Mock()
        fake.measure.side_effect = RuntimeError("顔が無い")
        with mock.patch.object(origqc, "missing", lambda: []), \
             mock.patch.object(origqc, "_setup", lambda: (fake, None)):
            res = origqc.check(Image.new("RGB", (256, 256)), "1girl")
        self.assertFalse(res["readable"])                         # 読めない物は崩れ
        self.assertTrue(res["bad"])
        self.assertEqual(res["regions"], [((0, 0, 256, 256), "body")])   # 崩れとして直す所も返す


class OmakaseUsesOriginalQcTest(unittest.TestCase):
    def test_default_check_adds_original_qc(self):
        hc = {"readable": True, "bad": ["手 1: 指が 6 本"], "hands": []}
        own = {"readable": True, "bad": ["数字の検品: 髪が白く飛んで形が消えている（hair.blown = 0.2）"],
               "regions": [((1, 2, 3, 4), "face")], "measured": True, "notes": []}
        with mock.patch("chatdraw.handcheck.check", lambda im, asked="": hc), \
             mock.patch("chatdraw.handcheck.bad_regions", lambda res: []), \
             mock.patch("chatdraw.handcheck.detail_regions", lambda res: []), \
             mock.patch("chatdraw.requestcheck.check", lambda im, p: {"readable": True, "missing": [], "people": []}), \
             mock.patch.object(origqc, "check", lambda im, p: own):
            res = omakase._default_check(Image.new("RGB", (8, 8)), "1girl")
        self.assertEqual(len(res["bad"]), 2)
        self.assertIn(((1, 2, 3, 4), "face"), res["regions"])
        self.assertTrue(res["readable"])


class OmakaseFixesFoundFaultsTest(unittest.TestCase):
    """数字の検品が見つけた髪の崩れを、おまかせが囲みの中だけ直し、直したあとで検品し直す"""

    def test_hair_fault_is_fixed_then_rechecked(self):
        import os
        from chatdraw.tests import test_omakase as t
        bad = {"readable": True, "bad": ["数字の検品: 髪が白く飛んで形が消えている（hair.blown = 0.2）"],
               "regions": [([10, 10, 20, 20], "hair")]}
        seen = []

        def check(image, prompt):
            seen.append(image.getpixel((15, 15)))
            return bad if len(seen) == 1 else t.OK
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            log, st = [], t.FakeStudio(Path(d))
            omakase.draw(st, "髪の長い女の子", 1, lambda m: None, have=[t.COMPOSE, t.HANDS, t.FACES],
                         painter_for=lambda m: t.FakePainter(m.repo, log), check=check, size=(128, 192))
            image, meta = st.saved
        self.assertIn("redraw", [e[0] for e in log])                       # 描き直しに逃がさず、直す
        self.assertEqual(seen[1], (10, 10, 10))                            # 直した絵を検品し直した
        self.assertEqual(image.getpixel((0, 0)), (180, 180, 180))           # 囲みの外は変えない
        self.assertIn("髪の直し", [s["stage"] for s in meta["omakase"]["steps"]])
        self.assertTrue(meta["passed"])


class EyeDoubtTest(unittest.TestCase):
    """目と口の点が確かでないときは、瞳の色と顔の形の外れを出さず、測れなかった崩れ（eyes.unsure）として顔の囲みで直す"""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import measure
        self.m = measure

    @staticmethod
    def pair(lw=20, lh=10, rw=20, rh=10, dy=0, la=150, ra=150):
        return {"found": 2, "left": {"cx": 100, "cy": 100, "w": lw, "h": lh, "area": la},
                "right": {"cx": 160, "cy": 100 + dy, "w": rw, "h": rh, "area": ra}}

    def test_sure_pair_is_measured(self):
        self.assertEqual(self.m.eye_doubt(self.pair(), 120), "")
        self.assertEqual(self.m.eye_doubt({"found": 1}, 20), "")      # 両目が読めないのは eyes.found が見る

    def test_doubtful_pairs(self):
        self.assertIn("小さい", self.m.eye_doubt(self.pair(), 26))               # 元の絵で顔の幅 26 画素
        self.assertIn("縦に細長い", self.m.eye_doubt(self.pair(rw=9, rh=82), 120))  # 髪の筋を目と取った
        self.assertIn("高さ", self.m.eye_doubt(self.pair(dy=-45), 120))          # 耳飾りとあごの影
        self.assertIn("大きさ", self.m.eye_doubt(self.pair(la=80, ra=590), 120))

    def test_unsure_is_a_face_fault_not_iris_or_form(self):
        m = {"eyes": {"found": 2, "unsure": 1, "iris_delta": None}, "face": {"reason": "顔が小さい"}}
        outs = self.m.judge(m, json.loads(self.m.NORMS.read_text(encoding="utf-8")))
        self.assertEqual([o["path"] for o in outs], ["eyes.unsure"])            # 崩れとして逃がさない
        res = origqc.from_outliers(outs, {"face": (1, 2, 3, 4), "body": (0, 0, 9, 9)}, (10, 10))
        self.assertEqual(res["regions"], [((1, 2, 3, 4), "face")])              # 顔の囲みで描き直す

    def test_sure_pair_keeps_iris_check(self):
        m = {"eyes": {"found": 2, "unsure": 0, "iris_delta": 0.2}, "face": {"rms": 0.03}}
        outs = self.m.judge(m, json.loads(self.m.NORMS.read_text(encoding="utf-8")))
        self.assertEqual([o["path"] for o in outs], ["eyes.iris_delta"])


class LearnTest(unittest.TestCase):
    """利用者の判定（★、戻す）から学んだ基準が、次の検品の判定に効く"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        from chatdraw import paths
        self.p = mock.patch.object(paths, "data_home", lambda: self.d)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_learned_norm_applies_to_next_judge(self):
        measure, normlearn = origqc._setup()
        self.assertEqual(normlearn.RECORDS, self.d / "learn" / "records.jsonl")   # 利用者のデータの置き場（入れた場所は書けない）
        self.assertEqual(measure.USER_NORMS, self.d / "learn" / "norms.user.json")
        # 髪の飛びが 0.02 の絵を利用者が 2 枚戻し、0.005 の絵を 2 枚通した → 共通の基準 0.03 では見逃す 0.02 を外れにする
        recs = [{"src": f"r{i}.png", "verdict": "reject", "by": "user", "reason": "髪が白く飛んでいる", "topics": ["hair"],
                 "flagged": [], "measure": {"hair": {"blown": 0.02 + i * 0.001}}} for i in range(2)]
        recs += [{"src": f"p{i}.png", "verdict": "pass", "by": "user", "reason": "", "topics": [], "flagged": [],
                  "measure": {"hair": {"blown": 0.005}}} for i in range(2)]
        normlearn.RECORDS.parent.mkdir(parents=True)
        normlearn.RECORDS.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
        m = {"hair": {"blown": 0.02}}
        self.assertNotIn("hair.blown", [o["path"] for o in measure.judge(m)])   # 学ぶ前は見逃す
        got = normlearn.learn()
        self.assertTrue(got["written"])
        self.assertIn("hair.blown", [o["path"] for o in measure.judge(m)])      # 学んだあとは崩れとして見つける

    def test_verdict_skips_tiny_image(self):
        p = self.d / "tiny.png"
        Image.new("RGB", (16, 16)).save(p)
        with mock.patch.object(origqc, "missing", lambda: []):
            res = origqc.verdict(p, "pass")
        self.assertFalse(res["recorded"])

    def test_favorite_records_pass(self):
        from chatdraw import ownstyle
        calls = []
        with mock.patch.object(origqc, "verdict", lambda path, value, reason="": calls.append((path, value))):
            ownstyle.learn_from("a.png", "pass").join(5)
        self.assertEqual(calls, [("a.png", "pass")])


if __name__ == "__main__":
    unittest.main()
