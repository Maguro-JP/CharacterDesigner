"""工程に分けて描く（chatdraw/phases.py）を偽の模型と偽の検品で通す。
工程は人の描き方の 12、各工程の直しは 1 回だけ、戻る回数にも上限があり、検品がずっと崩れを返しても必ず終わる。
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


def figure(size=(64, 96)):
    """白い紙に、暗い人物（体と頭）を置いた絵。右側を明るくして光の向きが読めるようにする"""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([w * 0.35, h * 0.25, w * 0.5, h * 0.95], fill=(60, 60, 80))
    d.rectangle([w * 0.5, h * 0.25, w * 0.65, h * 0.95], fill=(150, 150, 170))
    d.ellipse([w * 0.38, h * 0.05, w * 0.62, h * 0.25], fill=(120, 100, 90))
    return im


class Painter(FakePainter):
    abilities = (True, True)
    steps = 20

    def __init__(self):
        super().__init__()
        self.log = []

    def paint(self, prompt, seed, on_step=None, **kw):
        self.log.append(("paint", seed, self.steps, "base" in kw and kw["base"] is not None, kw.get("size")))
        super().paint(prompt, seed, on_step=on_step, **kw)
        if kw.get("on_preview"):
            kw["on_preview"](figure(kw.get("size") or (64, 96)))
        return figure(kw.get("size") or (64, 96))

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        self.log.append(("redraw", seed, kw.get("strength")))
        self.masks = getattr(self, "masks", []) + [mask]
        return image.copy()


def checks(always_bad: bool):
    """always_bad: どの検品も毎回崩れを返す（直しても消えない）。False: 1 回目だけ崩れを返す"""
    seen = {"request": 0, "body": 0, "hands": 0, "pose": 0}

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
        def points(image):
            w, h = image.size
            return {"readable": True, "points": {"left_eye": (w * 0.45, h * 0.15), "right_eye": (w * 0.55, h * 0.15),
                                                 "nose": (w * 0.5, h * 0.18), "left_ear": (w * 0.4, h * 0.15),
                                                 "left_shoulder": (w * 0.4, h * 0.27), "right_shoulder": (w * 0.6, h * 0.27)}}

        @staticmethod
        def pose(image):
            seen["pose"] += 1
            return {"readable": True, "bad": ["骨の長さの比が外れている"] if always_bad else [], "map": image}

        @staticmethod
        def hands(image, prompt):
            seen["hands"] += 1
            return dict(HAND) if (always_bad or seen["hands"] == 1) else dict(CLEAN_HAND)
    return C, seen


N = len(phases.PHASES)


class PhasesTest(unittest.TestCase):
    def run_phases(self, always_bad, painter=None, confirm=None):
        painter = painter or Painter()
        C, seen = checks(always_bad)
        said = []
        with TemporaryDirectory() as d:
            got = phases.draw(painter, "1girl, red scarf", 5, (64, 96), Path(d) / "k", say=said.append, checks=C, confirm=confirm)
            files = sorted(p.name for p in (Path(d) / "k").iterdir())
        return got, painter, seen, said, files

    def test_twelve_phases_in_order(self):
        self.assertEqual(phases.NAMES, ["目的", "サムネイル", "アタリ", "体の形", "顔・手・足の下描き", "服・髪・持ち物", "線画の清書",
                                        "下塗り", "光源", "影 2 段", "光・艶・目のハイライト", "仕上げ"])
        for name, decides, looks, numbers in phases.PHASES:
            self.assertTrue(decides and looks and numbers, name)   # 工程ごとに見る物と判定の数字を決めてある

    def test_always_bad_still_finishes_with_bounded_backs(self):
        got, painter, seen, said, files = self.run_phases(always_bad=True)
        self.assertEqual([r["phase"] for r in got["phases"]], phases.NAMES)
        self.assertEqual(len([f for f in files if f.endswith(".png")]), N - 1)   # 目的には絵が無い
        self.assertIn("phases.json", files)
        self.assertLessEqual(got["backs"], phases.BACKS)
        self.assertGreater(got["backs"], 0)   # 崩れが残ったので、崩れが決まった工程へ戻った
        self.assertTrue(any("そこへ戻って直します" in s for s in said))
        self.assertTrue(got["left"])   # 崩れが残っても終わる（残った崩れを返す）
        self.assertEqual(painter.steps, 20)   # 減らした工程の数を元に戻す
        # 描く回数に上限がある（サムネイル 2 枚 + アタリ 2 回、戻る回数ぶん）
        self.assertLessEqual(sum(1 for x in painter.log if x[0] == "paint"), 40)
        for i, name in enumerate(phases.NAMES, 1):
            self.assertTrue(any(s.startswith(f"工程 {i}/{N}「{name}」") for s in said), name)

    def test_thumbnails_small_and_picked(self):
        got, painter, *_ = self.run_phases(always_bad=False)
        thumbs = [x for x in painter.log if x[0] == "paint" and x[4] and x[2] == 5]
        self.assertEqual(len(thumbs), phases.THUMBS)   # 工程の数を 1/4 にした小さな絵を何枚か
        self.assertIn("picked", got["phases"][1]["numbers"])

    def test_clean_after_first_fix(self):
        got, painter, seen, said, files = self.run_phases(always_bad=False)
        self.assertEqual(got["left"], [])
        self.assertEqual(got["backs"], 0)
        for r in got["phases"]:   # 工程ごとに秒とメモリを残す
            self.assertIn("seconds", r)
            self.assertIn("mem_mb", r)

    def test_no_words_added(self):
        """渡す言葉は頼みの訳だけ。手・足・顔の直しにも five fingers などを足さない"""
        got, painter, *_ = self.run_phases(always_bad=True)
        for r in got["history"]:
            for w in r["words"]:
                rest = w.replace("(red scarf:1.3)", "red scarf")
                self.assertEqual({t.strip() for t in rest.split(",") if t.strip()} - {"1girl", "red scarf"}, set(), w)

    def test_stop_between_phases(self):
        painter = Painter()
        C, _ = checks(always_bad=True)
        orig = C.hands

        def hands(image, prompt):
            painter.stop = True
            return orig(image, prompt)
        C.hands = staticmethod(hands)
        with TemporaryDirectory() as d, self.assertRaises(Stopped):
            phases.draw(painter, "1girl", 1, (64, 96), Path(d) / "k", checks=C)

    def test_without_line_or_fix_still_finishes(self):
        painter = Painter()
        painter.abilities = (False, False)
        got, painter, *_ = self.run_phases(always_bad=True, painter=painter)
        self.assertEqual(len(got["phases"]), N)
        self.assertFalse(any(x[0] == "redraw" for x in painter.log))

    def test_fix_masks_are_regions_only(self):
        """直しは囲みの中だけ（絵全体を描き直さない）"""
        import numpy as np
        got, painter, *_ = self.run_phases(always_bad=True)
        self.assertTrue(painter.masks)
        for m in painter.masks:
            a = np.asarray(m)
            self.assertLess((a > 0).mean(), 0.99)

    def test_confirm_redo_and_words(self):
        asked, answers = [], {2: ["redo", "go"], 5: [("words", "blue ribbon"), "go"]}

        def confirm(i, name, image, row):
            asked.append(i)
            todo = answers.get(i)
            return todo.pop(0) if todo else "go"
        got, painter, seen, said, files = self.run_phases(always_bad=False, confirm=confirm)
        self.assertEqual(asked.count(2), 2)   # 描き直した工程はもう一度確かめる
        self.assertEqual(asked.count(5), 2)
        self.assertEqual(got["phases"][2]["visit"], 1)
        self.assertTrue(any("blue ribbon" in w for r in got["history"] for w in r["words"]))
        self.assertTrue(any("言葉を足しました" in s for s in said))

    def test_studio_way_phases(self):
        with TemporaryDirectory() as d:
            painter = Painter()
            s = Studio(FakeWords(), painter, Path(d))
            s.way = "phases"
            prompt, path = s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertEqual(prompt, "1girl, red scarf")   # 背景や構図の言葉を足さない
            self.assertTrue(path.exists())
            self.assertEqual([r["phase"] for r in s.last_phases], phases.NAMES)
            s.way = "one"
            s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertIsNone(s.last_phases)

    def test_studio_confirm_translates_words(self):
        with TemporaryDirectory() as d:
            s = Studio(FakeWords(), Painter(), Path(d))
            s.way = "phases"
            calls = []

            def ask(i, name, image, row):
                calls.append(i)
                return ("words", "赤いマフラー") if len(calls) == 1 else "go"
            s.phase_confirm = ask
            s.draw("赤いマフラーの子", 7, lambda m: None)
            words = [w for r in s.last_phases for w in r["words"]]
            self.assertFalse(any("マフラー" in w for w in words), words)   # 日本語のまま模型に渡さない


class ToolsTest(unittest.TestCase):
    """模型を使わない処理（chatdraw/phasetools.py）が、人物の外を変えず、数字を返す"""

    def test_lines_and_shade_only_inside_figure(self):
        import numpy as np
        from chatdraw import phasetools as pt
        im = figure((128, 192))
        out, hit = pt.weight_lines(im)
        a, b = np.asarray(im), np.asarray(out)
        m = pt._dilate(pt.silhouette(im), 1)
        self.assertTrue((a[~m] == b[~m]).all())
        lit = pt.light(im)
        self.assertEqual(lit["side"], "右")
        out2, hit2 = pt.shade_second(im, lit)
        self.assertGreater(hit2, 0)
        c = np.asarray(out2)
        self.assertTrue((a[~pt.silhouette(im)] == c[~pt.silhouette(im)]).all())
        cols = np.nonzero((a != c).any(axis=2))[1]
        self.assertTrue((cols < 64).all())   # 影の 2 段目は光と反対（左）の側だけ

    def test_numbers(self):
        from chatdraw import phasetools as pt
        im = figure((128, 192))
        self.assertTrue(pt.balance(im)["readable"])
        self.assertLess(pt.balance(im)["balance"], pt.BALANCE_MOST)
        self.assertEqual(pt.eye_tilt({"left_eye": (0, 10), "right_eye": (20, 10)}), 0.0)
        self.assertGreater(pt.eye_tilt({"left_eye": (0, 0), "right_eye": (20, 10)}), pt.EYE_TILT)
        self.assertTrue(pt.shrink_view(im)["readable"])
        self.assertTrue(pt.flip_view(im, (40, 0, 90, 50))["readable"])
        self.assertIn("weight_x", pt.thumb_weight(im))


class ToneGuardTest(unittest.TestCase):
    """描き重ねで出た霞み・枠・色褪せを、前の絵の色と明るさに合わせて消す（phase-bench の線画で出た崩れ）"""

    def test_haze_and_frame_removed(self):
        import numpy as np
        from PIL import Image, ImageDraw
        from chatdraw import phasetools as pt
        ref = figure((128, 192))
        a = np.asarray(ref, dtype=np.float32) * 0.5 + 110   # 黒が浮いて白く霞む・色が褪せる
        hazy = Image.fromarray(a.astype("uint8"))
        ImageDraw.Draw(hazy).rectangle([0, 0, 127, 191], outline=(40, 40, 40), width=4)   # 額縁のような枠
        self.assertTrue(pt.tone_flaws(pt.tone(hazy), pt.tone(ref)))
        out, rec = pt.guard(hazy, ref)
        self.assertTrue(rec["raw_flaws"])
        self.assertEqual(pt.tone_flaws(pt.tone(out), pt.tone(ref)), [])

    def test_mask_keeps_outside(self):
        import numpy as np
        from PIL import Image
        from chatdraw import phasetools as pt
        ref = figure((128, 192))
        other = Image.new("RGB", ref.size, (10, 200, 30))
        mask = Image.new("L", ref.size, 0)
        mask.paste(255, (40, 40, 80, 80))
        out, _ = pt.guard(other, ref, mask)
        a, b, m = np.asarray(out), np.asarray(ref), np.asarray(mask) == 0
        self.assertTrue((a[m] == b[m]).all())


class ConfirmBridgeTest(unittest.TestCase):
    """描く糸から呼んだ確かめが、画面の糸の窓の答えを待って返す"""

    def test_worker_waits_for_answer(self):
        import threading
        import time
        from chatdraw.app import PhaseAsk
        from chatdraw.tests.test_editing import app
        qapp = app()

        class W:
            studio = type("S", (), {"painter": Painter()})()

            def ask_phase(self, i, name, image, row):
                return "redo"
        ask = PhaseAsk(W())
        got = []
        t = threading.Thread(target=lambda: got.append(ask(1, "サムネイル", None, {})))
        t.start()
        end = time.time() + 10
        while t.is_alive() and time.time() < end:
            qapp.processEvents()
            time.sleep(0.01)
        self.assertEqual(got, ["redo"])


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

    def test_progress_runs_through_all_phases(self):
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
            self.assertEqual([r["phase"] for r in s.last_phases], phases.NAMES)
            self.assertEqual(events, ["one", "done"])   # 1 枚が出来た・終わったの信号は全部の工程のあとに 1 回ずつ
            self.assertEqual(len(ends), 1)
            # 進み具合の欄に「工程 i/12 名前」が順に出て、終わるまで帯は満ちない
            for i, name in enumerate(phases.NAMES, 1):
                self.assertTrue(any(st.startswith(f"工程 {i}/{N}　{name}") for st, *_ in seen), name)
            for st, v, mx, msg in seen[:ends[0]]:
                self.assertFalse(mx > 0 and v >= mx, f"終わる前に帯が満ちた: {st} {msg}")
                self.assertNotIn("完成", st + msg)
                self.assertNotIn("完了", st + msg)
            last5 = max(k for k, (st, *_r) in enumerate(seen) if st.startswith(f"工程 {N}/{N}"))
            first1 = min(k for k, (st, *_r) in enumerate(seen) if st.startswith(f"工程 1/{N}　目的"))
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


class PreviewTest(unittest.TestCase):
    """精度優先でも、描いている途中の絵と工程ごとの絵を窓に渡す（描いている所を画面に見せる）"""

    def test_each_phase_image_is_shown(self):
        shown = []
        with TemporaryDirectory() as d:
            phases.draw(Painter(), "red hair, 1girl", 1, (64, 64), Path(d), checks=checks(False)[0], on_preview=shown.append)
        self.assertGreaterEqual(len(shown), len(phases.PHASES))


class NoSketchModelTest(unittest.TestCase):
    """線に沿う部品も範囲の直しも無い世代（FLUX.1 など）でも、線画と塗りの工程を描き重ねで進める（前は構図の絵のまま止まっていた）"""

    def test_refine_used_when_no_sketch(self):
        class Dit(Painter):
            abilities = (False, False)

            def refine(self, prompt, seed, image, strength=0.5, on_step=None, on_preview=None):
                self.log.append(("refine", seed, strength))
                return image

        with TemporaryDirectory() as d:
            p = Dit()
            C, _seen = checks(False)
            got = phases.draw(p, "1girl, red scarf", 1, (64, 64), Path(d), checks=C)
        self.assertEqual(len(got["phases"]), len(phases.PHASES))
        self.assertTrue(any(x[0] == "refine" for x in p.log), p.log)
