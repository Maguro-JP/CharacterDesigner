"""頼みの欄とチャットの欄にカーソルを合わせると、模型に本当に渡した言葉（足した言葉・打ち消しを含む）が出ること"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class SentWordsTest(unittest.TestCase):
    def test_record_and_tooltip(self):
        from chatdraw import sent
        sent.clear()
        sent.record("描く", "masterpiece, 1girl, red scarf", "lowres, bad hands")
        lines = sent.tooltip_lines()
        self.assertIn("模型に渡した言葉（描く）: masterpiece, 1girl, red scarf", lines)
        self.assertIn("  打ち消し: lowres, bad hands", lines)
        for i in range(20):
            sent.record("直す", f"p{i}")
        self.assertEqual(len(sent.last()), sent.KEEP)

    def test_hover_shows_real_words_after_drawing(self):
        from chatdraw import sent
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.tests.test_editing import app
        a = app()
        sent.clear()
        with TemporaryDirectory() as tmp:
            w = Window(Studio(FakeWords(), FakePainter(), Path(tmp)))
            w.show(); QTest.qWait(20)
            try:
                sent.record("描く", "score_9, 1girl, holding umbrella", "extra arms")
                for target in (w.entry, w.chat.input):
                    vp = target.viewport() if hasattr(target, "viewport") else target
                    ev = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), vp.mapToGlobal(QPoint(5, 5)))
                    QApplication.sendEvent(vp, ev)
                    tip = target.toolTip()
                    self.assertIn("1girl, holding umbrella", tip)
                    self.assertIn("extra arms", tip)
            finally:
                w.closing_checked = True
                w.close()


if __name__ == "__main__":
    unittest.main()
