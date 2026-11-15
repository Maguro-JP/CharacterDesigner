"""検品の精度の台（tools/gen/qcbench.py）の正解の読み方と点の付け方。模型は使わない"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gen"))
import qcbench  # noqa: E402


class TruthTest(unittest.TestCase):
    def test_reads_parts(self):
        self.assertEqual(qcbench.flaw_parts("1. 両手の指が読めない。2. 両脚が交差して足先が重なる"), {"hands", "feet"})
        self.assertEqual(qcbench.flaw_parts("右の眉が髪に食い込む"), {"faces"})

    def test_fine_sentences_not_flaws(self):
        self.assertEqual(qcbench.flaw_parts("指は 5 本ずつ読める。手は描けた"), set())
        self.assertEqual(qcbench.flaw_parts("目の色の差 0.0。元の大きさで見て、目立つ崩れは見つけていない"), set())

    def test_toe_is_feet(self):
        self.assertEqual(qcbench.flaw_parts("足の指が 6 本"), {"feet"})

    def test_library_has_rows(self):
        rows = qcbench.truth()
        self.assertGreater(len(rows), 50)
        self.assertTrue(all(Path(qcbench.ROOT / r["path"]).exists() for r in rows))


class ScoreTest(unittest.TestCase):
    def test_score(self):
        rows = [{"path": "a", "flaws": ["hands", "feet"], "clean": False, "text": ""},
                {"path": "b", "flaws": [], "clean": True, "text": ""}]
        res = {"a": {"hands": [{"box": [0, 0, 1, 1], "bad": ["手 1: 指が 6 本"]}], "bad": ["手 1: 指が 6 本"]},
               "b": {"bad": [], "readable": True, "hands": [{"box": [0, 0, 1, 1], "bad": []}]}}
        s = qcbench.score(rows, res)
        self.assertEqual((s["caught"], s["located"], s["clean_quiet"]), (50.0, 100.0, 100.0))
        self.assertEqual(s["missed"][0][1], "feet")

    def test_body_flaws_count_by_part(self):
        # 余分な目・口は顔、腕は手、脚は足の崩れとして数える
        f = qcbench.said({"bad": [], "body_bad": ["目が多い（extra eyes 0.5）", "腕が多い（extra arms 0.4）", "脚が多いか、つながりがあり得ない（left の骨の比 3）"]})["flag"]
        self.assertEqual(f, ["faces", "feet", "hands"])

    def test_unread_counts_as_flag(self):
        # 検品できなかった部位は「崩れが無い」ではない（崩れとして扱う決まり）
        self.assertIn("feet", qcbench.said({"bad": [], "feet_reason": "足を読めない"})["flag"])


class OneEyeTest(unittest.TestCase):
    """台で取りこぼした顔: 片目が髪か物で隠れた顔を崩れと言う。頼んだときは言わない"""
    def test_hidden_eye(self):
        import facecheck
        self.assertIn("片目", facecheck.judge({"grey eyes": 0.43, "hair over one eye": 0.74})[0])
        self.assertIn("片目", facecheck.judge({"purple eyes": 0.33, "one eye covered": 0.43})[0])
        self.assertEqual(facecheck.judge({"blue eyes": 0.97, "hair between eyes": 0.52}), [])
        self.assertEqual(facecheck.judge({"grey eyes": 0.43, "hair over one eye": 0.74}, asked="1girl, hair over one eye"), [])


class MisreadTest(unittest.TestCase):
    """元の大きさで絵を見て、崩れではなかった句（横顔の向き、設定と違う目の色、正座の座り方）"""
    def test_not_flaws(self):
        self.assertEqual(qcbench.flaw_parts("顔が横顔に近い"), set())
        self.assertEqual(qcbench.flaw_parts("髪と靴の拡大が全身に近い枠、髪の拡大で目が赤い（設定は茶）"), set())
        self.assertEqual(qcbench.flaw_parts("1. 脚を横に流さず、かかとの上に正座のように座った。2. 水着が灰色"), set())

    def test_real_flaws_kept(self):
        self.assertEqual(qcbench.flaw_parts("右の目が潰れている"), {"faces"})
        self.assertEqual(qcbench.flaw_parts("かかとが逆を向く"), {"feet"})


class FalseAlarmTest(unittest.TestCase):
    def test_false_by_part(self):
        rows = [{"path": "b", "flaws": [], "clean": True, "text": ""}]
        res = {"b": {"bad": [], "feet_reason": "足を読めない", "hands": [{"box": [0, 0, 1, 1], "bad": ["手の形が読めない"]}]}}
        s = qcbench.score(rows, res)
        self.assertEqual(s["false_by_part"], {"hands": 1, "feet": 1, "faces": 0})
        self.assertEqual(s["clean_quiet"], 0.0)


class CacheTest(unittest.TestCase):
    """同じ中身の絵は、worktree が違って更新時刻が違っても測り直さない"""
    def test_same_content_reused(self):
        import json
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            img = Path(qcbench.ROOT / qcbench.truth()[0]["path"])
            with mock.patch.object(qcbench, "CACHE", Path(d)):
                key = Path(d) / (qcbench.re.sub(r"[^\w.-]", "_", str(img.relative_to(qcbench.ROOT))) + ".json")
                import hashlib
                key.write_text(json.dumps({"stamp": "sha1:" + hashlib.sha1(img.read_bytes()).hexdigest() + ":" + qcbench.QC_VERSION, "res": {"bad": ["x"]}}))
                os.utime(img)   # 更新時刻だけ変える
                self.assertEqual(qcbench.run_one(img), {"bad": ["x"]})


class SegCacheTest(unittest.TestCase):
    """アプリの経路では cdhome.HOME が data_home()/cd を向く。部位分けの模型を一つ上の置き場からも見つける"""
    def test_finds_parent_hub(self):
        import tempfile
        from unittest import mock
        import edit
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d) / "gen" / "hf" / "hub" / ("models--" + edit.SEG_MODEL.replace("/", "--")) / "snapshots" / "x"
            snap.mkdir(parents=True)
            (snap / "config.json").write_text("{}")
            with mock.patch.object(edit.cdhome, "HOME", Path(d) / "cd"), mock.patch.dict(os.environ, {"HF_HOME": str(Path(d) / "cd" / "gen" / "hf")}):
                os.environ.pop("HF_HUB_CACHE", None)   # アプリの試験が置いた置き場を見ない（patch.dict が戻す）
                self.assertEqual(edit.seg_cache_dir(), str(Path(d) / "gen" / "hf" / "hub"))


class AccuracyBenchTest(unittest.TestCase):
    """accuracy_bench は今の main にある台だけを流す（外れた chatdraw/accuracy.py を読まない）"""
    def test_runs_without_removed_module(self):
        import accuracy_bench
        from unittest import mock
        with mock.patch.dict(accuracy_bench.BENCHES, {"検品単体": lambda: {"score": 98.0}}, clear=True):
            self.assertEqual(accuracy_bench.run(), {"検品単体": {"score": 98.0}})
            with self.assertRaises(SystemExit):
                accuracy_bench.run(["拡大"])

    def test_render_keeps_old_rows(self):
        import accuracy_bench
        old = {"拡大": {"score": 86.6, "prev": "77.5", "date": "2026-11-08 23:50"}}
        text = accuracy_bench.render(old, {"検品単体": {"score": 98.0}}, "2026-11-14 12:00")
        self.assertIn("| 拡大 | 86.6 | 77.5 |", text)
        self.assertIn("| 検品単体 | 98.0 |  |", text)


class EyeSmearTest(unittest.TestCase):
    """描けない瞳をぼかしや虹色でごまかした目を崩れと言う。くっきりした目は言わない"""
    def _face(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (400, 400), (240, 220, 200))
        d = ImageDraw.Draw(im)
        for x in (150, 250):
            d.ellipse((x - 18, 182, x + 18, 218), fill=(255, 255, 255), outline=(0, 0, 0), width=3)
            d.ellipse((x - 9, 191, x + 9, 209), fill=(40, 60, 160), outline=(0, 0, 0), width=2)
        d.line((170, 280, 230, 280), fill=(0, 0, 0), width=3)
        return im, {"left_eye": (250, 200), "right_eye": (150, 200)}

    def test_sharp_eyes_pass(self):
        import facecheck
        im, kp = self._face()
        self.assertEqual(facecheck.eye_smear(im, kp, (60, 100, 340, 360)), [])

    def test_blurred_eye(self):
        import facecheck
        from PIL import ImageFilter
        im, kp = self._face()
        eye = im.crop((185, 135, 315, 265)).filter(ImageFilter.GaussianBlur(25))
        im.paste(eye, (185, 135))
        bad = facecheck.eye_smear(im, kp, (60, 100, 340, 360))
        self.assertEqual(len(bad), 1)
        self.assertIn("左の目", bad[0])

    def test_rainbow_eye(self):
        import facecheck
        import numpy as np
        from PIL import Image
        im, kp = self._face()
        hue = (np.add.outer(np.arange(80), np.arange(80)) * 255 // 160).astype("uint8")
        rb = Image.merge("HSV", [Image.fromarray(hue), Image.new("L", (80, 80), 220), Image.new("L", (80, 80), 220)]).convert("RGB")
        im.paste(rb, (110, 160))
        self.assertTrue(any("右の目" in b for b in facecheck.eye_smear(im, kp, (60, 100, 340, 360))))


if __name__ == "__main__":
    unittest.main()


class CatsTest(unittest.TestCase):
    """崩れの種類ごとの台（指の数・手の形・足・目・口・顔・腕と脚の数・左右・映り込み・頼んだ物・頼んでいない物）"""
    def test_reads_kinds(self):
        self.assertEqual(qcbench.flaw_cats("両手の指が読めない"), {"fingers"})
        self.assertEqual(qcbench.flaw_cats("指が崩れた手が頭の上に浮く"), {"fingers", "hand_shape"})
        self.assertEqual(qcbench.flaw_cats("腕が3本（両腕を頭の後ろに上げる）"), {"limbs"})
        self.assertEqual(qcbench.flaw_cats("手首に頼んでいない腕輪が出た"), {"extra"})
        self.assertEqual(qcbench.flaw_cats("両足先が重なって読めない"), {"feet"})
        self.assertEqual(qcbench.flaw_cats("腰に当てた手の指は 5 本読める。片手を腰に当てた"), set())

    def test_said_sure_and_unread(self):
        res = {"hands": [{"box": [0, 0, 1, 1], "bad": ["指が足りない（4 本。5 本のはず）"]},
                         {"box": [0, 0, 1, 1], "bad": ["手の形が読めない（指がくっついたか、ぼやけている）"]}],
               "request": {"readable": True, "extra": ["bracelet"], "missing": []}}
        sure, unread = qcbench.said_cats(res)
        self.assertEqual(sure, {"fingers", "extra"})
        self.assertEqual(unread, {"hand_shape"})

    def test_request_unread_is_flag(self):
        # 頼んだ物を読めなかった絵は、頼んだ物の崩れとして数える（検品できなかった絵を「崩れが無い」にしない）
        _, unread = qcbench.said_cats({"request": {"readable": False, "reason": "部品が無い"}})
        self.assertEqual(unread, {"missing", "extra"})

    def test_score_cats(self):
        rows = [{"path": "a", "cats": ["extra"], "clean": False}, {"path": "b", "cats": [], "clean": True}]
        res = {"a": {"request": {"readable": True, "extra": ["bracelet"]}}, "b": {"request": {"readable": True, "extra": ["bracelet"]}}}
        s = qcbench.score_cats(rows, res)["extra"]
        self.assertEqual((s["caught"], s["false"], s["clean_false"]), (100.0, 100.0, 100.0))

    def test_asked_tags(self):
        self.assertEqual(qcbench.asked_tags("r22 と同じ設定（standing, side view）"), "r22, standing, side view")


class ExtrasTest(unittest.TestCase):
    """頼んでいない物: 手首の飾り、2 本目の武器"""
    def test_bracelet_and_dual(self):
        import tagger
        got = {"bracelet": 0.46, "dual wielding": 0.25, "sword": 0.95}
        self.assertEqual(tagger.extras("1boy, holding sword", got), ["bracelet", "dual wielding"])
        self.assertEqual(tagger.extras("1girl, bracelet, dual wielding", got), ["sword"])


class ShodFeetTest(unittest.TestCase):
    """頼まずに描かれた靴の先を、足の指として数えない"""
    def test_shod(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from chatdraw import handcheck
        self.assertTrue(handcheck.shod({"boots": 0.9, "barefoot": 0.02}))
        self.assertFalse(handcheck.shod({"kneehighs": 0.61, "barefoot": 0.56, "toes": 0.46}))   # 靴下から指が透けた絵
        self.assertFalse(handcheck.shod({"barefoot": 0.9}))
        self.assertFalse(handcheck.shod(None))


class LegsCutTest(unittest.TestCase):
    def test_legs_cut(self):
        from chatdraw import sanity
        self.assertTrue(sanity.legs_cut({"feet out of frame": 0.45}, "")[0].startswith("脚"))
        self.assertEqual(sanity.legs_cut({"feet out of frame": 0.45}, "1girl, cowboy shot"), [])
        self.assertEqual(sanity.legs_cut({"feet out of frame": 0.36}, ""), [])

    def test_legs_cut_not_in_draw_flow(self):
        # 描く流れの検品（from_tags）には入れない（打ち消しと描き直しに触らない）
        from chatdraw import sanity
        self.assertEqual(sanity.from_tags({"feet out of frame": 0.6}, ""), [])


class KeepHandsTest(unittest.TestCase):
    """手のひらの模型が拾った物のうち、手首の近くか、DWPose が手の点を置いた所だけを手とする"""
    def test_face_only_picture(self):
        from unittest import mock
        from PIL import Image
        from chatdraw import handcheck
        im = Image.new("RGB", (512, 512))
        found = [(242, 346, "199,303,285,389:0"), (100, 100, "60,60,140,140:0")]
        with mock.patch.object(handcheck, "_keypoints", return_value={"nose": (256, 260)}), \
                mock.patch.object(handcheck, "_dw_hands", return_value=[[], [(90, 95), (100, 100), (110, 105), (95, 120), (120, 90)]]):
            self.assertEqual(handcheck.keep_hands(im, found), ["60,60,140,140:0"])

    def test_no_models_keeps_above_ankles(self):
        from unittest import mock
        from PIL import Image
        from chatdraw import handcheck
        im = Image.new("RGB", (200, 400))
        found = [(50, 50, "40,40,60,60:0"), (50, 390, "40,380,60,399:0")]
        with mock.patch.object(handcheck, "_keypoints", return_value={}), mock.patch.object(handcheck, "_dw_hands", return_value=None):
            self.assertEqual(handcheck.keep_hands(im, found), ["40,40,60,60:0"])
