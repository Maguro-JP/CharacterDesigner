"""保存の形（PSD・ORA・PNG・JPG）と、今の表示の書き出しと、ライブラリーに出す絵。

本物と同じ経路で流す: メニューの操作を押し、保存の窓で置き場と形を選び（窓だけ偽物に替える）、
開くの操作で開き直して、レイヤーの数・名前・順・表示・不透明度・画素が戻るかを見る。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, sweep_windows, wait_bg  # noqa: E402


class SaveFormatTest(unittest.TestCase):
    def setUp(self):
        from tempfile import mkdtemp, mktemp
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.canvas import Layer, blank
        from chatdraw.engine import Studio
        sweep_windows()
        self.app = QApplication.instance() or QApplication([])
        self.dir = Path(mkdtemp())
        self.w = Window(Studio(FakeWords(), FakePainter(), self.dir))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)
        c = self.w.canvas
        c.new_canvas(200, 160)
        p = QPainter(c.layers[1].image)
        p.fillRect(10, 10, 20, 20, QColor("red"))
        p.end()
        c.layers[1].name = "AI の絵"
        fix = blank(200, 160)
        p = QPainter(fix)
        p.fillRect(100, 60, 10, 10, QColor("blue"))
        p.end()
        c.layers.append(Layer("赤ペンの直し", fix, visible=False, opacity=0.5))
        c.rebuild()

    def tearDown(self):
        self.w.wait_io(5)
        self.w.hide()
        self.w.deleteLater()

    def save_via_menu(self, path: str, chosen: str = "") -> None:
        with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", return_value=(path, chosen)):
            self.w.shared["save_as"].trigger()
        wait_bg(self.app, self.w)

    def open_via_menu(self, path: str) -> None:
        self.w.canvas.new_canvas(50, 50)
        with mock.patch("chatdraw.app.QFileDialog.getOpenFileName", return_value=(path, "")):
            self.w.shared["open"].trigger()
        wait_bg(self.app, self.w)

    def assert_layers_back(self):
        c = self.w.canvas
        self.assertEqual(c.size_px(), (200, 160))
        self.assertEqual([l.name for l in c.layers], ["背景", "AI の絵", "赤ペンの直し"])
        self.assertEqual([l.visible for l in c.layers], [True, True, False])
        self.assertAlmostEqual(c.layers[2].opacity, 0.5, delta=1 / 255)
        self.assertEqual(c.layers[0].image.pixelColor(150, 150).name(), "#ffffff")
        self.assertEqual(c.layers[1].image.pixelColor(15, 15).name(), "#ff0000")
        self.assertEqual(c.layers[1].image.pixelColor(150, 150).alpha(), 0)
        self.assertEqual(c.layers[2].image.pixelColor(105, 65).name(), "#0000ff")

    def test_layered_roundtrip_psd_and_ora(self):
        from chatdraw import project
        names = project.filters()
        for i, suf in ((0, ".psd"), (1, ".ora")):
            with self.subTest(suf):
                # 名前に拡張子を書かず、形の欄で選んだだけでも、その形で書く
                self.save_via_menu(str(self.dir / "picture"), names[i])
                path = self.dir / ("picture" + suf)
                self.assertTrue(path.is_file(), path)
                self.assertEqual(self.w.project_path, str(path))
                self.open_via_menu(str(path))
                self.assert_layers_back()
                self.assertEqual(self.w.project_path, str(path))
        try:
            from psd_tools import PSDImage
        except ImportError:
            return
        psd = PSDImage.open(self.dir / "picture.psd")   # 別の部品で読んでも同じに見えるか（作画ソフトで開けるかの代わり）
        self.assertEqual([l.name for l in psd], ["背景", "AI の絵", "赤ペンの直し"])
        self.assertEqual([l.visible for l in psd], [True, True, False])
        self.assertEqual(psd[1].topil().getpixel((15, 15))[:3], (255, 0, 0))

    def test_ora_layout(self):
        import zipfile
        self.save_via_menu(str(self.dir / "a.ora"))
        with zipfile.ZipFile(self.dir / "a.ora") as z:
            first = z.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
            self.assertEqual(z.read("mimetype"), b"image/openraster")
            self.assertIn("mergedimage.png", z.namelist())
            xml = z.read("stack.xml").decode()
        self.assertLess(xml.index("赤ペンの直し"), xml.index("背景"))   # 上のレイヤーから並べる決まり

    def test_flat_png_and_jpg(self):
        from PySide6.QtGui import QImage
        for suf in (".png", ".jpg"):
            with self.subTest(suf):
                path = self.dir / ("flat" + suf)
                self.save_via_menu(str(path))
                img = QImage(str(path))
                self.assertEqual((img.width(), img.height()), (200, 160))
                px = img.pixelColor(15, 15)
                self.assertTrue(px.red() > 240 and px.green() < 20 and px.blue() < 20, px.name())
                self.assertEqual(img.pixelColor(105, 65).name(), "#ffffff")   # 隠したレイヤーは入れない
                self.open_via_menu(str(path))
                self.assertEqual(self.w.canvas.layers[0].image.pixelColor(15, 15).red() > 240, True)

    def test_default_format_follows_layers(self):
        from chatdraw import project
        seen = {}

        def ask(*a, **k):
            seen["name"], seen["filter"] = a[2], a[4] if len(a) > 4 else k.get("selectedFilter")
            return "", ""
        with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", ask):
            self.w.shared["save_as"].trigger()
        self.assertTrue(seen["name"].endswith(".psd"))
        self.assertEqual(seen["filter"], project.filters()[0])
        self.w.canvas.show_image(self._png())   # 1 枚の絵（上は空のレイヤー）なら PNG
        with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", ask):
            self.w.shared["save_as"].trigger()
        self.assertTrue(seen["name"].endswith(".png"))

    def _png(self) -> str:
        from PySide6.QtGui import QColor, QImage
        img = QImage(40, 30, QImage.Format_ARGB32)
        img.fill(QColor("green"))
        path = str(self.dir / "one.png")
        img.save(path)
        return path

    def test_export_flat_and_view_from_menu_key_and_right_click(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QImage, QKeySequence
        S = self.w.shared
        self.assertEqual(S["export_flat"].shortcut(), QKeySequence("Ctrl+E"))
        self.assertEqual(S["export_view"].shortcut(), QKeySequence("Ctrl+Alt+E"))
        file_menu = next(a.menu() for a in self.w.menuBar().actions() if a.text() == "ファイル")
        out = next(a.menu() for a in file_menu.actions() if a.text() == "書き出す")
        self.assertIn(S["export_flat"], out.actions())
        self.assertIn(S["export_view"], out.actions())
        m = self.w.build_canvas_menu()
        acts = m.actions()   # 並びを手元に持つ（持たないと、下の段のメニューの包みが先に消えた）
        sub = [a for a in acts if a.text() == "保存・書き出し"][0].menu()
        self.assertEqual([a for a in sub.actions()], [S["save"], S["save_as"], S["export_flat"], S["export_view"]])
        for k in ("save", "save_as", "export_flat", "export_view"):
            self.assertTrue(S[k].toolTip())
        pen = self.w.canvas.redpen   # 赤ペンの印は、重ねた絵には入らず、今の表示には入る
        pen.begin(QPointF(150, 120))
        for x, y in ((190, 120), (190, 150), (150, 150), (150, 121)):
            pen.add(QPointF(x, y))
        pen.end()
        self.w.canvas.set_zoom(3.0)
        self.w.canvas.rotate_view(15)
        flat, view = self.dir / "flat.png", self.dir / "view.png"
        with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", return_value=(str(flat), "")):
            sub.actions()[2].trigger()
        with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", return_value=(str(view), "")):
            sub.actions()[3].trigger()
        a, b = QImage(str(flat)), QImage(str(view))
        self.assertEqual((a.width(), a.height(), b.width(), b.height()), (200, 160, 200, 160))   # 拡大と回転は入れない
        self.assertEqual(a.pixelColor(15, 15).name(), "#ff0000")
        self.assertEqual(b.pixelColor(15, 15).name(), "#ff0000")
        diff = sum(1 for x in range(140, 200) for y in range(110, 160) if a.pixelColor(x, y) != b.pixelColor(x, y))
        self.assertGreater(diff, 20)   # 印の線が今の表示にだけある
        self.assertEqual(len(self.w.canvas.layers), 3)   # 書き出してもレイヤーはそのまま

    def test_reads_psd_with_offsets_and_rle(self):
        """CLIP STUDIO や Photoshop の書く PSD（RLE で縮め、レイヤーが絵の一部の大きさで位置を持つ）を読めるか"""
        try:
            from PIL import Image
            from psd_tools import PSDImage
            from psd_tools.api.layers import PixelLayer
        except ImportError:
            self.skipTest("psd_tools が無い")
        psd = PSDImage.new("RGB", (120, 90))
        part = Image.new("RGBA", (20, 10), (0, 200, 0, 255))
        psd.append(PixelLayer.frompil(part, psd, "green", top=30, left=40))
        path = self.dir / "other.psd"
        psd.save(path)
        self.open_via_menu(str(path))
        c = self.w.canvas
        self.assertEqual(c.size_px(), (120, 90))
        self.assertEqual(c.layers[-1].name, "green")
        self.assertEqual(c.layers[-1].image.pixelColor(45, 35).name(), "#00c800")
        self.assertEqual(c.layers[-1].image.pixelColor(39, 35).alpha(), 0)
        self.assertEqual(c.layers[-1].image.pixelColor(60, 35).alpha(), 0)


class LibraryShowsOnlyFilesTest(unittest.TestCase):
    def setUp(self):
        from tempfile import mkdtemp, mktemp
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        sweep_windows()
        self.app = QApplication.instance() or QApplication([])
        self.dir = Path(mkdtemp())
        self.w = Window(Studio(FakeWords(), FakePainter(), self.dir))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)

    def tearDown(self):
        self.w.hide()
        self.w.deleteLater()

    def _pic(self, name: str) -> str:
        from PySide6.QtGui import QColor, QImage
        img = QImage(20, 20, QImage.Format_ARGB32)
        img.fill(QColor("red"))
        path = str(self.dir / name)
        img.save(path)
        return path

    def test_missing_failed_and_deleted_are_not_listed(self):
        import time
        lib, panel = self.w.library, self.w.library_panel
        keep, gone = self._pic("keep.png"), self._pic("gone.png")
        for p in (keep, gone):
            panel.add(lib.add_work(p, {"text": "騎士"}))
        lib.add_work(str(self.dir / "never.png"), {"text": "描けませんでした"})   # ファイルの無い記録
        panel.refresh()                                                              # 開いた時と同じ並べ直し
        self.assertEqual(panel.works.count(), 2)
        self.w.activity.end("描けませんでした")                                     # 描けなかった回は絵の一覧に枠を作らない
        self.w.activity.end("止めました")
        self.assertEqual(self.w.history.count(), 0)
        self.w.activity.add(gone, "")
        self.assertEqual(self.w.history.count(), 1)
        os.remove(gone)                                                              # ほかのアプリで消した
        end = time.time() + 5
        while (panel.works.count() != 1 or self.w.history.count()) and time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertEqual(panel.works.count(), 1)
        self.assertEqual(panel.works.item(0).data(256 + 1), keep)
        self.assertEqual(self.w.history.count(), 0)
        self.w.delete_images([keep], ask=False)                                      # ごみ箱へ移した
        self.assertEqual(panel.works.count(), 0)


if __name__ == "__main__":
    unittest.main()
