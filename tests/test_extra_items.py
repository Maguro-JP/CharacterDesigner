"""頼んでいない服・持ち物の検品（tools/gen/tagger.extras）。白いビキニを頼んで白い上着が描かれた絵を、頼みと違う絵として返す"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import tagger  # noqa: E402


class ExtraItems(unittest.TestCase):
    def test_unasked_shirt_is_found(self):
        got = {"white shirt": 0.85, "open shirt": 0.7, "bikini": 0.9, "beach": 0.8}
        self.assertEqual(tagger.extras("1girl, white bikini, beach", got), ["white shirt", "open shirt"])

    def test_asked_items_and_weak_reads_are_not_counted(self):
        got = {"straw hat": 0.9, "jacket": 0.3, "bikini": 0.9}
        self.assertEqual(tagger.extras("1girl, bikini, straw hat", got), [])

    def test_unasked_sarong_is_found(self):
        # ビキニを頼んで、腰に長い布（sarong）を巻いた絵が出た（Windows の描画）
        self.assertEqual(tagger.extras("1girl, white bikini, beach", {"sarong": 0.93, "sandals": 0.84}), ["sarong"])


if __name__ == "__main__":
    unittest.main()
