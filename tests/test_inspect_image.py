"""単独の検品（inspect_image）と精度の測り（qc_eval）の、模型を使わない部分"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import inspect_image  # noqa: E402
import qc_eval  # noqa: E402


class FromAuto(unittest.TestCase):
    def test_items_and_culture(self):
        auto = {"problems": [{"unasked_item": ["cup"]}, {"item_count": ["dual wielding"]}, {"item_size": ["sword→dagger"]}],
                "cultural": [{"topic": "着物の合わせ", "hit": "kimono", "why": "w", "instead": "i"}]}
        problems, look = inspect_image.from_auto(auto)
        self.assertEqual([p["kind"] for p in problems], ["余分な持ち物", "持ち物の数", "持ち物の大きさ"])
        self.assertEqual(look[0]["kind"], "宗教・文化")
        self.assertEqual(look[0]["detail"]["tag"], "kimono")

    def test_unknown_key_keeps_its_name(self):
        problems, look = inspect_image.from_auto({"problems": [{"new_check": 1}]})
        self.assertEqual(problems[0]["kind"], "new_check")
        self.assertEqual(look, [])

    def test_page_writes_html(self):
        with tempfile.TemporaryDirectory() as d:
            r = {"src": str(Path(d) / "a.png"), "ok": False, "problems": [{"kind": "持ち物の数", "detail": {"x": 1}}],
                 "look": [], "unreadable": [], "heads_tall": 6.3}
            html = inspect_image.page([r], Path(d)).read_text(encoding="utf-8")
            self.assertIn("持ち物の数", html)
            self.assertIn("崩れ 1 件", html)


class Eval(unittest.TestCase):
    def test_kinds_found_maps_problem_names(self):
        r = {"problems": [{"kind": "余分な持ち物", "detail": {}}, {"kind": "測った値の外れ", "detail": {"eyes": 1}}],
             "look": [{"kind": "靴の左右", "detail": {}}]}
        self.assertEqual(qc_eval.kinds_found(r), {"extra_item", "eyes_closed", "shoes_mismatch"})


if __name__ == "__main__":
    unittest.main()
