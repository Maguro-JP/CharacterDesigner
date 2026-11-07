"""投げなわと多角形の選択を、画面の道具から押して最後まで通す。四角の選択と同じ仕組み（消す・塗る・写す・切り取る・AI の直し）に乗るか。
前は選択が四角だけで、斜めの所や曲がった所だけを直したいときに、要らない所まで範囲に入った"""
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

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


class SelectionToolsTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        src = self.d / "a.png"
        figure((100, 100)).save(src)
        self.w.edit_image(str(src))
        self.w.show()
        self.c = self.w.canvas
        self.c.resize(400, 400)
        self.c.actual()
        self.qapp.processEvents()

    def tearDown(self):
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def vp(self, x, y):
        from PySide6.QtCore import QPointF
        return self.c.mapFromScene(QPointF(x, y))

    def press(self, kind, x, y, button=None):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        button = button or Qt.LeftButton
        types = {"press": QMouseEvent.Type.MouseButtonPress, "move": QMouseEvent.Type.MouseMove,
                 "release": QMouseEvent.Type.MouseButtonRelease, "double": QMouseEvent.Type.MouseButtonDblClick}
        held = Qt.NoButton if kind == "release" else button
        pt = QPointF(self.vp(x, y))
        e = QMouseEvent(types[kind], pt, self.c.viewport().mapToGlobal(pt), button if kind != "move" else Qt.NoButton,
                        held, Qt.NoModifier)
        handler = {"press": self.c.mousePressEvent, "move": self.c.mouseMoveEvent,
                   "release": self.c.mouseReleaseEvent, "double": self.c.mouseDoubleClickEvent}[kind]
        handler(e)

    def triangle_by_polygon(self):
        self.w.tool_actions["polygon"].trigger()
        self.assertEqual(self.c.tool, "polygon")
        for x, y in ((10, 10), (90, 10), (10, 90)):
            self.press("press", x, y)
            self.press("release", x, y)
        self.press("double", 10, 90)
        self.assertIsNotNone(self.c.selection_shape)

    def pixel(self, x, y):
        return self.c.layers[self.c.current].image.pixelColor(x, y)

    def test_polygon_select_and_clear_only_inside(self):
        self.triangle_by_polygon()
        before_out = self.pixel(85, 85).rgba()
        self.w.shared["sel_clear"].trigger()
        self.assertEqual(self.pixel(20, 20).alpha(), 0)   # 三角の中は消えた
        self.assertEqual(self.pixel(85, 85).rgba(), before_out)   # 三角の外（四角の中）は残る
        self.c.undo()
        self.assertEqual(self.pixel(20, 20).alpha(), 255)

    def test_lasso_drag_fill_copy_cut_paste(self):
        from PySide6.QtGui import QColor
        self.w.tool_actions["lasso"].trigger()
        pts = [(10, 10), (90, 10), (90, 50), (50, 90), (10, 50)]
        self.press("press", *pts[0])
        for p in pts[1:]:
            self.press("move", *p)
        self.press("release", *pts[-1])
        self.assertIsNotNone(self.c.selection_shape)
        self.assertFalse(self.c.sel_item.isVisible())
        self.assertTrue(self.c.sel_path_item.isVisible())
        self.c.color = QColor(0, 0, 255)
        self.w.shared["sel_fill"].trigger()
        self.assertEqual(self.pixel(30, 30).blue(), 255)
        self.assertNotEqual(self.pixel(88, 88).rgb(), QColor(0, 0, 255).rgb())   # 切った角の外は塗らない
        self.w.shared["copy"].trigger()
        n = len(self.c.layers)
        self.w.shared["paste"].trigger()
        self.assertEqual(len(self.c.layers), n + 1)
        self.assertEqual(self.c.current, len(self.c.layers) - 1)   # 貼った物は一番上で選んだ状態
        self.c.select(0)
        self.w.shared["cut"].trigger()
        self.assertEqual(self.pixel(30, 30).alpha(), 0)

    def test_ai_fix_uses_polygon_shape(self):
        self.triangle_by_polygon()
        regions = self.w.fix_regions("笑顔に")
        self.assertEqual(len(regions), 1)
        mask = regions[0][0]
        self.assertEqual(mask.getpixel((20, 20)), 255)
        self.assertEqual(mask.getpixel((85, 85)), 0)   # 三角の外は AI に渡さない

    def test_polygon_escape_and_short(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        self.w.tool_actions["polygon"].trigger()
        self.press("press", 10, 10)
        self.press("release", 10, 10)
        self.c.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertEqual(self.c.poly_points, [])
        self.assertIsNone(self.c.selection)

    def test_alpha_from_color_panel(self):
        """色の欄の透明度を 50% にすると、塗った所が半分透ける。見本の色を選び直しても透明度は残る"""
        from PySide6.QtGui import QColor
        cp = self.w.color_panel
        cp.set_color(QColor("#ff0000"))
        cp.alpha_box.setValue(50)
        self.assertEqual(cp.alpha_slider.value(), 50)
        self.assertEqual(cp.alpha_preview.color.alpha(), 128)
        cp.set_color(QColor("#0000ff"))   # 見本を押したのと同じ
        self.assertEqual(self.c.color.alpha(), 128)
        n = len(self.c.layers)
        self.c.add_layer()
        self.assertEqual(len(self.c.layers), n + 1)
        self.w.tool_actions["select"].trigger()
        self.press("press", 10, 10)
        self.press("move", 50, 50)
        self.press("release", 50, 50)
        self.w.shared["sel_fill"].trigger()
        px = self.pixel(30, 30)
        self.assertTrue(120 <= px.alpha() <= 136, px.alpha())
        cp.alpha_slider.setValue(100)
        self.assertEqual(self.c.color.alpha(), 255)

    def test_no_selection_tells(self):
        said = []
        self.w.notify = lambda *a, **k: said.append(a[0])
        self.w.shared["sel_fill"].trigger()
        self.assertTrue(said and "選択範囲" in said[0])


class EnglishTest(unittest.TestCase):
    """言語を English にして開くと、メニューの外（ボタン・欄・ツールチップ・ダイアログ・右クリック）も英語になるか。
    前はメニューだけが英語で、ほかは日本語のままだった"""

    def setUp(self):
        from chatdraw import i18n
        from chatdraw.app import Window
        from chatdraw.settings import Settings
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.store = Settings()
        self.old = self.store.store.value("language")
        self.store.set("language", "English")
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.show()
        self.qapp.processEvents()
        self.i18n = i18n

    def tearDown(self):
        if self.old is None:
            self.store.store.remove("language")
        else:
            self.store.set("language", self.old)
        self.w.dirty = False
        self.w.close()
        self.i18n.install(self.qapp, "日本語")
        self.tmp.cleanup()

    def test_widgets_tooltips_tabs(self):
        w = self.w
        tabs = w.ai_panel.tabs
        names = [tabs.tabText(i) for i in range(tabs.count())]
        self.assertIn("Prompt", names)
        self.assertEqual(w.tool_actions["lasso"].toolTip(), "Lasso Select (drag around) (L)")
        self.assertEqual(w.color_panel.alpha_slider.toolTip()[:13], "Color opacity")
        self.assertEqual(w.color_panel.tabs.tabText(0), "Color")
        # 保存する並びは日本語の名前のまま（英語の名前で残すと、日本語に戻したときに並びが戻らない）
        self.assertIn("指示", w.ai_tabs.order())

    def test_dialog_and_context_menu(self):
        from PySide6.QtWidgets import QMenu, QMessageBox
        box = QMessageBox(QMessageBox.Information, "パレット", "このファイルはパレットとして読めませんでした")
        box.show()
        self.qapp.processEvents()
        self.assertEqual(box.text(), "This file could not be read as a palette.")
        box.close()
        m = QMenu()
        m.addAction("レイヤーを足す")
        m.addAction("元に戻す（Ctrl+Z）")
        m.show()
        self.qapp.processEvents()
        self.assertEqual([a.text() for a in m.actions()], ["Add Layer", "Undo (Ctrl+Z)"])
        m.close()


if __name__ == "__main__":
    unittest.main()
