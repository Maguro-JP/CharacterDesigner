import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import design


class WordTok:
    """単語と読点を1トークンずつに数える、試験用の読み手"""
    def __call__(self, text, add_special_tokens=False, verbose=False):
        words = text.replace(",", " , ").split()
        return type("R", (), {"input_ids": [hash(w) % 10000 for w in words]})()


class SplitWeighted(unittest.TestCase):
    def test_weight_applies_only_inside_parentheses(self):
        (ids, ws), = design.split_weighted(WordTok(), "child, (short skirt:1.6), nsfw")
        self.assertEqual(ws, [1.0, 1.0, 1.6, 1.6, 1.0, 1.0])
        self.assertEqual(len(ids), len(ws))

    def test_without_weights_matches_split_tokens(self):
        text = ", ".join(["red hat"] * 60)
        self.assertEqual(design.split_tokens(WordTok(), text), [i for i, _ in design.split_weighted(WordTok(), text)])

    def test_weights_follow_their_tokens_across_chunks(self):
        text = ", ".join(["red hat"] * 30) + ", (blue coat:1.4)"
        chunks = design.split_weighted(WordTok(), text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[-1][1][-2:], [1.4, 1.4])


if __name__ == "__main__":
    unittest.main()
