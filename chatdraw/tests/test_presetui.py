import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402


def window(d):
    from PySide6.QtWidgets import QApplication
    from chatdraw.app import Window
    QApplication.instance() or QApplication([])
    return Window(Studio(FakeWords(), FakePainter(), Path(d)))


class PresetResetTest(unittest.TestCase):
    def test_default_preset_restores_after_other_preset(self):
        from chatdraw.aipanel import DEFAULT_PRESET
        with TemporaryDirectory() as d:
            w = window(d)
            p = w.ai_panel
            self.assertEqual(p.preset, DEFAULT_PRESET)
            start = p.current()
            self.assertTrue(p.apply_name("イラスト"))
            p.seed_lock.setChecked(True)
            self.assertNotEqual(p.current(), start)
            self.assertTrue(p.apply_name(DEFAULT_PRESET))
            self.assertEqual(p.current(), start)
            self.assertFalse(p.seed_lock.isChecked())
            checked = [b.text() for b in p.preset_group.buttons() if b.isChecked()]
            self.assertEqual(checked, [DEFAULT_PRESET])


class WheelGuardTest(unittest.TestCase):
    def test_wheel_does_not_change_unfocused_spinbox(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication, QScrollArea, QSpinBox, QVBoxLayout, QWidget
        from chatdraw import wheelguard
        app = QApplication.instance() or QApplication([])
        wheelguard.install(app)
        area = QScrollArea()
        inner = QWidget()
        lay = QVBoxLayout(inner)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(50)
        lay.addWidget(spin)
        lay.addSpacing(2000)
        area.setWidget(inner)
        area.resize(200, 200)
        area.show()
        app.processEvents()
        self.assertEqual(spin.focusPolicy(), Qt.StrongFocus)
        spin.clearFocus()   # 表示した直後は最初の欄に焦点が来る。押していない状態にそろえる
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(spin, ev)
        self.assertEqual(spin.value(), 50)
        self.assertGreater(area.verticalScrollBar().value(), 0)   # 欄のほうがスクロールする
        spin.setFocus()
        app.processEvents()
        if spin.hasFocus():   # 押して選んだあとはホイールで変えられる
            QApplication.sendEvent(spin, ev)
            self.assertNotEqual(spin.value(), 50)
        area.close()


class NavigatorRectTest(unittest.TestCase):
    def test_view_rect_follows_and_drags(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        with TemporaryDirectory() as d:
            w = window(d)
            app = QApplication.instance()
            w.resize(1400, 900)
            w.show()
            w.canvas.set_zoom(2.0)
            nav = w.navigator
            nav.resize(240, 240)
            nav.redraw() if nav.isVisible() else nav.setPixmap(
                __import__("PySide6.QtGui", fromlist=["QPixmap"]).QPixmap.fromImage(
                    w.canvas.flatten().scaled(232, 232, Qt.KeepAspectRatio)))
            app.processEvents()
            r = nav.view_rect()
            self.assertIsNotNone(r)
            self.assertLess(r.width(), nav.pixmap().width())   # 拡大していると一部だけが見える
            before = w.canvas.horizontalScrollBar().value(), w.canvas.verticalScrollBar().value()
            c = r.center()
            for t, p, b in ((QEvent.MouseButtonPress, c, Qt.LeftButton), (QEvent.MouseMove, c + QPointF(0, 60), Qt.LeftButton),
                            (QEvent.MouseButtonRelease, c + QPointF(0, 60), Qt.NoButton)):
                QApplication.sendEvent(nav, QMouseEvent(t, p, p, Qt.LeftButton, b, Qt.NoModifier))
            after = w.canvas.horizontalScrollBar().value(), w.canvas.verticalScrollBar().value()
            self.assertGreater(after[1], before[1])
            self.assertAlmostEqual(nav.view_rect().center().y(), c.y() + 60, delta=3)
            w.close()


if __name__ == "__main__":
    unittest.main()
