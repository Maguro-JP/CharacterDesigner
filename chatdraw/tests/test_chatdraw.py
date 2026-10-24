"""チャットで頼むと絵ができるか。絵の模型と言葉の模型は偽物に替えて、流れだけを確かめる"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.engine import Studio, has_japanese  # noqa: E402


class FakeWords:
    def to_prompt(self, text):
        return "1girl, red scarf" if has_japanese(text) else text


class FakePainter:
    def __init__(self):
        self.calls = []

    def paint(self, prompt, seed, on_step=None, **kw):
        from PIL import Image
        self.calls.append((prompt, seed))
        if on_step:
            on_step(1, 1)
        return Image.new("RGB", (64, 96), "white")


class EngineTest(unittest.TestCase):
    def test_request_becomes_saved_image(self):
        with TemporaryDirectory() as d:
            painter = FakePainter()
            said = []
            prompt, path = Studio(FakeWords(), painter, Path(d)).draw("赤いマフラーの子", 7, said.append)
            self.assertEqual(prompt, "1girl, red scarf")
            self.assertTrue(path.exists())
            self.assertEqual(painter.calls, [("1girl, red scarf", 7)])
            self.assertIn("描いています（1/1）", said)

    def test_only_minor_and_sexual_together_is_refused(self):
        from chatdraw.engine import refused
        self.assertFalse(refused("赤いマフラーの騎士の少年、雪の城の前"))
        self.assertFalse(refused("adult woman, nude"))
        self.assertTrue(refused("child, nude"))
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                Studio(FakeWords(), FakePainter(), Path(d)).draw("裸の子ども", 1)

    def test_english_passes_through(self):
        self.assertFalse(has_japanese("knight, snow"))
        self.assertTrue(has_japanese("騎士"))


class WindowTest(unittest.TestCase):
    def test_chat_shows_image(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.entry.setText("雪の城の前の騎士")
            w.send()
            for _ in range(200):
                app.processEvents()
                if w.images:
                    break
                w.thread and w.thread.wait(10)
            self.assertEqual(len(w.images), 1)
            self.assertTrue(Path(w.images[0]).exists())
            self.assertTrue(w.button.isEnabled())


class LayoutTest(unittest.TestCase):
    def test_float_and_arrange(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.show()
        w.float_all()
        self.assertTrue(all(d.isFloating() for d, _ in w.panels.values()))
        from PySide6.QtCore import Qt
        d = w.panels["layers"][0]
        self.assertTrue(d.windowFlags() & Qt.WindowMinMaxButtonsHint)
        # 左上の端をつかんで広げたのと同じ動き: 位置と大きさが両方変わる
        d.setGeometry(100, 100, 400, 300)
        d.setGeometry(50, 60, 450, 340)
        self.assertEqual((d.width(), d.height()), (450, 340))
        self.assertLessEqual(abs(d.x() - 50) + abs(d.y() - 60), 4)   # 枠の分だけずれる
        w.arrange()
        self.assertFalse(any(d.isFloating() for d, _ in w.panels.values()))
        w.panels["history"][0].toggleViewAction().trigger()
        self.assertTrue(w.panels["history"][0].isHidden())


class DrawTest(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.canvas import Canvas
        QApplication.instance() or QApplication([])
        self.c = Canvas()
        self.c.new_canvas(100, 100)

    def px(self, x, y):
        return self.c.flatten().pixelColor(x, y).name()

    def test_pen_eraser_undo_on_layer(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("red"), 4
        c.snapshot()
        c.stroke(QPointF(10, 50), QPointF(90, 50))
        self.assertEqual(self.px(50, 50), "#ff0000")
        self.assertEqual(c.layers[0].image.pixelColor(50, 50).name(), "#ffffff")   # 背景には描かない
        c.tool = "eraser"
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        self.assertEqual(self.px(50, 50), "#ffffff")   # 消すと下の背景が見える
        c.undo()
        self.assertEqual(self.px(20, 50), "#ffffff")

    def test_layers_visibility_order(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("blue"), 10
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        c.add_layer()
        c.color = QColor("lime")
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        self.assertEqual(self.px(50, 50), "#00ff00")
        c.set_visible(c.current, False)
        self.assertEqual(self.px(50, 50), "#0000ff")
        c.set_visible(c.current, True)
        c.move_layer(-1)
        self.assertEqual(self.px(50, 50), "#0000ff")
        self.assertEqual(len(c.layers), 3)

    def test_keys_hold_tool_and_resize_brush(self):
        c = self.c
        c.set_tool("pen")
        c.hold("hand")
        self.assertEqual(c.tool, "hand")
        c.release()
        self.assertEqual(c.tool, "pen")
        c.size = 10
        c.resize_brush(1.25)
        self.assertEqual(c.size, 12)
        c.resize_brush(0.8)
        self.assertEqual(c.size, 9)

    def test_undo_keeps_only_touched_layer(self):
        from PySide6.QtCore import QPointF
        c = self.c
        c.snapshot()
        c.stroke(QPointF(10, 10), QPointF(20, 20))
        self.assertEqual(c.undo_stack[-1][0], "one")
        self.assertEqual(c._bytes(c.undo_stack[-1]), 100 * 100 * 4)   # 触った 1 枚の分だけ

    def test_fill_and_eyedropper(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("black"), 3
        c.stroke(QPointF(0, 30), QPointF(99, 30))   # 横線で上下に分ける
        c.color = QColor("#ff8800")
        c.fill(QPointF(50, 10))
        self.assertEqual(self.px(50, 10), "#ff8800")
        self.assertEqual(self.px(50, 80), "#ffffff")   # 線の向こうは塗らない
        c.pick(QPointF(50, 80))
        self.assertEqual(c.color.name(), "#ffffff")


if __name__ == "__main__":
    unittest.main()
