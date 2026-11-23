"""モード（起動時に選ぶ）・キャラクターデザインのメニュー・一括生成・キャラクターシート・追加資料を、窓から押して最後まで通す。

描くのは試験用の描き手（紙の色で塗るだけ）。最後の 1 本だけ、試験用の小さな SDXL（重みは乱数）を本物の engine.Painter で読んで流す。
見るのは、押した項目が全部動いて結果がファイルと .chara に入ること、design_status の足りない物が減ること、
モードを替えても絵とレイヤーが残ること"""
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

from PIL import Image, ImageDraw  # noqa: E402

from atelier_helpers import app  # noqa: E402

SPEC = {"name": "Akari", "look": "1girl, solo, short red hair, green eyes", "outfit": "blue hoodie, black skirt",
        "eyes": "large round eyes, emerald iris", "personality": "明るい", "role": "配達人", "age": "17",
        "height": "158cm", "backstory": "港町で荷物を運ぶ。", "negative": "extra weapons"}


def figure(size=(256, 384), color=(200, 80, 80)):
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.ellipse((size[0] * 0.38, size[1] * 0.04, size[0] * 0.62, size[1] * 0.2), fill=(245, 205, 175))
    d.rectangle((size[0] * 0.3, size[1] * 0.2, size[0] * 0.7, size[1] * 0.9), fill=color)
    return im


class Painter:
    """試験用の描き手。頼みに FAIL があれば落ちる（一括生成で 1 枚を失敗させる）"""
    model = "fake"

    def __init__(self):
        self.calls = []

    def ready(self):
        return True

    def paint(self, prompt, seed, on_step=None, **kw):
        self.calls.append(("paint", prompt, seed))
        if "FAIL" in prompt:
            raise RuntimeError("試験のための失敗")
        if on_step:
            on_step(1, 1)
        return figure()

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        self.calls.append(("redraw", prompt, seed))
        out = image.copy()
        out.paste(Image.new("RGB", image.size, (250, 250, 250)), (0, 0), mask)
        return out


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
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            w.dirty = False
            w.closing_checked = True
            w.close()
        self.qapp.processEvents()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def window(self, painter=None):
        from atelier.app.main_window import Window
        from atelier.ai.engine import Studio
        from atelier_helpers import FakeWords
        w = Window(Studio(FakeWords(), painter or Painter(), self.d / "out"))
        for k in ("mode/current", "mode/ask", "mode/tour_illustrator", "mode/tour_designer", "mode/tour_logo", "sheet_layout"):
            w.layout_store.remove(k)
        w.show()
        self.qapp.processEvents()
        self.windows.append(w)
        return w

    def wait(self, cond, secs=120):
        end = time.time() + secs
        while time.time() < end and not cond():
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertTrue(cond())

    def idle(self, w, secs=120):
        self.wait(lambda: w.thread is None, secs)

    def acts(self, menu):
        """メニューの項目（区切りを除く）。開くときの作り直しも通す"""
        menu.aboutToShow.emit()
        return {a.text(): a for a in menu.actions() if not a.isSeparator()}


class ModeTest(Base):
    def visible(self, w):
        return [a.text() for a in w.menuBar().actions() if a.isVisible()]

    def test_pick_at_start_remember_and_switch_keeps_layers(self):
        from atelier.app import modes
        w = self.window()
        seen = []

        def ask(dlg):
            seen.append(sorted(dlg.buttons))
            self.assertTrue(all(b.toolTip() for b in dlg.buttons.values()))
            dlg.dont_ask.setChecked(True)
            return "designer"
        # AtelIer は既定ではモードを聞かない。「起動したときにモードを聞く」を入れた人と同じにする
        modes.remember(w.layout_store, "", dont_ask=False)
        self.assertEqual(w.start_mode(ask), "designer")
        self.assertEqual(seen, [sorted(modes.MODES)])
        menus = self.visible(w)
        print(f"\nキャラクターデザイナーのメニュー {len(menus)} 本: {'、'.join(menus)}")
        self.assertIn("キャラクターデザイン", menus)
        self.assertNotIn("加工", menus)
        self.assertNotIn("ロゴ・スタンプ", menus)
        self.assertEqual(len(menus), len(modes.COMMON_MENUS) + 1)
        presets = [w.ai_panel.preset_box.itemAt(i).widget().text() for i in range(w.ai_panel.preset_box.count())]
        self.assertTrue(any("キャラデザ" in t for t in presets) and not any("背景美術" in t for t in presets))
        self.assertTrue(w.mode_tour is not None)   # 初めてのモードは短いツアーを出す
        w.mode_tour.close()
        # 絵とレイヤーを置いてから替える
        w.canvas.add_layer()
        names = [l.name for l in w.canvas.layers]
        before = w.canvas.flatten()
        w.mode_actions["logo"].trigger()
        self.qapp.processEvents()
        menus = self.visible(w)
        print(f"ロゴ・エンブレム・スタンプのメニュー {len(menus)} 本")
        self.assertIn("ロゴ・スタンプ", menus)
        self.assertNotIn("キャラクターデザイン", menus)
        self.assertEqual([l.name for l in w.canvas.layers], names)
        self.assertEqual(w.canvas.flatten(), before)
        self.assertFalse(w.panels["brushes"][0].isVisible())
        w.mode_actions["illustrator"].trigger()
        self.assertIn("加工", self.visible(w))
        self.assertTrue(w.panels["brushes"][0].isVisible())   # 前のモードで隠した欄は戻る
        print(f"イラストレーターのメニュー {len(self.visible(w))} 本")
        # 次の起動: 窓を出さずに覚えたモードで開く
        w2 = self.window()
        w2.layout_store.setValue("mode/current", "designer")
        w2.layout_store.setValue("mode/ask", 0)
        self.assertEqual(w2.start_mode(lambda dlg: self.fail("聞かない設定なのに窓が出た")), "designer")
        self.assertFalse(w2.mode_ask_action.isChecked())


class CharaMenuTest(Base):
    def test_menu_items_are_pressable_without_a_character(self):
        """人物が無くても項目は押せる（前は全部が無効だった）。押すと作るか開くかを聞く"""
        w = self.window()
        acts = self.acts(w.chara_menu)
        for name in ("キャラデザを作る…", "キャラクターを新しく作る…", "キャラクターを開く…", "追加資料", "キャラクターシートを作る",
                     "シートの並び", "キャラクターの一括生成…"):
            self.assertIn(name, acts)
            self.assertTrue(acts[name].isEnabled(), name)
            self.assertTrue(acts[name].toolTip() or acts[name].menu(), name)
        asked = []
        with mock.patch("PySide6.QtWidgets.QMessageBox.exec", lambda box: asked.append(box.text())):
            acts["キャラクターシートを作る"].trigger()
        self.assertTrue(asked)

    def test_every_item_runs_to_the_end(self):
        from character_designer import chara_design as charadesign
        from character_designer import chara_file as charafile
        w = self.window()
        acts = self.acts(w.chara_menu)
        with mock.patch.object(w, "_chara_spec_dialog", lambda init=None: dict(SPEC)):
            acts["キャラクターを新しく作る…"].trigger()
        path = Path(w.chara_file_path)
        self.assertTrue(path.is_file())
        ident = w.chara_id
        b = charadesign.bible()
        missing0 = len(b.design_status(ident)["missing"])
        extra = self.acts(w.chara_extra_menu)
        self.assertEqual(list(extra), [l for _k, l, _t, _f in charadesign.EXTRAS])
        answers = {"髪型差分": [{"id": "pony", "name": "ポニーテール", "tags": "ponytail"},
                               {"id": "bob", "name": "ボブ", "tags": "bob cut"}],
                   "服の差分": [{"id": "casual", "name": "私服", "tags": "white sweater, jeans"}],
                   "持ち物の設定": [{"id": "bag", "name": "鞄", "tags": "messenger bag"}]}
        done = []
        for label, act in extra.items():
            with self.subTest(item=label):
                self.assertTrue(act.isEnabled() and act.toolTip())
                with mock.patch.object(type(w), "_lines_dialog", lambda self, *a, l=label: answers.get(l, [])):
                    w.chara_extra_result = None
                    act.trigger()
                    self.wait(lambda: w.chara_extra_result is not None, 120)
                self.idle(w)
                done.append(label)
        ch = charafile.load(path)
        roles = set(ch["manifest"]["images"])
        for r in ("view-front", "view-left", "view-back", "view-right", "pose-stand", "hairstyle-pony", "outfit-casual",
                  "detail-outfit-1", "detail-item-bag", "detail-eyes", "detail-hair", "detail-height", "expr-smile"):
            self.assertIn(r, roles)
        self.assertFalse([r for r in roles if r.startswith("turn-")])
        st = b.design_status(ident)
        print(f"\n追加資料 {len(done)} 項目を押しました。足りない物 {missing0} 件 → {len(st['missing'])} 件: {st['missing']}")
        self.assertLess(len(st["missing"]), missing0)
        self.assertFalse([m for m in st["missing"] if "四面図" in m or "表情差分" in m or "目の拡大" in m])
        c = b.load("characters", ident)
        self.assertTrue(all(x["name"] and x["value"].startswith("#") for x in c["colors"]))
        # 足りない物を見る
        with mock.patch.object(w, "notify") as note:
            self.acts(w.chara_menu)["足りない物を見る"].trigger()
        self.assertTrue(note.called)
        # シート（並びの型ごとに）
        for layout in charadesign.SHEET_LAYOUTS:
            with self.subTest(layout=layout):
                lay = self.acts(self.acts(w.chara_menu)["シートの並び"].menu())
                lay[layout].trigger()
                self.acts(w.chara_menu)["キャラクターシートを作る"].trigger()
                self.idle(w)
                psd = b.BIBLE / "characters" / f"{ident}-sheet.psd"
                png = psd.with_suffix(".png")
                self.assertTrue(psd.is_file() and png.is_file())
                # 窓は組んだ区画をそのままレイヤーにして開く（このアプリは PSD を読まない）。PSD には同じ枚数の区画を書く
                import struct
                layers = w.canvas.layers
                names = [l.name for l in layers]
                raw = psd.read_bytes()
                self.assertEqual(raw[:4], b"8BPS")
                self.assertEqual(struct.unpack(">h", raw[42:44])[0], len(layers))
                for n in ("背景", "名前と設定", "四面図", "表情差分", "色の見本", "持ち物", "目の拡大", "追加資料"):
                    self.assertIn(n, names)
                with Image.open(png) as im:
                    print(f"シート「{layout}」: {im.size[0]}×{im.size[1]}、レイヤー {len(layers)} 枚、PSD {psd.stat().st_size} バイト")
        self.assertEqual(charafile.load(path)["manifest"]["sheet"], "sheet.psd")
        self.assertIsNotNone(charadesign.ja_font_path())

    def test_old_turn_names_still_read(self):
        """前の版の turn-* の絵も、シートと資料で今の名前（view-*）として読む"""
        from character_designer import chara_design as charadesign
        c = charadesign.save_character("old", "1girl", figure())
        b = charadesign.bible()
        for role in ("turn-front", "turn-side", "turn-back"):
            charadesign._add(b, c["id"], role, figure())
        self.assertTrue({"view-front", "view-left", "view-back"} <= set(charadesign.images_of(c["id"])))
        names = [l.name for l in charadesign.compose_sheet(c["id"])["layers"]]
        self.assertIn("三面図", names)


class BatchTest(Base):


    def test_characters_batch(self):
        from character_designer import chara_file as charafile
        w = self.window()
        paths = []
        for n in ("Aoi", "Ren"):
            ch = charafile.new(n, "1girl, " + n.lower(), "coat", ident=n.lower())
            paths.append(str(charafile.save(ch, self.d / f"{n}.chara")))
        (self.d / "broken.chara").write_text("x")
        acts = self.acts(w.chara_menu)
        with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames", lambda *a, **k: (paths + [str(self.d / "broken.chara")], "")):
            acts["キャラクターの一括生成…"].trigger()
        self.wait(lambda: getattr(w, "chara_batch_result", None) is not None, 300)
        res = w.chara_batch_result
        print(f"\nキャラクターの一括生成: {len(res['done'])}/{res['total']} 人、失敗 {res['failed']}")
        self.assertEqual(len(res["done"]), 2)
        self.assertEqual(len(res["failed"]), 1)
        for p in paths:
            roles = charafile.load(p)["manifest"]["images"]
            self.assertTrue({"view-front", "view-left", "view-back", "expr-smile"} <= set(roles))
        self.idle(w)


def _tiny():
    from atelier_helpers import TINY, tiny_ready
    return TINY if tiny_ready() else None


@unittest.skipUnless(_tiny(), "試験用の小さな SDXL が取れません")
class RealModelTest(Base):
    def test_extras_and_sheet_with_tiny_sdxl(self):
        from character_designer import chara_design as charadesign
        from character_designer import chara_file as charafile
        from atelier.models import catalog as models
        from atelier.ai.engine import Painter as Real
        from atelier.models.catalog import FILES, ImageModel
        tiny = ImageModel(_tiny(), "試験用の小さな SDXL", "", "", 0.1, 2, 5.0, files=FILES["bin"], family="sdxl", score=0)
        p = mock.patch.object(models, "IMAGES", models.IMAGES + (tiny,))
        p.start()
        self.patches.append(p)
        w = self.window(Real(_tiny(), steps=2, size=(256, 256)))
        with mock.patch.object(w, "_chara_spec_dialog", lambda init=None: dict(SPEC)):
            w.charafile_new()
        t0 = time.time()
        for key in ("turnaround", "eyes", "colors"):
            w.chara_extra_result = None
            self.assertTrue(w.chara_extra(key))
            self.wait(lambda: w.chara_extra_result is not None, 1800)
            self.idle(w, 600)
        out = w.chara_sheet_psd()
        self.assertTrue(Path(out).is_file() and Path(out).with_suffix(".png").is_file())
        roles = charafile.load(w.chara_file_path)["manifest"]["images"]
        print(f"\n小さな SDXL: 三面図・目の拡大・色の指定・シートを {time.time() - t0:.0f} 秒で通しました（絵 {len(roles)} 枚）")
        self.assertTrue({"view-front", "view-left", "view-back", "detail-eyes"} <= set(roles))
        text = "1girl, red scarf\nknight, snow"
        with mock.patch.object(type(w), "_batch_dialog", lambda self: (text, 1, 1, None)):
            w.batch_draw()
        self.wait(lambda: getattr(w, "batch_result", None) is not None, 1800)
        print(charadesign.__name__, __import__("atelier.ai.batch", fromlist=["x"]).summary(w.batch_result))
        self.idle(w, 600)


if __name__ == "__main__":
    unittest.main()
