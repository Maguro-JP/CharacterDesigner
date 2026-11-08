"""質を下げていた言葉の足し方を戻したことを守る試験（docs/knowledge/filter-audit.md）。

- 好み（学び）が動かすのは質の言葉だけ。構図・姿勢・色・服・背景・人数・髪型・明るさは動かさない
- 足す言葉（variety）は場所だけで、頭の質の言葉を押し出さない
- 打ち消しは CLIP の 75 語片に収め、基準の体の語を崩れの打ち消しより先に置く
- おまかせは点の一番高い模型から描く
"""
import random
import unittest
from unittest import mock


class FakeTokenizer:
    """1 語を 1 語片、記号を 1 語片と数える（本物の CLIP より多めに数える側）"""

    def __call__(self, text, add_special_tokens=False):
        import re
        return {"input_ids": re.findall(r"[a-z0-9]+|[^\sa-z0-9]", text.lower())}


class PrefTable(unittest.TestCase):
    def test_quality_words_pass(self):
        from chatdraw.prefclass import category
        for w in ("masterpiece", "best quality", "absurdres", "very aesthetic", "highly detailed", "clean lineart"):
            self.assertEqual(category(w), "quality", w)

    def test_other_words_blocked(self):
        from chatdraw.prefclass import category, is_quality
        cases = {"full body": "composition", "from above": "composition", "sitting": "pose", "waving": "pose",
                 "red dress": "color", "school uniform": "clothes", "outdoors": "background", "beach": "background",
                 "2girls": "people", "solo": "people", "ponytail": "hair", "long hair": "hair", "dark": "brightness",
                 "backlighting": "brightness"}
        for w, cat in cases.items():
            self.assertEqual(category(w), cat, w)
            self.assertFalse(is_quality(w), w)
        self.assertFalse(is_quality("sword"))   # 表に無い語は通さない


class WordLearn(unittest.TestCase):
    def _stats(self, tags):
        return {"tags": {t: {"n": 10.0, "miss": 10.0} for t in tags}, "models": {"m": {"n": 10.0, "fail": 10.0}}}

    def test_adjust_moves_only_quality(self):
        from chatdraw import wordlearn
        prompt = "1girl, solo, beach, red bikini, waving, masterpiece"
        with mock.patch.object(wordlearn, "stats", return_value=self._stats(["beach", "red bikini", "waving", "masterpiece"])):
            out, moved, explored = wordlearn.adjust(prompt, "m", rng=mock.Mock(random=lambda: 0.99))
        self.assertFalse(explored)
        self.assertEqual(moved, ["masterpiece"])
        self.assertEqual(sorted(t.strip() for t in out.split(",")), sorted(t.strip() for t in prompt.split(",")))

    def test_guidance_not_moved(self):
        from chatdraw import wordlearn
        with mock.patch.object(wordlearn, "stats", return_value=self._stats([])):
            self.assertEqual(wordlearn.guidance("m", 5.0), 5.0)


class Variety(unittest.TestCase):
    def test_only_place_added(self):
        from chatdraw import variety
        base = "1girl, solo, smile"
        for seed in range(40):
            out = variety.vary(base, seed, tags=True, text=base)
            added = [t.strip() for t in out[len(base):].split(",") if t.strip()]
            words = variety.added_words()
            self.assertTrue(all(a.lower() in words for a in added), (seed, added))
            for k in ("shot", "pose", "hair", "hair_color", "clothes", "face", "light"):
                for tag, _s in dict(variety.TABLES)[k][0]:
                    if tag.lower() not in words:
                        self.assertNotIn(tag, out[len(base):], (seed, k))

    def test_quality_prefix_kept(self):
        from chatdraw import engine
        from chatdraw.variety import vary
        tok = FakeTokenizer()
        prefix = "masterpiece, best quality, newest, absurdres, highres, safe, "
        for req in ("1girl, solo, knight, silver armor, holding sword, standing",
                    "1girl, solo, red bikini, long hair, beach, waving", "1boy, solo, guitar, rooftop, night"):
            for seed in range(20):
                body = vary(req, seed, tags=True, text=req)
                text = engine.fit_tokens(tok, prefix, body, "")
                self.assertTrue(text.startswith("masterpiece"), (req, seed, text))
                self.assertIn(req, text)


class Negative(unittest.TestCase):
    def test_negative_fits_and_body_first(self):
        from chatdraw import engine
        from chatdraw.body import NEGATIVE as BODY
        from chatdraw.sanity import NEGATIVE as SANE
        tok = FakeTokenizer()
        neg = engine.fit_negative(tok, ", ".join(["lowres, worst quality, low quality", BODY, SANE]))
        self.assertLessEqual(len(tok(neg)["input_ids"]), 75)
        self.assertTrue(neg.startswith("lowres"))

    def test_sanity_negative_uses_known_tags(self):
        from chatdraw.sanity import NEGATIVE
        for w in ("eyes on body", "eyes on objects", "floating limbs", "impossible anatomy", "conjoined"):
            self.assertNotIn(w, NEGATIVE)


class Omakase(unittest.TestCase):
    def test_best_model_first(self):
        from chatdraw import omakase
        ranked = ["a", "b", "c", "d", "e"]
        for seed in range(50):
            self.assertEqual(omakase.explore(ranked, seed), ranked)


if __name__ == "__main__":
    unittest.main()
