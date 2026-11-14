"""検品の精度の台（tools/gen/qcbench.py）の正解の読み方と点の付け方。模型は使わない"""
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


if __name__ == "__main__":
    unittest.main()
