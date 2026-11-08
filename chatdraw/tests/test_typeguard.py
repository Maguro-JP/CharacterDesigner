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
