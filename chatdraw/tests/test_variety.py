"""似た絵ばかりにしない: 書かれていない所を種で選ぶ、おまかせの模型を固定しない、落ちても段を下げて描く"""
import itertools
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from chatdraw import omakase, variety
from chatdraw.engine import Studio, vary_background


def overlap(prompts):
    """頼みの言葉どうしの重なり（タグの Jaccard の平均）。1 なら毎回同じ言葉"""
    sets = [{t.strip() for t in p.split(",") if t.strip()} for p in prompts]
    pairs = list(itertools.combinations(sets, 2))
    return sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)


class VarietyTest(unittest.TestCase):
    def test_tables_are_large_enough(self):
        for k, (table, _w) in variety.TABLES.items():
            self.assertGreaterEqual(len(table), 16, k)
            self.assertEqual(len(set(table)), len(table), k)

    def test_same_request_gives_different_prompts(self):
        seeds = [random.randrange(2 ** 31) for _ in range(20)]
        got = [vary_background("1girl, solo", s, text="女の子") for s in seeds]
        self.assertLess(overlap(got), 0.2)   # 前は背景だけで 0.30、おまかせは 1.0（毎回同じ言葉）

    def test_written_items_are_kept(self):
        out = vary_background("1girl, solo, beach, smile, ponytail", 3, text="浜辺で笑うポニーテールの女の子")
        self.assertTrue(out.startswith("1girl, solo, beach, smile, ponytail, "), out)
        chosen = variety.pick(3, "浜辺で笑うポニーテールの女の子\n1girl, solo, beach, smile, ponytail")
        self.assertFalse({"place", "face", "hair"} & set(chosen), chosen)
        self.assertIn("pose", chosen)   # 書かれていない項目は足す

    def test_no_person_items_for_scenery(self):
        self.assertTrue(set(variety.PERSON) <= variety.fixed("scenery, no humans"))

    def test_same_seed_repeats(self):
        self.assertEqual(vary_background("1girl", 5), vary_background("1girl", 5))
        self.assertTrue(vary_background("A girl.", 5, tags=False).endswith("."))


class ExploreTest(unittest.TestCase):
    def test_first_model_changes_by_seed_but_prefers_top(self):
        ranked = [(f"m{i}", "") for i in range(6)]
        firsts = [omakase.explore(ranked, s)[0][0] for s in range(600)]
        counts = {m: firsts.count(m) for m in set(firsts)}
        self.assertGreater(counts["m0"], counts["m1"])
        self.assertGreater(counts["m1"], counts["m2"])
        self.assertGreater(sum(v for m, v in counts.items() if m in ("m3", "m4", "m5")), 30)   # 外れも少し混ぜる
        self.assertLess(counts["m0"], 400)
        self.assertEqual(sorted(omakase.explore(ranked, 9)), sorted(ranked))   # 並びは減らさない


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
            self.assertEqual(calls[2][0], 1 + 7919)   # 3 回目は別の種

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
