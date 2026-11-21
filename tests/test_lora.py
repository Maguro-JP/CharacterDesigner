"""キャラクターシートを、アプリの窓から押して最後まで通す（LoRA と学習セットの試験は AtelIer の tests/test_lora.py にある）。"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ATELIER_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image  # noqa: E402

from atelier_helpers import app  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        from atelier.files import paths
        self.patches = [mock.patch.object(paths, "data_home", lambda: self.d / "data"),
                        mock.patch.object(paths, "LLM_HOME", self.d / "LLM"),
                        mock.patch.object(paths, "HOME", self.d / "home")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def wait(self, cond, secs=20):
        end = time.time() + secs
        while time.time() < end and not cond():
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertTrue(cond())


class SheetTest(Base):
    def test_sheet_from_window_opens_layers_and_writes_psd(self):
        """設定資料の人物から、窓のメニューの「キャラクターシートを作る」で PSD を書き、レイヤーのまま開く"""
        from character_designer import chara_design as charadesign
        from atelier.files import project_file as project
        from atelier.app.main_window import Window
        from atelier.ai.engine import Studio
        from atelier_helpers import FakePainter, FakeWords
        c = charadesign.save_character("hero", "1girl, red hair", Image.new("RGB", (64, 96), "red"))
        b = charadesign.bible()
        for role, color in (("turn-front", "red"), ("turn-side", "orange"), ("turn-back", "brown"), ("expr-smile", "pink")):
            charadesign._add(b, c["id"], role, Image.new("RGB", (64, 96), color))
        w = Window(Studio(FakeWords(), FakePainter(), self.d / "out"))
        try:
            w.chara_id = c["id"]
            w._fill_chara_menu()
            act = next(a for a in w.chara_menu.actions() if a.text() == "キャラクターシートを作る")
            self.assertTrue(act.isEnabled())
            self.assertTrue(act.toolTip())
            act.trigger()
            out = self.d / "home" / "bible" / "characters" / f"{c['id']}-sheet.psd"
            self.assertTrue(out.is_file())
            self.assertTrue(out.with_suffix(".png").is_file())   # まとめた 1 枚も隣に置く
            self.wait(lambda: "表情差分" in [l.name for l in w.canvas.layers])
            names = [l.name for l in w.canvas.layers]
            # 前の版の名前（turn-*）の絵も、今の名前で読んで並べる。区画ごとに 1 枚のレイヤー
            self.assertEqual(names, ["背景", "名前と設定", "色の見本", "三面図", "目の拡大", "表情差分"])
            import struct
            self.assertEqual(struct.unpack(">h", out.read_bytes()[42:44])[0], 6)   # PSD にも区画ごとに 6 枚
            self.assertEqual(w.canvas.size_px()[0], 2400)
        finally:
            w.dirty = False
            w.close()


if __name__ == "__main__":
    unittest.main()
