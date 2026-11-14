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
                key.write_text(json.dumps({"stamp": "sha1:" + hashlib.sha1(img.read_bytes()).hexdigest(), "res": {"bad": ["x"]}}))
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


if __name__ == "__main__":
    unittest.main()
