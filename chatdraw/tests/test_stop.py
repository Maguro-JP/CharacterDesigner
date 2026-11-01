"""緊急停止・進み具合の表示・欄とタブの配置の試験。

止める試験は、本物と同じ経路（頼みを書いて「描く」→ 裏の糸で Studio.draw → 模型）で、
止める旗を見ない重い工程（模型の読み込み・言葉の模型の答え待ち・1 工程の中・検品）を偽の模型で長く走らせ、
緊急停止を押してから、画面が待機に戻るまでと、裏の糸が本当に終わるまでの秒数を測る。
前は、読み込み中に押した止めるの旗を描く処理の頭で戻していたため、押しても最後まで描いてキャンバスに置いた。
"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg  # noqa: E402

HEAVY = 8.0     # 重い工程の長さ（秒）。止まらなければ、これだけかかる
LIMIT = 2.0     # 押してから止まるまでの目標（秒）


def busy(sec: float):
    """止める旗を見ない重い処理。本物の torch の計算や読み込みと同じく、短い C の呼び出しを繰り返す"""
    end = time.time() + sec
    while time.time() < end:
        time.sleep(0.02)


class SlowPainter(FakePainter):
    """phase の工程で HEAVY 秒、旗を見ずに動く。描く処理の頭で旗を戻す（本物の Painter.paint と同じ）"""

    def __init__(self, phase: str):
        super().__init__()
        self.phase = phase

    def paint(self, prompt, seed, on_step=None, **kw):
        if self.phase == "load":
            busy(HEAVY)                 # 模型の読み込み（from_pretrained）は旗を見ない
        self.stop = False               # 本物の paint と同じ戻し方
        if self.phase == "step":
            busy(HEAVY)                 # 1 工程の中（模型の計算）
        return super().paint(prompt, seed, on_step=on_step, **kw)


class SlowWords(FakeWords):
    def to_prompt(self, text, tags=True):
        busy(HEAVY)                     # 言葉の模型の答え待ち
        return super().to_prompt(text, tags)


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def pump(a, sec: float):
    end = time.time() + sec
    while time.time() < end:
        a.processEvents()
        time.sleep(0.01)


class EmergencyStopTest(unittest.TestCase):
    def run_and_stop(self, painter, words=None):
        from chatdraw.app import Window
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(words or FakeWords(), painter, Path(d)))
            w.settings.set("output_dir", str(Path(d) / "out"))
            before = w.canvas.flatten().copy()
            layers = len(w.canvas.layers) if hasattr(w.canvas, "layers") else None
            w.entry.setText("雪の城の前の騎士")
            w.send()
            pump(a, 0.6)                                  # 重い工程に入るまで待つ
            self.assertIsNotNone(w.thread, "描き始めていない")
            self.assertTrue(w.stop_button.isEnabled())
            worker = w.thread
            t0 = time.time()
            w.emergency_stop.trigger()                    # ツールバーの緊急停止
            ui = time.time() - t0
            while worker.isRunning() and time.time() - t0 < HEAVY + 5:
                a.processEvents()
                worker.wait(10)
            gone = time.time() - t0
            pump(a, 0.3)
            print(f"\n  {painter.__class__.__name__}/{getattr(painter, 'phase', 'words')}: 画面 {ui:.2f} 秒、裏の糸 {gone:.2f} 秒")
            self.assertLess(ui, 0.5, "押した直後に画面が待機に戻らない")
            self.assertLess(gone, LIMIT, f"押してから {gone:.1f} 秒止まらなかった")
            self.assertIsNone(w.thread)
            self.assertTrue(w.button.isEnabled(), "すぐに次の操作ができない")
            self.assertFalse(w.stop_button.isEnabled())
            self.assertEqual(w.canvas.flatten(), before, "止めたのにキャンバスが変わった")
            if layers is not None:
                self.assertEqual(len(w.canvas.layers), layers)
            self.assertEqual(w.activity.state.text(), "待機中")
            # 止めたあと、すぐに次の 1 枚を描ける
            w.studio.painter = FakePainter()
            w.studio.words = FakeWords()
            w.entry.setText("次の騎士")
            w.send()
            end = time.time() + 10
            while w.thread is not None and time.time() < end:
                a.processEvents()
                w.thread and w.thread.wait(10)
            a.processEvents()
            self.assertEqual(len(w.images), 1, "止めたあとの 1 枚が描けない")
            w.close()

    def test_stop_while_loading_model(self):
        self.run_and_stop(SlowPainter("load"))

    def test_stop_inside_one_step(self):
        self.run_and_stop(SlowPainter("step"))

    def test_stop_while_waiting_words_model(self):
        self.run_and_stop(FakePainter(), SlowWords())

    def test_stop_heavy_task(self):
        """拡大などの裏の処理（Task）も、旗を見ない重い工程の中で止まる"""
        from chatdraw.app import Window
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            got = []
            w._run_task(lambda step: (busy(HEAVY), got.append(1)), lambda r: got.append("done"))
            pump(a, 0.3)
            worker, t0 = w.thread, time.time()
            w.emergency_stop.trigger()
            while worker.isRunning() and time.time() - t0 < HEAVY + 5:
                a.processEvents()
                worker.wait(10)
            gone = time.time() - t0
            pump(a, 0.2)
            print(f"\n  Task: 裏の糸 {gone:.2f} 秒")
            self.assertLess(gone, LIMIT)
            self.assertEqual(got, [], "止めた処理の答えが届いた")
            self.assertTrue(w.button.isEnabled())
            w.close()

    def test_stop_when_idle_says_so(self):
        from chatdraw.app import Window
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            wait_bg(a, w)
            w.emergency_stop.trigger()
            self.assertEqual(w.activity.state.text(), "待機中")
            self.assertIn(w.emergency_stop, w.stop_bar.actions())                # ツールバーに見えている
            self.assertIs(w.activity.stop_tool.defaultAction(), w.emergency_stop)  # 進みの欄にもある
            self.assertIs(w.progress_popup.stop.defaultAction(), w.emergency_stop)  # 右下の進みにもある
            w.close()


class ProgressTest(unittest.TestCase):
    def test_shows_stage_elapsed_last_step_and_background(self):
        from chatdraw.app import Window
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            act = w.activity
            wait_bg(a, w)
            self.assertEqual(act.state.text(), "待機中")
            act.begin("騎士", "新しく描く")
            act.status("絵の模型を読んでいます")
            self.assertIn("工程 3/5", act.state.text())
            act.status("描いています（3/24）", 3, 24)
            self.assertIn("工程 4/5", act.state.text())
            self.assertIn("3/24", act.state.text())
            self.assertIn("経過", act.time.text())
            self.assertIn("残り", act.time.text())
            self.assertIn("最後に進んだ時刻", act.alive.text())
            act.end("止めました")
            self.assertEqual(act.state.text(), "待機中")
            # 裏の処理（保存・言葉の模型）も同じ所に出し、終われば待機中に戻る
            gate = __import__("threading").Event()
            w.in_background(lambda: gate.wait(5), lambda v: None, "言葉の模型の答え待ち")
            a.processEvents()
            self.assertIn("言葉の模型の答え待ち", act.alive.text())
            self.assertEqual(act.state.text(), "裏の処理中")
            gate.set()
            end = time.time() + 5
            while w.bg_pending and time.time() < end:
                a.processEvents()
                time.sleep(0.01)
            self.assertEqual(act.state.text(), "待機中")
            self.assertEqual(act.alive.text(), "")
            w.close()


class LayoutTest(unittest.TestCase):
    def tearDown(self):
        from PySide6.QtCore import QSettings
        from chatdraw.tabdock import ORDER_KEY, OUT_KEY
        st = QSettings("CharacterDesigner", "chatdraw")
        for k in (ORDER_KEY, OUT_KEY):
            st.remove(k)

    def test_tabs_reorder_pull_out_restore_and_reset(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMainWindow
        from chatdraw.app import Window
        app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            self.assertTrue(w.dockOptions() & QMainWindow.GroupedDragging)
            tabs = w.ai_tabs
            self.assertTrue(tabs.bar.isMovable())
            first = tabs.order()
            tabs.bar.moveTab(0, 2)                            # ドラッグでの並べ替えと同じ呼び方
            moved = tabs.order()
            self.assertNotEqual(moved, first)
            dock = tabs.pull_out("模型", QPoint(200, 200))      # 欄の外へ出す
            self.assertIsNotNone(dock)
            self.assertNotIn("模型", tabs.order())
            self.assertTrue(dock.isFloating())
            w.tabifyDockWidget(w.panels["layers"][0], dock)   # 別の欄に入れる（重ねてタブにまとめる）
            w.close()
            # 次の起動で戻る
            w2 = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            self.assertIn("模型", w2.ai_tabs.docks)
            self.assertEqual(w2.ai_tabs.order(), [n for n in moved if n != "模型"])
            w2.ai_tabs.docks["模型"].close()                     # 閉じると AI の欄のタブに戻る
            self.assertIn("模型", w2.ai_tabs.order())
            self.assertIsNotNone(w2.ai_tabs.pull_out("直す・仕上げ", QPoint(100, 100)))   # タブの名前は描く順の並べ直しで変わった
            w2.reset_layout()                                  # 配置を初期に戻す
            self.assertEqual(w2.ai_tabs.order(), first)
            self.assertEqual(w2.ai_tabs.docks, {})
            w2.close()

    def test_drag_tab_out_with_mouse(self):
        """見出しの帯からタブを下へ引き出すと、そのタブが欄になって浮く（本物のマウスの知らせを送る）"""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from chatdraw.app import Window
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.show()
            bar = w.ai_tabs.bar
            at = QPointF(bar.tabRect(1).center())
            name = bar.tabText(1)

            def send(kind, p, buttons):
                ev = QMouseEvent(kind, p, bar.mapToGlobal(p), Qt.LeftButton, buttons, Qt.NoModifier)
                a.sendEvent(bar, ev)
            send(QEvent.MouseButtonPress, at, Qt.LeftButton)
            send(QEvent.MouseMove, at + QPointF(0, 10), Qt.LeftButton)
            send(QEvent.MouseMove, at + QPointF(0, bar.height() + 80), Qt.LeftButton)
            send(QEvent.MouseButtonRelease, at + QPointF(0, bar.height() + 80), Qt.NoButton)
            a.processEvents()
            self.assertIn(name, w.ai_tabs.docks)
            self.assertTrue(w.ai_tabs.docks[name].isFloating())
            w.reset_layout()
            w.close()


class PopupTest(unittest.TestCase):
    """進みのポップアップの動き（出る・閉じる・閉じたあと・位置・進みの欄と二重に出さない）"""

    def setUp(self):
        from chatdraw.app import Window
        self.a = app()
        self.d = TemporaryDirectory()
        self.w = Window(Studio(FakeWords(), FakePainter(), Path(self.d.name)))
        self.w.resize(1300, 850)
        self.w.show()
        wait_bg(self.a, self.w)
        self.p = self.w.progress_popup
        self.p.close_popup()

    def tearDown(self):
        self.w.close()
        self.d.cleanup()

    def test_shows_on_run_and_stays_closed_after_close(self):
        act, p = self.w.activity, self.p
        act.begin("騎士", "新しく描く")
        pump(self.a, 0.4)
        self.assertTrue(p.isVisible())                               # 描き始めたら出る
        self.assertEqual(p.pos(), p.target())                        # 右下に止まる
        g = self.w.centralWidget().geometry()
        self.assertTrue(g.contains(p.geometry()))                    # 絵の欄の中（ほかの欄に重ならない）
        p.close_popup()
        act.status("描いています（3/24）", 3, 24)
        act.status("描いています（4/24）", 4, 24)
        pump(self.a, 0.3)
        self.assertFalse(p.isVisible(), "× で閉じたのに、次の進みでまた出た")
        act.end("描きました", None, record=False)
        pump(self.a, 0.3)
        self.assertFalse(p.isVisible(), "× で閉じたのに、終わりでまた出た")
        act.begin("次の騎士", "新しく描く")                            # 次の 1 回はまた出る
        pump(self.a, 0.4)
        self.assertTrue(p.isVisible())

    def test_failures_show_even_after_close(self):
        self.w.activity.begin("騎士", "新しく描く")
        self.p.close_popup()
        self.w.fail("描けませんでした: 模型がありません")
        pump(self.a, 0.4)
        self.assertTrue(self.p.isVisible())                          # 描けなかった理由は閉じていても出す
        self.assertIn("模型がありません", self.p.text.text())

    def test_not_doubled_with_progress_panel(self):
        dock = self.w.panels["progress"][0]
        dock.show()
        dock.raise_()
        pump(self.a, 0.2)
        self.w.activity.begin("騎士", "新しく描く")
        self.w.activity.status("描いています（3/24）", 3, 24)
        pump(self.a, 0.3)
        self.assertFalse(self.p.isVisible(), "進みの欄が見えているのに、ポップアップにも二重に出た")
        dock.hide()
        self.w.activity.status("描いています（4/24）", 4, 24)
        pump(self.a, 0.4)
        self.assertTrue(self.p.isVisible())                          # 欄を閉じたらポップアップに出る
        self.w.activity.end("止めました")

    def test_follows_window_resize(self):
        self.w.activity.begin("騎士", "新しく描く")
        pump(self.a, 0.4)
        self.w.resize(1000, 700)
        pump(self.a, 0.4)
        self.assertEqual(self.p.pos(), self.p.target())
        self.assertTrue(self.w.centralWidget().geometry().contains(self.p.geometry()))
        self.w.activity.end("止めました")


if __name__ == "__main__":
    unittest.main()
