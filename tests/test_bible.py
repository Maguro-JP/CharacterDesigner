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

    def test_body_plan_defaults_to_humanoid_and_can_be_set(self):
        self.assertEqual(bible.body_plan("k")["counts"]["腕"], 2)
        bible.set_body("k", "centaur")
        plan = bible.body_plan("k")
        self.assertEqual(plan["counts"]["脚（馬）"], 4)
        self.assertNotIn("脚", plan["counts"])            # ケンタウロスに人の脚は無い
        with self.assertRaises(SystemExit):
            bible.set_body("k", "nothing")

    def test_body_plans_keep_the_known_counts(self):
        import json
        plans = json.loads((bible.ROOT / "casts" / "body-plans.json").read_text(encoding="utf-8"))["plans"]
        expect = {"humanoid": ("脚", 2), "insect": ("脚", 6), "spider": ("脚", 8), "octopus": ("腕", 8), "squid": ("触腕", 2),
                  "fish": ("脚", 0), "dragon": ("翼", 2), "wyvern": ("脚", 2), "ryu": ("翼", 0), "lamia": ("脚", 0)}
        for k, (part, n) in expect.items():
            self.assertEqual(plans[k]["counts"][part], n, k)
        for k, p in plans.items():
            self.assertTrue(p["ja"] and p["notes"] and p["counts"], k)

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


def fill_design(bible, ident):
    """資料の 8 区分を全部そろえた状態にする（試験用）"""
    c = bible.load("characters", ident)
    c.update(age="28", height="168cm・7.5 頭身", role="r", personality="p", backstory="b", eyes={"tags": "x"},
             expressions=[{"id": "neutral"}], outfit_parts={"top": "coat"}, colors={"髪": "#000000"}, rules="r", negative="n")
    roles = ["view-front", "view-back", "view-left", "view-right", "pose-1", "pose-2", "pose-3", "detail-eyes", "detail-hair",
             "detail-outfit-coat"] + [f"expr-{i}" for i in range(8)] + ["hairstyle-1", "hairstyle-2"]
    c["images"] = {r: "x.jpg" for r in roles}
    bible.save("characters", c)


class DesignModeTest(unittest.TestCase):
    """AI が人物を絵にするのは、キャラデザモードで設計がそろってから。人の参考資料があればイラストレーターモードで描ける"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = bible.BIBLE
        bible.BIBLE = Path(self.tmp.name)
        bible.new_character("sera", "セラ", "adult woman, dark green hair", "long navy coat")

    def tearDown(self):
        bible.BIBLE = self.old
        self.tmp.cleanup()

    def test_new_character_is_not_ready(self):
        st = bible.design_status("sera")
        self.assertFalse(st["ready"])
        self.assertTrue(any("目" in m for m in st["missing"]))
        with self.assertRaises(bible.DesignNotReady):
            bible.require_design("sera")

    def test_reference_allows_illustrator_mode(self):
        ref = Path(self.tmp.name) / "ref.png"
        ref.write_bytes(b"x")
        self.assertEqual(bible.require_design("sera", str(ref)), "illustrator")
        with self.assertRaises(bible.DesignNotReady):
            bible.require_design("sera", str(ref) + ".missing")

    def test_ready_after_design_and_approved_sheets(self):
        fill_design(bible, "sera")
        self.assertTrue(bible.design_status("sera")["ready"])
        self.assertEqual(bible.require_design("sera"), "design")


class DesignStepsSkipGateTest(unittest.TestCase):
    """三面図はキャラデザモードの手順なので、設計がそろっていなくても描ける（門を通らない）"""

    def test_turnaround_draws_while_designing(self):
        from unittest import mock
        tmp = tempfile.TemporaryDirectory()
        old = bible.BIBLE
        bible.BIBLE = Path(tmp.name)
        try:
            bible.new_character("sera", "セラ", "adult woman", "coat")
            plan = {"base_cmd": ["true"], "views": {"front": {"base": "b.png", "strength": 0.6, "seed": 0}}}
            seen = []

            def fake_draw(ident, out, count, seed, **kw):
                # 本物の draw と同じく、designing が無ければ門を通す
                if not kw.get("designing"):
                    bible.require_design(ident, kw.get("reference"))
                seen.append(kw)
                return ["try-0.png"]
            with mock.patch.object(bible, "turnaround_plan", return_value=plan), \
                    mock.patch.object(bible, "draw", side_effect=fake_draw):
                files = bible.turnaround("sera", tmp.name, count=1)
            self.assertEqual(len(files["front"]), 1)
            self.assertTrue(seen[0]["designing"])
        finally:
            bible.BIBLE = old
            tmp.cleanup()


class CharSheetTest(unittest.TestCase):
    """資料の 8 区分。足りない区分を出し、書き出しでは無い所を「未作成」と書く"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = bible.BIBLE
        bible.BIBLE = Path(self.tmp.name)
        bible.new_character("sera", "セラ", "adult woman", "coat")

    def tearDown(self):
        bible.BIBLE = self.old
        self.tmp.cleanup()

    def test_eight_sections_and_missing(self):
        import charsheet
        st = charsheet.status("sera")
        self.assertEqual(len(st["sections"]), 8)
        self.assertFalse(st["ready"])
        self.assertTrue(any("正面" in m for m in st["sections"]["views"]["missing"]))

    def test_items_need_their_own_closeups(self):
        import charsheet
        fill_design(bible, "sera")
        self.assertTrue(charsheet.status("sera")["ready"])
        bible.add_item("sera", "ledger", "帳面", "book")
        self.assertFalse(charsheet.status("sera")["ready"])

    def test_render_marks_missing(self):
        import charsheet
        out = Path(self.tmp.name) / "s.html"
        r = charsheet.render("sera", str(out))
        self.assertFalse(r["ready"])
        self.assertIn("未作成", out.read_text(encoding="utf-8"))
