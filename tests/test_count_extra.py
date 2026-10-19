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


if __name__ == "__main__":
    unittest.main()
