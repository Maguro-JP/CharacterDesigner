"""矛盾の検品（chatdraw/sanity.py の from_tags）と、検品できなかった絵を崩れとして描き直しに回す経路（chatdraw/engine.py）。
規則は模型なしで確かめ、描き直しの経路は偽の模型（FakePainter）で本物と同じ Studio.draw を通す"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chatdraw import sanity


class ContradictionTagsTest(unittest.TestCase):
    """数・物理・左右・目の色・人数の食い違いを、絵全体のタグで崩れにする。頼んだ物は崩れにしない"""

    def test_each_kind(self):
        cases = {
            "体から離れた手足": {"disembodied limb": 0.6},
            "途切れた手足": {"severed limb": 0.6},
            "宙に浮く持ち物": {"floating object": 0.7},
            "左右で食い違う服や飾り": {"single glove": 0.6},
            "左右で違う目": {"heterochromia": 0.6},
            "人数が違う": {"multiple girls": 0.8},
            "腕が多い": {"extra arms": 0.5},
            "耳が多い": {"extra ears": 0.6},
        }
        for word, got in cases.items():
            with self.subTest(word=word):
                out = sanity.from_tags(got, "1girl, solo, blue eyes")
                self.assertTrue(any(o.startswith(word) for o in out), out)

    def test_asked_is_not_a_flaw(self):
        self.assertEqual(sanity.from_tags({"single glove": 0.8}, "1girl, single glove"), [])
        self.assertEqual(sanity.from_tags({"asymmetrical legwear": 0.8}, "1girl, asymmetrical outfit"), [])
        self.assertEqual(sanity.from_tags({"heterochromia": 0.9}, "1girl, heterochromia"), [])
        self.assertEqual(sanity.from_tags({"multiple girls": 0.9}, "2girls"), [])
        self.assertEqual(sanity.from_tags({"floating object": 0.9}, "1girl, floating object, magic"), [])

    def test_eye_color_other_than_asked(self):
        out = sanity.from_tags({"red eyes": 0.8}, "1girl, blue eyes")
        self.assertTrue(any("頼んでいない目の色" in o for o in out), out)
        self.assertEqual(sanity.from_tags({"blue eyes": 0.7, "aqua eyes": 0.6}, "1girl, blue eyes"), [])   # 近い色は同じ
        self.assertEqual(sanity.from_tags({"blue eyes": 0.5, "red eyes": 0.7}, "1girl, blue eyes"), [])    # 頼んだ色が読める
        self.assertTrue(sanity.from_tags({"yellow eyes": 0.7}, "1girl"))   # 色を頼んでいなければ黄色い目は崩れ

    def test_too_few_people(self):
        out = sanity.from_tags({"solo": 0.9}, "2girls, park")
        self.assertTrue(any(o.startswith("人数が違う") for o in out), out)

    def test_avoid_words(self):
        bad = sanity.from_tags({"single glove": 0.6, "disembodied limb": 0.6}, "1girl")
        words = sanity.avoid_words(bad)
        self.assertIn("single glove", words)
        self.assertIn("disembodied limb", words)


class Words:
    negative: list = []

    def to_prompt(self, text, tags=True):
        return text


class UncheckedIsFlawTest(unittest.TestCase):
    """検品の部品が無い・読めない絵は「崩れが無い」ではなく崩れの 1 件にし、通ったことにしない"""

    def _draw(self, hand, asked, odd, own):
        from chatdraw import finishers, handcheck, origqc, requestcheck
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter
        s = Studio(Words(), FakePainter(), Path(tempfile.mkdtemp()))
        s.REDRAW_TRIES = 1
        with mock.patch.dict(os.environ, {"CD_CHECK": "on"}), \
                mock.patch.object(handcheck, "check", lambda im, asked=None: dict(hand)), \
                mock.patch.object(origqc, "check", lambda im, p, hair="": dict(own)), \
                mock.patch.object(requestcheck, "check", lambda im, t: dict(asked)), \
                mock.patch.object(sanity, "check", lambda im, p, tags=None: dict(odd)):
            _p, path = s.draw("1girl, solo", 7)
        return finishers.sidecar(path)

    ok_hand = {"readable": True, "bad": [], "hands": []}
    ok_asked = {"readable": True, "missing": [], "extra": []}
    ok_odd = {"readable": True, "bad": [], "avoid": []}
    ok_own = {"readable": True, "bad": [], "regions": [], "measured": True}

    def test_all_read_passes(self):
        meta = self._draw(self.ok_hand, self.ok_asked, self.ok_odd, self.ok_own)
        self.assertTrue(meta["passed"])
        self.assertEqual(meta["redraws"][-1]["bad"], [])

    def test_each_unread_is_a_flaw(self):
        cases = {
            "手と指": dict(hand={"readable": False, "bad": [], "hands": [], "reason": "部品が無い"}),
            "数字の作画監督": dict(own={"readable": True, "bad": [], "regions": [], "measured": False,
                                   "notes": ["部品が無い: depth"]}),
            "頼んだ物と人数": dict(asked={"readable": False, "missing": [], "extra": [], "reason": "部品が無い"}),
            "体の数と目": dict(odd={"readable": False, "bad": [], "avoid": [], "reason": "部品が無い"}),
        }
        for what, kw in cases.items():
            with self.subTest(what=what):
                args = dict(hand=self.ok_hand, asked=self.ok_asked, odd=self.ok_odd, own=self.ok_own)
                args.update(kw)
                meta = self._draw(**args)
                self.assertFalse(meta["passed"])
                bad = meta["redraws"][0]["bad"]
                self.assertTrue(any(b.startswith("検品できなかった: " + what) for b in bad), bad)

    def test_non_inpaint_model_is_still_checked(self):
        """囲みの直しのできない模型でも、手と作画監督の検品を通す（前は飛ばしていた）"""
        meta = self._draw({"readable": True, "bad": ["指が 6 本"], "hands": []}, self.ok_asked, self.ok_odd, self.ok_own)
        self.assertFalse(meta["passed"])
        self.assertIn("指が 6 本", meta["hand_rounds"][0]["bad"])


if __name__ == "__main__":
    unittest.main()
