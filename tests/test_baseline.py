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
        self.assertEqual(baseline.complete("fox, forest")["negative"], [])

    def test_solo_keeps_one_person(self):
        self.assertIn("multiple girls", neg_of("1girl, solo"))
        self.assertNotIn("multiple girls", neg_of("2girls"))


if __name__ == "__main__":
    unittest.main()
