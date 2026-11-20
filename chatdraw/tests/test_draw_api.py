"""人間の筆入力と同じ描画経路を使う構造化ストロークAPIの試験"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class StructuredStrokeTest(unittest.TestCase):
    def setUp(self):
        app()
        from chatdraw.canvas import Canvas
        self.canvas = Canvas()
        self.canvas.new_canvas(100, 100)

    def tearDown(self):
        self.canvas.close()

    def test_stroke_uses_canvas_brush_and_is_one_undo_step(self):
        from PySide6.QtGui import QColor
        layer = self.canvas.layers[self.canvas.current]
        self.assertEqual(self.canvas.draw_stroke([(10, 20), (50, 20), (80, 20)],
                                                 color="#e02030", size=7, brush="ペン"), 3)
        self.assertGreater(layer.image.pixelColor(40, 20).alpha(), 0)
        self.assertEqual(self.canvas.undo_names[-1], "ペン")
        self.canvas.undo()
        self.assertEqual(layer.image.pixelColor(40, 20).alpha(), 0)
        self.canvas.redo()
        self.assertGreater(self.canvas.layers[self.canvas.current].image.pixelColor(40, 20).alpha(), 0)
        self.assertEqual(self.canvas.tool, "pen")
        self.assertEqual(self.canvas.color, QColor("#000000"))
        self.assertEqual(self.canvas.size, 6)

    def test_rejects_invalid_points_without_changing_canvas_or_history(self):
        layer = self.canvas.layers[self.canvas.current]
        before = layer.image.copy()
        history = len(self.canvas.undo_stack)
        for points in ([], [(100, 20)], [(float("nan"), 2)], [(1, 2, 3)]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.canvas.draw_stroke(points)
        self.assertEqual(len(self.canvas.undo_stack), history)
        self.assertEqual(layer.image.pixelColor(5, 5).alpha(), before.pixelColor(5, 5).alpha())

    def test_rejects_invalid_pressure_and_brush(self):
        with self.assertRaises(ValueError):
            self.canvas.draw_stroke([(1, 1), (2, 2)], pressures=[1.0])
        with self.assertRaises(ValueError):
            self.canvas.draw_stroke([(1, 1)], brush="存在しないブラシ")
        with self.assertRaises(ValueError):
            self.canvas.draw_stroke([(1, 1)], pressures=[1.5])

    def test_rejects_locked_or_hidden_layer(self):
        layer = self.canvas.layers[self.canvas.current]
        layer.locked = True
        with self.assertRaises(PermissionError):
            self.canvas.draw_stroke([(5, 5), (10, 10)])
        layer.locked = False
        layer.visible = False
        with self.assertRaises(PermissionError):
            self.canvas.draw_stroke([(5, 5), (10, 10)])

    def test_rejects_when_another_stroke_is_active(self):
        from chatdraw.canvas import blank
        self.canvas.buffer = blank(100, 100)
        with self.assertRaises(RuntimeError):
            self.canvas.draw_stroke([(5, 5), (10, 10)])
        self.canvas.buffer = None


if __name__ == "__main__":
    unittest.main()
