"""0.5.18 に戻したときに消えた画面の機能（作成枚数の欄、複数枚の 1 枚の失敗、一括生成）を窓から押して確かめる"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, sweep_windows  # noqa: E402


class FlakyPainter(FakePainter):
    """2 回目の描く呼び出しだけ落ちる描き手。FAIL を含む頼みも落ちる"""
    fail_on = {2}

    def paint(self, prompt, seed, on_step=None, **kw):
        self.n = getattr(self, "n", 0) + 1
        if self.n in self.fail_on or "FAIL" in str(prompt):
            raise RuntimeError("試験で落とした 1 枚")
        return super().paint(prompt, seed, on_step, **kw)


def run_until(app, w, cond, limit=120.0):
    end = time.time() + limit
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        w.thread and w.thread.wait(10)
        time.sleep(0.01)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.d = TemporaryDirectory()

    def tearDown(self):
        sweep_windows()
        self.d.cleanup()

    def window(self, painter=None, size=(1600, 1000)):
        from chatdraw.app import Window
        w = Window(Studio(FakeWords(), painter or FakePainter(), Path(self.d.name)))
        w.studio.way = "one"
        w.resize(*size)
        w.show()
        QTest.qWait(200)
        w.closing_checked = True   # 閉じるときの確かめの窓を出さない。窓は sweep_windows が閉じる
        return w


class CountFieldTest(Base):
    """作成枚数は描くボタンの左に「枚数」の名前つきの欄で出し、幅 0 に潰れず、打てる。詳しい設定には枚数を置かない"""

    def test_count_field_beside_draw_button(self):
        w = self.window()
        spin = w.ai_panel.count_spin
        self.assertTrue(spin.isVisible())
        self.assertGreaterEqual(spin.width(), 50, spin.geometry())
        self.assertEqual(w.count_label.text(), "枚数")
        self.assertTrue(w.count_label.isVisible())
        spin.setFocus(); spin.selectAll()
        QTest.keyClicks(spin, "3")
        QTest.keyClick(spin, Qt.Key_Return)
        self.assertEqual(spin.value(), 3)
        detail = w.ai_panel.sections["詳しい設定"]
        texts = [l.text() for l in detail.findChildren(QLabel)]
        self.assertFalse(any("枚数" in t for t in texts), texts)
        self.assertFalse(any(b.isVisible() for b in w.ai_panel.count_buttons[1]))

    def test_narrow_window_keeps_width(self):
        w = self.window(size=(900, 700))
        self.assertGreaterEqual(w.ai_panel.count_spin.width(), 50)

    def test_model_heading(self):
        w = self.window()
        self.assertFalse(w.model_label.text().startswith("絵の模型"), w.model_label.text())
        heads = [l.text() for l in w.findChildren(QLabel) if l.objectName() == "sectionHead"]
        self.assertIn("絵の模型", heads)


class OneFailureTest(Base):
    def test_one_failure_keeps_the_rest(self):
        w = self.window(FlakyPainter())
        w.studio.draw_anyway = None   # 段を下げる描き直しは別の試験で見る。ここは落ちた 1 枚の扱いを見る
        w.entry.setText("雪の城の前の騎士")
        w.ai_panel.set_count(3)
        w.button.click()   # 窓のボタンから押す（clicked は真偽値を渡す）
        self.assertTrue(run_until(self.app, w, lambda: w.thread is None and getattr(w.job, "drawn", None) is not None, 120))
        self.assertTrue(run_until(self.app, w, lambda: w.thread is None, 60))
        self.assertEqual(w.job.drawn, 2)
        self.assertEqual(len(w.job.reasons), 1)
        self.assertIn("2 枚目", w.job.reasons[0])
        self.assertEqual(len(w.batch), 2)


class BatchTest(Base):
    def test_parse(self):
        from chatdraw import batch
        jobs, bad = batch.parse("1girl, red scarf\n# 飛ばす\n\nknight, snow", 2, 10)
        self.assertEqual([(j["text"], j["count"], j["seed"]) for j in jobs], [("1girl, red scarf", 2, 11), ("knight, snow", 2, 14)])
        jobs, bad = batch.parse("頼み,枚数,種\n\"cat, sitting\",3,5\ndog,x,1\n,1,1", 1, 0)
        self.assertEqual([(j["text"], j["count"], j["seed"]) for j in jobs], [("cat, sitting", 3, 5)])
        self.assertEqual(len(bad), 2)

    def test_stop(self):
        from chatdraw import batch, engine

        seen = []

        def draw(text, seed, neg):
            seen.append(text)
            engine.STOP.set()
            return f"/tmp/{seed}.png"
        try:
            res = batch.run(batch.parse("a\nb\nc")[0], draw, stopped=engine.STOP.is_set)
        finally:
            engine.STOP.clear()
        self.assertEqual((len(res["done"]), res["stopped"], seen), (1, True, ["a"]))

    def test_from_file_menu_one_fails(self):
        w = self.window(FlakyPainter.__new__(FlakyPainter))
        w.studio.painter.__init__()
        w.studio.painter.fail_on = set()
        file_menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "ファイル")
        self.assertIn(w.batch_action, file_menu.actions())
        w._fill_ai_menu()
        self.assertNotIn("一括生成…", [a.text() for a in w.ai_menu.actions()])
        self.assertTrue(w.batch_action.toolTip())
        text = "1girl, red scarf\nFAIL on purpose\nknight, snow"
        with mock.patch.object(type(w), "_batch_dialog", lambda self: (text, 1, 3, None)):
            w.batch_action.trigger()
        self.assertTrue(run_until(self.app, w, lambda: getattr(w, "batch_result", None) is not None, 120))
        res = w.batch_result
        self.assertEqual(len(res["done"]), 2)
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(res["failed"][0][0], 2)
        lib = [i["path"] for i in w.library.items]
        self.assertTrue(all(p in lib for p in res["done"]))


class MemModeWindowTest(Base):
    """設定の窓の「メモリの使い方」で選んだものが、保存したときに描く仕組みに効くこと"""

    def test_pick_in_settings(self):
        from chatdraw import membudget, settings as st
        w = self.window()
        self.addCleanup(lambda: (w.settings.set("mem_mode", "自動"), membudget.set_mode("自動")))

        def exec_(dlg):
            box = dlg.inputs["mem_mode"][1]
            self.assertEqual([box.itemText(i) for i in range(box.count())], list(membudget.MODES))
            box.setCurrentText("控えめに動かす")
            dlg.save()
            return True
        with mock.patch.object(st.SettingsDialog, "exec", exec_), \
                mock.patch.object(type(w), "_studio_from_settings", lambda self: self.studio):
            w.open_settings()
        self.assertEqual(membudget.mode(), "控えめに動かす")
        self.assertAlmostEqual(membudget.budget(10, 0).ram, 6.0)


class DebugModeTest(Base):
    """デバッグモード: 設定で入れると下に「記録」の欄が出て、例外の全文・空きメモリ・模型に渡した言葉が流れ、
    描けなかった理由の全文を窓で出す。切れば止まる"""

    def setUp(self):
        super().setUp()
        import chatdraw.paths as paths
        self._home, paths.HOME = paths.HOME, Path(self.d.name)   # 記録のファイルを試験の置き場に書く

    def tearDown(self):
        from chatdraw import debuglog
        import chatdraw.paths as paths
        debuglog.configure(False)
        paths.HOME = self._home
        super().tearDown()

    def test_debug_mode_shows_full_exception(self):
        from chatdraw import debuglog, sent
        w = self.window(FlakyPainter())
        w.studio.draw_anyway = None
        self.addCleanup(lambda: [w.settings.set(k, 0) for k in ("debug", "debug_budget")])   # 利用者の設定に残さない
        w.settings.set("debug", 1)
        w.settings.set("debug_budget", 1)
        w.apply_debug_mode()
        self.assertTrue(debuglog.on() and debuglog.lifted("budget"))
        self.assertFalse(w._debug_dock().isHidden())
        w.entry.setText("騎士")
        w.ai_panel.set_count(3)
        w.button.click()
        self.assertTrue(run_until(self.app, w, lambda: w.thread is None and getattr(w.job, "drawn", None) == 2, 120))
        text = w.debug_view.toPlainText()
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("試験で落とした 1 枚", text)
        self.assertIn("空きメモリ", text)
        sent.record("描く", "1girl, knight", "lowres")
        self.assertTrue(run_until(self.app, w, lambda: "[言葉] 描く: 1girl, knight" in w.debug_view.toPlainText(), 10))
        self.assertTrue(debuglog.file().exists())
        self.assertIn("Traceback", w.debug_box.detailedText())
        w.settings.set("debug", 0)
        w.apply_debug_mode()
        self.assertFalse(debuglog.on())
        self.assertTrue(w._debug_dock().isHidden())

    def test_budget_lift_draws_instead_of_stopping(self):
        from types import SimpleNamespace
        from chatdraw import debuglog, engine, membudget as mb
        p = engine.Painter.__new__(engine.Painter)
        p._note = lambda *a, **k: None
        plan = SimpleNamespace(ok=False, reason="足りない", lighter="小さくしてください", size=(512, 512),
                               ram_peak=lambda: 30.0, vram_peak=lambda: 0.0)
        b = mb.Budget(8.0, 0.0, 10.0, 0.0)
        with self.assertRaises(mb.OverBudget):
            p._check_budget(plan, b)
        debuglog.configure(True, ["budget"])
        p._check_budget(plan, b)   # 外したときは止めずに描く
        self.assertTrue(p.low_memory)

    def test_old_logs_are_removed(self):
        from chatdraw import debuglog
        f = debuglog.folder()
        f.mkdir(parents=True, exist_ok=True)
        (f / "chatdraw-20200101.log").write_text("x")
        os.utime(f / "chatdraw-20200101.log", (0, 0))
        (f / "chatdraw-new.log").write_text("x")
        self.assertEqual(debuglog.prune(), 1)
        self.assertTrue((f / "chatdraw-new.log").exists())


class CloseTest(Base):
    """閉じた窓の、アプリ全体で効くキー（緊急停止）と保存の裏の糸を外す。残ると開け閉めのあとにキーで落ちた"""

    def test_close_drops_global_keys_and_io_thread(self):
        import threading
        before = sum(t.name == "io" for t in threading.enumerate())
        for _ in range(3):
            w = self.window()
            got = []
            w.run_io(lambda: 1, got.append)
            w.wait_io()
            self.assertTrue(run_until(self.app, w, lambda: got == [1], 5))
            self.assertFalse(w.emergency_stop.shortcut().isEmpty())
            w.close()
            QApplication.processEvents()
            self.assertTrue(w.emergency_stop.shortcut().isEmpty())
            self.assertFalse(w.emergency_stop.isEnabled())
        end = time.time() + 3
        while sum(t.name == "io" for t in threading.enumerate()) > before and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(sum(t.name == "io" for t in threading.enumerate()), before)

    def test_draw_button_click_does_not_crash(self):
        """描くボタンの clicked は真偽値を渡す。頼みの文と取り違えて落ちないこと"""
        w = self.window()
        w.entry.setText("赤いマフラーの女の子")
        w.button.click()
        self.assertTrue(run_until(self.app, w, lambda: w.thread is None and len(w.images) == 1, 60))


class MouseSidePanelsTest(Base):
    """マウスの戻る・進むは、キャンバスの外（レイヤーの欄、履歴、メニューの帯）でも絵の元に戻す・やり直すになる"""

    def test_back_forward_on_panels(self):
        from PySide6.QtWidgets import QListWidget, QTreeWidget, QToolBar
        w = self.window()
        got = []
        w.shared["undo"].triggered.connect(lambda *_: got.append("undo"))
        w.shared["redo"].triggered.connect(lambda *_: got.append("redo"))
        w.shared["undo"].setEnabled(True); w.shared["redo"].setEnabled(True)
        targets = [x for x in w.findChildren(QListWidget) + w.findChildren(QTreeWidget) + w.findChildren(QToolBar) if x.isVisible()]
        self.assertTrue(targets)
        for t in targets:
            got.clear()
            vp = t.viewport() if hasattr(t, "viewport") else t
            w.canvas.setFocus(); QApplication.processEvents()
            QTest.mousePress(vp, Qt.BackButton, Qt.NoModifier, vp.rect().center())
            QTest.mousePress(vp, Qt.ForwardButton, Qt.NoModifier, vp.rect().center())
            self.assertEqual(got, ["undo", "redo"], type(t).__name__)


if __name__ == "__main__":
    unittest.main()
