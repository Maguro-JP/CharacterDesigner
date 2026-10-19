import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import pieces  # noqa: E402


class CountExtra(unittest.TestCase):
    def test_two_separate_bags_when_one_asked(self):
        found = [("a bag", 0.4, [0, 0, 50, 50]), ("a bag", 0.3, [200, 200, 260, 260])]
        with mock.patch.object(pieces, "detect", return_value=found):
            self.assertEqual(len(pieces.count_extra("x.png", "girl, holding a book bag")), 1)

    def test_one_bag_or_asked_two(self):
        one = [("a bag", 0.4, [0, 0, 50, 50]), ("a school bag", 0.3, [5, 5, 45, 45])]
        with mock.patch.object(pieces, "detect", return_value=one):
            self.assertEqual(pieces.count_extra("x.png", "holding a bag"), [])
        two = [("a bag", 0.4, [0, 0, 50, 50]), ("a bag", 0.3, [200, 200, 260, 260])]
        with mock.patch.object(pieces, "detect", return_value=two):
            self.assertEqual(pieces.count_extra("x.png", "two bags, holding bag"), [])

    def test_swordsman_hilt_apart_from_blade(self):
        # 剣士の言い方でも剣を数え、柄と刃が離れた絵を 1 件にする
        apart = [("a sword hilt", 0.3, [0, 0, 60, 60]), ("a sword blade", 0.6, [300, 400, 420, 900])]
        with mock.patch.object(pieces, "detect", return_value=apart) as d:
            self.assertEqual(len(pieces.count_extra("x.png", "1girl, swordsman, full body")), 1)
            self.assertIn("a sword blade", d.call_args[0][1])
        joined = [("a sword hilt", 0.3, [0, 0, 60, 60]), ("a sword", 0.6, [0, 0, 120, 500])]
        with mock.patch.object(pieces, "detect", return_value=joined):
            self.assertEqual(pieces.count_extra("x.png", "1girl, swordsman"), [])


if __name__ == "__main__":
    unittest.main()
