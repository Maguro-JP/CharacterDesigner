"""「描かせたらずっと止まっている」の試験。

本物と同じ経路（頼みを書いて「描く」→ 裏の糸の Job → Studio.draw → 模型）で、知らせを出さない重い所
（CPU の 1 歩、部品の取得、メモリの空き待ち、工程の確かめの窓）を偽の模型で長く走らせ、
進み具合の欄の知らせが 10 秒以上途切れないこと、画面の糸が固まらないこと、何を待っているかが出ること、
一時停止で待って続けられることを測る。0.5.36 までは、この間に何も出ず止まって見えた。
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402

SILENT = 13.0   # 知らせを出さない重い所の長さ（秒）。10 秒より長くして途切れを起こす
GAP = 10.0      # 知らせが途切れてよい長さの上限（秒）
FREEZE = 0.2    # 画面の糸が固まってよい長さの上限（秒）


def busy(sec: float):
    end = time.time() + sec
    while time.time() < end:
        time.sleep(0.02)


class SilentPainter(FakePainter):
    """1 歩の中で SILENT 秒、知らせを出さずに動く（CPU で大きな模型の 1 歩を回すのと同じ）"""

    def __init__(self, note: str | None = None, times: int = 1):
        super().__init__()
        self.note, self.left = note, times

    def paint(self, prompt, seed, on_step=None, **kw):
        self.left -= 1
        if self.left < 0:
            pass
        elif self.note:
            from chatdraw import waitnote
            with waitnote.waiting(self.note):
                busy(SILENT)
        else:
            busy(SILENT)
        return super().paint(prompt, seed, on_step=on_step, **kw)


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class Watch:
    """進み具合の欄の知らせの時刻と、画面の糸の固まりを測る"""

    def __init__(self, w):
        from PySide6.QtCore import QTimer
        self.msgs, self.freezes, self.states = [], [], []
        orig = w.activity.status

        def status(msg, *a):
            self.msgs.append((time.monotonic(), msg))
            orig(msg, *a)
            self.states.append(w.activity.state.text())
        w.activity.status = status
        self.last = time.monotonic()
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)

    def _tick(self):
        now = time.monotonic()
        if now - self.last > FREEZE:
            self.freezes.append(round(now - self.last, 2))
        self.last = now

    def gaps(self, t0):
        out, prev = [], t0
        for t, _m in self.msgs:
            out.append(t - prev)
            prev = t
        return out


def run_until_done(a, w, limit):
    end = time.time() + limit
    while time.time() < end and w.thread is not None:
        a.processEvents()
        time.sleep(0.005)
    a.processEvents()


class StallTest(unittest.TestCase):
    def draw(self, painter, way="one", before=None):
        from chatdraw.app import Window
        a = app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        studio = Studio(FakeWords(), painter, Path(d.name))
        studio.way = way
        w = Window(studio)
        self.addCleanup(w.close)
        w.settings.set("output_dir", str(Path(d.name) / "out"))
        watch = Watch(w)
        w.entry.setText("赤い髪の女の人")
        t0 = time.monotonic()
        watch.last = t0
        w.send()
        if before:
            before(a, w)
        run_until_done(a, w, SILENT * 4 + 30)
        watch.timer.stop()
        return w, watch, t0

    def test_notice_never_gap_10s_one_draw(self):
        w, watch, t0 = self.draw(SilentPainter())
        gaps = watch.gaps(t0)
        print(f"\n  1 回で描く: 知らせ {len(gaps)} 件、一番長い途切れ {max(gaps):.1f} 秒、画面の固まり {watch.freezes}")
        self.assertEqual(len(w.images), 1, "描き終えていない")
        self.assertLess(max(gaps), GAP, "知らせが 10 秒以上途切れた")
        self.assertTrue(any(m.startswith("動いています: ") for _t, m in watch.msgs), "途切れた間に何をしているかが出ない")
        # 重い所の間（画面の糸は何もしていない）に固まらない
        self.assertFalse([f for f in watch.freezes if f > 0.5], f"画面の糸が固まった: {watch.freezes}")

    def test_waiting_note_is_shown(self):
        _w, watch, _t0 = self.draw(SilentPainter("検品の部品（試験）を取っています"))
        self.assertTrue(any("待っています: 検品の部品（試験）を取っています" in m for _t, m in watch.msgs),
                        "何を待っているかが出ない")

    def test_notice_never_gap_10s_phases(self):
        w, watch, t0 = self.draw(SilentPainter(), way="phases")
        gaps = watch.gaps(t0)
        print(f"\n  精度優先: 知らせ {len(gaps)} 件、一番長い途切れ {max(gaps):.1f} 秒")
        self.assertEqual(len(w.images), 1, "描き終えていない")
        self.assertLess(max(gaps), GAP, "知らせが 10 秒以上途切れた")
        said = [m for _t, m in watch.msgs]
        self.assertTrue(any("約 13 倍" in m for m in said), "始める前に長くかかることを出していない")
        self.assertTrue(any("目安" in m for m in said))
        # 精度優先の回に、1 回で描く回の 5 段の番号（工程 1/5 確認中）を出さない
        self.assertFalse([t for t in watch.states if "/5" in t], watch.states[:5])
        self.assertTrue(any(t.startswith("工程 2/12") for t in watch.states))

    def test_pause_and_continue(self):
        def pause(a, w):
            t = time.time()
            while time.time() - t < 1.0:
                a.processEvents()
                time.sleep(0.01)
            self.assertTrue(w.activity.pause_tool.isVisible() or not w.isVisible())
            w.activity.pause_tool.setChecked(True)   # 「⏸ 一時停止」を押す
            t = time.time()
            while time.time() - t < SILENT + 8:   # 1 歩が終わっても、続けるまで待っている
                a.processEvents()
                time.sleep(0.01)
            self.assertIsNotNone(w.thread, "一時停止したのに描き終えた")
            self.assertEqual(w.activity.pause_tool.text(), "▶ 続ける")
            w.activity.pause_tool.setChecked(False)   # 「▶ 続ける」
        w, watch, t0 = self.draw(SilentPainter(), before=pause)
        said = [m for _t, m in watch.msgs]
        self.assertEqual(len(w.images), 1, "続けたあとに描き終えていない")
        self.assertTrue(any(m.startswith("一時停止しています") for m in said))
        self.assertLess(max(watch.gaps(t0)), GAP)
        self.assertFalse(w.activity.pause_tool.isVisibleTo(w.activity), "描き終えたのに一時停止のボタンが残っている")


class WaitMemoryTest(unittest.TestCase):
    def test_wait_memory_tells_each_step(self):
        from chatdraw import pausekeep
        told = []
        got = pausekeep.wait_memory(8, wait_s=20, step_s=5, free=lambda: 2.0, sleep=lambda s: None,
                                    on_wait=lambda t, f: told.append((t, f)))
        self.assertFalse(got)
        self.assertEqual([t for t, _f in told], [0.0, 5.0, 10.0, 15.0], "待つ間の知らせが無い")

    def test_memory_retry_says_while_waiting(self):
        from chatdraw import engine, pausekeep

        class P:
            need_gb = 4.0
            stop = False

        said, n = [], {"k": 0}

        def run():
            n["k"] += 1
            raise MemoryError("out of memory")
        old_wait, old_s = pausekeep.wait_memory, engine.MEMORY_WAIT_S
        engine.MEMORY_WAIT_S = 10.0

        def fake_wait(need, wait_s, stopped, on_wait):
            for t in (0.0, 5.0):
                on_wait(t, 1.0)
            return False
        pausekeep.wait_memory = fake_wait
        try:
            with self.assertRaises(engine.MemoryPaused):
                engine.memory_retry(P(), run, said.append)
        finally:
            pausekeep.wait_memory, engine.MEMORY_WAIT_S = old_wait, old_s
        self.assertTrue([m for m in said if "メモリが空くのを待っています（5/10 秒" in m], said)


class PhaseEtaTest(unittest.TestCase):
    def test_remaining_by_phase(self):
        app()
        from chatdraw.activity import ActivityPanel
        p = ActivityPanel()
        p.begin("試験", "新規")
        p.status("工程 1/12「目的」: 試験")
        self.assertIsNone(p.phase_eta())
        p.phase_at[1] = time.time() - 30
        p.status("工程 2/12「サムネイル」: 試験")
        p.phase_at[2] = time.time()
        left = p.phase_eta()
        self.assertIsNotNone(left)
        self.assertAlmostEqual(left, 30 * 11, delta=5)   # 1 工程 30 秒 × 残り 11 工程
        p._show_time()
        self.assertIn("残り約", p.time.text())


class PhaseLabelTest(unittest.TestCase):
    """進み具合の欄の工程の番号が、精度優先で実際に動いている工程と食い違わないか。
    知らせの並びは、本物の窓で試験用の小さな模型を精度優先で描かせたときの物（サムネイルを 3 回やり直して工程 2 で打ち切った回）"""

    SEQ = ["AI が使えるかを確かめました", "1/1 枚目を描きます", "工程に分けて描きます（目的 → サムネイル）",
           "頼みを描く言葉に直しています", "工程 1/12「目的」: 何を一番見せるか", "工程 1/12「目的」の検品: 崩れは見つかりませんでした",
           "工程 2/12「サムネイル」: 構図", "工程 2/12「サムネイル」の検品: 残った崩れ 人数が違う",
           "「サムネイル」の未解決項目を工程 2「サムネイル」へ戻して直します（1/3 回目）", "工程 2/12「サムネイル」: 構図"]

    def panel(self):
        app()
        from chatdraw.activity import ActivityPanel
        p = ActivityPanel()
        p.begin("赤い髪の女の人", "新規")
        return p

    def test_no_five_stage_number_in_precise(self):
        p = self.panel()
        for m in self.SEQ[:4]:
            p.status(m)
            if m.startswith("工程に分けて") or p.phased:
                self.assertNotIn("/5", p.state.text(), f"精度優先なのに 1 回で描く回の番号が出た: {p.state.text()}")
        self.assertEqual(p.state.text(), "精度優先: 準備中")

    def test_retry_is_shown(self):
        p = self.panel()
        for m in self.SEQ:
            p.status(m)
        self.assertEqual(p.state.text(), "工程 2/12　サムネイル（やり直し 1/3 回目）")
        p.status("工程 3/12「アタリ」: 頭の大きさ")
        self.assertEqual(p.state.text(), "工程 3/12　アタリ")

    def test_stopped_is_not_done(self):
        p = self.panel()
        for m in self.SEQ:
            p.status(m)
        p.status("工程 2/12「サムネイル」で停止しました（未解決の崩れが残っています）。未完成として保存します")
        self.assertEqual(p.state.text(), "工程 2/12「サムネイル」で停止（未完成）")
        p.end("描きました", "x.png", record=False)
        self.assertIn("未完成", p.detail.text())
        self.assertIn("工程 3〜12 は描いていません", p.detail.text())


class WaitNoteTest(unittest.TestCase):
    def test_nested(self):
        from chatdraw import waitnote
        self.assertIsNone(waitnote.current())
        with waitnote.waiting("外"):
            with waitnote.waiting("中"):
                self.assertEqual(waitnote.current()[0], "中")
            self.assertEqual(waitnote.current()[0], "外")
        self.assertIsNone(waitnote.current())

    def test_threads(self):
        from chatdraw import waitnote
        done = threading.Event()

        def hold():
            with waitnote.waiting("裏"):
                done.wait(2)
        t = threading.Thread(target=hold)
        t.start()
        time.sleep(0.1)
        self.assertEqual(waitnote.current()[0], "裏")
        done.set()
        t.join()
        self.assertIsNone(waitnote.current())


if __name__ == "__main__":
    unittest.main()
