"""崩れの数を本当の数にする直し（描画確認からの引き継ぎ 1）の試験"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import numpy as np
    import scipy  # noqa: F401
    import qc
except ImportError:
    np = None


@unittest.skipIf(np is None, "numpy か scipy が無い")
class EdgeCutPersonTest(unittest.TestCase):
    def test_background_leaf_at_edge_is_not_a_cut(self):
        rgb = np.full((400, 300, 3), 250, np.uint8)
        rgb[0:80, 100:160] = (30, 120, 40)        # 背景の葉が上の端で切れている
        rgb[100:380, 120:180] = (200, 60, 60)     # 人物は端から離れている
        person = np.zeros((400, 300), bool)
        person[100:380, 120:180] = True
        self.assertIn("上", qc.edge_cut(rgb))               # 色だけで見ると切れと取る
        self.assertEqual(qc.edge_cut(rgb, person=person), [])

    def test_person_cut_is_still_found(self):
        rgb = np.full((400, 300, 3), 250, np.uint8)
        rgb[100:400, 120:180] = (200, 60, 60)     # 足が下の端で切れている
        person = np.zeros((400, 300), bool)
        person[100:400, 120:180] = True
        self.assertIn("下", qc.edge_cut(rgb, person=person))


class UnmeasuredTest(unittest.TestCase):
    def test_words_without_tags_are_separated(self):
        import loop
        vocab = {"bikini", "red trim", "smile"}
        got = loop.unmeasured_words("black bikini with red trim, smile, wistful gaze across the bay", vocab)
        self.assertEqual(got, ["wistful gaze across the bay"])


if __name__ == "__main__":
    unittest.main()
