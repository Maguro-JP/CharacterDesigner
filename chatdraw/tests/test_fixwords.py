"""赤ペンの直しで絵の模型に渡る言葉。偽の模型に渡った言葉を見て、指示の意味・元の絵の言葉・ぶつかる語の外し・種の変化を確かめる。
前は直しの言葉が指示の訳だけで、言葉の模型が無いと「目を大きくして」が空、「指を5本にして」が book になり、
指示を変えても同じ直しになった"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from chatdraw import finishers  # noqa: E402
from chatdraw.engine import Studio, Words  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter  # noqa: E402

SOURCE = "1girl, solo, black hair, long hair, brown eyes, white dress, holding staff, staff in right hand, smile, outdoors"

# 指示、指示の意味として入るはずの語、外れるはずの元の語
CASES = [
    ("目を大きくして", ["large eyes"], []),
    ("指を5本にして", ["five fingers"], []),
    ("髪を赤くして", ["red hair"], ["black hair"]),
    ("もう少し細く", ["slender"], []),
    ("手を直して", ["detailed hands", "five fingers"], []),
    ("右手に剣を持たせて", ["holding sword", "sword in right hand"], ["staff in right hand"]),
    ("服を青いドレスに", ["blue dress"], ["white dress"]),
    ("髪を短くして", ["short hair"], ["long hair"]),
    ("目を閉じて", ["closed eyes"], []),
]


def mask(size=(64, 96)):
    m = Image.new("L", size, 0)
    m.paste(255, (16, 16, 48, 48))
    return m


class FixWordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.painter = FakePainter()
        self.studio = Studio(Words(Path("")), self.painter, Path(self.tmp.name))   # 言葉の模型なし（辞書の訳）
        self.image = Image.new("RGB", (64, 96), (200, 180, 160))

    def tearDown(self):
        self.tmp.cleanup()

    def passed(self, note, seed=1, source=SOURCE):
        said = []
        self.painter.calls.clear()
        self.studio.fix(self.image, [(mask(), note)], seed, on_status=said.append, source=source)
        first = next(c for c in self.painter.calls if c[0] == "redraw")
        return first[1], first[2], said

    def test_each_instruction_reaches_the_model(self):
        for note, want, gone in CASES:
            with self.subTest(note=note):
                prompt, _seed, said = self.passed(note)
                tags = [t.strip() for t in prompt.split(",")]
                for w in want:
                    self.assertIn(w, tags, f"{note} の意味が言葉に入っていない: {prompt}")
                self.assertEqual(tags[0], want[0], f"指示の訳を前に置く: {prompt}")
                self.assertNotIn("book", tags)
                for g in gone:
                    self.assertNotIn(g, tags, f"ぶつかる元の語が残っている: {prompt}")
                for keep in ("1girl", "solo", "outdoors"):   # 元の絵の言葉が入る
                    self.assertIn(keep, tags, prompt)
                self.assertTrue(any(s.startswith("渡した言葉: ") for s in said), "渡した言葉をチャットに出す")

    def test_different_instructions_give_different_words(self):
        prompts = {self.passed(note)[0] for note, _w, _g in CASES}
        self.assertEqual(len(prompts), len(CASES))

    def test_untranslated_word_is_told(self):
        _p, _s, said = self.passed("髪をふわふわにして")
        told = [s for s in said if s.startswith("赤ペンの指示のうち、訳せなかった語")]
        self.assertTrue(told and "ふわふわ" in told[0] and "言葉の模型" in told[0], said)
        self.assertTrue(any(c[0] == "redraw" for c in self.painter.calls), "訳せない語があっても描く")

    def test_seed_changes_each_press_unless_locked(self):
        import random
        seeds = [random.randrange(0, 2_000_000_000) for _ in range(3)]   # aipanel.seeds の固定なしの式
        got = [self.passed("髪を赤くして", seed=s)[1] for s in seeds]
        self.assertEqual(len(set(got)), 3, "押すたびに違う種で直す")
        same = [self.passed("髪を赤くして", seed=5)[1] for _ in range(2)]
        self.assertEqual(same[0], same[1], "種を固定したときは同じ種")

    def test_no_record_reads_tags_from_picture(self):
        from unittest import mock
        fake = mock.Mock()
        fake.read.return_value = {"1girl": 0.99, "green hair": 0.9, "kimono": 0.8}
        with mock.patch("chatdraw.requestcheck._tagger", return_value=fake):
            prompt, _s, _said = self.passed("髪を赤くして", source=None)
        tags = [t.strip() for t in prompt.split(",")]
        self.assertEqual(tags[0], "red hair")
        self.assertIn("kimono", tags)
        self.assertNotIn("green hair", tags)

    def test_finishers_get_source_and_fresh_seed(self):
        finishers.use_painter(self.painter)
        finishers.use_source(SOURCE)
        try:
            run = finishers._redraw_with("masterpiece, clean lineart", 0.25)
            self.painter.calls.clear()
            run(self.image, mask())
            run(self.image, mask())
            calls = [c for c in self.painter.calls if c[0] == "redraw"]
            self.assertIn("white dress", calls[0][1])
            self.assertTrue(calls[0][1].startswith("masterpiece, clean lineart"))
            self.assertNotEqual(calls[0][2], calls[1][2])
        finally:
            finishers.use_source("")
            finishers.use_painter(None)


class FixCheckTest(FixWordsTest):
    def test_kind_sets_strength(self):
        from chatdraw.engine import fix_strength
        from chatdraw.jaterms import fix_tags
        self.assertEqual(fix_strength(0.75, fix_tags("髪を赤くして")[0]), 0.95)
        self.assertEqual(fix_strength(0.75, fix_tags("目を閉じて")[0]), 0.95)
        self.assertEqual(fix_strength(0.6, fix_tags("手を直して")[0]), 0.6)

    def test_region_and_result_are_told_once(self):
        from unittest import mock
        res = {"readable": True, "missing": ["red hair"], "extra": []}
        with mock.patch("chatdraw.requestcheck.check", return_value=res) as chk:
            _p, _s, said = self.passed("髪を赤くして")
        self.assertEqual(chk.call_count, 1, "直したあとの検品は 1 回だけ")
        self.assertTrue(any(s.startswith("直す所: 1 か所目") for s in said), said)
        self.assertTrue(any("指示どおりになっていない" in s and "red hair" in s for s in said), said)
        self.assertEqual(sum(c[0] == "redraw" for c in self.painter.calls if c[1].startswith("red hair")), 1, "直し続けない")


if __name__ == "__main__":
    unittest.main()
