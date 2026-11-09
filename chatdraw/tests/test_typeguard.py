"""打っている欄のキーがショートカットに取られないこと（頼みの欄・指示の欄・数の欄）"""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

from chatdraw import typeguard


class TypeGuardTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        typeguard.install(self.app)
        self.win = QMainWindow()
        box = QWidget(); lay = QVBoxLayout(box)
        self.line = QLineEdit(); self.text = QPlainTextEdit()
        lay.addWidget(self.line); lay.addWidget(self.text)
        self.win.setCentralWidget(box)
        self.fired = []
        for seq in ("B", "Space", "Delete", "Ctrl+Z", "Ctrl+Return", "Shift+Escape"):
            a = QAction(seq, self.win)
            a.setShortcut(QKeySequence(seq))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(lambda *_, s=seq: self.fired.append(s))
            self.win.addAction(a)
        self.win.show()
        QTest.qWaitForWindowExposed(self.win)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _type(self, w):
        w.setFocus(); QApplication.processEvents()
        QTest.keyClicks(w, "abc b")
        QTest.keyClick(w, Qt.Key_Delete)
        QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier)

    def test_line_keeps_letters_space_delete_undo(self):
        self._type(self.line)
        self.assertEqual(self.fired, [])
        self.assertEqual(self.line.text(), "")   # 打った「abc b」を Ctrl+Z で欄の中で戻した

    def test_text_box_keeps_letters(self):
        self.text.setFocus(); QApplication.processEvents()
        QTest.keyClicks(self.text, "bb b")
        self.assertEqual(self.fired, [])
        self.assertEqual(self.text.toPlainText(), "bb b")

    def test_stop_and_draw_still_work_in_field(self):
        self.line.setFocus(); QApplication.processEvents()
        QTest.keyClick(self.line, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual(self.fired, ["Ctrl+Return"])
        # 非常停止（Shift+Esc）は欄が取らない（ほかの試験の窓が同じキーを持つと、ここで押しても曖昧になるので判定だけ見る）
        self.assertFalse(typeguard.keep_for_text(Qt.Key_Escape, Qt.ShiftModifier))

    def test_shortcut_works_outside_field(self):
        self.win.centralWidget().setFocus(); QApplication.processEvents()
        QTest.keyClick(self.win.centralWidget(), Qt.Key_B)
        self.assertEqual(self.fired, ["B"])


if __name__ == "__main__":
    unittest.main()


class WindowFieldsTest(unittest.TestCase):
    """本物の窓の、見えている全部の文字の欄で、道具のキー（B E T R V など）と Space、Delete が欄に入ること"""

    def test_every_visible_field(self):
        import os, sys
        from pathlib import Path
        from tempfile import TemporaryDirectory
        os.environ.setdefault("CD_CHECK", "off")
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.tests.test_editing import app
        app()
        with TemporaryDirectory() as tmp:
            w = Window(Studio(FakeWords(), FakePainter(), Path(tmp)))
            w.resize(1400, 900); w.show(); w.activateWindow(); QTest.qWait(50)
            try:
                fields = [f for f in w.findChildren(QLineEdit) + w.findChildren(QPlainTextEdit)
                          if f.isVisible() and f.isEnabled() and not f.isReadOnly()]
                self.assertGreater(len(fields), 0)
                letters = "bentrvgmlhiouz "
                for f in fields:
                    tool = w.canvas.tool
                    f.setFocus(); QApplication.processEvents()
                    f.clear()
                    QTest.keyClicks(f, letters)
                    got = f.text() if isinstance(f, QLineEdit) else f.toPlainText()
                    if not (isinstance(f, QLineEdit) and (f.validator() is not None or f.inputMask() or f.maxLength() < len(letters))):   # 数の欄は文字を受けない
                        self.assertIn(letters.strip(), got, f"{f.objectName() or type(f).__name__} {f.placeholderText()!r}")
                    self.assertEqual(w.canvas.tool, tool, f"{f.placeholderText()!r} で道具が替わった")
                    self.assertIn(QApplication.focusWidget(), (f, f.parentWidget()), f"{f.placeholderText()!r} から焦点が離れた")
            finally:
                w.closing_checked = True
                w.close()


class CountFieldTest(unittest.TestCase):
    """作成枚数は種とまとめず、描くボタンの左に「枚数」の名前つきの欄で出し、打てること"""

    def test_count_field_separate_from_seed(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.tests.test_editing import app
        app()
        with TemporaryDirectory() as tmp:
            w = Window(Studio(FakeWords(), FakePainter(), Path(tmp)))
            w.show(); QTest.qWait(30)
            try:
                spin = w.ai_panel.count_spin
                self.assertTrue(spin.isVisible())
                self.assertEqual(w.count_label.text(), "枚数")
                self.assertTrue(w.count_label.isVisible())
                spin.setFocus(); spin.selectAll()
                QTest.keyClicks(spin, "3")
                QTest.keyClick(spin, Qt.Key_Return)
                self.assertEqual(spin.value(), 3)
                texts = [l.text() for l in w.ai_panel.findChildren(type(w.count_label))]
                self.assertFalse(any("枚数と種" in t for t in texts), texts)
            finally:
                w.closing_checked = True
                w.close()


class MouseSideButtonTest(unittest.TestCase):
    """マウスの戻る・進むボタンで、絵の元に戻す・やり直すが効き、打っている欄では欄の元に戻すになること"""

    def test_back_forward(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.tests.test_editing import app
        app()
        with TemporaryDirectory() as tmp:
            w = Window(Studio(FakeWords(), FakePainter(), Path(tmp)))
            w.resize(1200, 800); w.show(); QTest.qWait(30)
            try:
                got = []
                w.shared["undo"].triggered.connect(lambda *_: got.append("undo"))
                w.shared["redo"].triggered.connect(lambda *_: got.append("redo"))
                w.shared["undo"].setEnabled(True); w.shared["redo"].setEnabled(True)
                vp = w.canvas.viewport()
                w.canvas.setFocus(); QApplication.processEvents()
                QTest.mousePress(vp, Qt.BackButton, Qt.NoModifier, vp.rect().center())
                QTest.mousePress(vp, Qt.ForwardButton, Qt.NoModifier, vp.rect().center())
                self.assertEqual(got, ["undo", "redo"])
                w.entry.setFocus(); QApplication.processEvents()
                QTest.keyClicks(w.entry, "abc")
                QTest.mousePress(w.entry.viewport() if hasattr(w.entry, "viewport") else w.entry, Qt.BackButton)
                text = w.entry.toPlainText() if hasattr(w.entry, "toPlainText") else w.entry.text()
                self.assertNotEqual(text, "abc")
                self.assertEqual(got, ["undo", "redo"])   # 欄の中では絵の元に戻すを呼ばない
            finally:
                w.closing_checked = True
                w.close()


class StopWordTest(unittest.TestCase):
    """描く頼みの中の「止め」や、言葉の模型の取り違えで、緊急停止を呼ばないこと"""

    def test_only_short_stop_request_stops(self):
        from unittest import mock
        from chatdraw import commands
        self.assertTrue(commands.is_stop_request("止めて"))
        self.assertTrue(commands.is_stop_request("今の中止。"))
        for t in ("髪をピンで止めている女の子を描いて", "止めてある自転車と少女", "雨が止んだ街で傘を閉じる少女"):
            self.assertFalse(commands.is_stop_request(t), t)
        w = mock.MagicMock()
        stop = commands.BY_NAME["stop"]
        got = commands.handle(w, "止めてある自転車と少女", picked=(stop, ""))
        self.assertIsNone(got)
        w.stop.assert_not_called()
        commands.handle(w, "止めて", picked=(stop, ""))
        w.stop.assert_called_once()


class IoThreadTest(unittest.TestCase):
    """窓を開いて閉じても、保存の裏の糸が残らないこと（残ると窓ごとに増え、消えた窓へ返してアプリが落ちた）"""

    def test_io_thread_ends_on_close(self):
        import threading
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.tests.test_editing import app
        app()
        before = sum(t.name == "io" for t in threading.enumerate())
        with TemporaryDirectory() as tmp:
            for _ in range(3):
                w = Window(Studio(FakeWords(), FakePainter(), Path(tmp)))
                got = []
                w.run_io(lambda: 1, got.append)
                w.wait_io()
                w.closing_checked = True
                w.close()
                QApplication.processEvents()
        import time
        end = time.time() + 3
        while sum(t.name == "io" for t in threading.enumerate()) > before and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(sum(t.name == "io" for t in threading.enumerate()), before)


class CountFieldVisibleTest(unittest.TestCase):
    """描くボタンの左の枚数の欄が、幅 0 に潰れずに見えて打てること。模型の欄の書き方"""

    def test_count_has_width_and_model_heading(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from PySide6.QtWidgets import QLabel
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.tests.test_editing import app
        app()
        with TemporaryDirectory() as tmp:
            w = Window(Studio(FakeWords(), FakePainter(), Path(tmp)))
            w.resize(1600, 1000); w.show(); QTest.qWait(200)
            try:
                spin = w.ai_panel.count_spin
                self.assertGreaterEqual(spin.width(), 50, spin.geometry())
                self.assertFalse(w.model_label.text().startswith("絵の模型"), w.model_label.text())
                heads = [l.text() for l in w.findChildren(QLabel) if l.objectName() == "sectionHead"]
                self.assertIn("絵の模型", heads)
                w._fill_ai_menu()
                self.assertNotIn("一括生成…", [a.text() for a in w.ai_menu.actions()])
                self.assertTrue(w.batch_action.isEnabled())
            finally:
                w.closing_checked = True
                w.close()
