"""女性の基準の体（chatdraw/body.py）が、利用者の決めた体型（casts/body-types.json の anime.ideal）と食い違わないか。
mature female を描く言葉に入れると、年配の太った体と顔で描いた"""
import json
import unittest
from pathlib import Path

from chatdraw import body, jaterms

ROOT = Path(__file__).resolve().parents[1]


class BodyTest(unittest.TestCase):
    def test_matches_users_ideal(self):
        ideal = json.loads((ROOT / "casts" / "body-types.json").read_text(encoding="utf-8"))["anime"]["ideal"]
        self.assertEqual(body.TAGS, ideal["tags"])
        for w in ideal["negative"].split(", "):
            self.assertIn(w, body.NEGATIVE)

    def test_woman_is_not_mature_female(self):
        tags = jaterms.tags_from("白いビキニの女性")
        self.assertNotIn("mature female", tags)
        self.assertIn("slender body", tags)
        self.assertIn("mature female", body.NEGATIVE)


if __name__ == "__main__":
    unittest.main()
