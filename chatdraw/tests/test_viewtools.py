"""表示の回転・リセット・左右反転・グリッド・拡大率の数字・操作の履歴・リボンの並び・赤ペンのマイクを、
メニュー、帯、右クリック、キーの本物の経路で押して確かめる"""
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
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def find(menu, text):
    for a in menu.actions():
        if a.text() == text:
            return a
        if a.menu() is not None:
            got = find(a.menu(), text)
            if got is not None:
                return got
    return None


class ViewToolsTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.show()
        self.w.activateWindow()
        figure((200, 200)).save(self.d / "a.png")
        self.w.edit_image(str(self.d / "a.png"))
        self.c = self.w.canvas
        self.qapp.processEvents()

    def tearDown(self):
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def menu_bar(self, text):
        for m in self.w.menuBar().actions():
            if m.menu() is not None:
                a = find(m.menu(), text)
                if a is not None:
                    return a
        self.fail(text)

    def test_view_menu_rotate_flip_reset(self):
        self.menu_bar("右に回す").trigger()
        self.assertAlmostEqual(self.c.angle, 15)
        self.assertEqual(self.w.angle_slider.value(), 15)   # 帯のつまみも合う
        self.menu_bar("左右反転で表示").trigger()
        self.assertTrue(self.c.flipped)
        self.assertTrue(self.w.shared["flip_view"].isChecked())
        self.assertLess(self.c.transform().determinant(), 0)
        self.c.set_zoom(3.0)
        self.menu_bar("表示をリセット").trigger()
        self.assertEqual((self.c.angle, self.c.flipped), (0.0, False))
        t = self.c.transform()
        self.assertAlmostEqual(t.m12(), 0)
        self.assertGreater(t.m11(), 0)
        self.assertTrue(self.c.auto_fit)   # 全体表示に戻る

    def test_rotation_is_clockwise_on_screen_even_when_flipped(self):
        def screen_dir():
            mid = self.c.mapToScene(self.c.viewport().rect().center())
            a = self.c.mapFromScene(mid)
            b = self.c.mapFromScene(mid + QPointF(50, 0))
            return b.x() - a.x(), b.y() - a.y()
        self.c.set_angle(90)
        dx, dy = screen_dir()
        self.assertGreater(dy, 20)   # 右にあった所が下へ（右回り）
        self.c.reset_view()
        self.c.flip_view()
        self.assertLess(screen_dir()[0], -20)   # 反転で右が左に見える
        self.c.set_angle(90)
        self.assertLess(screen_dir()[1], -20)   # 左に見えていた所が上へ（見た目でも右回り）

    def test_angle_slider_and_keys(self):
        self.w.angle_slider.setValue(-30)
        self.assertAlmostEqual(self.c.angle, -30)
        self.c.setFocus()
        QTest.keyClick(self.w, Qt.Key_Backslash, Qt.ControlModifier)   # 回転を戻す
        self.assertAlmostEqual(self.c.angle, 0)
        self.w.shared["rotate_reset"].trigger()
        self.c.set_angle(190)
        self.assertAlmostEqual(self.c.angle, -170)   # -180〜180 にそろえる

    def test_r_drag_rotates_and_r_tap_is_blur(self):
        vp = self.c.viewport()
        center = vp.rect().center()
        self.c.setFocus()
        undo = len(self.c.undo_stack)
        QTest.keyPress(self.c, Qt.Key_R)
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, center + QPoint(80, 0))
        QTest.mouseMove(vp, center + QPoint(0, 80))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, center + QPoint(0, 80))
        QTest.keyRelease(self.c, Qt.Key_R)
        self.assertAlmostEqual(self.c.angle, 90, delta=2)
        self.assertNotEqual(self.c.tool, "blur")   # ドラッグしたときはぼかしに持ち替えない
        self.assertEqual(len(self.c.undo_stack), undo)   # 回しただけで絵に線を引かない
        QTest.keyClick(self.c, Qt.Key_R)
        self.assertEqual(self.c.tool, "blur")

    def test_context_menu_and_ribbon_have_view_items(self):
        m = self.w.build_canvas_menu()
        for text in ("表示をリセット", "左右反転で表示", "右に回す", "グリッド"):
            self.assertIsNotNone(find(m, text), text)
        find(m, "右に回す").trigger()
        self.assertAlmostEqual(self.c.angle, 15)
        find(m, "表示をリセット").trigger()
        self.assertAlmostEqual(self.c.angle, 0)
        from PySide6.QtWidgets import QToolButton
        texts = {b.defaultAction().text() for b in self.w.ribbon.findChildren(QToolButton) if b.defaultAction()}
        for text in ("表示をリセット", "左右反転で表示", "角度を指定…", "グリッド", "操作の履歴…"):
            self.assertIn(text, texts)
        bottom = {a.text() for a in self.w.bottom_bar.actions()}
        for text in ("角度", "表示をリセット", "拡大率の数字", "左右反転で表示"):
            self.assertIn(text, bottom)

    def test_grid_draws_and_is_not_saved(self):
        before = self.c.flatten()
        self.menu_bar("グリッド").trigger()
        self.assertTrue(self.c.grid)
        self.assertTrue(self.w.shared["grid"].isChecked())
        self.w.grab()   # 描かせても落ちない
        self.assertEqual(self.c.flatten(), before)   # 保存する絵には入らない
        QTest.keyClick(self.w, Qt.Key_Apostrophe, Qt.ControlModifier)
        self.assertFalse(self.c.grid)

    def test_zoom_box_and_zoom_keys(self):
        self.w.zoom_box.setValue(250)
        self.assertAlmostEqual(self.c.zoom(), 2.5, places=2)
        self.w.shared["zoom_in"].trigger()
        self.assertEqual(self.w.zoom_box.value(), round(self.c.zoom() * 100))
        self.assertAlmostEqual(self.c.zoom(), 2.5 * 1.25, places=2)

    def test_brush_bracket_keys(self):
        self.c.setFocus()
        size = self.c.size
        QTest.keyClick(self.c, Qt.Key_BracketRight)
        self.assertGreater(self.c.size, size)
        QTest.keyClick(self.c, Qt.Key_BracketLeft)
        QTest.keyClick(self.c, Qt.Key_BracketLeft)
        self.assertLess(self.c.size, size + 1)

    def test_op_history_window(self):
        dock = self.w.panels["history"][0]
        dock.hide()
        self.menu_bar("操作の履歴…").trigger()
        self.assertTrue(dock.isVisible())
        self.assertIs(self.w.activity.tabs.currentWidget(), self.w.activity.ops)

    def test_ribbon_order_dialog_and_saved(self):
        r = self.w.ribbon
        names = [r.tabText(k) for k in range(r.count())]
        self.menu_bar("リボンの並びを変える…")   # メニューにある
        from chatdraw.ribbon import OrderDialog
        dlg = OrderDialog(r, self.w)
        dlg.list.setCurrentRow(len(names) - 1)
        for _ in range(len(names)):
            dlg.up.click()
        self.assertEqual(dlg.names()[0], names[-1])
        dlg.buttons.button(dlg.buttons.StandardButton.Ok).click()
        self.assertEqual(r.tabText(0), names[-1])
        saved = str(self.w.layout_store.value("ribbon/order")).split("\t")
        self.assertEqual(saved[0], names[-1])
        # 次に開いた窓でも同じ並び
        from chatdraw.app import Window
        w2 = Window(Studio(FakeWords(), FakePainter(), self.d))
        try:
            self.assertEqual(w2.ribbon.tabText(0), names[-1])
        finally:
            r.tabBar().moveTab(0, len(names) - 1)   # 並びを元に戻して、ほかの試験に残さない
            w2.dirty = False
            w2.close()
        self.assertEqual([r.tabText(k) for k in range(r.count())], names)

    def test_redpen_note_has_mic(self):
        pen = self.c.redpen
        pen.begin(QPointF(10, 10))
        pen.add(QPointF(40, 40))
        pen.end()
        self.w.edit_note(1)
        self.assertTrue(self.w.note_box.isVisible())
        self.assertTrue(self.w.note_mic.isVisible())
        self.assertTrue(self.w.note_mic.toolTip())

        class Fake:
            def start(self):
                pass

            def stop(self):
                return b""

            def transcribe(self, audio):
                return "笑顔に"
        mic = self.w.note_mic
        mic.kind, mic.listener = "whisper", Fake()
        mic.click()
        mic.click()
        for _ in range(50):
            self.qapp.processEvents()
            if self.w.note_edit.text():
                break
            QTest.qWait(20)
        self.assertEqual(self.w.note_edit.text(), "笑顔に")
        QTest.keyClick(self.w.note_edit, Qt.Key_Return)
        self.assertEqual(pen.texts[0], "笑顔に")
        self.assertFalse(self.w.note_box.isVisible())


if __name__ == "__main__":
    unittest.main()
