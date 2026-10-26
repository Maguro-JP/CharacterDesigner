"""検品を通った絵でも、手・足・顔の枠をすべて細部の描き直しに回す（chatdraw/handcheck.detail_regions）"""
import unittest

from chatdraw import handcheck


class DetailRegions(unittest.TestCase):
    def test_all_seen_parts_are_listed_even_when_not_bad(self):
        res = {"hands": [{"box": [1, 2, 3, 4], "bad": []}, {"box": [5, 6, 7, 8], "seen": False}],
               "feet": [{"box": [9, 9, 20, 20], "bad": []}], "faces": [{"box": [0, 0, 10, 10]}]}
        self.assertEqual(handcheck.detail_regions(res),
                         [([1, 2, 3, 4], "hand"), ([9, 9, 20, 20], "foot"), ([0, 0, 10, 10], "face")])
        self.assertEqual(handcheck.bad_regions(res), [])


if __name__ == "__main__":
    unittest.main()
