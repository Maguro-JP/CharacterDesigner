"""体の最低限（baseline.complete）: 頼みごとに書かれていなくても腕は 2 本・尾は 1 本などを打ち消しで守り、
違う体を頼んだときはその打ち消しを外す。頼んだ言葉は打ち消しに入れない"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import baseline  # noqa: E402
import free_text  # noqa: E402


def neg_of(prompt):
    return [w.strip() for w in free_text.full_prompt(prompt)[1].split(",")]


class Baseline(unittest.TestCase):
    def test_person_gets_two_arms_without_asking(self):
        n = neg_of("1girl, smile")
        for w in ("extra arms", "extra legs", "multiple heads", "extra fingers"):
            self.assertIn(w, n)

    def test_asked_body_is_not_negated(self):
        self.assertNotIn("extra arms", neg_of("1girl, asura, six arms"))
        self.assertNotIn("multiple tails", neg_of("1girl, kitsune, nine tails"))
        n = neg_of("1girl, centaur")
        self.assertNotIn("extra legs", n)
        self.assertNotIn("four legs", n)

    def test_species_adds_its_parts_and_drops_human_ears(self):
        pos = free_text.full_prompt("1girl, cat girl")[0]
        self.assertIn("cat ears", pos)
        self.assertIn("cat tail", pos)
        self.assertIn("human ears", neg_of("1girl, cat girl"))
        self.assertIn("pointy ears", free_text.full_prompt("1boy, elf")[0])

    def test_no_double_and_word_boundary(self):
        pos = free_text.full_prompt("1girl, cat girl, cat ears")[0]
        self.assertEqual(pos.count("cat ears"), 1)
        self.assertNotIn("pointy ears", free_text.full_prompt("1girl, selfie")[0])

    def test_animal_alone_gets_no_humanoid_negative(self):
        r = baseline.complete("fox, forest")
        self.assertNotIn("extra arms", r["negative"])
        self.assertIn("quadruped", r["applied"])   # 動物には動物の決まり（脚 4 本）を掛ける

    def test_solo_keeps_one_person(self):
        self.assertIn("multiple girls", neg_of("1girl, solo"))
        self.assertNotIn("multiple girls", neg_of("2girls"))


if __name__ == "__main__":
    unittest.main()


class Rules(unittest.TestCase):
    def test_every_rule_is_complete(self):
        import json
        d = json.loads(baseline.RULES.read_text(encoding="utf-8"))
        ids = [x["id"] for x in d["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        for x in d["rules"]:
            self.assertTrue(x["why"] and x["topic"], x["id"])
            self.assertTrue(x["when"] or x["person"], x["id"])
            self.assertTrue(x["add"] or x["negative"], x["id"])

    def test_unasked_hat_unless_headwear_asked(self):
        self.assertIn("hat", neg_of("1girl, smile"))
        self.assertNotIn("hat", neg_of("1girl, witch"))
        self.assertNotIn("hat", neg_of("1girl, beret"))

    def test_pairs_and_items(self):
        self.assertIn("mismatched footwear", neg_of("1girl, full body, boots"))
        self.assertIn("multiple swords", neg_of("1boy, knight, holding sword"))
        self.assertNotIn("multiple swords", neg_of("1boy, knight, dual wielding, sword"))
        self.assertNotIn("heterochromia", neg_of("1girl, heterochromia"))
        self.assertIn("heterochromia", neg_of("1girl, blue eyes"))

    def test_checks_are_linked(self):
        r = baseline.complete("1girl, cat girl, holding sword, full body")
        c = baseline.checks(r["applied"])
        self.assertEqual(c["sword"], "held_items")
        self.assertEqual(c["arms"], "body_parts")
        self.assertIn("catgirl", c)


class Override(unittest.TestCase):
    def test_off_by_id_or_topic(self):
        self.assertNotIn("hat", baseline.complete("1girl", off=["headwear"])["negative"])
        topic = "頼んでいない眼鏡は描かない"
        self.assertNotIn("glasses", baseline.complete("1girl", off=[topic])["negative"])

    def test_asked_word_beats_rule(self):
        self.assertNotIn("glasses", neg_of("1girl, glasses"))
        self.assertNotIn("human ears", neg_of("1girl, cat girl, human ears"))

    def test_tiers_order_and_animals(self):
        r = baseline.complete("1girl, cat girl")
        self.assertNotIn("quadruped", r["applied"])
        self.assertLess(r["applied"].index("arms"), r["applied"].index("catgirl"))
        self.assertLess(r["applied"].index("catgirl"), r["applied"].index("headwear"))
        a = baseline.complete("cat, sitting, no humans")
        self.assertIn("quadruped", a["applied"])
        self.assertNotIn("arms", a["applied"])
        self.assertNotIn("quadruped", baseline.complete("kitsune, fox, no humans")["applied"])

    def test_unknown_words(self):
        try:
            import tagger
            tagger.vocabulary()
        except Exception:
            self.skipTest("言葉の表が読めない")
        self.assertEqual(baseline.unknown("1girl, red dress, smile"), [])
        self.assertIn("glaive", baseline.unknown("1girl, glaive"))


class Swimsuit(unittest.TestCase):
    def test_default_and_override(self):
        pos = free_text.full_prompt("1girl, adult woman, swimsuit, beach")[0]
        self.assertIn("plain white bikini", pos)
        self.assertNotIn("plain white bikini", free_text.full_prompt("1girl, adult woman, black one-piece swimsuit")[0])

    def test_minor_and_swimsuit_still_blocked(self):
        with self.assertRaises(ValueError):
            free_text.full_prompt("1girl, high school student, swimsuit")
