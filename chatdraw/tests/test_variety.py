"""似た絵ばかりにしない: 書かれていない所を種で選ぶ、おまかせの模型を固定しない、落ちても段を下げて描く"""
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from chatdraw import omakase, variety
from chatdraw.engine import Studio, vary_background


class VarietyTest(unittest.TestCase):
    def test_tables_are_large_enough(self):
        for k, (table, _w) in variety.TABLES.items():
            self.assertGreaterEqual(len(table), 16, k)
            self.assertEqual(len(set(table)), len(table), k)

    def test_same_request_gives_different_places(self):
        # 足すのは場所だけ（構図・髪・服・表情を足すと頼みと質から絵が引っ張られた。chatdraw/tests/test_quality2.py）
        seeds = range(40)
        # 読み解ける頼みは、その場面の場所の中から種で変える。読み解けない頼みは無地か簡単な背景（でたらめな場所を足さない）
        got = {vary_background("1girl, solo", s, text="剣を持った騎士の女の子") for s in seeds}
        self.assertEqual(len(got), 3, got)
        plain = {vary_background("1girl, solo", s, text="女の子") for s in seeds}
        self.assertTrue(all("simple background" in p for p in plain), plain)

    def test_written_items_are_kept(self):
        out = vary_background("1girl, solo, beach, smile, ponytail", 3, text="浜辺で笑うポニーテールの女の子")
        self.assertEqual(out, "1girl, solo, beach, smile, ponytail")   # 場所を書いたので何も足さない
        chosen = variety.pick(3, "浜辺で笑うポニーテールの女の子\n1girl, solo, beach, smile, ponytail")
        self.assertFalse({"place", "face", "hair"} & set(chosen), chosen)

    def test_no_person_items_for_scenery(self):
        self.assertTrue(set(variety.PERSON) <= variety.fixed("scenery, no humans"))

    def test_same_seed_repeats(self):
        self.assertEqual(vary_background("1girl", 5), vary_background("1girl", 5))
        self.assertTrue(vary_background("A girl.", 5, tags=False).endswith("."))


class ExploreTest(unittest.TestCase):
    def test_keeps_best_first(self):
        ranked = [(f"m{i}", "") for i in range(6)]
        self.assertTrue(all(omakase.explore(ranked, s) == ranked for s in range(100)))


class Boom(Exception):
    pass


class DrawAnywayTest(unittest.TestCase):
    def test_falls_back_and_draws(self):
        with TemporaryDirectory() as d:
            st = Studio(painter=mock.Mock(model="a", stop=False, avoid=""), out=Path(d))
            calls = []

            def draw(text, seed, on_status=None, size=None, **kw):
                calls.append((seed, size))
                if len(calls) < 3:
                    raise MemoryError("足りない")
                return "p", Path(d) / "x.png"

            said = []
            with mock.patch.object(st, "draw", side_effect=draw), mock.patch.object(st, "_fallback_model", return_value=None):
                self.assertEqual(st.draw_anyway("女の子", 1, said.append, size=(832, 1216))[0], "p")
            self.assertEqual(len(calls), 3)
            self.assertLess(calls[1][1][0], 832)   # 2 回目は小さく描く
            self.assertLess(calls[2][1][0], calls[1][1][0])   # 3 回目はもっと小さく描く（上限で止めずに段を下げ続ける）

    def test_reports_reasons_only_when_all_fail(self):
        st = Studio(painter=mock.Mock(model="a", stop=False, avoid=""), out=Path("."))
        with mock.patch.object(st, "draw", side_effect=Boom("x")), mock.patch.object(st, "_fallback_model", return_value=None):
            with self.assertRaises(RuntimeError) as cm:
                st.draw_anyway("女の子", 1, size=(832, 1216))
        self.assertIn("次の手", str(cm.exception))

    def test_refused_is_not_retried(self):
        st = Studio(painter=mock.Mock(model="a", stop=False, avoid=""), out=Path("."))
        with mock.patch.object(st, "draw", side_effect=ValueError("子どもを性的に描く頼みは描きません")) as d:
            with self.assertRaises(ValueError):
                st.draw_anyway("x", 1)
        self.assertEqual(d.call_count, 1)


class PresetTest(unittest.TestCase):
    def test_redpen_is_not_a_preset(self):
        from chatdraw.aipanel import PRESETS
        self.assertNotIn("赤ペンで直す", [p[0] for p in PRESETS])
        self.assertFalse([p for p in PRESETS if p[2] == 2])


if __name__ == "__main__":
    unittest.main()
