import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402


class NotSolo(unittest.TestCase):
    def test_mixed_bodies_are_caught(self):
        self.assertIsNotNone(qc.not_solo({"1girl": 0.73, "solo": 0.2, "multiple girls": 0.18}, "crouching, woman"))

    def test_single_person_passes(self):
        self.assertIsNone(qc.not_solo({"1girl": 0.99, "solo": 0.98}, "crouching, woman"))

    def test_asked_group_passes(self):
        self.assertIsNone(qc.not_solo({"1girl": 0.9, "solo": 0.1}, "2girls, friends"))


if __name__ == "__main__":
    unittest.main()
