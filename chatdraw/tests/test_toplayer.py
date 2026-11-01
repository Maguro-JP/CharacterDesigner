"""AI の結果（描いた・直した・加工した・綺麗にした・広げた）が、どの経路でも一番上の新しいレイヤーに置かれて選ばれるか。
前は結果を一番下に入れ、上の空のレイヤーを選んでいたため、結果が出たことに気づけなかった"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


class TopLayerTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.old_place = self.w.settings.store.value("result_place")
        self.w.settings.set("result_place", "上のレイヤー")
        self.w.settings.set("output_dir", str(self.d / "out"))
        self.src = self.d / "a.png"
        figure().save(self.src)
        self.w.edit_image(str(self.src))

    def tearDown(self):
        if self.old_place is None:
            self.w.settings.store.remove("result_place")
        else:
            self.w.settings.set("result_place", self.old_place)
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def png(self, name, size=(96, 128)):
        p = self.d / name
        Image.new("RGB", size, (10, 200, 30)).save(p)
        return str(p)

    def assertTop(self, name):
        c = self.w.canvas
        self.assertEqual(c.current, len(c.layers) - 1, [l.name for l in c.layers])
        self.assertEqual(c.layers[-1].name, name)

    def test_default_is_top_layer(self):
        from chatdraw.settings import Settings
        from PySide6.QtCore import QSettings
        s = QSettings(str(self.d / "s.ini"), QSettings.IniFormat)
        self.assertEqual(Settings(s).get("result_place"), "上のレイヤー")

    def test_same_size_result_keeps_original_below(self):
        n = len(self.w.canvas.layers)
        self.w.put_result(self.png("r.png"), "AI の直し 1")
        self.assertTop("AI の直し 1")
        self.assertEqual(len(self.w.canvas.layers), n + 1)
        self.w.canvas.undo()
        self.assertEqual(len(self.w.canvas.layers), n)

    def test_new_drawing_is_top_and_selected(self):
        self.w.mode.setCurrentIndex(0)
        self.w.images.append("x")
        self.w.place(self.png("new.png", (64, 64)))
        self.assertTop("AI の絵 1")
        self.assertNotIn("レイヤー 1", [l.name for l in self.w.canvas.layers])

    def test_drawing_on_canvas_is_top(self):
        self.w.mode.setCurrentIndex(1)
        self.w.images.append("x")
        self.w.canvas.select(0)   # 下のレイヤーを選んでいても、結果は一番上
        self.w.place(self.png("on.png"))
        self.assertTop("AI の絵 1")

    def test_finished_same_size_and_upscaled(self):
        base = figure()
        self.w._place_finished("clean", base, base.copy())
        self.assertTop("綺麗にした絵")
        self.w._place_finished("clean", base, base.resize((192, 256)))
        self.assertTop("綺麗にした絵（拡大）")
        self.assertEqual(self.w.canvas.size_px(), (192, 256))

    def test_outpaint_is_top(self):
        self.assertIsNotNone(self.w.outpaint_canvas(32, 0, 32, 0))
        self.assertTop("広げた絵")

    def test_lineart_and_pixel_are_top(self):
        for make, name in ((self.w.make_lineart, "線画"), (lambda: self.w.make_pixel(32, 8), "ドット絵")):
            self.w.canvas.select(0)
            n = len(self.w.canvas.layers)
            make()
            for _ in range(500):
                self.qapp.processEvents()
                if len(self.w.canvas.layers) > n:
                    break
                import time
                time.sleep(0.01)
            self.assertTop(name)

    def test_separate_file_leaves_canvas(self):
        self.w.settings.set("result_place", "別ファイル")
        names = [l.name for l in self.w.canvas.layers]
        with mock.patch("PySide6.QtCore.QProcess.startDetached", return_value=True) as start:
            placed = self.w.put_result(self.png("r.png"), "AI の直し 1")
        self.assertFalse(placed)
        self.assertEqual([l.name for l in self.w.canvas.layers], names)
        args = start.call_args[0][1]
        self.assertEqual(args[-2:], ["--open", str(self.d / "r.png")])


if __name__ == "__main__":
    unittest.main()
