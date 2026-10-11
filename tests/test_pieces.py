"""持ち物の途中切れの検品（tools/gen/pieces.py）のうち、検出器を使わない所の試験。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import pieces  # noqa: E402


class Clusters(unittest.TestCase):
    def test_split_broom_is_two(self):
        # 手に持った白い柄と、床に置いた穂（魔女の絵で検出器が出した箱）
        boxes = [[472, 508, 520, 1083], [108, 943, 485, 1080], [109, 943, 317, 1071], [293, 1023, 462, 1071]]
        self.assertEqual(len(pieces.clusters(boxes)), 2)

    def test_whole_broom_is_one(self):
        # 本体の箱が柄と穂を両方含む
        boxes = [[100, 200, 500, 1000], [380, 200, 420, 900], [100, 850, 300, 1000]]
        self.assertEqual(len(pieces.clusters(boxes)), 1)

    def test_asked_words(self):
        self.assertEqual(pieces.asked("1girl, witch, holding broom"), ["broom"])
        self.assertEqual(pieces.asked("1girl, broomstick riding"), [])


if __name__ == "__main__":
    unittest.main()
