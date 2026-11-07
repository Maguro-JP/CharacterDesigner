"""Tab キーと作成枚数の置き場所を、利用者と同じキーで押して確かめる。
前は文字を打っている途中の Tab で欄が全部隠れ、もう一度押すと閉じていた欄まで全部出た"""
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app  # noqa: E402


class TabKeyTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.w = Window(Studio(FakeWords(), FakePainter(), Path(self.tmp.name)))
        self.w.show()
        self.w.activateWindow()
        self.qapp.processEvents()

    def tearDown(self):
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def tab(self, target):
        target.setFocus()
        self.qapp.processEvents()
        QTest.keyClick(target, Qt.Key_Tab)
        self.qapp.processEvents()

    def test_tab_in_text_does_not_hide_panels(self):
        chat = self.w.panels["chat"][0]
        self.assertTrue(chat.isVisible())
        before = [b.isVisible() for b in self.w._all_bars()]
        self.tab(self.w.entry)
        self.assertTrue(chat.isVisible(), "文字の欄の Tab で欄が隠れた")
        self.assertEqual([b.isVisible() for b in self.w._all_bars()], before)
        self.assertFalse(getattr(self.w, "_all_hidden", False))

    def test_tab_on_canvas_toggles_and_restores_only_shown(self):
        docks = [d for d, _a in self.w.panels.values()]
        closed = next(d for d in docks if d.isVisible())
        closed.hide()
        shown = [b for b in self.w._all_bars() if b.isVisible()]
        self.tab(self.w.canvas)
        self.assertTrue(all(not b.isVisible() for b in self.w._all_bars()))
        self.tab(self.w.canvas)
        self.assertEqual([b for b in self.w._all_bars() if b.isVisible()], shown)
        self.assertFalse(closed.isVisible(), "閉じていた欄まで出た")

    def test_count_next_to_draw_button(self):
        spin = self.w.ai_panel.count_spin
        bar = self.w.ai_panel.draw_bar
        widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
        self.assertIn(spin, widgets)
        self.assertEqual(widgets.index(spin) + 1, widgets.index(self.w.button))
        self.assertIn("作成枚数", spin.toolTip())
        spin.setFocus()
        QTest.keyClick(spin, Qt.Key_Up)
        self.assertEqual(self.w.ai_panel.count(), spin.value())


if __name__ == "__main__":
    unittest.main()
