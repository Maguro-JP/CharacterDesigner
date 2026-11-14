"""描く補助（図形の道具・Shift の固定・定規・手ぶれ補正・描いて止めると形を整える）。
道具は窓の道具の帯とメニューから選び、絵の上をマウスで押して動かして離す（本物と同じ経路）。描けた画素の場所で確かめる"""
import math
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.assist import recognize  # noqa: E402
from chatdraw.tests.test_brushtools import window  # noqa: E402


def mouse(c, pts, mods=None, hold_ms=0):
    """絵の座標の点の列を、押す・動かす・（止める）・離すのマウスにして流す"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    mods = mods or Qt.NoModifier
    vp = c.viewport()

    def send(kind, p, button, buttons):
        q = QPointF(c.mapFromScene(*p))
        QApplication.sendEvent(vp, QMouseEvent(kind, q, QPointF(vp.mapToGlobal(q.toPoint())), button, buttons, mods))
    send(QEvent.MouseButtonPress, pts[0], Qt.LeftButton, Qt.LeftButton)
    for p in pts[1:]:
        send(QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton)
    if hold_ms:
        QTest.qWait(hold_ms)
    send(QEvent.MouseButtonRelease, pts[-1], Qt.LeftButton, Qt.NoButton)


def click(c, p, double=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    at = c.mapFromScene(*p)
    if double:
        QTest.mouseDClick(c.viewport(), Qt.LeftButton, Qt.NoModifier, at)
    else:
        QTest.mouseClick(c.viewport(), Qt.LeftButton, Qt.NoModifier, at)


def ink(c, x, y, r=1) -> bool:
    """(x, y) の近く（r 画素）に描いた色があるか"""
    img = c.layers[c.current].image
    return any(img.pixelColor(x + dx, y + dy).alpha() > 60 for dx in range(-r, r + 1) for dy in range(-r, r + 1)
               if 0 <= x + dx < img.width() and 0 <= y + dy < img.height())


def inked(c) -> list:
    img = c.layers[c.current].image
    return [(x, y) for y in range(img.height()) for x in range(img.width()) if img.pixelColor(x, y).alpha() > 60]


class Base(unittest.TestCase):
    def setUp(self):
        self.w = window()
        self.c = self.w.canvas
        self.w.size_box.setValue(3)

    def tool(self, key):
        self.w.tool_actions[key].trigger()
        self.assertEqual(self.c.tool, key)


class ShapeToolsTest(Base):
    def test_shift_line_snaps_to_15_degrees(self):
        from PySide6.QtCore import Qt
        self.tool("line")
        mouse(self.c, [(20, 100), (100, 100), (150, 108)], Qt.ShiftModifier)
        self.assertTrue(ink(self.c, 148, 100))        # 8 画素ずれた終わりが、まっすぐ横にそろう
        self.assertFalse(ink(self.c, 150, 108))

    def test_shift_rect_is_square_and_ellipse_is_circle(self):
        from PySide6.QtCore import Qt
        self.tool("rect")
        mouse(self.c, [(20, 20), (120, 60)], Qt.ShiftModifier)
        self.assertTrue(ink(self.c, 20, 110))   # 縦も 100 画素
        self.assertTrue(ink(self.c, 120, 120))
        self.c.undo()
        self.assertEqual(inked(self.c), [])
        self.tool("ellipse")
        mouse(self.c, [(40, 40), (160, 80)], Qt.ShiftModifier)
        self.assertTrue(ink(self.c, 100, 160))  # 正円の下の端（中心 100,100、半径 60）
        self.assertTrue(ink(self.c, 160, 100))

    def test_regular_polygon_from_center_to_corner(self):
        self.tool("regpoly")
        from PySide6.QtTest import QTest
        QTest.qWait(30)
        self.assertTrue(self.w.poly_sides.isVisible() and self.w.fill_shapes.isVisible())
        self.w.poly_sides.setValue(4)
        mouse(self.c, [(100, 100), (150, 100)])
        for x, y in ((150, 100), (100, 150), (50, 100), (100, 50)):   # 角が 4 つ、真ん中から 50 画素
            self.assertTrue(ink(self.c, x, y, 2), (x, y))
        self.assertFalse(ink(self.c, 100, 100, 3))
        self.c.undo()
        self.assertEqual(inked(self.c), [])

    def test_polygon_shape_by_clicks_and_enter(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.tool("polyshape")
        for p in ((30, 30), (170, 30), (100, 160)):
            click(self.c, p)
        self.assertEqual(inked(self.c), [])   # 閉じるまでは描かない
        QTest.keyClick(self.c, Qt.Key_Return)
        self.assertTrue(ink(self.c, 100, 30))
        self.assertTrue(ink(self.c, 65, 95, 2))
        self.assertEqual(self.c.undo_names[-1], "多角形")
        self.c.undo()
        self.assertEqual(inked(self.c), [])
        # 始めの角を押しても閉じる。Esc は置きかけをやめる
        for p in ((30, 30), (170, 30), (100, 160), (30, 30)):
            click(self.c, p)
        self.assertTrue(ink(self.c, 100, 30))
        self.c.undo()
        for p in ((30, 30), (170, 30)):
            click(self.c, p)
        QTest.keyClick(self.c, Qt.Key_Escape)
        self.assertEqual(self.c.shape_points, [])
        self.assertEqual(inked(self.c), [])


class RulerTest(Base):
    def wobbly(self, a, b, n=30, amp=6):
        return [(a[0] + (b[0] - a[0]) * i / n + amp * math.sin(i), a[1] + (b[1] - a[1]) * i / n + amp * math.cos(i * 1.3))
                for i in range(n + 1)]

    def test_parallel_ruler_from_menu_keeps_strokes_straight(self):
        self.w.ruler_actions["parallel"].trigger()   # 表示 > 定規 > 平行線
        self.assertEqual(self.c.ruler, "parallel")
        self.assertEqual(self.w.ruler.currentData(), "parallel")
        self.tool("pen")
        mouse(self.c, self.wobbly((30, 60), (170, 75)))
        ys = {y for _x, y in inked(self.c)}
        self.assertLessEqual(max(ys) - min(ys), 5)   # 横の定規なので、縦に揺らしても 1 本の横線（太さ 3）

    def test_concentric_ruler_keeps_radius(self):
        self.w.ruler.setCurrentIndex(self.w.ruler.findData("concentric"))
        self.tool("pen")
        pts = [(100 + 50 * math.cos(t / 10) + 5 * math.sin(t), 100 + 50 * math.sin(t / 10)) for t in range(25)]
        mouse(self.c, [(150, 100)] + pts)
        rs = [math.hypot(x - 100, y - 100) for x, y in inked(self.c)]
        self.assertLess(max(rs) - min(rs), 6)

    def test_radial_ruler_and_moving_the_center(self):
        self.w.ruler.setCurrentIndex(self.w.ruler.findData("radial"))
        self.c.set_ruler_point(0, __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(20, 20))
        self.tool("pen")
        mouse(self.c, [(60, 60)] + self.wobbly((60, 60), (160, 160), amp=5)[1:])
        for x, y in inked(self.c):
            self.assertLess(abs(x - y), 5)   # 中心 (20, 20) から外へ向かう線は、y = x の上に乗る

    def test_two_point_perspective_picks_nearest_direction(self):
        self.w.ruler.setCurrentIndex(self.w.ruler.findData("persp2"))
        self.tool("pen")
        mouse(self.c, [(100, 40), (100, 50), (103, 90), (98, 150)])   # ほぼ縦に描くと縦の線
        xs = {x for x, _y in inked(self.c)}
        self.assertLessEqual(max(xs) - min(xs), 5)

    def test_ruler_handle_drag_moves_point(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.w.ruler.setCurrentIndex(self.w.ruler.findData("concentric"))
        vp = self.c.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, self.c.mapFromScene(100, 100))
        mouse_move = self.c.mapFromScene(60, 70)
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseMove, QPointF(mouse_move), QPointF(mouse_move), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, mouse_move)
        p = self.c.ruler_pts[0]
        self.assertAlmostEqual(p.x(), 60, delta=1.5)
        self.assertAlmostEqual(p.y(), 70, delta=1.5)
        self.assertEqual(inked(self.c), [])   # 丸をつかんだ間は描かない

    def test_line_tool_follows_ruler(self):
        self.w.ruler.setCurrentIndex(self.w.ruler.findData("parallel"))
        self.tool("line")
        mouse(self.c, [(30, 50), (170, 90)])
        self.assertTrue(ink(self.c, 160, 50))
        self.assertFalse(ink(self.c, 170, 90, 3))


class CorrectionTest(Base):
    def test_stabilizer_range_and_line_reaches_release_point(self):
        self.assertEqual(self.w.stabilizer.maximum(), 100)
        self.w.stabilizer.setValue(100)
        self.tool("pen")
        mouse(self.c, [(20, 100), (60, 100), (100, 100), (180, 100)])
        self.assertTrue(ink(self.c, 179, 100))   # 前は補正で遅れた分が切れ、離した所まで線が届かなかった
        self.c.undo()
        self.assertEqual(inked(self.c), [])

    def test_quickshape_turns_wobbly_circle_into_circle_and_undo_steps_back(self):
        self.w.quickshape_action.trigger()   # 表示 > 定規 > 描いて止めると形を整える
        self.assertTrue(self.c.quickshape and self.w.quickshape.isChecked())
        self.tool("pen")
        names = []
        self.c.shaped.connect(names.append)
        pts = [(100 + (55 + 4 * math.sin(5 * t / 8)) * math.cos(t / 8), 100 + (55 + 4 * math.sin(5 * t / 8)) * math.sin(t / 8))
               for t in range(52)]
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        vp = self.c.viewport()

        def send(kind, p, b, bs):
            q = QPointF(self.c.mapFromScene(*p))
            QApplication.sendEvent(vp, QMouseEvent(kind, q, q, b, bs, Qt.NoModifier))
        send(QEvent.MouseButtonPress, pts[0], Qt.LeftButton, Qt.LeftButton)
        for p in pts[1:]:
            send(QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton)
        for _ in range(100):   # 止めて待つ（ほかの試験と一緒に流すと遅れるので、整うまで最大 5 秒待つ）
            if names:
                break
            QTest.qWait(50)
        send(QEvent.MouseButtonRelease, pts[-1], Qt.LeftButton, Qt.NoButton)
        self.assertEqual(names, ["円"])
        shaped = inked(self.c)
        cx = sum(x for x, _y in shaped) / len(shaped)
        cy = sum(y for _x, y in shaped) / len(shaped)

        def spread(px):
            rs = [math.hypot(x - cx, y - cy) for x, y in px]
            return max(rs) - min(rs)
        self.assertEqual(self.c.undo_names[-1], "形を整える")
        self.c.undo()
        raw = inked(self.c)
        self.assertTrue(raw and raw != shaped)   # 1 回目の元に戻すで、整える前の線
        self.assertLess(spread(shaped), 6)          # 太さ 3 の円の輪（ふちのにじみを入れて 6 未満）
        self.assertGreater(spread(raw), spread(shaped) + 3)   # 揺れた線（半径 51〜59）より細い輪にそろう
        self.c.undo()
        self.assertEqual(inked(self.c), [])

    def test_quickshape_waits_for_pause_and_leaves_free_lines(self):
        self.w.quickshape.setChecked(True)
        self.tool("pen")
        mouse(self.c, [(100 + 50 * math.cos(t / 8), 100 + 50 * math.sin(t / 8)) for t in range(52)])   # 止めずに離す
        self.assertNotEqual(self.c.undo_names[-1], "形を整える")
        self.c.undo()
        mouse(self.c, [(20 + 4 * i, 100 + 30 * math.sin(i / 4)) for i in range(40)], hold_ms=800)   # 波は形にしない
        self.assertNotEqual(self.c.undo_names[-1], "形を整える")


class RecognizeTest(unittest.TestCase):
    def test_shapes(self):
        import random
        random.seed(3)

        def j(pts):
            return [(x + random.uniform(-2, 2), y + random.uniform(-2, 2)) for x, y in pts]

        def seg(a, b, n=20):
            return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
        cases = {
            "circle": [(100 + 50 * math.cos(t / 40 * 6.3), 100 + 50 * math.sin(t / 40 * 6.3)) for t in range(41)],
            "ellipse": [(100 + 80 * math.cos(t / 40 * 6.3), 100 + 30 * math.sin(t / 40 * 6.3)) for t in range(41)],
            "rect": seg((70, 20), (120, 20)) + seg((120, 20), (120, 90)) + seg((120, 90), (20, 90)) + seg((20, 90), (20, 20)) + seg((20, 20), (68, 21)),
            "triangle": seg((50, 10), (110, 110)) + seg((110, 110), (10, 110)) + seg((10, 110), (49, 12)),
            "line": seg((0, 0), (150, 60), 40),
            None: [(100 + 50 * math.cos(t / 40 * 3), 100 + 50 * math.sin(t / 40 * 3)) for t in range(41)],   # 弧は形にしない
        }
        for want, pts in cases.items():
            got = recognize(j(pts))
            self.assertEqual(got and got[0], want if want else None, want)


class MenuTest(Base):
    def test_fill_checkbox_only_for_shapes(self):
        from PySide6.QtTest import QTest
        self.tool("pen")
        QTest.qWait(30)
        self.assertFalse(self.w.fill_shapes.isVisible())   # 前は帯の部品だけを隠していて、ペンでも「塗り」が出たままだった
        self.tool("ellipse")
        QTest.qWait(30)
        self.assertTrue(self.w.fill_shapes.isVisible())

    def test_menus_and_tooltips(self):
        titles = {a.text(): a.menu() for a in self.w.menuBar().actions() if a.menu()}
        view = [a.text() for a in titles["表示"].actions()]
        self.assertIn("定規", view)
        self.assertIn("図形", view)
        shapes = next(a.menu() for a in titles["表示"].actions() if a.text() == "図形")
        shapes.actions()[-1].trigger()   # 表示 > 図形 > 正多角形（おすすめの配置では道具の帯に出ない）
        self.assertEqual(self.c.tool, "regpoly")
        for k in ("line", "rect", "ellipse", "polyshape", "regpoly"):
            self.assertIn("Shift", self.w.tool_actions[k].toolTip())
        for a in self.w.ruler_actions.values():
            self.assertTrue(a.toolTip())
        self.assertTrue(self.w.ruler.toolTip() and self.w.quickshape.toolTip() and self.w.stabilizer.toolTip())


class TabletTest(Base):
    """ペンタブレットの経路。前はペンで引いた直線・図形だけタイムラプスの写しが撮られず、押しただけの赤ペンが点の印で残り、
    手ぶれ補正の線が離した所まで届かなかった"""
    def tab(self, kind, x, y, buttons):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QPointingDevice, QTabletEvent
        from PySide6.QtWidgets import QApplication
        q = QPointF(self.c.mapFromScene(x, y))
        QApplication.sendEvent(self.c.viewport(), QTabletEvent(kind, QPointingDevice.primaryPointingDevice(), q, q, 0.8, 0, 0, 0, 0, 0,
                                                               Qt.NoModifier, Qt.LeftButton, buttons))

    def stroke(self, pts):
        from PySide6.QtCore import QEvent, Qt
        self.tab(QEvent.TabletPress, *pts[0], Qt.LeftButton)
        for p in pts[1:]:
            self.tab(QEvent.TabletMove, *p, Qt.LeftButton)
        self.tab(QEvent.TabletRelease, *pts[-1], Qt.NoButton)

    def test_tablet_shape_emits_stroke_done(self):
        done = []
        self.c.stroke_done.connect(lambda: done.append(1))
        self.tool("rect")
        self.stroke([(20, 20), (100, 100)])
        self.assertEqual(done, [1])
        self.assertTrue(ink(self.c, 20, 60))

    def test_tablet_tap_with_redpen_leaves_no_mark(self):
        self.tool("redpen")
        self.stroke([(50, 50)])
        self.assertEqual(len(self.c.redpen.marks), 0)

    def test_tablet_stabilized_line_reaches_end(self):
        self.w.stabilizer.setValue(100)
        self.tool("pen")
        self.stroke([(20, 100), (60, 100), (180, 100)])
        self.assertTrue(ink(self.c, 179, 100))


if __name__ == "__main__":
    unittest.main()
