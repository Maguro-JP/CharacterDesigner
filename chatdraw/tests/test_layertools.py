"""レイヤーのコピー・切り取り・貼り付け・複製・反転と、対称定規（線対称・点対称）。
窓のメニュー・キー・レイヤーの欄の右クリック・絵の上のマウスから押して、画素とレイヤーの数で確かめる（本物と同じ経路）。
直したバグ: ロックしたレイヤーの切り取り・消す・塗る、隠した・ロックしたレイヤーへの結合、図形に効かない対称、絵の大きさを変えても動かない軸"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.tests.test_brushtools import drag, window  # noqa: E402


def menu_action(w, top: str, text: str):
    """メニューの棒の top の中から、見出しが text の操作を探す（下の段も見る）"""
    from PySide6.QtWidgets import QMenu
    menus = {m.menuAction(): m for m in w.findChildren(QMenu)}

    def walk(menu):
        for a in menu.actions():
            if a in menus:
                found = walk(menus[a])
                if found:
                    return found
            elif a.text() == text:
                return a
    for a in w.menuBar().actions():
        if a.text() == top:
            return walk(menus[a])


def press_keys(w, seq: str):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    w.activateWindow()
    w.canvas.setFocus()
    QApplication.processEvents()
    k = QKeySequence(seq)[0]
    QTest.keyClick(w.canvas, k.key(), k.keyboardModifiers())


def red(c, layer=None):
    from PySide6.QtGui import QColor
    c.layers[c.current if layer is None else layer].image.fill(QColor("red"))


class LayerOpsTest(unittest.TestCase):
    def test_menus_have_layer_ops_with_keys(self):
        w = window()
        for top, text, key in (("編集", "レイヤーをコピー", "Ctrl+Alt+C"), ("編集", "レイヤーを切り取り", "Ctrl+Alt+X"),
                               ("編集", "レイヤーを貼り付け", "Ctrl+Alt+V"), ("編集", "同じ位置に貼り付け", "Ctrl+Shift+V"),
                               ("編集", "結合してコピー", "Ctrl+Shift+C"), ("レイヤー", "レイヤーを複製", ""),
                               ("レイヤー", "選択範囲をコピーして新しいレイヤーへ", "Ctrl+J"),
                               ("レイヤー", "選択範囲を切り取って新しいレイヤーへ", "Ctrl+Shift+J"),
                               ("レイヤー", "下のレイヤーと結合", ""), ("レイヤー", "レイヤーの中を消す", ""),
                               ("レイヤー", "レイヤーを左右反転", ""), ("レイヤー", "レイヤーを上下反転", ""),
                               ("表示", "点対称（中心の周り）", "")):
            a = menu_action(w, top, text)
            self.assertIsNotNone(a, text)
            self.assertEqual(a.shortcut().toString(), key, text)
            self.assertTrue(a.toolTip(), text)   # 説明はツールチップに出す
        # 窓の中で同じキーを 2 つの操作に付けていない
        from chatdraw import keys
        seen = {}
        for name, a in keys.collect(w).items():
            k = a.shortcut().toString()
            if k:
                self.assertNotIn(k, seen, f"{k}: {name} と {seen.get(k)}")
                seen[k] = name

    def test_duplicate_copy_cut_paste_layer_and_undo(self):
        w = window()
        c = w.canvas
        red(c)
        c.layers[c.current].opacity = 0.5
        menu_action(w, "レイヤー", "レイヤーを複製").trigger()
        self.assertEqual(len(c.layers), 3)
        self.assertEqual(c.layers[c.current].name, "レイヤー 1 のコピー")
        self.assertEqual(c.layers[c.current].image.pixelColor(5, 5).name(), "#ff0000")
        self.assertEqual(c.layers[c.current].opacity, 0.5)
        c.undo()
        self.assertEqual(len(c.layers), 2)
        press_keys(w, "Ctrl+Alt+X")                  # 切り取り
        self.assertEqual(len(c.layers), 1)
        from PySide6.QtWidgets import QApplication
        self.assertEqual(QApplication.clipboard().image().pixelColor(5, 5).name(), "#ff0000")
        press_keys(w, "Ctrl+Alt+V")                  # 貼り付け（選んでいるレイヤーのすぐ上、選んだ状態）
        self.assertEqual(len(c.layers), 2)
        self.assertEqual(c.current, 1)
        self.assertEqual(c.layers[1].name, "レイヤー 1")
        self.assertEqual(c.layers[1].opacity, 0.5)
        press_keys(w, "Ctrl+Alt+C")
        press_keys(w, "Ctrl+Alt+V")
        self.assertEqual([x.name for x in c.layers], ["背景", "レイヤー 1", "レイヤー 1 のコピー"])
        c.undo()
        c.undo()
        c.undo()
        self.assertEqual([x.name for x in c.layers], ["背景", "レイヤー 1"])   # 切り取りも元に戻すで戻る

    def test_via_copy_cut_and_paste_in_place(self):
        from PySide6.QtCore import QRect
        w = window()
        c = w.canvas
        red(c)
        c.set_selection(QRect(50, 60, 30, 20))
        press_keys(w, "Ctrl+J")
        self.assertEqual(len(c.layers), 3)
        new = c.layers[c.current].image
        self.assertEqual(new.pixelColor(60, 70).name(), "#ff0000")
        self.assertEqual(new.pixelColor(10, 10).alpha(), 0)            # 選択の外は写さない
        press_keys(w, "Ctrl+Shift+J")                                   # 写したレイヤーから切り取る
        self.assertEqual(len(c.layers), 4)
        self.assertEqual(c.layers[2].image.pixelColor(60, 70).alpha(), 0)
        self.assertEqual(c.layers[3].image.pixelColor(60, 70).name(), "#ff0000")
        # 選択の中をコピーし、選択を外してから同じ位置に貼る
        w.shared["copy"].trigger()
        w.shared["deselect"].trigger()
        press_keys(w, "Ctrl+Shift+V")
        img = c.layers[c.current].image
        self.assertEqual(len(c.layers), 5)
        self.assertEqual(img.pixelColor(60, 70).name(), "#ff0000")
        self.assertEqual(img.pixelColor(5, 5).alpha(), 0)
        # 結合してコピーは見えている絵（白い背景＋赤）
        c.set_selection(QRect(0, 0, 10, 10))
        press_keys(w, "Ctrl+Shift+C")
        from PySide6.QtWidgets import QApplication
        clip = QApplication.clipboard().image()
        self.assertEqual((clip.width(), clip.height()), (10, 10))
        self.assertEqual(clip.pixelColor(5, 5).name(), "#ff0000")
        for _ in range(4):
            c.undo()
        self.assertEqual(len(c.layers), 2)
        self.assertEqual(c.layers[1].image.pixelColor(60, 70).name(), "#ff0000")

    def test_flip_and_clear_layer(self):
        from PySide6.QtGui import QColor
        w = window()
        c = w.canvas
        c.layers[c.current].image.setPixelColor(10, 20, QColor("blue"))
        menu_action(w, "レイヤー", "レイヤーを左右反転").trigger()
        self.assertEqual(c.layers[c.current].image.pixelColor(189, 20).name(), "#0000ff")
        menu_action(w, "レイヤー", "レイヤーを上下反転").trigger()
        self.assertEqual(c.layers[c.current].image.pixelColor(189, 179).name(), "#0000ff")
        menu_action(w, "レイヤー", "レイヤーの中を消す").trigger()
        self.assertEqual(c.layers[c.current].image.pixelColor(189, 179).alpha(), 0)
        c.undo()
        c.undo()
        c.undo()
        self.assertEqual(c.layers[c.current].image.pixelColor(10, 20).name(), "#0000ff")

    def test_layer_panel_right_click_has_ops(self):
        w = window()
        c = w.canvas
        red(c)
        lp = w.layer_panel
        row = lp.row_of(c.current)
        pos = lp.list.visualItemRect(lp.list.item(row)).center()
        m = lp.context_menu(pos)
        texts = [a.text() for a in m.actions()]
        for t in ("レイヤーを複製", "レイヤーを切り取り", "レイヤーをコピー", "レイヤーを貼り付け",
                  "選択範囲をコピーして新しいレイヤーへ", "レイヤーの中を消す", "レイヤーを左右反転", "下のレイヤーと結合"):
            self.assertIn(t, texts)
        next(a for a in m.actions() if a.text() == "レイヤーを複製").trigger()
        self.assertEqual(len(c.layers), 3)

    def test_locked_and_hidden_layers_are_kept(self):
        """直したバグ: ロックしたレイヤーの選択範囲の切り取り・消す・塗るが絵を変えていた。隠した・ロックしたレイヤーへ結合していた"""
        from PySide6.QtCore import QRect
        w = window()
        c = w.canvas
        red(c)
        c.set_locked(c.current, True)
        c.set_selection(QRect(10, 10, 50, 50))
        for k in ("cut", "sel_clear", "sel_fill", "via_cut", "clear_layer", "flip_layer_h"):
            w.shared[k].trigger()
            self.assertEqual(c.layers[c.current].image.pixelColor(20, 20).name(), "#ff0000", k)
        w.shared["layer_cut"].trigger()
        self.assertEqual(len(c.layers), 2)
        c.set_locked(c.current, False)
        c.set_selection(None)
        c.set_locked(0, True)
        self.assertFalse(c.merge_down())                                # 下がロック
        self.assertEqual(len(c.layers), 2)
        c.set_locked(0, False)
        c.set_visible(0, False)
        self.assertFalse(c.merge_down())                                # 下が隠れている
        c.set_visible(0, True)
        c.set_visible(1, False)
        self.assertFalse(c.merge_down())                                # 上が隠れている（黙って捨てていた）
        c.set_visible(1, True)
        self.assertTrue(c.merge_down())
        self.assertEqual(len(c.layers), 1)


class SymmetryTest(unittest.TestCase):
    def setUp(self):
        self.w = window()
        self.c = self.w.canvas
        self.w.size_box.setValue(4)

    def mode(self, key):
        self.w.symmetry.setCurrentIndex(self.w.symmetry.findData(key))

    def black(self, x, y):
        return self.c.flatten().pixelColor(x, y).name() == "#000000"

    def test_vertical_horizontal_point_with_pen(self):
        self.w.tool_actions["pen"].trigger()
        self.mode("ud")
        self.assertTrue(self.c.mirror_item.isVisible())
        drag(self.c, [(40, 30), (50, 30), (60, 30)])
        self.assertTrue(self.black(50, 30) and self.black(50, 169))     # 200 - 30 - 1 付近
        self.mode("point")
        drag(self.c, [(20, 100), (25, 110), (30, 120)])
        self.assertTrue(self.black(25, 110) and self.black(175, 90))
        self.mode("both")
        drag(self.c, [(150, 150), (155, 150), (160, 150)])
        for x, y in ((155, 150), (45, 150), (155, 50), (45, 50)):
            self.assertTrue(self.black(x, y), (x, y))
        # メニューの「対称定規」と欄の選びは同じ設定
        self.assertTrue(self.w.symmetry_actions["both"].isChecked())
        self.w.symmetry_actions[""].trigger()
        self.assertEqual(self.c.symmetry, "")
        self.assertFalse(self.c.mirror_item.isVisible())

    def test_shapes_follow_symmetry(self):
        """直したバグ: 直線・四角・楕円は対称にしても片側にしか描かれなかった"""
        self.mode("lr")
        self.w.tool_actions["line"].trigger()
        drag(self.c, [(20, 100), (40, 120), (60, 140)])
        self.assertTrue(self.black(40, 120) and self.black(160, 120))
        self.mode("point")
        self.w.tool_actions["rect"].trigger()
        drag(self.c, [(20, 20), (30, 30), (40, 40)])
        self.assertTrue(self.black(20, 30) and self.black(180, 170))

    def test_axis_drag_and_resize(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest
        c = self.c
        self.mode("lr")
        self.w.tool_actions["pen"].trigger()
        vp = c.viewport()
        start = c.mapFromScene(QPointF(100, 100))
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        end = c.mapFromScene(QPointF(120, 80))
        QTest.mouseMove(vp, end)
        ev = QMouseEvent(QEvent.MouseMove, QPointF(end), QPointF(vp.mapToGlobal(end)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication_send(vp, ev)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, end)
        self.assertAlmostEqual(c.axis_center().x(), 120, delta=1.5)   # 丸をつかんで動かした（描いていない）
        self.assertEqual(c.flatten().pixelColor(110, 90).name(), "#ffffff")
        drag(c, [(100, 40), (105, 40), (110, 40)])
        self.assertTrue(self.black(105, 40) and self.black(135, 40))   # 2×120 - 105
        menu_action(self.w, "表示", "軸を真ん中に戻す").trigger()
        self.assertEqual(c.axis_center().x(), 100)
        c.new_canvas(400, 200)
        self.assertEqual(c.mirror_item.path().boundingRect().center().x(), 200)   # 絵の大きさに合わせる


def QApplication_send(target, ev):
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(target, ev)


if __name__ == "__main__":
    unittest.main()
