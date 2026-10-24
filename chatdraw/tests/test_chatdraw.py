"""チャットで頼むと絵ができるか。絵の模型と言葉の模型は偽物に替えて、流れだけを確かめる"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.engine import Studio, has_japanese  # noqa: E402


class FakeWords:
    def ready(self):
        return True

    def to_prompt(self, text):
        return "1girl, red scarf" if has_japanese(text) else text


class FakePainter:
    model = "fake"

    def __init__(self):
        self.calls = []

    def ready(self):
        return True

    def paint(self, prompt, seed, on_step=None, **kw):
        from PIL import Image
        self.calls.append((prompt, seed))
        if on_step:
            on_step(1, 1)
        return Image.new("RGB", (64, 96), "white")


class EngineTest(unittest.TestCase):
    def test_request_becomes_saved_image(self):
        with TemporaryDirectory() as d:
            painter = FakePainter()
            said = []
            prompt, path = Studio(FakeWords(), painter, Path(d)).draw("赤いマフラーの子", 7, said.append)
            self.assertEqual(prompt, "1girl, red scarf")
            self.assertTrue(path.exists())
            self.assertEqual(painter.calls, [("1girl, red scarf", 7)])
            self.assertIn("描いています（1/1）", said)

    def test_only_minor_and_sexual_together_is_refused(self):
        from chatdraw.engine import refused
        self.assertFalse(refused("赤いマフラーの騎士の少年、雪の城の前"))
        self.assertFalse(refused("adult woman, nude"))
        self.assertTrue(refused("child, nude"))
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                Studio(FakeWords(), FakePainter(), Path(d)).draw("裸の子ども", 1)

    def test_english_passes_through(self):
        self.assertFalse(has_japanese("knight, snow"))
        self.assertTrue(has_japanese("騎士"))


class WindowTest(unittest.TestCase):
    def test_chat_shows_image(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.entry.setText("雪の城の前の騎士")
            w.send()
            for _ in range(200):
                app.processEvents()
                if w.images:
                    break
                w.thread and w.thread.wait(10)
            self.assertEqual(len(w.images), 1)
            self.assertTrue(Path(w.images[0]).exists())
            item = w.history.item(0)                       # 描いた絵の欄の履歴に、結果と頼みが残る
            self.assertIn("描けました", item.toolTip())          # 詳しい言葉はカーソルを重ねたときに出す
            self.assertIn("雪の城の前の騎士", item.toolTip())
            self.assertEqual(item.text(), "")                     # 見た目は絵だけ
            self.assertEqual(w.activity.state.text(), "待機中")
            self.assertTrue(w.button.isEnabled())


class LayoutTest(unittest.TestCase):
    def test_float_and_arrange(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.show()
        from chatdraw.settings import Settings
        self.assertIsInstance(w.settings, Settings)   # 並びの保存と取り違えない
        w.float_all()
        self.assertTrue(all(d.isFloating() for d, _ in w.panels.values()))
        from PySide6.QtCore import Qt
        d = w.panels["layers"][0]
        self.assertTrue(d.windowFlags() & Qt.WindowMinMaxButtonsHint)
        # 左上の端をつかんで広げたのと同じ動き: 位置と大きさが両方変わる
        d.setGeometry(100, 100, 400, 300)
        d.setGeometry(50, 60, 450, 340)
        self.assertEqual((d.width(), d.height()), (450, 340))
        self.assertLessEqual(abs(d.x() - 50) + abs(d.y() - 60), 4)   # 枠の分だけずれる
        w.arrange()
        from PySide6.QtCore import Qt as _Qt
        self.assertEqual(w.dockWidgetArea(w.panels["chat"][0]), _Qt.RightDockWidgetArea)   # AI は右
        self.assertEqual(w.dockWidgetArea(w.panels["brushes"][0]), _Qt.LeftDockWidgetArea)   # 道具は左
        self.assertFalse(any(d.isFloating() for d, _ in w.panels.values()))
        w.panels["history"][0].toggleViewAction().trigger()
        self.assertTrue(w.panels["history"][0].isHidden())
        title = w.panels["layers"][0].titleBarWidget()
        title.toggle()
        self.assertTrue(w.panels["layers"][0].widget().isHidden())   # 畳むと中身が隠れて見出しだけ残る
        title.toggle()
        self.assertFalse(w.panels["layers"][0].widget().isHidden())


class PreviewTest(unittest.TestCase):
    def test_sketch_lines_keep_ratio_and_colored_lines(self):
        from PIL import Image, ImageDraw
        from chatdraw.engine import sketch_lines
        im = Image.new("RGB", (100, 100), "#f8f4ea")   # 白でない紙
        d = ImageDraw.Draw(im)
        d.line((10, 50, 90, 50), fill="#d03020", width=3)   # 赤い線
        d.line((50, 10, 50, 90), fill="#b0b0b0", width=3)   # 薄い鉛筆
        out = sketch_lines(im, (200, 400))
        self.assertEqual(out.size, (200, 400))
        self.assertEqual(out.getpixel((5, 5)), (0, 0, 0))           # 余白と紙は線なし
        self.assertGreater(out.getpixel((100, 200))[0], 150)         # 交わる所
        self.assertGreater(out.getpixel((40, 200))[0], 200)         # 赤い線も線になる
        self.assertGreater(out.getpixel((100, 150))[0], 200)        # 薄い線も線になる（縦横比を保って中央）
        self.assertEqual(out.getpixel((100, 20)), (0, 0, 0))        # 正方形の外の余り

    def test_latent_preview_shape(self):
        import torch
        from chatdraw.engine import latent_preview
        im = latent_preview(torch.zeros(1, 4, 16, 12))
        self.assertEqual(im.size, (12, 16))

    def test_preview_shows_over_canvas_and_clears(self):
        from PIL import Image
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.show_preview(Image.new("RGB", (25, 25), "red"))
            self.assertTrue(w.canvas.overlay.isVisible())
            w.fail("止めました")
            self.assertFalse(w.canvas.overlay.isVisible())


class SettingsTest(unittest.TestCase):
    def test_dialog_saves_and_applies(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.settings import Settings, SettingsDialog
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            store = QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat)
            st = Settings(store)
            self.assertEqual(st.get("steps"), 24)
            dlg = SettingsDialog(st)
            dlg.inputs["steps"][1].setValue(30)
            dlg.inputs["image_model"][1].setCurrentText("Lykon/dreamshaper-xl-lightning")
            dlg.save()
            self.assertEqual(st.get("steps"), 30)
            self.assertEqual(st.get("image_model"), "Lykon/dreamshaper-xl-lightning")


class DrawTest(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.canvas import Canvas
        QApplication.instance() or QApplication([])
        self.c = Canvas()
        self.c.new_canvas(100, 100)

    def px(self, x, y):
        return self.c.flatten().pixelColor(x, y).name()

    def test_pen_eraser_undo_on_layer(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("red"), 4
        c.snapshot()
        c.stroke(QPointF(10, 50), QPointF(90, 50))
        self.assertEqual(self.px(50, 50), "#ff0000")
        self.assertEqual(c.layers[0].image.pixelColor(50, 50).name(), "#ffffff")   # 背景には描かない
        c.tool = "eraser"
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        self.assertEqual(self.px(50, 50), "#ffffff")   # 消すと下の背景が見える
        c.undo()
        self.assertEqual(self.px(20, 50), "#ffffff")

    def test_layers_visibility_order(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("blue"), 10
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        c.add_layer()
        c.color = QColor("lime")
        c.stroke(QPointF(50, 50), QPointF(50, 50))
        self.assertEqual(self.px(50, 50), "#00ff00")
        c.set_visible(c.current, False)
        self.assertEqual(self.px(50, 50), "#0000ff")
        c.set_visible(c.current, True)
        c.move_layer(-1)
        self.assertEqual(self.px(50, 50), "#0000ff")
        self.assertEqual(len(c.layers), 3)

    def test_brushes_differ(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("black"), 20
        alphas = {}
        for name in ("ペン", "エアブラシ", "鉛筆"):
            c.new_canvas(100, 100)
            c.set_brush(name)
            c.stroke(QPointF(20, 50), QPointF(80, 50))
            alphas[name] = c.layers[1].image.pixelColor(50, 50).alpha()
            edge = c.layers[1].image.pixelColor(50, 58).alpha()
            alphas[name + "の縁"] = edge
        self.assertGreater(alphas["ペン"], 240)
        self.assertLess(alphas["エアブラシ"], alphas["ペン"])          # エアブラシは薄く重ねる
        self.assertLess(alphas["エアブラシの縁"], alphas["ペンの縁"])   # 縁がぼける

    def test_keys_hold_tool_and_resize_brush(self):
        c = self.c
        c.set_tool("pen")
        c.hold("hand")
        self.assertEqual(c.tool, "hand")
        c.release()
        self.assertEqual(c.tool, "pen")
        c.size = 10
        c.resize_brush(1.25)
        self.assertEqual(c.size, 12)
        c.resize_brush(0.8)
        self.assertEqual(c.size, 9)

    def test_undo_keeps_only_touched_layer(self):
        from PySide6.QtCore import QPointF
        c = self.c
        c.snapshot()
        c.stroke(QPointF(10, 10), QPointF(20, 20))
        self.assertEqual(c.undo_stack[-1][0], "one")
        self.assertEqual(c._bytes(c.undo_stack[-1]), 100 * 100 * 4)   # 触った 1 枚の分だけ

    def test_fill_and_eyedropper(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("black"), 3
        c.stroke(QPointF(0, 30), QPointF(99, 30))   # 横線で上下に分ける
        c.color = QColor("#ff8800")
        c.fill(QPointF(50, 10))
        self.assertEqual(self.px(50, 10), "#ff8800")
        self.assertEqual(self.px(50, 80), "#ffffff")   # 線の向こうは塗らない
        c.pick(QPointF(50, 80))
        self.assertEqual(c.color.name(), "#ffffff")

    def drag(self, tool, a, b):
        from PySide6.QtCore import QPointF
        c = self.c
        c.set_tool(tool)
        c._press(QPointF(*a), 1.0)
        c.drag(QPointF(*a), QPointF(*b))
        c.end_drag(QPointF(*a), QPointF(*b))
        c.drag_start = None

    def test_shapes_gradient_and_move(self):
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("red"), 4
        self.drag("line", (10, 10), (90, 10))
        self.assertEqual(self.px(50, 10), "#ff0000")
        self.drag("rect", (20, 30), (80, 70))
        self.assertEqual(self.px(20, 50), "#ff0000")
        self.assertEqual(self.px(50, 50), "#ffffff")        # 線だけ
        c.fill_shapes = True
        self.drag("ellipse", (30, 40), (70, 60))
        self.assertEqual(self.px(50, 50), "#ff0000")        # 塗りつぶし
        c.undo()
        self.assertEqual(self.px(50, 50), "#ffffff")
        self.drag("move", (0, 0), (0, 20))                  # レイヤーを下へ 20 動かす
        self.assertEqual(self.px(50, 30), "#ff0000")
        self.assertEqual(self.px(50, 10), "#ffffff")
        c.color, c.bg_color = QColor("#000000"), QColor("#0000ff")
        c.new_canvas(100, 100)
        self.drag("gradient", (0, 50), (100, 50))
        self.assertLess(c.flatten().pixelColor(5, 50).blue(), 40)
        self.assertGreater(c.flatten().pixelColor(95, 50).blue(), 220)

    def test_selection_limits_painting(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("red"), 6
        self.drag("select", (0, 0), (50, 100))
        self.assertIsNotNone(c.selection)
        c.set_tool("pen")
        c._press(QPointF(10, 50), 1.0)
        c.stroke(QPointF(10, 50), QPointF(90, 50))
        c.end_stroke()
        c.last = None
        self.assertEqual(self.px(30, 50), "#ff0000")
        self.assertEqual(self.px(70, 50), "#ffffff")        # 範囲の外には描かない
        c.set_selection(None)
        c.set_tool("pen")
        c.stroke(QPointF(60, 20), QPointF(90, 20))
        c.select_all()
        c.clear_selection_area()
        self.assertEqual(self.px(70, 20), "#ffffff")        # Delete で中を消す
        c.undo()
        self.assertEqual(self.px(70, 20), "#ff0000")

    def test_blur_softens_edge(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        c = self.c
        c.color, c.size = QColor("black"), 30
        c.stroke(QPointF(50, 0), QPointF(50, 99))
        before = c.layers[1].image.pixelColor(67, 50).alpha()
        c.size = 40
        c.set_tool("blur")
        for _ in range(4):
            c.stroke(QPointF(50, 30), QPointF(50, 70))
        after = c.layers[1].image.pixelColor(67, 50).alpha()
        self.assertGreater(after, before)                   # 縁の外へにじむ


class ColorPanelTest(unittest.TestCase):
    def test_hex_swatch_swap(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QApplication
        from chatdraw.canvas import Canvas
        from chatdraw.colorpanel import ColorPanel
        QApplication.instance() or QApplication([])
        c = Canvas()
        panel = ColorPanel(c)
        panel.hex.setText("#3d7bff")
        panel._hex_entered()
        self.assertEqual(c.color.name(), "#3d7bff")
        c.swap_colors()
        self.assertEqual((c.color.name(), c.bg_color.name()), ("#ffffff", "#3d7bff"))
        self.assertEqual(panel.hex.text(), "#ffffff")
        panel.remember()
        self.assertEqual(panel.recent, ["#ffffff"])


class SetupTest(unittest.TestCase):
    def test_choose_models_writes_settings(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.models import IMAGES, PASS, offered_images, offered_words
        from chatdraw.settings import Settings
        from chatdraw.setup import AUTO, SetupDialog
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            st = Settings(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
            dlg = SetupDialog(st, first=True)
            image, words = dlg.chosen()
            self.assertEqual(image, offered_images()[0])                       # 初めは点のいちばん高い物
            self.assertEqual(words, offered_words()[0])
            for m in IMAGES:                                                    # 確かめていない模型は出さない（取っていなくても確かめた物は出す）
                self.assertEqual(m.repo in dlg.image_radios, m.score > 0)
            from chatdraw.models import WORDS
            low = next(m for m in WORDS if 0 < m.score < PASS)
            self.assertFalse(dlg.words_radios[low.file].parent().isVisibleTo(dlg))   # 推奨だけのときは隠す
            dlg.only_rec.setChecked(False)
            self.assertTrue(dlg.words_radios[low.file].parent().isVisibleTo(dlg))    # 外すと出す
            dlg.image_radios[AUTO].setChecked(True)
            dlg.no_words.setChecked(True)
            dlg.apply()
            self.assertEqual(st.get("image_model"), AUTO)
            self.assertEqual(st.get("words_model"), "")
            self.assertEqual(int(st.store.value("setup_done")), 1)
            again = SetupDialog(st, first=False)                                # 入れ替えの画面は今の選択を出す
            self.assertTrue(again.image_radios[AUTO].isChecked())
            self.assertTrue(again.no_words.isChecked())

    def test_unused_words_model_passes_request_through(self):
        from chatdraw.engine import Words
        self.assertFalse(Words(Path("")).ready())
        self.assertEqual(Words(Path("")).to_prompt("騎士"), "騎士")


class PathsTest(unittest.TestCase):
    def test_shared_llm_folder(self):
        import importlib
        import os
        from unittest import mock
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"LLM_HOME": d}):
            import chatdraw.paths as paths
            paths = importlib.reload(paths)
            try:
                self.assertEqual(paths.GGUF, Path(d) / "gguf")             # 言葉の模型
                self.assertEqual(paths.HUB, Path(d) / "huggingface")       # 絵の模型
                paths.ensure_shared()
                self.assertTrue((Path(d) / "README.txt").exists())
                (Path(d) / "gguf" / "a.gguf").write_bytes(b"x")
                self.assertEqual(paths.find_gguf("a.gguf"), Path(d) / "gguf" / "a.gguf")
                self.assertEqual(paths.llm_target(), Path(d) / "gguf")   # 新しく取る物も共有の置き場へ
            finally:
                os.environ.pop("LLM_HOME")
                importlib.reload(paths)


class UpgradeTest(unittest.TestCase):
    def test_superseded_words_model_switches_without_deleting(self):
        from chatdraw.models import WORDS, successor
        self.assertEqual(successor("/x/qwen2.5-1.5b-instruct-q4_k_m.gguf"), WORDS[0])
        self.assertIsNone(successor("/x/my-own-model.gguf"))     # 利用者が自分で入れた模型はそのまま
        self.assertIsNone(successor(""))

    def test_window_switches_to_successor(self):
        from unittest import mock
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.models import WORDS
        from chatdraw.settings import Settings
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            old = Path(d) / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
            old.write_bytes(b"x")
            new = Path(d) / WORDS[0].file
            new.write_bytes(b"y")
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.settings = Settings(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
            w.settings.set("words_model", str(old))
            with mock.patch("chatdraw.setup.find_gguf", lambda name: Path(d) / name if (Path(d) / name).exists() else None):
                w.upgrade_models()
            self.assertEqual(w.settings.get("words_model"), str(new))
            self.assertTrue(old.exists())                                    # 古い模型は消さない


class MigrateTest(unittest.TestCase):
    def make_old(self, root: Path) -> Path:
        old = root / "Programs" / "CharacterDesigner"
        (old / ".cache" / "gen" / "hf" / "hub" / "models--a--b" / "snapshots").mkdir(parents=True)
        (old / ".cache" / "gen" / "hf" / "hub" / "models--a--b" / "snapshots" / "w.bin").write_bytes(b"w")
        (old / ".cache" / "gen" / "lib").mkdir(parents=True)                 # 取り直せる部品
        (old / ".cache" / "llm").mkdir(parents=True)
        (old / ".cache" / "llm" / "q.gguf").write_bytes(b"q")
        (old / ".cache" / "llm" / "model.gguf").symlink_to("q.gguf")
        (old / "library" / "mine").mkdir(parents=True)
        (old / "library" / "mine" / "a.png").write_bytes(b"p")
        (old / "python").mkdir()
        (old / "python" / "python.exe").write_bytes(b"x")
        return old

    def test_moves_everything_then_removes_old(self):
        from chatdraw.migrate import migrate
        with TemporaryDirectory() as d:
            root = Path(d)
            old = self.make_old(root)
            hub, gguf, works = root / "LLM" / "huggingface", root / "LLM" / "gguf", root / "Pictures"
            self.assertTrue(migrate(old, hub, gguf, works, root / "log.txt"))
            self.assertTrue((hub / "models--a--b" / "snapshots" / "w.bin").exists())   # 絵の模型
            self.assertTrue((gguf / "q.gguf").exists())                                  # 言葉の模型
            self.assertFalse((gguf / "model.gguf").exists())                             # 別名は持っていかない
            self.assertTrue((works / "previous-version" / "library" / "mine" / "a.png").exists())   # 描いた物
            self.assertFalse(old.exists())                                               # 前の版は残さない
            self.assertIn("前の版の場所を消した", (root / "log.txt").read_text(encoding="utf-8"))

    def test_keeps_old_when_something_cannot_move(self):
        from unittest import mock
        from chatdraw import migrate as m
        with TemporaryDirectory() as d:
            root = Path(d)
            old = self.make_old(root)
            with mock.patch.object(m.shutil, "move", side_effect=OSError("使用中")):
                self.assertFalse(m.migrate(old, root / "h", root / "g", root / "w", root / "log.txt"))
            self.assertTrue((old / "library" / "mine" / "a.png").exists())             # 移せないなら何も消さない
            self.assertTrue((old / ".cache" / "llm" / "q.gguf").exists())

    def test_same_model_already_shared_is_not_duplicated(self):
        from chatdraw.migrate import migrate
        with TemporaryDirectory() as d:
            root = Path(d)
            old = self.make_old(root)
            gguf = root / "LLM" / "gguf"
            gguf.mkdir(parents=True)
            (gguf / "q.gguf").write_bytes(b"shared")
            self.assertTrue(migrate(old, root / "LLM" / "huggingface", gguf, root / "Pictures", root / "log.txt"))
            self.assertEqual((gguf / "q.gguf").read_bytes(), b"shared")                 # 共有の物は上書きしない
            self.assertFalse(old.exists())


class ManagerTest(unittest.TestCase):
    def test_list_and_delete_only_what_user_confirms(self):
        from unittest import mock
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication, QMessageBox
        from chatdraw import manager
        from chatdraw.settings import Settings
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            hub, gguf = Path(d) / "huggingface", Path(d) / "gguf"
            (hub / "models--cagliostrolab--animagine-xl-4.0" / "snapshots" / "x").mkdir(parents=True)
            (hub / "models--cagliostrolab--animagine-xl-4.0" / "snapshots" / "x" / "model_index.json").write_text("{}")
            (hub / "models--TencentARC--t2i-adapter-sketch-sdxl-1.0" / "snapshots" / "x").mkdir(parents=True)   # 部品は出さない
            gguf.mkdir()
            (gguf / "Qwen3.5-2B-Q4_K_M.gguf").write_bytes(b"a")
            (gguf / "mine.gguf").write_bytes(b"b")
            with mock.patch.object(manager, "HUB", hub), mock.patch.object(manager, "GGUF", gguf), \
                    mock.patch.object(manager, "OWN_LLM", Path(d) / "none"):
                items = manager.installed()
                self.assertEqual([i.name for i in items], ["Animagine XL 4.0", "Qwen3.5 2B", "mine"])
                st = Settings(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
                st.set("words_model", str(gguf / "mine.gguf"))
                dlg = manager.ModelManager(st)
                self.assertTrue(dlg.in_use(items[2]))                           # 使っている物は消せない
                with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
                    dlg.ask_delete(items[1])
                self.assertTrue((gguf / "Qwen3.5-2B-Q4_K_M.gguf").exists())    # 「いいえ」なら消さない
                with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                    dlg.ask_delete(items[1])
                    dlg.ask_delete(items[0])
                self.assertFalse((gguf / "Qwen3.5-2B-Q4_K_M.gguf").exists())
                self.assertFalse((hub / "models--cagliostrolab--animagine-xl-4.0").exists())
                self.assertTrue((hub / "models--TencentARC--t2i-adapter-sketch-sdxl-1.0").exists())
                with self.assertRaises(ValueError):                            # 置き場の外は消さない
                    manager.delete(manager.Item("words", "x", Path(d) / "other" / "a.gguf", 0, ""))


class ChooseTest(unittest.TestCase):
    def test_auto_picks_from_installed_only(self):
        from chatdraw.choose import choose_image
        from chatdraw.models import IMAGES
        anime, known, fast = IMAGES
        self.assertEqual(choose_image("写実的な街の写真", "", None, [anime, fast])[0], fast)
        self.assertEqual(choose_image("制服の女の子", "", None, [anime, known])[0], known)
        self.assertEqual(choose_image("赤いマフラーの騎士", "", None, [anime, known, fast])[0], anime)
        self.assertEqual(choose_image("写実的な街の写真", "", None, [anime])[0], anime)     # 取っていない物は選ばない
        self.assertIsNone(choose_image("騎士", "", None, [])[0])

    def test_auto_uses_words_model_answer(self):
        from chatdraw.choose import choose_image
        from chatdraw.models import IMAGES

        class Asker(FakeWords):
            def ask(self, system, text, max_tokens=160):
                self.seen = system
                return "2"
        w = Asker()
        m, why = choose_image("騎士", "knight", w, list(IMAGES))
        self.assertEqual(m, IMAGES[1])
        self.assertIn("realistic", w.seen)                                   # 候補の説明を見せて選ばせる

    def test_studio_switches_painter_when_auto(self):
        from unittest import mock
        from chatdraw.models import IMAGES
        with TemporaryDirectory() as d:
            st = Studio(FakeWords(), FakePainter(), Path(d))
            st.image_auto = True
            said = []
            made = []

            class Made(FakePainter):
                def __init__(self, model, steps=24, guidance=5.0):
                    super().__init__()
                    self.model = model
                    made.append(model)
            with mock.patch("chatdraw.choose.installed_images", return_value=[IMAGES[0], IMAGES[2]]), \
                    mock.patch("chatdraw.engine.Painter", Made):
                st.draw("写実的な街の写真", 1, said.append)
            self.assertEqual(made, [IMAGES[2].repo])
            self.assertTrue(any("DreamShaper" in m for m in said))


if __name__ == "__main__":
    unittest.main()
