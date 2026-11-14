"""ブラシの見本の線・色の欄（数字・色の出方・自分のパレット・スポイト）・足した道具（スプレー・指先・文字・手ぶれ補正・左右対称）。
道具は窓の道具の帯を押して持ち替え、絵の上をマウスで押して動かして離す（本物と同じ経路）。画素が変わったかで確かめる"""
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

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402


def window():
    from PySide6.QtWidgets import QApplication
    from chatdraw.app import Window
    QApplication.instance() or QApplication([])
    w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
    w.resize(1400, 900)
    w.show()
    w.canvas.new_canvas(200, 200)
    w.canvas.set_zoom(1.0)
    return w


def drag(c, pts):
    """絵の座標の点の列を、ビューの上のマウスの押す・動かす・離すにして流す"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    vp = c.viewport()
    at = [c.mapFromScene(x, y) for x, y in pts]
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at[0])
    for p in at[1:]:
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, QPointF
        ev = QMouseEvent(QEvent.MouseMove, QPointF(p), QPointF(vp.mapToGlobal(p)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication_send(vp, ev)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at[-1] if at else QPoint())


def QApplication_send(target, ev):
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(target, ev)


def changed(before, after) -> int:
    return sum(1 for y in range(0, after.height(), 2) for x in range(0, after.width(), 2)
               if before.pixelColor(x, y) != after.pixelColor(x, y))


class BrushPreviewTest(unittest.TestCase):
    def test_preview_follows_size_color_opacity_and_hardness(self):
        w = window()
        pv = w.brush_preview
        if not w.panel_in_front("brushes"):
            w.toggle_panel("brushes")                                    # 欄の帯でブラシの欄を出す
        if w.tour is not None and w.tour.isVisible():
            w.tour.finish()
        self.assertTrue(pv.isVisibleTo(w))
        w.size_box.setValue(4)
        thin = pv.render(240, 56)
        w.size_box.setValue(30)
        thick = pv.render(240, 56)
        count = lambda im: sum(1 for y in range(im.height()) for x in range(im.width()) if im.pixelColor(x, y).alpha() > 40)
        self.assertGreater(count(thick), count(thin) * 2)               # 太さが見本に出る
        w.color_panel.set_color(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor("#ff0000"))
        img = pv.render(240, 56)
        reds = [img.pixelColor(x, 28) for x in range(240) if img.pixelColor(x, 28).alpha() > 200]
        self.assertTrue(reds and all(c.red() > 200 and c.green() < 60 for c in reds[:5]))   # 色が見本に出る
        w.flow.setValue(30)
        faint = max(pv.render(240, 56).pixelColor(x, 28).alpha() for x in range(240))
        self.assertLess(faint, 120)                                      # 濃さが見本に出る
        w.flow.setValue(100)
        w.hardness.setValue(100)
        hard = pv.render(240, 56)
        w.hardness.setValue(0)
        soft = pv.render(240, 56)
        self.assertNotEqual(hard, soft)                                  # 硬さが見本に出る
        self.assertEqual(w.canvas.size, 30)                              # 見本を描いても太さは変えない

    def test_cursor_ring_matches_size(self):
        w = window()
        c = w.canvas
        w.tool_actions["pen"].trigger()
        w.size_box.setValue(40)
        from PySide6.QtCore import QPointF
        c._ring(QPointF(100, 100))
        self.assertAlmostEqual(c.cursor_ring.rect().width(), 40, delta=0.5)
        self.assertTrue(c.cursor_ring.isVisible())
        w.tool_actions["spray"].trigger()
        c._ring(QPointF(100, 100))
        self.assertAlmostEqual(c.cursor_ring.rect().width(), 80, delta=0.5)   # スプレーは太さが半径
        self.assertTrue(c.cursor_ring.isVisible())


class ColorPanelTest(unittest.TestCase):
    def test_numbers_hex_and_eyedropper_button(self):
        from PySide6.QtGui import QColor
        w = window()
        cp = w.color_panel
        cp.h_box.setValue(120)
        cp.s_box.setValue(100)
        cp.v_box.setValue(100)
        self.assertEqual(w.canvas.color.name(), "#00ff00")
        self.assertEqual(cp.hex.text(), "#00ff00")
        cp.set_color(QColor("#3d7bff"))
        self.assertEqual(cp.h_box.value(), QColor("#3d7bff").hsvHue())  # 色を変えると数字もそろう
        cp.eyedropper_wanted.emit()
        self.assertEqual(w.canvas.tool, "eyedropper")
        self.assertTrue(w.tool_actions["eyedropper"].isChecked())

    def test_palette_add_remove_save_load(self):
        from PySide6.QtGui import QColor
        w = window()
        cp = w.color_panel
        cp.set_color(QColor("#112233"))
        cp.add_to_palette()
        cp.add_to_palette("#abcdef")
        cp.add_to_palette("#abcdef")
        self.assertEqual(cp.mine, ["#112233", "#abcdef"])
        self.assertEqual(cp.mine_grid.count(), 2)
        with TemporaryDirectory() as d:
            path = str(Path(d) / "p.json")
            cp.save_palette(path)
            cp.remove_from_palette("#112233")
            self.assertEqual(cp.mine, ["#abcdef"])
            self.assertEqual(cp.load_palette(path), 2)
            self.assertEqual(cp.mine, ["#112233", "#abcdef"])
            Path(path).write_text('{"colors": ["bad", "#00ff00"]}', encoding="utf-8")
            self.assertEqual(cp.load_palette(path), 1)
        cp.mine_grid.itemAt(0).widget().click()
        self.assertEqual(w.canvas.color.name(), "#00ff00")

    def test_rainbow_mode_draws_many_hues(self):
        from PySide6.QtGui import QColor
        w = window()
        c = w.canvas
        w.tool_actions["pen"].trigger()
        w.color_panel.set_color(QColor("#ff0000"))
        w.color_panel.mode.setCurrentText("虹色")
        self.assertEqual(c.color_mode, "虹色")
        w.size_box.setValue(6)
        drag(c, [(10 + i * 9, 100) for i in range(21)])
        img = c.flatten()
        hues = {img.pixelColor(x, 100).hsvHue() // 30 for x in range(10, 190) if img.pixelColor(x, 100).saturation() > 100}
        self.assertGreaterEqual(len(hues), 3)                            # 線の途中で色相が回る
        w.color_panel.mode.setCurrentText("単色")


class NewToolsTest(unittest.TestCase):
    def test_spray_puts_scattered_dots(self):
        from PySide6.QtGui import QColor
        w = window()
        c = w.canvas
        w.tool_actions["spray"].trigger()
        self.assertEqual(c.tool, "spray")
        c.color = QColor("#000000")
        w.size_box.setValue(20)
        before = c.flatten()
        drag(c, [(100, 100), (110, 100), (120, 100)])
        after = c.flatten()
        n = changed(before, after)
        self.assertGreater(n, 10)
        self.assertEqual(before.pixelColor(10, 10), after.pixelColor(10, 10))   # 円の外は変えない
        c.undo()
        self.assertEqual(changed(before, c.flatten()), 0)                # 元に戻せる

    def test_smudge_drags_color(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QPainter
        w = window()
        c = w.canvas
        p = QPainter(c.layers[c.current].image)
        p.fillRect(QRect(0, 0, 100, 200), QColor("#0000ff"))
        p.end()
        w.tool_actions["smudge"].trigger()
        w.size_box.setValue(20)
        self.assertEqual(c.flatten().pixelColor(115, 100).name(), "#ffffff")
        drag(c, [(90, 100), (100, 100), (110, 100), (120, 100)])
        px = c.flatten().pixelColor(115, 100)
        self.assertGreater(px.blue() - px.red(), 40)                     # 青が右へ伸びた

    def test_text_tool_asks_and_places_text(self):
        w = window()
        c = w.canvas
        w.tool_actions["text"].trigger()
        before = c.flatten()
        with mock.patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("あA", True)):
            drag(c, [(20, 20)])
        self.assertGreater(changed(before, c.flatten()), 5)
        with mock.patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("", False)):
            mid = c.flatten()
            drag(c, [(120, 120)])
        self.assertEqual(changed(mid, c.flatten()), 0)                   # やめたら何も置かない

    def test_symmetry_mirrors_pen(self):
        w = window()
        c = w.canvas
        w.tool_actions["pen"].trigger()
        w.symmetry.setCurrentIndex(w.symmetry.findData("lr"))
        self.assertTrue(c.mirror_item.isVisible())
        w.size_box.setValue(6)
        drag(c, [(20, 50), (40, 50), (60, 50)])
        img = c.flatten()
        self.assertEqual(img.pixelColor(40, 50).name(), "#000000")
        self.assertEqual(img.pixelColor(160, 50).name(), "#000000")      # 200 - 40
        w.symmetry.setCurrentIndex(w.symmetry.findData(""))
        self.assertFalse(c.mirror_item.isVisible())

    def test_stabilizer_smooths_jitter(self):
        from PySide6.QtCore import QPointF
        w = window()
        c = w.canvas
        w.stabilizer.setValue(25)   # 強さは 0〜100。25 は前の 0〜20 の段の 5 と同じ効き
        self.assertEqual(c.stabilizer, 25)
        c.steady = QPointF(0, 0)
        p = c.steadied(QPointF(60, 0))
        self.assertAlmostEqual(p.x(), 10.0)                              # 1/6 だけ近づく
        w.tool_actions["pen"].trigger()
        jag = [(20 + i * 8, 100 + (12 if i % 2 else -12)) for i in range(18)]
        drag(c, jag)
        img = c.flatten()
        ys = [y for y in range(200) if img.pixelColor(90, y).name() != "#ffffff"]
        self.assertTrue(ys)
        self.assertLess(max(ys) - min(ys), 20)                           # ぎざぎざ（±12）が均される
        w.stabilizer.setValue(0)

    def test_new_tools_have_command_and_tour(self):
        from chatdraw import commands, tours
        w = window()
        names = {cm.name for cm in commands.COMMANDS}
        cat = tours.catalog(w)
        for key in ("spray", "smudge", "text"):
            self.assertIn(key, w.tool_actions)
            self.assertIn(key, names)
            self.assertIn(key, cat)
            self.assertFalse(w.tool_actions[key].icon().isNull())


if __name__ == "__main__":
    unittest.main()
