"""設定資料集（tools/gen/bible.py）の保存と、描く言葉の組み立ての試験（模型は使わない）。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import bible  # noqa: E402


class Bible(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = bible.BIBLE
        bible.BIBLE = Path(self.tmp.name)
        bible.new_character("k", "騎士", "1girl, brown hair", "silver armor, red scarf")
        bible.add_item("k", "lantern", "ランタン", "holding lantern")
        bible.add_item("k", "sword", "剣", "sword on hip", avoid="second sword")
        bible.new_world("w", "城塞", "medieval fantasy, snow")
        bible.add_location("w", "gate", "城門", "castle gate, torches")

    def tearDown(self):
        bible.BIBLE = self.old
        self.tmp.cleanup()

    def test_look_comes_first_and_scene_is_added(self):
        pos, neg = bible.prompt("k", scene="walking", world="w", location="gate")
        self.assertTrue(pos.startswith("1girl, brown hair, holding lantern"))   # 見た目の次に持ち物、そのあと服
        self.assertLess(pos.index("holding lantern"), pos.index("silver armor"))
        self.assertIn("castle gate, torches", pos)
        self.assertIn("medieval fantasy, snow", pos)

    def test_outfit_can_be_swapped_and_items_chosen(self):
        pos, _ = bible.prompt("k", outfit="casual clothes", items=["lantern"])
        self.assertIn("casual clothes", pos)
        self.assertNotIn("silver armor", pos)
        self.assertIn("holding lantern", pos)
        self.assertNotIn("sword on hip", pos)
        self.assertIn("white background", pos)          # 世界が無ければ白い背景

    def test_avoid_words_go_to_negative(self):
        _, neg = bible.prompt("k", items=["sword"])
        self.assertIn("second sword", neg)
        _, neg = bible.prompt("k", items=["lantern"])
        self.assertNotIn("second sword", neg)                # 選ばなかった持ち物の分は入れない

    def test_item_replaced_by_same_id(self):
        bible.add_item("k", "lantern", "大きいランタン", "holding big lantern")
        items = bible.load("characters", "k")["items"]
        self.assertEqual([i["name"] for i in items if i["id"] == "lantern"], ["大きいランタン"])


if __name__ == "__main__":
    unittest.main()
