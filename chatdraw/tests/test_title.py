"""ウィンドウのタイトルに今の版を出す。β版（1.0 より前）の間は「CharacterDesigner 0.5.15 β」の形にする"""
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chatdraw import app, updater  # noqa: E402
from chatdraw.paths import ROOT  # noqa: E402


class TitleTest(unittest.TestCase):
    def test_title_uses_root_version(self):
        ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        title = app.app_title()
        self.assertTrue(title.startswith(f"CharacterDesigner {ver}"), title)
        if ver.startswith("0."):
            self.assertEqual(title, f"CharacterDesigner {ver} β")

    def test_title_follows_version_bump(self):
        with mock.patch.object(updater, "current", return_value="0.5.99"):
            self.assertEqual(app.app_title(), "CharacterDesigner 0.5.99 β")
        with mock.patch.object(updater, "current", return_value="1.0.0"):
            self.assertEqual(app.app_title(), "CharacterDesigner 1.0.0")   # 正式版では β を付けない

    def test_title_without_version_file(self):
        with mock.patch.object(updater, "current", return_value="0"):
            self.assertEqual(app.app_title(), "CharacterDesigner")

    def test_window_shows_version(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        with mock.patch.object(updater, "current", return_value="0.5.15"):
            w = app.Window()
            try:
                self.assertEqual(w.windowTitle(), "CharacterDesigner 0.5.15 β")
                w.show_progress("描いています", 30)
                self.assertEqual(w.windowTitle(), "30% 描いています - CharacterDesigner 0.5.15 β")
                w.show_progress("", -2)
                self.assertEqual(w.windowTitle(), "CharacterDesigner 0.5.15 β")
            finally:
                w.close()
                w.deleteLater()


if __name__ == "__main__":
    unittest.main()
