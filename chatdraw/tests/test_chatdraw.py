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

    def paint(self, prompt, seed, on_step=None):
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


class DrawTest(unittest.TestCase):
    def test_pen_eraser_undo(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Canvas
        QApplication.instance() or QApplication([])
        c = Canvas()
        c.new_canvas(100, 100)
        c.color, c.size = QColor("red"), 4
        c.undo_stack.append(c.image.copy())
        c.stroke(QPointF(10, 50), QPointF(90, 50))
        self.assertEqual(c.image.pixelColor(50, 50).name(), "#ff0000")
        c.tool = "eraser"
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        self.assertEqual(c.image.pixelColor(50, 50).name(), "#ffffff")
        c.undo()
        self.assertEqual(c.image.pixelColor(50, 50).name(), "#ffffff")  # 戻すと線を引く前の白
        self.assertEqual(c.image.pixelColor(20, 50).name(), "#ffffff")


if __name__ == "__main__":
    unittest.main()
