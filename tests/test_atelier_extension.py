"""CharacterDesigner を AtelIer の拡張として登録すると、AtelIer の窓にキャラクターデザインのメニューが出ること。

pip で入れると entry points（pyproject.toml の `atelier.extensions`）で登録される。ここでは同じ物を
atelier.extensions.register で登録して、入れずに同じ形を確かめる。entry points の書き方が本体の読み方と合うことも見る。
"""
from __future__ import annotations

import os
import sys
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from atelier_helpers import FakePainter, FakeWords, app, use_extension  # noqa: E402
from atelier import extensions  # noqa: E402
from character_designer import extension  # noqa: E402

MENU = "キャラクターデザイン"


class EntryPointTest(unittest.TestCase):
    def test_pyproject_points_at_the_extension(self):
        meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        points = meta["project"]["entry-points"][extensions.GROUP]
        self.assertEqual(points, {"character_designer": "character_designer.extension:EXTENSION"})
        self.assertIsInstance(extension.EXTENSION, extensions.Extension)

    def test_entry_point_loads_through_atelier(self):
        class Point:
            name, value = "character_designer", "character_designer.extension:EXTENSION"

            def load(self):
                return extension.EXTENSION

        with mock.patch("importlib.metadata.entry_points", lambda group: [Point()] if group == extensions.GROUP else []):
            self.assertEqual(extensions.load_entry_points(), ["chara"])


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        d = Path(self.tmp.name)
        from atelier.files import paths
        self.patches = [mock.patch.object(paths, "data_home", lambda: d / "data"),
                        mock.patch.object(paths, "LLM_HOME", d / "LLM"),
                        mock.patch.object(paths, "HOME", d / "home")]
        for p in self.patches:
            p.start()
        self.d = d

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_menu_appears_in_atelier_window(self):
        from atelier.ai.engine import Studio
        from atelier.app.main_window import Window
        use_extension()
        self.assertIn("chara", [e.name for e in extensions.registered()])
        w = Window(Studio(FakeWords(), FakePainter(), self.d / "out"))
        try:
            menus = [a.text() for a in w.menuBar().actions() if a.menu() is not None]
            print(f"\nAtelIer の窓のメニュー {len(menus)} 本: {'、'.join(menus)}")
            self.assertIn(MENU, menus)
            self.assertIn("キャラデザを作る…", [a.text() for a in w.chara_menu.actions()])
            self.assertIn("キャラクターを開く…", [a.text() for a in w.file_menu.actions()])
            self.assertIn("designer", w.mode_actions)
        finally:
            w.dirty = False
            w.closing_checked = True
            w.close()


if __name__ == "__main__":
    unittest.main()
