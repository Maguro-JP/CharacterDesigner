"""持ち物の検品（qc.held_items）: 頼んでいない持ち物と、同じ物の数を、タグから拾う"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import qc
except ImportError:  # numpy などの無い環境
    qc = None


@unittest.skipIf(qc is None, "qc を読めない")
class HeldItems(unittest.TestCase):
    def test_unasked_cup(self):
        r = qc.held_items({"holding cup": 0.56, "kimono": 0.9}, "1girl, kimono, smile")
        self.assertEqual(r["unasked"], ["cup"])

    def test_asked_item_is_not_counted(self):
        r = qc.held_items({"holding sword": 0.8}, "1boy, knight, holding sword")
        self.assertEqual(r["unasked"], [])

    def test_body_holdings_are_not_items(self):
        r = qc.held_items({"holding hands": 0.9, "holding own hair": 0.7, "holding hat": 0.6}, "1girl")
        self.assertEqual(r["unasked"], [])

    def test_two_swords(self):
        self.assertEqual(qc.held_items({"dual wielding": 0.5}, "knight, sword")["many"], ["dual wielding"])
        self.assertEqual(qc.held_items({"dual wielding": 0.5}, "knight, dual wielding")["many"], [])

    def test_weak_tags_are_ignored(self):
        r = qc.held_items({"holding cup": 0.3, "multiple swords": 0.2}, "1girl")
        self.assertEqual(r, {"unasked": [], "many": []})


if __name__ == "__main__":
    unittest.main()
