"""全部の入口を機械で押して回ったときに見つかった不具合の再現。

メニューの項目は triggered の真偽（False）を最初の引数に渡すので、引数に既定のある処理をそのまま繋ぐと、
真偽を道や名前として読んで落ちた。キャンバスは、キーやボタンを押したまま窓を離れると、離したことが届かずに
回転・手のひら・描きかけの線が残った。"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


class BugHuntTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.show()
        src = self.d / "a.png"
        figure().save(src)
        self.w.edit_image(str(src))
        self.c = self.w.canvas
        self.pump()

    def tearDown(self):
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def pump(self):
        for _ in range(3):
            self.qapp.processEvents()

    def action(self, text):
        for top in self.w.menuBar().actions():
            for a in top.menu().actions():
                if a.text() == text:
                    return a
        self.fail(text)

    def test_menu_merge_visible_keeps_layer_name(self):
        self.action("見えているレイヤーを結合").trigger()
        self.pump()
        self.w.grab()
        self.assertEqual(len(self.c.layers), 1)
        self.assertIsInstance(self.c.layers[0].name, str)

    def test_menu_save_layer_png_opens_dialog(self):
        out = self.d / "layer.png"
        with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", return_value=(str(out), "")):
            self.action("レイヤーを PNG で保存…").trigger()
        self.assertTrue(out.exists())

    def test_menu_export_layers_opens_dialog(self):
        folder = self.d / "out"
        folder.mkdir()
        with mock.patch("chatdraw.app.QFileDialog.getExistingDirectory", return_value=str(folder)):
            self.action("全部のレイヤーを PNG で書き出す…").trigger()
        self.assertEqual(len(list(folder.glob("*.png"))), len(self.c.layers))

    # キャンバス: 押したまま窓を離れる
    def key(self, k):
        self.qapp.sendEvent(self.c, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))

    def focus_out(self):
        self.qapp.sendEvent(self.c, QFocusEvent(QEvent.FocusOut, Qt.ActiveWindowFocusReason))

    def test_rotate_key_released_on_focus_out(self):
        self.key(Qt.Key_R)
        self.assertTrue(self.c.rotating)
        self.focus_out()
        self.assertFalse(self.c.rotating)

    def test_space_hand_released_on_focus_out(self):
        self.c.set_tool("pen")
        self.key(Qt.Key_Space)
        self.assertEqual(self.c.tool, "hand")
        self.focus_out()
        self.assertEqual(self.c.tool, "pen")

    def test_stroke_ends_on_focus_out(self):
        self.c.set_tool("pen")
        vp = self.c.viewport()
        p = QPointF(self.c.mapFromScene(QPointF(20, 20)))
        self.qapp.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, p, p, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.assertIsNotNone(self.c.last)
        self.focus_out()
        self.assertIsNone(self.c.last)
        self.c.undo()   # 描きかけの線も 1 回の元に戻すで消える
        self.pump()

    def test_right_click_menus_do_not_pile_up(self):
        """右クリックのメニューは閉じたら捨てる（前は 1 回ごとに 20 余りのメニューが窓に溜まった）"""
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QApplication, QMenu
        before = len(self.w.findChildren(QMenu))
        for _ in range(5):
            QTimer.singleShot(0, lambda: QApplication.activePopupWidget() and QApplication.activePopupWidget().close())
            self.w.canvas_menu(self.w.mapToGlobal(QPoint(50, 50)))
            self.qapp.sendPostedEvents(None, QEvent.DeferredDelete)   # deleteLater を済ませる
            self.pump()
        self.assertLessEqual(len(self.w.findChildren(QMenu)), before + 2)


if __name__ == "__main__":
    unittest.main()
