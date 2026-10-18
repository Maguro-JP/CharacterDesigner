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
        self.assertEqual(r, {"unasked": [], "many": [], "small": []})

    def test_sword_drawn_as_dagger(self):
        self.assertEqual(qc.held_items({"dagger": 0.7, "sword": 0.4}, "knight, holding sword")["small"], ["sword→dagger"])
        self.assertEqual(qc.held_items({"dagger": 0.6, "sword": 0.9}, "knight, holding sword")["small"], [])
        self.assertEqual(qc.held_items({"dagger": 0.7}, "thief, dagger")["small"], [])


if __name__ == "__main__":
    unittest.main()


class Rating(unittest.TestCase):
    def test_rating_is_kept_and_not_reread(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
        import tagger
        tagger._RATING["/x.png"] = {"general": 0.9, "questionable": 0.0}
        self.assertEqual(tagger.rating("/x.png")["general"], 0.9)
        tagger._RATING.pop("/x.png")


@unittest.skipIf(qc is None, "qc を読めない")
class BodyParts(unittest.TestCase):
    def test_extra_parts_unless_asked(self):
        self.assertEqual(qc.body_parts({"multiple tails": 0.6, "extra ears": 0.5}, "fox girl, fox tail")["extra"],
                         ["multiple tails", "extra ears"])
        self.assertEqual(qc.body_parts({"multiple tails": 0.6}, "kitsune, multiple tails")["extra"], [])
        self.assertEqual(qc.body_parts({"extra ears": 0.2}, "cat girl")["extra"], [])

    def test_wings_drawn_as_arms(self):
        self.assertEqual(qc.body_parts({"winged arms": 0.7}, "angel, white wings")["swapped"], ["wings→winged arms"])
        self.assertEqual(qc.body_parts({"winged arms": 0.7}, "harpy, winged arms")["swapped"], [])


class MissingWords(unittest.TestCase):
    def test_motion_and_cropped_feet_are_not_missing(self):
        import tagger
        try:
            tagger.vocabulary()
        except Exception:
            self.skipTest("言葉の表が読めない")
        got = {"1girl": 0.9}
        self.assertNotIn("walking", tagger.missing("1girl, walking", got))
        self.assertNotIn("boots", tagger.missing("1girl, cowboy shot, boots", got))
        self.assertIn("boots", tagger.missing("1girl, full body, boots", got))
