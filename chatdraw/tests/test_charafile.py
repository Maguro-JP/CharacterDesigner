"""キャラクターファイル（.chara）と「キャラデザを作る」を、アプリの窓から押して最後まで通す。

描くのは試験用の小さな SDXL（重みは乱数。絵の出来は見ない）を本物の engine.Painter で読んだ物。
見るのは、流れの工程が全部通ること、.chara に保存して閉じ、開き直して中身が一致すること、
そのキャラクターで描くと模型に渡る言葉（描き手の paint に渡る言葉と禁止ワード）に設定の言葉が入ること"""
import io
import json
import os
import sys
import time
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from chatdraw.tests.test_editing import app  # noqa: E402

SPEC = {"name": "Akari", "look": "1girl, solo, short red hair, green eyes", "outfit": "blue hoodie, black skirt",
        "eyes": "large round eyes, emerald iris, star-shaped highlight", "personality": "明るい", "role": "配達人",
        "negative": "extra weapons"}


class Base(unittest.TestCase):
    def setUp(self):
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        from chatdraw import paths
        self.patches = [mock.patch.object(paths, "data_home", lambda: self.d / "data"),
                        mock.patch.object(paths, "LLM_HOME", self.d / "LLM"),
                        mock.patch.object(paths, "HOME", self.d / "home")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        # 止めた描画の裏の糸が終わるまで待ってから次へ進む。待たないと、裏の糸が描く仕事の鍵（WORK）を持ったまま残り、
        # 次の試験の直しが「前の処理の後片付けを待っています」のまま終わらなかった
        from chatdraw import engine
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(180000)
        engine.STOP.clear()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def wait(self, cond, secs=60):
        end = time.time() + secs
        while time.time() < end and not cond():
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertTrue(cond())


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (32, 48), color).save(buf, "PNG")
    return buf.getvalue()


class FileTest(Base):
    def test_round_trip_and_words(self):
        from chatdraw import charafile
        ch = charafile.new("Akari", "1girl, red hair", "hoodie", ident="akari", personality="明るい")
        ch["manifest"]["eyes"]["tags"] = "green eyes, red hair"
        ch["manifest"]["words"] = {"prompt": "smile", "negative": "extra arms"}
        ch["files"]["images/turn-front.png"] = _png("red")
        ch["manifest"]["images"]["turn-front"] = "images/turn-front.png"
        charafile.thumb(ch)
        out = charafile.save(ch, self.d / "a")
        self.assertEqual(out.suffix, ".chara")
        with zipfile.ZipFile(out) as z:
            self.assertEqual(sorted(z.namelist()), ["images/turn-front.png", "manifest.json", "thumb.png"])
        got = charafile.load(out)
        self.assertEqual(got["manifest"], ch["manifest"])
        self.assertEqual(got["files"], ch["files"])
        words, neg = charafile.prompt_words(got)
        self.assertEqual(words, "1girl, red hair, green eyes, hoodie, smile")   # 同じ言葉は 1 回だけ
        self.assertEqual(neg, "extra arms")
        self.assertEqual(charafile.reference(got).size, (32, 48))

    def test_old_version_is_read_and_new_version_refused(self):
        from chatdraw import charafile
        old = self.d / "old.chara"
        with zipfile.ZipFile(old, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": charafile.FORMAT, "version": 1, "character": {
                "id": "kai", "name": "Kai", "look": "1boy, black hair", "outfit": "coat", "negative": "hat", "age": "17",
                "images": {"color": "images/color.png"}, "eyes": {"tags": "sharp eyes", "notes": ""}}}))
            z.writestr("images/color.png", _png("black"))
        ch = charafile.load(old)
        m = ch["manifest"]
        self.assertEqual((m["version"], m["id"], m["name"], m["profile"]["age"]), (2, "kai", "Kai", "17"))
        self.assertEqual(m["words"]["negative"], "hat")
        self.assertEqual(m["images"], {"color": "images/color.png"})
        new = self.d / "new.chara"
        with zipfile.ZipFile(new, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": charafile.FORMAT, "version": 99}))
        with self.assertRaises(charafile.BadFile):
            charafile.load(new)

    def test_bible_round_trip_with_refset_and_sheet(self):
        from chatdraw import charadesign, charafile, refs
        c = charadesign.save_character("hero", "1girl, red hair", Image.new("RGB", (64, 96), "red"))
        b = charadesign.bible()
        for role, color in (("turn-front", "red"), ("expr-smile", "pink")):
            charadesign._add(b, c["id"], role, Image.new("RGB", (64, 96), color))
        b.set_eyes(c["id"], "amber eyes")
        charadesign.write_sheet_psd(c["id"])
        ref = self.d / "ref.png"
        Image.new("RGB", (40, 40), "green").save(ref)
        refs.RefSets().put("hero の組", "character", c["id"], [str(ref)], "herostyle")
        ch = charafile.from_bible(c["id"], loras=[{"file": "x.safetensors", "scale": 0.7}])
        m = ch["manifest"]
        self.assertEqual(sorted(m["images"]), ["color", "expr-smile", "turn-front"])
        self.assertEqual(m["sheet"], "sheet.psd")
        self.assertEqual(len(m["refset"]["images"]), 1)
        self.assertEqual(len(m["expressions"]), len(b.DEFAULT_EXPRESSIONS))
        path = charafile.save(ch, self.d / "hero.chara")
        # 別の手元（空の置き場）に戻す
        with mock.patch("chatdraw.paths.HOME", self.d / "other"), mock.patch("chatdraw.paths.data_home", lambda: self.d / "data2"):
            ident = charafile.to_bible(charafile.load(path))
            b2 = charadesign.bible()
            c2 = b2.load("characters", ident)
            self.assertEqual(c2["eyes"]["tags"], "amber eyes")
            self.assertTrue((self.d / "other" / c2["images"]["turn-front"]).is_file())
            self.assertTrue((b2.BIBLE / "characters" / f"{ident}-sheet.psd").is_file())
            self.assertEqual(refs.RefSets().for_target("character", ident)[0]["words"], "herostyle")
            again = charafile.from_bible(ident)
            self.assertEqual(again["files"], ch["files"])
            self.assertEqual(b2.design_status(ident)["missing"], charadesign.bible().design_status(ident)["missing"])
        charadesign.bible()   # 置き場を戻す


def _tiny():
    from chatdraw.tests.test_finish_quality import TINY, tiny_ready
    return TINY if tiny_ready() else None


@unittest.skipUnless(_tiny(), "試験用の小さな SDXL が取れません")
class AppFlowTest(Base):
    def setUp(self):
        super().setUp()
        from chatdraw import models
        from chatdraw.models import FILES, ImageModel
        self.TINY = _tiny()
        tiny = ImageModel(self.TINY, "試験用の小さな SDXL", "", "", 0.1, 2, 5.0, files=FILES["bin"], family="sdxl", score=0)
        self.patches.append(mock.patch.object(models, "IMAGES", models.IMAGES + (tiny,)))
        self.patches[-1].start()

    def window(self, painter):
        from chatdraw.app import Window
        from chatdraw.engine import Studio, Words
        w = Window(Studio(Words(Path("")), painter, self.d / "out"))
        w.show()
        self.qapp.processEvents()
        return w

    def close(self, w):
        w.dirty = False
        w.closing_checked = True
        w.close()
        self.qapp.processEvents()

    def test_design_save_reopen_and_draw(self):
        from chatdraw import charafile
        from chatdraw.engine import Painter
        painter = Painter(self.TINY, steps=2, size=(256, 256))
        w = self.window(painter)
        try:
            # 1. キャラデザを作る（メニューから押す。設定の窓だけ、書いた値を返す形に替える）
            w._fill_chara_menu()
            act = next(a for a in w.chara_menu.actions() if a.text() == "キャラデザを作る…")
            self.assertTrue(act.toolTip())
            with mock.patch.object(type(w), "_chara_spec_dialog", lambda self, init=None: dict(SPEC)):
                act.trigger()
            self.wait(lambda: getattr(w, "chara_design_result", None) is not None, 1800)
            res = w.chara_design_result
            self.assertEqual(sorted(res["turn"]), ["back", "front", "left"])
            self.assertEqual(len(res["expressions"]), 8)
            self.assertEqual(len(res["log"]), 7)
            self.assertTrue(res["missing"])   # 四面図・ポーズなどはまだ無い（design-status と同じ判定）
            self.assertTrue(Path(res["sheet"]).is_file())
            self.wait(lambda: any(l.name == "三面図" for l in w.canvas.layers))
            saved = Path(res["path"])
            self.assertTrue(saved.is_file())
            before = charafile.load(saved)
            self.assertEqual(before["manifest"]["eyes"]["tags"], SPEC["eyes"])
            self.assertEqual(before["manifest"]["sheet"], "sheet.psd")
            # 2. ファイルのメニューの「キャラクターを保存」
            file_acts = {a.text(): a for a in w.menuBar().actions()[0].menu().actions()}
            file_acts["キャラクターを保存"].trigger()
            self.assertEqual(charafile.load(saved)["files"], before["files"])
            # ライブラリーの「キャラクター」に出る
            lib = w.library_panel
            self.assertIn("キャラクター", [lib.tabs.tabText(i) for i in range(lib.tabs.count())])
            self.assertEqual([lib.characters.item(i).data(0x0101) for i in range(lib.characters.count())], [str(saved)])
        finally:
            self.close(w)
        # 3. 閉じてから、新しい窓で開き直す
        w = self.window(painter)
        try:
            self.assertIsNone(w.studio.character)
            file_acts = {a.text(): a for a in w.menuBar().actions()[0].menu().actions()}
            with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *a, **k: (str(saved), "")):
                file_acts["キャラクターを開く…"].trigger()
            got = charafile.load(saved)
            self.assertEqual(w.chara_file["manifest"], got["manifest"])
            self.assertEqual(w.chara_file["files"], before["files"])
            self.assertIn("short red hair", w.studio.character["words"])
            # 4. そのキャラクターで描く。模型に渡った言葉に設定の言葉が入る
            seen = []
            real = w.studio.painter.paint

            def spy(prompt, *a, **k):
                seen.append({"prompt": prompt, "negative": getattr(w.studio.painter, "avoid", "") or ""})
                return real(prompt, *a, **k)
            w.studio.painter.paint = spy
            w.entry.setText("walking in a park")
            w.send()
            # 模型に渡った最初の言葉で確かめ、そのあと止める（小さな模型の絵を待たない）
            self.wait(lambda: bool(seen), 900)
            drawn = seen[0]
            for word in ("short red hair", "green eyes", "blue hoodie", "emerald iris", "walking"):
                self.assertIn(word, drawn["prompt"])
            self.assertIn("extra weapons", drawn["negative"])
            w.stop()
            self.wait(lambda: w.thread is None, 600)
        finally:
            self.close(w)


if __name__ == "__main__":
    unittest.main()
