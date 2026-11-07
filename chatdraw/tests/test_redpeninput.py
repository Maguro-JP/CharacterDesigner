"""赤ペンの指示の欄に打った文字が、欄に入ること（キャンバスやショートカットに取られない）。
赤ペンの印を付けたあとや直したあとに、道具が勝手に替わらないこと。キー・マウス・ボタンの本物の経路で流す"""
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

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QEnterEvent, QInputMethodEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


class RedPenInputTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        src = self.d / "a.png"
        figure().save(src)
        self.w.resize(1200, 800)
        self.w.show()
        self.w.activateWindow()
        self.w.canvas.replace_with_image(str(src))
        QTest.qWait(50)
        self.w.tool_actions["redpen"].trigger()   # 帯のボタンと同じ経路

    def tearDown(self):
        self.w.closing_checked = True   # 閉じる前の「保存しますか」は、この試験では見ない
        self.w.close()
        self.tmp.cleanup()

    def draw_mark(self):
        """キャンバスの上をマウスで引いて、赤ペンで囲む"""
        c = self.w.canvas
        vp = c.viewport()
        start = c.mapFromScene(c.sceneRect().center()) + QPoint(-40, -40)
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
        for i in range(1, 16):
            QTest.mouseMove(vp, start + QPoint(5 * i, 3 * i))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(75, 45))
        QTest.qWait(20)
        self.assertEqual(len(c.redpen.marks), 1)
        return self.w.note_edit

    def assert_kept(self, edit, text):
        self.assertTrue(edit.isVisible())
        self.assertIs(QApplication.focusWidget(), edit)
        self.assertEqual(edit.text(), text)
        self.assertEqual(self.w.canvas.tool, "redpen")
        self.assertEqual(len(self.w.canvas.redpen.marks), 1)

    def test_keyclicks(self):
        edit = self.draw_mark()
        QTest.keyClicks(edit, "make the hand bigger")
        self.assert_kept(edit, "make the hand bigger")

    def test_single_letter_shortcuts(self):
        edit = self.draw_mark()
        for ch in "BELRTVMGIHZXD":
            QTest.keyClick(edit, ch)
        QTest.keyClick(edit, Qt.Key_Space)
        self.assert_kept(edit, "BELRTVMGIHZXD ")

    def test_delete_tab_undo(self):
        edit = self.draw_mark()
        QTest.keyClicks(edit, "abc")
        QTest.keyClick(edit, Qt.Key_Home)
        QTest.keyClick(edit, Qt.Key_Delete)
        self.assert_kept(edit, "bc")
        QTest.keyClick(edit, Qt.Key_Z, Qt.ControlModifier)   # 欄の中の元に戻す（印は消さない）
        self.assert_kept(edit, "abc")
        QTest.keyClick(edit, Qt.Key_Tab)   # Tab で欄を離れない（帯を隠すなどに取られない）
        self.assert_kept(edit, "abc")

    def test_input_method(self):
        edit = self.draw_mark()
        QApplication.sendEvent(edit, QInputMethodEvent("てをおおきく", []))
        done = QInputMethodEvent("", [])
        done.setCommitString("手を大きく")
        QApplication.sendEvent(edit, done)
        self.assert_kept(edit, "手を大きく")

    def test_mouse_over_canvas_keeps_focus(self):
        """欄を出したまま、マウスがキャンバスの上に入って動いても、文字は欄に入る"""
        edit = self.draw_mark()
        c = self.w.canvas
        p = QPointF(c.rect().center())
        QApplication.sendEvent(c, QEnterEvent(p, p, QPointF(c.mapToGlobal(c.rect().center()))))
        QTest.mouseMove(c.viewport(), QPoint(10, 10))
        QTest.keyClicks(QApplication.focusWidget(), "b")
        self.assert_kept(edit, "b")

    def test_click_outside_then_back(self):
        """欄の外（書く欄）を押してから欄に戻っても、打った文字は欄に入る"""
        edit = self.draw_mark()
        QTest.keyClicks(edit, "a")
        QTest.mouseClick(self.w.entry, Qt.LeftButton)
        QTest.mouseClick(edit, Qt.LeftButton)
        QTest.keyClicks(QApplication.focusWidget(), "be")
        self.assert_kept(edit, "abe")

    def test_enter_keeps_tool(self):
        """指示を残したあとも、道具は赤ペンのまま"""
        edit = self.draw_mark()
        QTest.keyClicks(edit, "hand")
        QTest.keyClick(edit, Qt.Key_Return)
        self.assertEqual(self.w.canvas.redpen.texts, ["hand"])
        self.assertEqual(self.w.canvas.tool, "redpen")
        self.assertTrue(self.w.tool_actions["redpen"].isChecked())

    def test_marks_gone_keeps_tool(self):
        """印を全部消しても（元に戻す）、道具は赤ペンのまま。描く形だけ新しく描くに戻る"""
        edit = self.draw_mark()
        QTest.keyClick(edit, Qt.Key_Escape)
        self.w.canvas.setFocus()
        QTest.keyClick(self.w.canvas, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(self.w.canvas.redpen.marks, [])
        self.assertEqual(self.w.canvas.tool, "redpen")
        self.assertTrue(self.w.tool_actions["redpen"].isChecked())
        self.assertEqual(self.w.mode.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
