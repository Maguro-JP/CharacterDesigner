"""言葉の模型が無いとき、対応表にある日本語の言葉だけで描く言葉に直す。表に無い頼みは、模型を入れるよう返す。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import free_text  # noqa: E402


class FreeDictTest(unittest.TestCase):
    def test_reads_known_words_without_model(self):
        r = free_text.describe("赤い髪の剣士の女性、全身")
        self.assertTrue(r["allowed"])
        self.assertEqual(r["reader"], "dict")
        for t in ("1girl", "red hair", "full body", "swordsman"):
            self.assertIn(t, r["tags"])

    def test_unknown_words_still_ask_for_model(self):
        r = free_text.describe("あいうえお")
        self.assertFalse(r["allowed"])
        self.assertIn("模型", r["reason"])


if __name__ == "__main__":
    unittest.main()
