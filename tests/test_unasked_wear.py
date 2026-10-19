import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402


class UnaskedWear(unittest.TestCase):
    def test_unasked_items_and_prints(self):
        tags = {"jacket": 0.7, "katana": 0.6, "clothes writing": 0.8, "t-shirt": 0.9}
        self.assertEqual(qc.unasked_wear(tags, "plain white t-shirt, jeans"), ["clothes writing", "jacket", "katana"])

    def test_asked_ones_pass(self):
        tags = {"jacket": 0.7, "katana": 0.6, "clothes writing": 0.8}
        self.assertEqual(qc.unasked_wear(tags, "leather jacket, katana, t-shirt with logo print"), [])

    def test_weak_tags_pass(self):
        self.assertEqual(qc.unasked_wear({"coat": 0.3}, "dress"), [])


if __name__ == "__main__":
    unittest.main()
