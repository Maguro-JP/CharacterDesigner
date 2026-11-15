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
        def pose(image):
            seen["pose"] = seen.get("pose", 0) + 1
            return {"readable": True, "bad": ["骨の長さの比が外れている"] if always_bad else [], "map": image}

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
        self.assertEqual([r["phase"] for r in got["phases"]], ["構図", "体型と姿勢", "線画", "塗り", "仕上げ"])
        self.assertEqual(files, ["01-構図.png", "02-体型と姿勢.png", "03-線画.png", "04-塗り.png", "05-仕上げ.png", "phases.json"])
        # 構図: ラフ 1 回 + 種を変えた描き直し 1 回（工程の数は半分）。線画: 線に沿って 1 回。直しは各工程 1 回だけ
        self.assertEqual(painter.log[0], ("paint", 5, 10, False))
        self.assertEqual(painter.log[1], ("paint", 6, 10, False))
        self.assertEqual(painter.log[2], ("paint", 7, 10, False))   # 体型と姿勢: 種を変えたラフ 1 回
        self.assertEqual(painter.log[3], ("paint", 5, 20, True))    # 線画: ラフの線に沿う
        self.assertEqual(sum(1 for x in painter.log if x[0] == "paint"), 4)
        self.assertEqual(sum(1 for x in painter.log if x[0] == "redraw"), 3)   # 線画・塗り・仕上げで 1 回ずつ
        self.assertEqual(painter.steps, 20)   # ラフの工程の数を元に戻す
        self.assertTrue(all(r["fixed"] for r in got["phases"]))
        self.assertTrue(got["left"])   # 崩れが残っても終わる（残った崩れを返す）
        self.assertTrue(any(s.startswith(phases.WORDS_NOTE) for s in said))
        # 工程の始めには必ず「工程 i/5「名前」」を出す（アプリの進みの帯がこれで全体の進みを出す）
        for i, (name, *_r) in enumerate(phases.PHASES, 1):
            self.assertTrue(any(s.startswith(f"工程 {i}/5「{name}」") for s in said), name)

    def test_clean_after_first_fix(self):
        got, painter, seen, said, files = self.run_phases(always_bad=False)
        self.assertEqual(got["left"], [])
        self.assertTrue(got["checked"])
        # 構図の 1 回目の検品だけが崩れを返す: 構図の描き直し 1 回、線画 1 回。直したあとは崩れが無いので塗り・仕上げは直さない
        self.assertEqual(sum(1 for x in painter.log if x[0] == "paint"), 3)
        self.assertEqual([r["fixed"] for r in got["phases"]], [True, False, True, False, False])

    def test_no_words_added(self):
        """渡す言葉は頼みの訳だけ。手・足・顔の直しにも five fingers などを足さない"""
        got, painter, *_ = self.run_phases(always_bad=True)
        for r in got["phases"]:
            for w in r["words"]:
                rest = w.replace("(red scarf:1.3)", "red scarf")
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
        self.assertEqual(len(got["phases"]), 5)
        self.assertFalse(any(x[0] == "redraw" for x in painter.log))

    def test_studio_way_phases(self):
        with TemporaryDirectory() as d:
            painter = Painter()
            s = Studio(FakeWords(), painter, Path(d))
            s.way = "phases"
            prompt, path = s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertEqual(prompt, "1girl, red scarf")   # 背景や構図の言葉を足さない
            self.assertTrue(path.exists())
            self.assertEqual([r["phase"] for r in s.last_phases], ["構図", "体型と姿勢", "線画", "塗り", "仕上げ"])
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
                for i, name in enumerate(["構図", "体型と姿勢", "線画", "塗り", "仕上げ"], 1):
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
                self.assertEqual(names[:5], ["工程 1: 構図", "工程 2: 体型と姿勢", "工程 3: 線画", "工程 4: 塗り", "工程 5: 仕上げ"])
                self.assertFalse(any(l.visible for l in c.layers[:5]))
                self.assertEqual(c.current, len(c.layers) - 1)   # 描いた絵が一番上で選ばれたまま
            finally:
                w.dirty = False
                w.close()


if __name__ == "__main__":
    unittest.main()


class BrokenChecksTest(unittest.TestCase):
    """検品の部品が例外を出しても、描く流れは落ちずに最後の工程まで描き、検品できなかったと残す（0.5.30 で 1 工程目のあとに落ちた）"""

    def test_all_phases_drawn_when_checks_raise(self):
        class Boom:
            @staticmethod
            def request(image, prompt):
                raise RuntimeError("部品が無い")
            body = pose = hands = request

        with TemporaryDirectory() as d:
            p = Painter()
            got = phases.draw(p, "red hair, 1girl", 1, (64, 64), Path(d), checks=Boom)
            self.assertEqual(len(got["phases"]), len(phases.PHASES))
            self.assertFalse(got["checked"])
            self.assertIsNotNone(got["image"])


class WindowFlowTest(unittest.TestCase):
    """本物の窓の経路（offscreen の Window、偽の模型）で精度優先を流す。1 工程目のあとに帯が満ちて終わったように見えた"""

    def test_progress_runs_through_five_phases(self):
        import time
        from unittest import mock
        from chatdraw.app import Window
        from chatdraw.tests.test_editing import app
        qapp = app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        s = Studio(FakeWords(), Painter(), Path(d.name))
        s.way = "phases"
        w = Window(s)
        try:
            seen, chat, events = [], [], []
            act = w.activity
            orig = act.status

            def status(msg, step=None, total=None):
                orig(msg, step, total)
                seen.append((act.state.text(), act.bar.value(), act.bar.maximum(), msg))
            act.status = status
            add = w.chat.add
            w.chat.add = lambda who, text, *a, **k: (chat.append(text), add(who, text, *a, **k))[1]
            ends = []
            end = act.end
            act.end = lambda *a, **k: (ends.append(len(seen)), end(*a, **k))[1]
            with mock.patch.object(w, "_keep_original", lambda x: x):
                w._draw_now("赤いマフラーの子")
            w.job.one.connect(lambda *_: events.append("one"))
            w.job.done.connect(lambda: events.append("done"))
            t = time.time()
            while w.thread is not None and time.time() - t < 120:
                qapp.processEvents()
                time.sleep(0.01)
            qapp.processEvents()
            self.assertIsNone(w.thread, "描く処理が終わらない")
            self.assertEqual([r["phase"] for r in s.last_phases], ["構図", "体型と姿勢", "線画", "塗り", "仕上げ"])
            self.assertEqual(events, ["one", "done"])   # 1 枚が出来た・終わったの信号は 5 工程のあとに 1 回ずつ
            self.assertEqual(len(ends), 1)
            # 進み具合の欄に「工程 i/5 名前」が順に出て、終わるまで帯は満ちない
            for i, name in enumerate(["構図", "体型と姿勢", "線画", "塗り", "仕上げ"], 1):
                self.assertTrue(any(st.startswith(f"工程 {i}/5　{name}") for st, *_ in seen), name)
            for st, v, mx, msg in seen[:ends[0]]:
                self.assertFalse(mx > 0 and v >= mx, f"終わる前に帯が満ちた: {st} {msg}")
                self.assertNotIn("完成", st + msg)
                self.assertNotIn("完了", st + msg)
            last5 = max(k for k, (st, *_r) in enumerate(seen) if st.startswith("工程 5/5"))
            first1 = min(k for k, (st, *_r) in enumerate(seen) if st.startswith("工程 1/5　構図"))
            self.assertLess(first1, last5)
            # 模型に渡した言葉は会話に出さず、進み具合の欄の詳細（ツールチップ）にだけ置く
            self.assertFalse([c for c in chat if "渡す言葉" in c or "渡した言葉" in c], chat)
            self.assertIn("模型に渡す言葉: 1girl, red scarf", act.detail.toolTip())
        finally:
            w.dirty = False
            w.close()

    def test_way_pick_switches_mode(self):
        from chatdraw.app import Window
        from chatdraw.settings import AI_MODE, PRECISE
        from chatdraw.tests.test_editing import app
        app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        w = Window(Studio(FakeWords(), Painter(), Path(d.name)))
        old = w.settings.store.value("draw_way")
        try:
            self.assertEqual([w.way_pick.itemText(i) for i in range(w.way_pick.count())], ["AI モード", "精度優先"])
            self.assertTrue(w.way_pick.toolTip())
            w.way_pick.setCurrentIndex(1)
            self.assertEqual(w.studio.way, "phases")
            self.assertEqual(w.settings.get("draw_way"), PRECISE)
            w.way_pick.setCurrentIndex(0)
            self.assertNotEqual(w.studio.way, "phases")
            self.assertEqual(w.settings.get("draw_way"), AI_MODE)
        finally:
            if old is None:
                w.settings.store.remove("draw_way")
            else:
                w.settings.set("draw_way", old)
            w.dirty = False
            w.close()


class WaySettingTest(unittest.TestCase):
    def test_two_modes_and_old_values(self):
        from PySide6.QtCore import QSettings
        from chatdraw.settings import AI_MODE, FIELDS, PRECISE, Settings, studio_way
        field = next(f for f in FIELDS if f[0] == "draw_way")
        self.assertEqual(field[3], f"choice:{AI_MODE},{PRECISE}")
        self.assertEqual(field[4], AI_MODE)   # 既定は AI モード
        self.assertEqual(studio_way(PRECISE, "おまかせ"), "phases")
        self.assertEqual(studio_way(AI_MODE, "おまかせ"), "auto")
        self.assertEqual(studio_way(AI_MODE, "1つの模型で描く"), "one")
        self.assertEqual(studio_way(AI_MODE, "構図と仕上げを分けて描く"), "two")
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for old, way in (("工程に分けて描く", "phases"), ("構図と仕上げを分けて描く", "two"), ("おまかせ", "auto"), ("1つの模型で描く", "one")):
            st = Settings(QSettings(str(Path(d.name) / f"{way}.ini"), QSettings.IniFormat))
            st.set("draw_way", old)   # 前の版の 1 つの欄の値は、選んでいた描き方のまま読む
            self.assertEqual(studio_way(st.get("draw_way"), st.get("ai_way")), way, old)


class CountLimitTest(unittest.TestCase):
    """枚数の欄は数字だけで、8 枚や 9 枚で勝手に止めない"""

    def test_count_spin_has_no_small_cap(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        w = Window(Studio(FakeWords(), FakePainter(), Path(d.name)))
        try:
            spin = w.ai_panel.count_spin
            self.assertEqual(spin.suffix(), "")
            spin.setValue(25)
            self.assertEqual(spin.value(), 25)
        finally:
            w.close()
