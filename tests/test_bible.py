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

    def test_turnaround_plan_uses_colors_and_no_items(self):
        c = bible.load("characters", "k")
        c["turnaround"] = {"cape": "110,25,30", "words": "cape hanging behind back"}
        bible.save("characters", c)
        plan = bible.turnaround_plan("k", "/tmp/out", seed=5)
        cmd = plan["base_cmd"]
        self.assertIn("--cape", cmd)
        self.assertEqual(cmd[cmd.index("--cape") + 1], "110,25,30")
        self.assertEqual(cmd[cmd.index("--skin") + 1], bible.BASE_COLORS["skin"])   # 設定に無い色は既定
        self.assertNotIn("--boots", cmd)
        self.assertEqual(set(plan["views"]), {"front", "side", "back"})
        for v, kw in plan["views"].items():
            self.assertEqual(kw["items"], [])                     # 三面図では持ち物を持たせない
            self.assertEqual(kw["base"], f"/tmp/out/base-{v}.png")
            self.assertEqual(kw["seed"], 5)
        self.assertGreater(plan["views"]["front"]["strength"], plan["views"]["side"]["strength"])
        self.assertIn("from behind", plan["views"]["back"]["pose"])
        self.assertIn("cape hanging behind back", plan["views"]["front"]["pose"])   # 下絵で隠れる物は言葉で補う
        pos, _ = bible.prompt("k", pose=plan["views"]["back"]["pose"], items=[])
        self.assertNotIn("holding lantern", pos)

    def test_eyes_follow_the_look_in_the_prompt(self):
        bible.set_eyes("k", "tareme, large brown eyes, two highlights", "垂れ目")
        pos, _ = bible.prompt("k")
        self.assertTrue(pos.startswith("1girl, brown hair, tareme, large brown eyes"))
        self.assertEqual(bible.load("characters", "k")["eyes"]["notes"], "垂れ目")

    def test_expressions_merge_defaults_and_own(self):
        bible.add_expression("k", "smile", "微笑み", "faint smile")          # 既定と同じ id は差し替える
        bible.add_expression("k", "wry", "苦笑い", "wry smile, sweatdrop")   # 固有のものは後ろに足す
        ex = bible.expressions_of("k")
        ids = [e["id"] for e in ex]
        self.assertEqual(ids[: len(bible.DEFAULT_EXPRESSIONS)], [e["id"] for e in bible.DEFAULT_EXPRESSIONS])
        self.assertEqual(ids[-1], "wry")
        self.assertEqual(next(e for e in ex if e["id"] == "smile")["tags"], "faint smile")

    def test_expression_plan_uses_face_words_only(self):
        bible.set_eyes("k", "tareme, two highlights")
        plan = bible.expressions_plan("k", only=["angry", "neutral"])
        self.assertEqual([p["id"] for p in plan], ["neutral", "angry"])
        angry = plan[1]["prompt"]
        self.assertIn("tareme", angry)
        self.assertIn("furrowed brow", angry)
        self.assertNotIn("silver armor", angry)       # 服や持ち物は顔の枠に入れない
        self.assertNotIn("lantern", angry)
        self.assertIn("asymmetrical eyes", plan[1]["negative"])
        for e in bible.DEFAULT_EXPRESSIONS:            # 口・眉・目のどれかを必ず書いている
            self.assertTrue(any(w in e["tags"] for w in ("eye", "brow")), e["id"])

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
