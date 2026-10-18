"""宗教・文化の配慮（styles/cultural.json と filters.cultural）が、当たるべき所で当たり、普通の頼みごとでは黙ることを確かめる"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import filters  # noqa: E402


def ids(text):
    return {a["id"] for a in filters.cultural(text)}


class Rules(unittest.TestCase):
    def test_every_rule_is_complete(self):
        rules = json.loads((ROOT / "styles" / "cultural.json").read_text(encoding="utf-8"))["rules"]
        self.assertGreaterEqual(len(rules), 15)
        for r in rules:
            for k in ("id", "topic", "level", "why", "instead", "source"):
                self.assertTrue(r.get(k), f"{r.get('id')} に {k} が無い")
            self.assertIn(r["level"], ("hate", "caution", "advise"))
            self.assertTrue(r.get("words") or r.get("triggers"), r["id"])

    def test_hits(self):
        self.assertIn("nazi", ids("officer, nazi uniform"))
        self.assertIn("swastika", ids("卍の旗"))
        self.assertIn("prophet", ids("prophet muhammad portrait"))
        self.assertIn("war_bonnet", ids("girl wearing a war bonnet"))
        self.assertIn("kimono_fold", ids("1girl, kimono, smile"))
        self.assertIn("blackface", ids("ブラックフェイスの道化"))

    def test_pairs_need_both_words(self):
        self.assertNotIn("sacred_sexual", ids("nun, holding rosary"))
        self.assertIn("sacred_sexual", ids("nun, lingerie"))
        self.assertNotIn("food_taboo", ids("muslim girl, hijab, smile"))
        self.assertIn("food_taboo", ids("muslim girl, eating bacon"))
        self.assertNotIn("sacred_text_feet", ids("bible on the table"))
        self.assertIn("sacred_text_feet", ids("bible on the floor"))

    def test_ordinary_requests_stay_quiet(self):
        for t in ("1girl, school uniform, red scarf, snow castle", "赤いマフラーの騎士の少年", "knight, armor, sword",
                  "natural light, forest", "ナチュラルメイクの女性", "braided hair"):
            self.assertEqual(filters.cultural(t), [], t)

    def test_scene_words_add_negative(self):
        self.assertIn("swastika", filters.negative("1boy, monk, buddhist temple"))
        self.assertIn("nazi", filters.negative("1girl, military uniform, armband"))
        self.assertNotIn("swastika", filters.negative("1girl, forest"))

    def test_advice_does_not_block_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "none.json"
            self.assertIsNone(filters.check("nazi officer", p))
            self.assertTrue(filters.advice_lines("nazi officer"))

    def test_filter_blocks_when_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.json"
            p.write_text(json.dumps({"filters": [{"name": "宗教・文化への配慮", "enabled": True, "cultural": True, "words": []}]}),
                         encoding="utf-8")
            self.assertIn("宗教・文化", filters.check("nazi officer", p))
            self.assertIn("宗教・文化", filters.check("nun, lingerie", p))
            self.assertIsNone(filters.check("knight, armor", p))
            # 描き方の注意（advise）だけの頼みごとは止めない
            self.assertIsNone(filters.check("1girl, kimono", p))


class Describe(unittest.TestCase):
    def test_describe_returns_advice_apart_from_notes(self):
        import free_text
        r = free_text.describe("1girl, kimono, smile")
        self.assertTrue(r["allowed"])
        self.assertTrue(any("着物の合わせ" in a for a in r["advice"]))
        self.assertFalse(any("着物の合わせ" in n for n in r["notes"]))
        self.assertEqual(free_text.describe("1girl, school uniform")["advice"], [])


if __name__ == "__main__":
    unittest.main()
