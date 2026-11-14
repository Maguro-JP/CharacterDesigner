"""工程に分けて描く（chatdraw/phases.py）を偽の模型と偽の検品で通す。
工程は構図 → 線画 → 塗り → 仕上げの順、各工程の直しは 1 回だけ、検品がずっと崩れを返しても必ず終わる。
0.5.20 で「検品を通るまで直す」を繋げたら終わらなくなったので、回数が決まっていることを数えて確かめる"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw import phases  # noqa: E402
from chatdraw.engine import Stopped, Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402

HAND = {"readable": True, "bad": ["手 1: 指が 6 本"], "hands": [{"box": [10, 10, 30, 30], "bad": ["指が 6 本"], "seen": True}],
        "feet": [], "faces": []}
CLEAN_HAND = {"readable": True, "bad": [], "hands": [], "feet": [], "faces": []}


class Painter(FakePainter):
    abilities = (True, True)
    steps = 20

    def __init__(self):
        super().__init__()
        self.log = []

    def paint(self, prompt, seed, on_step=None, **kw):
        self.log.append(("paint", seed, self.steps, "base" in kw and kw["base"] is not None))
        return super().paint(prompt, seed, on_step=on_step, **kw)

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        self.log.append(("redraw", seed, kw.get("strength")))
        return super().redraw(prompt, seed, image, mask, on_step=on_step, **kw)


def checks(always_bad: bool):
    """always_bad: どの検品も毎回崩れを返す（直しても消えない）。False: 1 回目だけ崩れを返す"""
    seen = {"request": 0, "body": 0, "hands": 0}

    class C:
        @staticmethod
        def request(image, prompt):
            seen["request"] += 1
            bad = always_bad or seen["request"] == 1
            return {"readable": True, "missing": ["red scarf"] if bad else [], "extra": [], "people": [], "body": []}

        @staticmethod
        def body(image, prompt, tags=None):
            seen["body"] += 1
            return {"readable": True, "bad": ["余分な腕"] if always_bad else [], "avoid": []}

        @staticmethod
        def hands(image, prompt):
            seen["hands"] += 1
            return dict(HAND) if (always_bad or seen["hands"] == 1) else dict(CLEAN_HAND)
    return C, seen


class PhasesTest(unittest.TestCase):
    def run_phases(self, always_bad, painter=None):
        painter = painter or Painter()
        C, seen = checks(always_bad)
        said = []
        with TemporaryDirectory() as d:
            got = phases.draw(painter, "1girl, red scarf", 5, (64, 96), Path(d) / "k", say=said.append, checks=C)
            files = sorted(p.name for p in (Path(d) / "k").iterdir())
        return got, painter, seen, said, files

    def test_order_and_one_fix_each(self):
        got, painter, seen, said, files = self.run_phases(always_bad=True)
        self.assertEqual([r["phase"] for r in got["phases"]], ["構図", "線画", "塗り", "仕上げ"])
        self.assertEqual(files, ["1-構図.png", "2-線画.png", "3-塗り.png", "4-仕上げ.png", "phases.json"])
        # 構図: ラフ 1 回 + 種を変えた描き直し 1 回（工程の数は半分）。線画: 線に沿って 1 回。直しは各工程 1 回だけ
        self.assertEqual(painter.log[0], ("paint", 5, 10, False))
        self.assertEqual(painter.log[1], ("paint", 6, 10, False))
        self.assertEqual(painter.log[2], ("paint", 5, 20, True))
        self.assertEqual(sum(1 for x in painter.log if x[0] == "paint"), 3)
        self.assertEqual(sum(1 for x in painter.log if x[0] == "redraw"), 3)   # 線画・塗り・仕上げで 1 回ずつ
        self.assertEqual(painter.steps, 20)   # ラフの工程の数を元に戻す
        self.assertTrue(all(r["fixed"] for r in got["phases"]))
        self.assertTrue(got["left"])   # 崩れが残っても終わる（残った崩れを返す）
        self.assertTrue(any("渡す言葉" in s for s in said))

    def test_clean_after_first_fix(self):
        got, painter, seen, said, files = self.run_phases(always_bad=False)
        self.assertEqual(got["left"], [])
        self.assertTrue(got["checked"])
        # 構図の 1 回目の検品だけが崩れを返す: 構図の描き直し 1 回、線画 1 回。直したあとは崩れが無いので塗り・仕上げは直さない
        self.assertEqual(sum(1 for x in painter.log if x[0] == "paint"), 3)
        self.assertEqual([r["fixed"] for r in got["phases"]], [True, True, False, False])

    def test_no_words_added(self):
        """渡す言葉は頼みの訳と、手・足・顔の直しの言葉だけ"""
        got, *_ = self.run_phases(always_bad=True)
        from chatdraw.handcheck import FIX_WORDS
        for r in got["phases"]:
            for w in r["words"]:
                rest = w.replace("(red scarf:1.3)", "red scarf")
                for fw in FIX_WORDS.values():
                    rest = rest.replace(fw, "")
                self.assertEqual({t.strip() for t in rest.split(",") if t.strip()} - {"1girl", "red scarf"}, set(), w)

    def test_stop_between_phases(self):
        painter = Painter()
        C, _ = checks(always_bad=True)
        orig = C.hands

        def hands(image, prompt):
            painter.stop = True   # 線画の検品のあとに止める
            return orig(image, prompt)
        C.hands = staticmethod(hands)
        with TemporaryDirectory() as d, self.assertRaises(Stopped):
            phases.draw(painter, "1girl", 1, (64, 96), Path(d) / "k", checks=C)

    def test_without_line_or_fix_still_finishes(self):
        painter = Painter()
        painter.abilities = (False, False)
        got, painter, *_ = self.run_phases(always_bad=True, painter=painter)
        self.assertEqual(len(got["phases"]), 4)
        self.assertFalse(any(x[0] == "redraw" for x in painter.log))

    def test_studio_way_phases(self):
        with TemporaryDirectory() as d:
            painter = Painter()
            s = Studio(FakeWords(), painter, Path(d))
            s.way = "phases"
            prompt, path = s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertEqual(prompt, "1girl, red scarf")   # 背景や構図の言葉を足さない
            self.assertTrue(path.exists())
            self.assertEqual([r["phase"] for r in s.last_phases], ["構図", "線画", "塗り", "仕上げ"])
            s.way = "one"
            s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertIsNone(s.last_phases)


class PhaseLayersTest(unittest.TestCase):
    def test_phase_images_are_hidden_layers_below(self):
        from PIL import Image
        from chatdraw.app import Window
        from chatdraw.tests.test_editing import app
        qapp = app()
        with TemporaryDirectory() as d:
            d = Path(d)
            w = Window(Studio(FakeWords(), Painter(), d))
            try:
                rows = []
                for i, name in enumerate(["構図", "線画", "塗り", "仕上げ"], 1):
                    p = d / f"{i}.png"
                    Image.new("RGB", (64, 64), (i * 40, 0, 0)).save(p)
                    rows.append({"phase": name, "image": str(p), "found": ["崩れ"], "fixed": True, "after": [], "seconds": 1.0})
                final = d / "final.png"
                Image.new("RGB", (64, 64), "white").save(final)
                w.mode.setCurrentIndex(0)
                w.job_kind = "draw"
                w.studio.last_phases = rows
                w.images.append("x")
                w.place(str(final))
                w._put_phases()
                qapp.processEvents()
                c = w.canvas
                names = [l.name for l in c.layers]
                self.assertEqual(names[:4], ["工程 1: 構図", "工程 2: 線画", "工程 3: 塗り", "工程 4: 仕上げ"])
                self.assertFalse(any(l.visible for l in c.layers[:4]))
                self.assertEqual(c.current, len(c.layers) - 1)   # 描いた絵が一番上で選ばれたまま
            finally:
                w.dirty = False
                w.close()


if __name__ == "__main__":
    unittest.main()
