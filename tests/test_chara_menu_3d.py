"""キャラクターデザインのメニューの「3D キャラを作る…」から、選んだ絵で AtelIer の 3D に進む画面へ渡ること（AtelIer の tests/test_features.py から移した）。"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image, ImageDraw  # noqa: E402

from atelier_helpers import FakePainter, FakeWords, app  # noqa: E402


def figure() -> Image.Image:
    im = Image.new("RGB", (120, 160), "white")
    ImageDraw.Draw(im).ellipse((30, 20, 90, 150), fill=(200, 80, 80))
    return im


class CharaMenu3DTest(unittest.TestCase):
    def test_chara_menu_entry_opens_3d(self):
        from PySide6.QtWidgets import QFileDialog
        from atelier.ai.engine import Studio
        from atelier.app.main_window import Window
        app()
        with TemporaryDirectory() as d, mock.patch("atelier.files.paths.HOME", Path(d) / "home"):
            src = Path(d) / "c.png"
            figure().save(src)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.chara_menu.aboutToShow.emit()
            act = next(a for a in w.chara_menu.actions() if a.text() == "3D キャラを作る…")
            self.assertTrue(act.toolTip())
            with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(src), "")), \
                    mock.patch.object(w, "open_3d") as opened:
                w.canvas.layers.clear() if hasattr(w.canvas.layers, "clear") else None   # 絵が無いので、絵を選ぶ窓から取る
                act.trigger()
            self.assertEqual(opened.call_args[0][0], str(src))
            w.dirty = False
            w.closing_checked = True
            w.close()


if __name__ == "__main__":
    unittest.main()
