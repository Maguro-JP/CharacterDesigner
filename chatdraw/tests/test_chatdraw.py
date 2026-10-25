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
from PySide6.QtCore import Qt  # noqa: E402
import chatdraw.motion  # noqa: E402

chatdraw.motion.MOTION = False   # 試験は動きを切って、結果だけを見る（動きは MotionTest で見る）


class FakeWords:
    def ready(self):
        return True

    def to_prompt(self, text, tags=True):
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
        self.kw = kw
        if on_step:
            on_step(1, 1)
        return Image.new("RGB", (64, 96), "white")

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        """直す所を、紙と同じ色で塗る（本物は模型で描き直す。崩れが出ないので確かめは 1 回で通る）"""
        from PIL import Image
        self.calls.append(("redraw", prompt, seed))
        self.kw = kw
        out = image.copy()
        out.paste(Image.new("RGB", image.size, "#ffffff"), (0, 0), mask)
        return out


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
            for _ in range(400):
                app.processEvents()
                if w.images and not w.thread:   # 描き終わり（finish）まで待つ。1 枚できた直後は結果の言葉がまだ付いていない
                    break
                w.thread and w.thread.wait(10)
            self.assertEqual(len(w.images), 1)
            self.assertTrue(Path(w.images[0]).exists())
            item = w.history.item(0)                       # 描いた絵の欄の履歴に、結果と頼みが残る
            self.assertIn("描けました", item.toolTip())          # 詳しい言葉はカーソルを重ねたときに出す
            self.assertIn("雪の城の前の騎士", item.toolTip())
            self.assertEqual(item.text(), "")                     # 見た目は絵だけ
            self.assertEqual(w.activity.state.text(), "待機中")
            self.assertFalse(w.panels["progress"][0].isHidden())         # 描き終わった直後は結果が読めるよう出しておく
            w.hide_progress_if_idle(0)
            for _ in range(20):
                app.processEvents()
            self.assertFalse(w.panels["progress"][0].isHidden())         # 時間がたっても隠さない（消えると状態が分からなかった）
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
        # おすすめの配置: 左に手で描く道具、右の上に表示・中に AI・下に履歴、真ん中の上に進み・下にチャット
        area = lambda k: w.dockWidgetArea(w.panels[k][0])
        for k in ("color", "brushes", "layers"):
            self.assertEqual(area(k), _Qt.LeftDockWidgetArea)
        for k in ("view", "chat", "history"):
            self.assertEqual(area(k), _Qt.RightDockWidgetArea)
        self.assertEqual(area("progress"), _Qt.TopDockWidgetArea)
        self.assertFalse(w.panels["progress"][0].isHidden())            # 進みは描いていなくても出しておく（消えると状態が分からなかった）
        self.assertEqual(area("talk"), _Qt.BottomDockWidgetArea)
        ys = [w.panels[k][0].y() for k in ("view", "chat", "history")]
        self.assertEqual(ys, sorted(ys))                                 # 右は上から表示・AI・履歴
        self.assertEqual(w.corner(_Qt.BottomLeftCorner), _Qt.LeftDockWidgetArea)   # 上下の欄は真ん中だけ
        w.panels["history"][0].toggleViewAction().trigger()             # 欄の帯のアイコンで隠す・出す
        self.assertTrue(w.panels["history"][0].isHidden())
        w.panels["history"][0].toggleViewAction().trigger()
        self.assertFalse(w.panels["history"][0].isHidden())
        self.assertIn(w.panels["history"][0].toggleViewAction(), w.panel_bar.actions())
        w.place_bar(w.panel_bar, _Qt.BottomToolBarArea)                 # 帯は下にも置ける
        self.assertEqual(w.toolBarArea(w.panel_bar), _Qt.BottomToolBarArea)
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
            for m in IMAGES:                                                    # 一覧の模型はすべて札がある（推奨だけ表示を外すと選べる）
                self.assertIn(m.repo, dlg.image_radios)
            untested = next(m for m in IMAGES if m.score <= 0)
            self.assertFalse(dlg.image_radios[untested.repo].parent().isVisibleTo(dlg))   # 初めは推奨だけ
            low = next((m for m in IMAGES if 0 < m.score < PASS), None)
            if low is not None:
                self.assertFalse(dlg.image_radios[low.repo].parent().isVisibleTo(dlg))   # 推奨だけのときは隠す
                dlg.only_rec.setChecked(False)
                self.assertTrue(dlg.image_radios[low.repo].parent().isVisibleTo(dlg))    # 外すと出す
            self.assertFalse(hasattr(dlg, "words_radios"))                     # 言葉の模型は選ばせない
            dlg.image_radios[AUTO].setChecked(True)
            dlg.apply()
            self.assertEqual(st.get("image_model"), AUTO)
            self.assertTrue(st.get("words_model").endswith(offered_words()[0].file))   # いちばん点の高い物を使う
            self.assertEqual(int(st.store.value("setup_done")), 1)
            again = SetupDialog(st, first=False)                                # 入れ替えの画面は今の選択を出す
            self.assertTrue(again.image_radios[AUTO].isChecked())

    def test_unused_words_model_passes_request_through(self):
        from chatdraw.engine import Words
        self.assertFalse(Words(Path("")).ready())
        # 言葉の模型が無いときも、日本語をそのまま渡さず、表で拾った語で描く（そのまま渡すと全く違う絵が出た）
        self.assertEqual(Words(Path("")).to_prompt("騎士"), "knight, armor")
        self.assertEqual(Words(Path("")).to_prompt("ぴょぴょ"), "ぴょぴょ")   # 拾えない時だけそのまま


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


class TabsTest(unittest.TestCase):
    def test_panels_switch_with_tabs_and_history_goes_back(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        self.assertEqual([w.ai_tabs.tabText(i) for i in range(w.ai_tabs.count())], ["描き方"])
        self.assertEqual([w.view_tabs.tabText(i) for i in range(w.view_tabs.count())], ["全体", "参考画像"])
        r = w.ribbon
        self.assertEqual([r.tabText(i) for i in range(r.count())], ["ホーム", "描く", "AI", "表示"])
        r._clicked(r.currentIndex())                                   # 開いているタブを押すと畳む
        self.assertTrue(r.collapsed and not r.currentWidget().isVisibleTo(r))
        r._clicked(0)                                                  # もう一度押すと広げる
        self.assertFalse(r.collapsed)
        self.assertEqual([w.brush_tabs.tabText(i) for i in range(w.brush_tabs.count())], ["ブラシ", "設定"])
        self.assertEqual([w.color_panel.tabs.tabText(i) for i in range(2)], ["カラー", "パレット"])
        tabs = w.activity.tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["描いた絵", "操作"])
        c = w.canvas
        c.new_canvas(100, 100)
        c.color, c.size = QColor("red"), 4
        for y in (20, 50):
            c.snapshot()
            c.stroke(QPointF(10, y), QPointF(90, y))
        ops = w.activity.ops
        self.assertEqual([ops.item(i).text() for i in range(ops.count())], ["始め", "ペン", "ペン"])
        ops.setCurrentRow(1)                                   # 1 本目のあとまで戻る
        px = lambda y: c.flatten().pixelColor(50, y).name()
        self.assertEqual((px(20), px(50)), ("#ff0000", "#ffffff"))
        ops.setCurrentRow(2)                                   # また進める
        self.assertEqual(px(50), "#ff0000")


class TourTest(unittest.TestCase):
    def test_tour_walks_all_steps_and_remembers(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.resize(1400, 900)
        w.show()
        w.layout_store.remove("tour_done")
        w.maybe_tour()
        t = w.tour
        self.assertTrue(t.isVisible())
        n = len(t.steps)
        for i in range(n):
            for _ in range(5):
                app.processEvents()
            t._place()
            self.assertEqual(t.count.text(), f"{i + 1} / {n}")
            hole = t.hole()
            small = hole is not None and hole.width() * hole.height() < w.width() * w.height() * 0.4
            if small:                                                    # 説明の札は抜いた所に重ならない（大きな所は中に置く）
                self.assertFalse(hole.intersects(t.card.geometry()), (i, hole, t.card.geometry()))
            t.next.click()
        self.assertEqual(int(w.layout_store.value("tour_done")), 1)
        w.maybe_tour()                                                   # 2 回目は出さない
        self.assertIs(w.tour, t)


class StatusTest(unittest.TestCase):
    def test_status_bar_bottom_band_and_notice(self):
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.notice import Notice
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.resize(1400, 900)
        w.show()
        w.arrange()
        w.canvas.new_canvas(300, 200)
        self.assertEqual(w.st_size.text(), "300×200")
        w.canvas.moved.emit(12, 34)
        self.assertEqual(w.st_pos.text(), "12, 34")
        w.tool_actions["eraser"].trigger()
        self.assertEqual(w.st_tool.text(), "消しゴム")
        self.assertEqual(w.toolBarArea(w.bottom_bar), _Qt.BottomToolBarArea)   # 下の帯
        w.zoom_slider.setValue(200)
        self.assertAlmostEqual(w.canvas.zoom(), 2.0, places=2)
        w.zoom_label.click()                                                     # 押すと全体表示
        self.assertNotEqual(w.zoom_label.text(), "200%")
        n = w.notify("保存しました", "ok")
        m = w.notify("描けました", "ok")
        self.assertTrue(n.isVisible() and m.isVisible())
        self.assertLess(m.y(), n.y())                                            # 新しい知らせは上に積む
        self.assertTrue(n.geometry().right() <= w.width())


class MotionTest(unittest.TestCase):
    def test_panels_move_anywhere_and_animate(self):
        import time
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QApplication
        from chatdraw import motion
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.resize(1400, 900)
        w.show()
        w.arrange()
        for k in ("chat", "layers", "history"):                        # 右の欄も下に置ける
            w.move_panel(w.panels[k][0], _Qt.BottomDockWidgetArea)
            self.assertEqual(w.dockWidgetArea(w.panels[k][0]), _Qt.BottomDockWidgetArea)
        menu = w.panels["layers"][0].titleBarWidget().place_menu()   # 見出しの「⋯」から選べる
        self.assertIn("下に置く", [a.text() for a in menu.actions()])
        motion.MOTION = True
        try:
            w.panels["brushes"][0].show()
            title = w.panels["color"][0].titleBarWidget()
            title.toggle()                                               # 畳むと高さが動いて縮む
            # 動きは時計で進むので、機械が忙しいと 1 秒では終わらなかった。畳み終わるまで（最長 8 秒）待つ
            end = time.time() + 8
            while time.time() < end and not (w.panels["color"][0].height() < 60 and w.panels["color"][0].widget().isHidden()):
                app.processEvents()
            self.assertLess(w.panels["color"][0].height(), 60)
            self.assertTrue(w.panels["color"][0].widget().isHidden())
            n = w.notify("描けました", "ok")
            self.assertIsNotNone(n.graphicsEffect())                     # 出る途中は透明から見えるまで動く
            end = time.time() + 1
            while time.time() < end:
                app.processEvents()
            self.assertIsNone(n.graphicsEffect())
        finally:
            motion.MOTION = False


class LayoutsTest(unittest.TestCase):
    def test_presets_align_split_save_export(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QApplication
        from chatdraw import layouts as L
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.resize(1500, 900)
        w.show()
        w.arrange()
        area = lambda k: w.dockWidgetArea(w.panels[k][0])
        for name, fn in L.PRESETS.items():                                # 決まった配置はどれも当てられる
            fn(w)
            app.processEvents()
            self.assertTrue(L.visible(w) or name == "絵だけ", name)
        L.drawing_focus(w)
        self.assertTrue(w.panels["talk"][0].isHidden())
        L.recommended(w)                                                   # おすすめ: リボンを出さず、道具はよく使うものだけ
        self.assertTrue(w.ribbon_bar.isHidden())
        self.assertTrue(w.tool_actions["pen"].isVisible() and not w.tool_actions["gradient"].isVisible())
        L.creator(w)                                                       # クリエイター向け: リボンと全部の道具
        self.assertFalse(w.ribbon_bar.isHidden())
        self.assertTrue(w.tool_actions["gradient"].isVisible())
        L.ai_focus(w)                                                      # AI 特化: 手で描く道具は出さず、赤ペンだけ出す
        self.assertTrue(w.tool_actions["redpen"].isVisible() and not w.tool_actions["pen"].isVisible())
        self.assertTrue(w.panels["color"][0].isHidden())
        L.canvas_only(w)
        self.assertEqual(L.visible(w), [])
        L.recommended(w)
        L.align(w, "left")                                                 # 左に寄せる
        self.assertTrue(all(area(k) == _Qt.LeftDockWidgetArea for k in L.visible(w)))
        L.align(w, "right")
        self.assertTrue(all(area(k) == _Qt.RightDockWidgetArea for k in L.visible(w)))
        L.split(w, 3)                                                      # 3 等分: 左右の欄が幅の 1/3 前後
        app.processEvents()
        left = [w.panels[k][0] for k in L.visible(w) if area(k) == _Qt.LeftDockWidgetArea][0]
        self.assertGreater(left.width(), 1500 // 3 - 120)
        with TemporaryDirectory() as d:
            store = QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat)
            L.recommended(w)
            app.processEvents()
            L.save(w, store, "いつもの")
            self.assertEqual(L.saved_names(store), ["いつもの"])
            L.drawing_focus(w)
            app.processEvents()
            self.assertTrue(L.load(w, store, "いつもの"))                  # 自分の配置に戻せる
            app.processEvents()
            self.assertFalse(w.panels["talk"][0].isHidden())
            L.export(w, str(Path(d) / "mine.json"), "いつもの")
            L.drawing_focus(w)
            self.assertEqual(L.import_(w, str(Path(d) / "mine.json")), "いつもの")   # 書き出した配置を読み込める
            app.processEvents()
            self.assertFalse(w.panels["talk"][0].isHidden())
            (Path(d) / "bad.json").write_text("{}")
            self.assertIsNone(L.import_(w, str(Path(d) / "bad.json")))
            L.remove(store, "いつもの")
            self.assertEqual(L.saved_names(store), [])


class FeatureTourTest(unittest.TestCase):
    def test_every_feature_has_a_tour_shown_once_on_first_use(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw import tours
        from chatdraw.app import TOOLS, Window
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.layout_store = QSettings(str(Path(d) / "l.ini"), QSettings.IniFormat)
            w.resize(1400, 900)
            w.show()
            w.arrange()
            cat = tours.catalog(w)
            for key, _l, _s in TOOLS:                                     # すべての道具とすべての欄に案内がある
                if key:
                    self.assertIn(key, cat)
            for key in w.panels:
                self.assertIn(key, cat)
            for key in ("layout_save", "layout_export", "draw", "rough", "model", "manager"):
                self.assertIn(key, cat)
            w.tool_actions["blur"].trigger()                              # 初めて使うと出る
            self.assertTrue(w.tour.isVisible())
            self.assertIn("ぼかし", w.tour.title.text())
            w.tour.finish()
            app.processEvents()
            first = w.tour
            w.tool_actions["blur"].trigger()                              # 2 回目は出さない
            self.assertIs(w.tour, first)
            ran = []
            self.assertTrue(w.feature_tour("layout_save", lambda: ran.append(1)))
            self.assertEqual(ran, [])                                     # 案内を閉じてから保存の窓を開く
            w.tour.next.click()
            self.assertEqual(ran, [1])
            w.layout_store.setValue("feature_tours", 0)                   # 出さない設定
            self.assertFalse(w.feature_tour("layout_export", lambda: ran.append(2)))
            self.assertEqual(ran, [1, 2])
            w.layout_store.setValue("feature_tours", 1)
            tours.reset(w)
            self.assertFalse(tours.seen(w, "blur"))                        # もう一度出るようにできる


class FitSizeTest(unittest.TestCase):
    def test_rough_size_keeps_canvas_ratio(self):
        from chatdraw.app import fit_size
        w, h = fit_size(512, 768)
        self.assertEqual((w % 64, h % 64), (0, 0))
        self.assertAlmostEqual(w / h, 512 / 768, delta=0.03)
        self.assertLess(abs(w * h - 832 * 1216) / (832 * 1216), 0.1)


class ChooseTest(unittest.TestCase):
    def test_auto_picks_from_installed_only(self):
        from chatdraw.choose import choose_image
        from chatdraw.models import image_model
        anime = image_model("cagliostrolab/animagine-xl-4.0")
        known = image_model("OnomaAIResearch/Illustrious-xl-early-release-v0")
        fast = image_model("Lykon/dreamshaper-xl-lightning")
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
            from chatdraw.models import image_model
            fast = image_model("Lykon/dreamshaper-xl-lightning")
            with mock.patch("chatdraw.choose.installed_images", return_value=[IMAGES[0], fast]), \
                    mock.patch("chatdraw.engine.Painter", Made):
                st.draw("写実的な街の写真", 1, said.append)
            self.assertEqual(made, [fast.repo])
            self.assertTrue(any("DreamShaper" in m for m in said))


if __name__ == "__main__":
    unittest.main()


class CommandsTest(unittest.TestCase):
    """チャットから全部の機能を AI に頼めるか"""
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        self.w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))

    def test_every_tool_panel_preset_has_command(self):
        from chatdraw import commands, layouts
        names = {c.name for c in commands.COMMANDS}
        for key in self.w.tool_actions:
            self.assertIn(key, names)
        for key in self.w.panels:
            self.assertIn(f"show_{key}", names)
        presets = {n for c in commands.COMMANDS if c.name.startswith("layout_")
                   for n in layouts.PRESETS if c.say.startswith(n.replace(" ", "")[:2])}
        self.assertEqual(presets, set(layouts.PRESETS))

    def test_handle_runs_and_draw_passes(self):
        from chatdraw import commands
        self.assertEqual(commands.handle(self.w, "消しゴムにして"), "消しゴムにしました")
        self.assertEqual(self.w.canvas.tool, "eraser")
        self.assertIsNone(commands.handle(self.w, "赤いスカーフの女の子を描いて"))

    def test_send_does_not_draw_for_command(self):
        self.w.entry.setText("スポイトにして")
        self.w.send()
        self.assertEqual(self.w.canvas.tool, "eyedropper")
        self.assertIsNone(self.w.thread)


class ThemeTest(unittest.TestCase):
    """テーマを替えてもアイコンが地に溶けず、AI プリセットと画風が描く言葉に届くか"""
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        self.app = QApplication.instance() or QApplication([])
        self.w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))

    def test_every_theme_icons_contrast(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor, QIcon
        from chatdraw import themes
        from chatdraw.icons import icon
        for name in themes.THEMES:
            t = self.w.set_theme(name) or themes.current
            img = icon("pen").pixmap(QSize(24, 24), QIcon.Normal, QIcon.Off).toImage()
            ink = [QColor(img.pixel(x, y)) for x in range(img.width()) for y in range(img.height()) if QColor.fromRgba(img.pixel(x, y)).alpha() > 200]
            self.assertTrue(ink, name)
            bg = QColor(t["bar"])
            diff = max(abs(c.lightness() - bg.lightness()) for c in ink)
            self.assertGreater(diff, 100, f"{name}: アイコンと帯の明るさの差 {diff}")
        self.w.set_theme(themes.DEFAULT)

    def test_ai_preset_and_style_reach_prompt(self):
        p = self.w.ai_panel
        self.assertTrue(p.apply_name("ラフを清書"))
        self.assertEqual(self.w.mode.currentIndex(), 1)
        self.assertEqual(self.w.strength.value(), 100)
        p.set_style("水彩")
        self.assertIn("watercolor", p.style_tags())
        p.save_current("試験の設定")
        self.assertIn("試験の設定", p.own_presets())
        self.w.layout_store.remove("ai_presets/試験の設定")

    def test_commands_for_theme_style_preset(self):
        from chatdraw import commands
        self.assertEqual(commands.handle(self.w, "画風を水彩にして"), "画風を「水彩」にしました")
        self.assertEqual(self.w.ai_panel.style, "水彩")
        self.assertEqual(commands.handle(self.w, "キャラデザにして"), "AI プリセット「キャラデザ」にしました。描きたい絵を書いてください")
        self.assertIsNone(commands.handle(self.w, "自然の中の少女を描いて"))
        commands.handle(self.w, "テーマをペーパーにして")
        from chatdraw import themes
        self.assertEqual(themes.current["name"], "ペーパー")
        self.w.set_theme(themes.DEFAULT)


class ThemeLookTest(unittest.TestCase):
    """テーマの模様・演出・自分のテーマ"""
    def setUp(self):
        from tempfile import mktemp
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        self.app = QApplication.instance() or QApplication([])
        self.w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)

    def test_every_pattern_paints_and_moves(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter
        from chatdraw import backdrop, themes
        for kind in backdrop.PATTERNS:
            t = themes.finish({"pattern": kind})
            frames = []
            for phase in (0.0, 1.5):
                img = QImage(200, 120, QImage.Format_RGB32)
                p = QPainter(img)
                backdrop.paint(p, QRect(0, 0, 200, 120), t, phase)
                p.end()
                frames.append(img)
            if kind in ("stars", "grid", "stripes", "neongrid", "gears", "leaves", "sunburst"):
                self.assertNotEqual(frames[0], frames[1], f"{kind} が動かない")

    def test_every_preset_has_pattern_and_gradient(self):
        from chatdraw import themes
        pats = {themes.THEMES[n]["pattern"] for n in themes.THEMES}
        self.assertEqual(len(pats), len(themes.THEMES))                 # テーマごとに模様が違う
        self.assertIn("stop:1 {bar2}", themes.TEMPLATE)

    def test_custom_theme_save_apply_remove(self):
        from chatdraw import themes
        from chatdraw.themeedit import ThemeEditor
        ed = ThemeEditor(self.w)
        ed.set("a1", "#00ff00")
        self.assertEqual(themes.current["a1"], "#00ff00")              # 替えるとその場で当たる
        ed.reject()
        self.assertEqual(themes.current["name"], themes.DEFAULT)      # やめると元に戻る
        ed = ThemeEditor(self.w)
        ed.set("a1", "#00ff00")
        ed.set("pattern", "gears")
        ed.save("緑の歯車")
        self.assertEqual(themes.current["name"], "緑の歯車")
        self.assertEqual(themes.current["pattern"], "gears")
        themes.CUSTOM.clear()
        themes.load_custom(self.w.layout_store)                          # 次に起動しても残る
        self.assertIn("緑の歯車", themes.CUSTOM)
        self.w.set_theme(themes.DEFAULT)
        themes.remove_custom(self.w.layout_store, "緑の歯車")
        self.assertNotIn("緑の歯車", themes.all_names())


def wait_idle(app, w, limit: float = 300.0):
    """裏の処理が終わる（w.thread が None になる）まで待つ"""
    import time as _t
    end = _t.time() + limit
    while w.thread is not None and _t.time() < end:
        app.processEvents()
        w.thread and w.thread.wait(10)
    app.processEvents()


class FixAndBatchTest(unittest.TestCase):
    """赤ペン先生・範囲の描き直し・枚数・種・参考画像・拡大"""
    def setUp(self):
        from tempfile import mkdtemp, mktemp
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        self.app = QApplication.instance() or QApplication([])
        self.dir = Path(mkdtemp())
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.dir))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)
        self.w.canvas.new_canvas(200, 160)

    def circle(self, cx, cy, r):
        import math
        from PySide6.QtCore import QPointF
        pen = self.w.canvas.redpen
        pen.begin(QPointF(cx + r, cy))
        for k in range(1, 41):
            a = 2 * math.pi * k / 40
            pen.add(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        pen.end()

    def test_notes_by_number(self):
        from chatdraw.redpen import notes
        self.assertEqual(notes("1: 手を直して 2: 帽子を青に", 2), ["手を直して", "帽子を青に"])
        self.assertEqual(notes("①指を5本に②目を大きく", 2), ["指を5本に", "目を大きく"])
        self.assertEqual(notes("もっときれいに", 2), ["もっときれいに", "もっときれいに"])

    def test_circle_mask_fills_inside(self):
        self.circle(60, 60, 30)
        m = self.w.canvas.redpen.masks()[0]
        self.assertEqual(m.pixelColor(60, 60).value(), 255)          # 囲んだ中も直す所
        self.assertEqual(m.pixelColor(150, 140).value(), 0)          # 外は直さない

    def test_redpen_fix_makes_layer_and_clears_marks(self):
        from PIL import Image
        self.circle(50, 50, 20)
        self.circle(150, 100, 20)
        self.assertEqual(self.w.mode.currentIndex(), 0)
        self.w.canvas.marked.emit()
        self.assertEqual(self.w.mode.currentIndex(), 2)              # 赤ペンで囲むと「直す」になる
        layers = len(self.w.canvas.layers)
        self.w.entry.setText("1: 手を直して 2: 帽子を青に")
        self.w.send()
        wait_idle(self.app, self.w)
        fixes = [c for c in self.painter.calls if c[0] == "redraw"]
        self.assertEqual(len(fixes), 2)                               # 印ごとに 1 回ずつ直す
        self.assertEqual(len(self.w.canvas.layers), layers + 1)      # 直した所は新しいレイヤー
        self.assertEqual(self.w.canvas.redpen.marks, [])             # 直したら印は消える
        layer = Image.open(self.w.images[-1])
        self.assertEqual(layer.size, (200, 160))                      # 絵と同じ大きさで重ね、
        self.assertEqual(layer.getpixel((5, 150))[3], 0)              # 直していない所は透かす（下のレイヤーを隠さない）
        self.assertEqual(layer.getpixel((50, 50))[3], 255)

    def test_fix_without_marks_does_nothing(self):
        self.w.mode.setCurrentIndex(2)
        self.w.entry.setText("直して")
        self.w.send()
        self.assertIsNone(self.w.thread)
        self.assertEqual(self.painter.calls, [])

    def test_selection_fix(self):
        from PySide6.QtCore import QRect
        self.w.canvas.set_selection(QRect(10, 10, 40, 40))
        self.w.mode.setCurrentIndex(2)
        self.w.entry.setText("笑顔に")
        self.w.send()
        wait_idle(self.app, self.w)
        self.assertEqual([c for c in self.painter.calls if c[0] == "redraw"], [("redraw", "1girl, red scarf", self.w.ai_panel.seed.value() + 1)])

    def test_batch_seed_meta_and_redo(self):
        import json
        self.w.ai_panel.set_count(4)
        self.w.entry.setText("雪の城の前の騎士")
        self.w.send()
        wait_idle(self.app, self.w)
        seeds = [c[1] for c in self.painter.calls]
        self.assertEqual(len(seeds), 4)
        self.assertEqual(seeds, list(range(seeds[0], seeds[0] + 4)))  # 種は続けて使う
        self.assertEqual(self.w.history.count(), 4)
        meta = json.loads(Path(self.w.images[0]).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual((meta["text"], meta["seed"]), ("雪の城の前の騎士", seeds[0]))
        self.w.entry.clear()
        self.w.redo_from(self.w.images[2])                            # 履歴から同じ設定に戻す
        self.assertEqual(self.w.entry.text(), "雪の城の前の騎士")
        self.assertTrue(self.w.ai_panel.seed_lock.isChecked())
        self.painter.calls.clear()
        self.w.send()
        wait_idle(self.app, self.w)
        self.assertEqual([c[1] for c in self.painter.calls], [seeds[2]])   # 同じ種で描き直せる

    def test_count_from_words(self):
        self.w.entry.setText("猫耳の少女を2枚")
        self.w.send()
        wait_idle(self.app, self.w)
        self.assertEqual(len(self.painter.calls), 2)

    def test_reference_asks_before_fetching(self):
        """参考画像の部品が無ければ、取る前に大きさを出して聞く。断れば参考画像なしで描く"""
        from unittest import mock
        from PIL import Image
        from PySide6.QtWidgets import QMessageBox
        ref = self.dir / "ref.png"
        Image.new("RGB", (32, 32), "blue").save(ref)
        self.w.reference.load(str(ref))
        self.w.ai_panel.use_ref.setChecked(True)
        self.painter.reference_ready = lambda: False
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No) as asked:
            self.w.entry.setText("雪の城の前の騎士")
            self.w.send()
            wait_idle(self.app, self.w)
        self.assertTrue(asked.called)
        self.assertNotIn("reference", self.painter.kw)

    def test_reference_reaches_painter(self):
        from PIL import Image
        ref = self.dir / "ref.png"
        Image.new("RGB", (32, 32), "blue").save(ref)
        self.w.reference.load(str(ref))
        self.w.ai_panel.use_ref.setChecked(True)
        self.w.ai_panel.ref_scale.setValue(80)
        self.w.entry.setText("雪の城の前の騎士")
        self.w.send()
        wait_idle(self.app, self.w)
        self.assertEqual(self.painter.kw["reference"].getpixel((0, 0)), (0, 0, 255))
        self.assertAlmostEqual(self.painter.kw["ref_scale"], 0.8)

    def test_seams_found_and_repaired(self):
        """直した縁に継ぎ目が出たら見つけ、その所だけを描き直して確かめ直す"""
        from PIL import Image
        from chatdraw.engine import Studio as RealStudio, seams
        before = Image.new("RGB", (120, 100), "white")
        m = Image.new("L", before.size, 0)
        m.paste(255, (30, 30, 90, 70))
        broken = before.copy()
        broken.paste((40, 40, 40), (30, 30, 90, 70))
        self.assertIsNotNone(seams(before, broken, m))               # 縁にくっきりした段差
        self.assertIsNone(seams(before, before, m))                  # 変わらなければ継ぎ目なし

        class Seamy(FakePainter):
            def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
                self.calls.append(("redraw", prompt, seed, mask.getbbox()))
                out = image.copy()
                out.paste((40, 40, 40) if len(self.calls) == 1 else (250, 250, 250), (0, 0), mask)
                return out
        painter = Seamy()
        said = []
        RealStudio(FakeWords(), painter, self.dir).fix(before, [(m, "笑顔に")], 5, on_status=said.append)
        self.assertTrue(any("継ぎ目を消しています" in t for t in said))   # まず間違えた線だけを元に戻し、
        self.assertTrue(any("確かめました" in t for t in said))          # もう一度確かめる

    def test_flaws_find_what_broke_before(self):
        """前に出た崩れ（消した跡の丸・切れた線・薄く残った元の線）を見つけ、変えていない絵では何も言わない"""
        from PIL import Image, ImageDraw, ImageFilter
        from chatdraw.engine import erase, flaws
        img = Image.new("RGB", (200, 160), (235, 190, 170))
        d = ImageDraw.Draw(img)
        for x in range(0, 200, 9):                                     # 髪の毛のような線が直す所を横切る
            d.line((x, 0, x + 40, 160), fill=(90, 50, 40), width=2)
        d.ellipse((80, 60, 120, 100), outline=(30, 20, 20), width=4)   # 直したい形（開いた目）
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).ellipse((70, 50, 130, 110), fill=255)
        self.assertEqual(flaws(img, img, m), [])
        erased = erase(img, m)                                         # 消して平らに埋めただけ
        found = " ".join(flaws(img, erased, m))
        self.assertIn("線が切れた", found)
        ghost = Image.blend(img, erased, 0.55)                          # 元の形が薄く透ける
        self.assertIn("元の形が薄く残る", " ".join(flaws(img, Image.composite(ghost, img, m), m)))

    def test_fix_with_flaws_is_hidden_and_reported(self):
        from PIL import Image
        from chatdraw.engine import erase

        class Breaks(FakePainter):
            def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
                self.calls.append(("redraw", prompt, seed))
                return erase(image, mask)
        self.w.studio.painter = Breaks()
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self.w.canvas.layers[1].image)
        for x in range(0, 200, 9):
            p.setPen(QColor(90, 50, 40))
            p.drawLine(x, 0, x + 40, 160)
        p.end()
        from PySide6.QtCore import QRect
        self.w.canvas.set_selection(QRect(60, 40, 70, 70))
        self.w.mode.setCurrentIndex(2)
        self.w.entry.setText("目を閉じて")
        self.w.send()
        wait_idle(self.app, self.w)
        top = self.w.canvas.layers[self.w.canvas.current]
        self.assertIn("崩れあり", top.name)
        self.assertFalse(top.visible)                                  # 崩れた直しは見えなくして重ねる（元の絵を壊さない）
        self.assertTrue(self.w.studio.last_flaws)

    def test_redraw_keeps_picture_outside_marks(self):
        """直すのは囲んだ所の中だけ。元の絵は縮めも広げもせず、外の画素は 1 つも変えない"""
        from types import SimpleNamespace
        from PIL import Image, ImageChops
        from chatdraw.engine import Painter
        seen = {}

        def fake(**kw):
            seen.update(size=kw["image"].size, strength=kw["strength"])
            return SimpleNamespace(images=[Image.new("RGB", kw["image"].size, "red")])
        p = Painter("x")
        p._pipe, p._inpaint = SimpleNamespace(device="cpu"), fake
        img = Image.effect_noise((203, 157), 60).convert("RGB")
        m = Image.new("L", img.size, 0)
        m.paste(255, (60, 40, 140, 120))
        out = p.redraw("smile", 1, img, m)
        self.assertEqual(out.size, img.size)
        self.assertEqual(seen["size"], (208, 160))                    # 8 の倍数へは端を足すだけ
        self.assertLess(seen["strength"], 0.5)                        # 既定は少しだけ直す
        outside = ImageChops.multiply(ImageChops.difference(out, img).convert("L"), Image.eval(m, lambda v: 255 - v))
        self.assertEqual(outside.getbbox(), None)                     # 外は元のまま
        self.assertEqual(out.getpixel((100, 80)), (255, 0, 0))        # 中は直っている

    @unittest.skipUnless(__import__("chatdraw.upscale", fromlist=["ready"]).ready(), "拡大の重みが手元に無い")
    def test_upscale_doubles_canvas(self):
        n = len(self.w.canvas.layers)
        self.w.canvas.layers[1].name = "線"
        self.w.upscale_canvas()
        wait_idle(self.app, self.w)
        self.assertEqual(self.w.canvas.size_px(), (400, 320))
        self.assertEqual(len(self.w.canvas.layers), n)                 # レイヤーは分かれたまま
        self.assertEqual(self.w.canvas.layers[1].name, "線")


class NoConsoleTest(unittest.TestCase):
    """pythonw.exe の起動（標準の出力が None）でも、進み表示（tqdm）を書く所で落ちない"""
    def test_streams_attached(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            code = ("import sys; sys.stdout = None; sys.stderr = None\n"
                    "import chatdraw.app\n"
                    "from tqdm import tqdm\n"
                    "for _ in tqdm(range(3)): pass\n"
                    "sys.stderr.write('written\\n'); sys.stderr.flush()\n")
            libs = os.pathsep.join(str(ROOT / ".cache" / n / "lib") for n in ("simple", "gen"))
            env = dict(os.environ, CD_HOME=d, QT_QPA_PLATFORM="offscreen", PYTHONPATH=libs)
            r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertIn("written", (Path(d) / "chatdraw.log").read_text(encoding="utf-8"))


class SystemTest(unittest.TestCase):
    """絵の上の指示・作業ファイル・PSD・自動保存・更新・加工・ライブラリーと好み"""
    def setUp(self):
        from tempfile import mkdtemp, mktemp
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        self.app = QApplication.instance() or QApplication([])
        self.dir = Path(mkdtemp())
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.dir))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)
        self.w.canvas.new_canvas(200, 160)

    def mark(self, x, y, note=""):
        from PySide6.QtCore import QPointF
        pen = self.w.canvas.redpen
        pen.begin(QPointF(x, y))
        for dx, dy in ((30, 0), (30, 30), (0, 30), (0, 2)):
            pen.add(QPointF(x + dx, y + dy))
        pen.end()
        pen.texts[-1] = note

    def test_notes_written_on_picture_need_no_chat(self):
        from chatdraw.redpen import merge
        self.assertEqual(merge(["笑顔に", ""], "2: 帽子を青に"), ["笑顔に", "帽子を青に"])
        self.mark(20, 20, "笑顔に")
        self.mark(120, 80, "帽子を青に")
        self.w.mode.setCurrentIndex(2)
        self.w.entry.clear()
        self.w.send()                                                 # チャットが空でも、絵の上の指示で直す
        wait_idle(self.app, self.w)
        self.assertEqual(len([c for c in self.painter.calls if c[0] == "redraw"]), 2)

    def test_note_editor_on_canvas(self):
        self.mark(20, 20)
        self.w.edit_note(1)
        self.assertFalse(self.w.note_edit.isHidden())
        self.w.note_edit.setText("目を大きく")
        self.w._note_done()
        self.assertEqual(self.w.canvas.redpen.texts, ["目を大きく"])

    def test_project_roundtrip_psd_and_autosave(self):
        import struct
        from PySide6.QtGui import QColor, QPainter
        from chatdraw import project
        p = QPainter(self.w.canvas.layers[1].image)
        p.fillRect(10, 10, 20, 20, QColor("red"))
        p.end()
        self.w.canvas.layers[1].name = "赤"
        self.mark(50, 50, "直す")
        path = self.dir / "a.cdproj"
        project.save(self.w.canvas, path)
        self.w.canvas.new_canvas(50, 50)
        self.w.open_path(str(path))
        self.assertEqual(self.w.canvas.size_px(), (200, 160))
        self.assertEqual(self.w.canvas.layers[1].name, "赤")
        self.assertEqual(self.w.canvas.layers[1].image.pixelColor(15, 15).name(), "#ff0000")
        self.assertEqual(self.w.canvas.redpen.texts, ["直す"])
        psd = self.dir / "a.psd"
        project.export_psd(self.w.canvas, psd)
        head = psd.read_bytes()[:26]
        self.assertEqual(head[:4], b"8BPS")
        self.assertEqual(struct.unpack(">II", head[14:22]), (160, 200))
        try:
            from psd_tools import PSDImage
        except ImportError:
            PSDImage = None
        if PSDImage:
            layers = list(PSDImage.open(psd))
            self.assertEqual([l.name for l in layers], ["背景", "赤"])
            self.assertEqual(layers[1].topil().getpixel((15, 15))[:3], (255, 0, 0))
        from unittest import mock
        auto = self.dir / "auto" / "autosave.cdproj"
        with mock.patch("chatdraw.project.autosave_path", return_value=auto):
            self.w.dirty = True
            self.w.autosave()
            self.assertTrue(auto.exists())
            self.w.layout_store.setValue("running", 0)
            self.assertFalse(self.w.offer_restore())                   # 正しく閉じていれば聞かない

    def test_update_check(self):
        import json as _json
        from chatdraw import updater
        self.assertTrue(updater.newer("v0.2.0", "0.1.9"))
        self.assertFalse(updater.newer("0.1.0", "0.1.0"))
        feed = self.dir / "latest.json"
        feed.write_text(_json.dumps({"tag_name": "v99.0.0", "html_url": "x",
                                     "assets": [{"name": "CharacterDesigner-Setup.exe", "browser_download_url": "https://e/s.exe"}]}))
        info = updater.check(feed.as_uri())
        self.assertEqual((info["version"], info["setup"]), ("99.0.0", "https://e/s.exe"))
        feed.write_text(_json.dumps({"tag_name": "v0.0.1"}))
        self.assertIsNone(updater.check(feed.as_uri()))
        self.assertIsNone(updater.check("http://127.0.0.1:9/none"))     # 確かめられないときは黙る

    def test_pixel_and_chibi(self):
        n = len(self.w.canvas.layers)
        self.w.make_pixel(long=32, colors=8)
        self.assertEqual(self.w.canvas.layers[-1].name if self.w.canvas.current == len(self.w.canvas.layers) - 1
                         else self.w.canvas.layers[self.w.canvas.current].name, "ドット絵")
        self.assertEqual(len(self.w.canvas.layers), n + 1)
        self.w.make_chibi()
        wait_idle(self.app, self.w)
        self.assertEqual([c[0] for c in self.painter.calls], ["redraw"])
        self.assertIn("ちびキャラ", [l.name for l in self.w.canvas.layers])
        self.assertTrue(self.w.canvas.layers[self.w.canvas.current].visible)   # 絵全体を描き替える加工は、崩れの検査で隠さない

    def test_library_learns_taste(self):
        from chatdraw.library import DISLIKE, LIKE
        lib = self.w.library
        for prompt, rating in (("red hair, watercolor", LIKE), ("red hair, armor", LIKE), ("dark, horror", DISLIKE),
                               ("dark, gore", DISLIKE), ("red hair", 0)):
            item = lib.add_work(str(self.dir / "x.png"), {"prompt": prompt, "style_name": "水彩"})
            lib.rate(item["id"], rating)
        p = lib.profile()
        self.assertEqual(p["tags"], ["red hair"])                      # 好きに 2 回以上出た言葉
        self.assertEqual(p["avoid"], ["dark"])                         # いまいちに 2 回以上、好きに無い言葉
        self.assertEqual(p["style"], "水彩")
        self.assertIn("red hair", self.w.ai_panel.style_tags())        # 描く言葉に足す
        self.w.layout_store.setValue("use_taste", 0)
        self.assertNotIn("red hair", self.w.ai_panel.style_tags())     # 外せる
        self.w.layout_store.setValue("use_taste", 1)
        self.w.entry.setText("雪の城の前の騎士")
        self.w.send()
        wait_idle(self.app, self.w)
        self.assertEqual(self.painter.avoid, "dark")                   # 避ける言葉は描かない物に足す
        self.assertEqual(lib.works()[0]["text"], "雪の城の前の騎士")    # 描いた絵は作品に入る
        from PIL import Image
        doc = self.dir / "doc.png"
        Image.new("RGB", (8, 8), "red").save(doc)
        self.w.library_panel.add_doc(str(doc), "この塗りが好き")
        self.assertEqual(lib.docs()[0]["note"], "この塗りが好き")
        self.assertTrue(Path(lib.docs()[0]["path"]).exists())          # 写しを取る


class UsableTest(unittest.TestCase):
    """画面に収まる・Tab で戻せる・キーとカーソルと模型の置き場を変えられる"""
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw import fit
        self.app = QApplication.instance() or QApplication([])
        fit.install(self.app)
        self.w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        self.w.show()

    def tearDown(self):
        self.w.dirty = False
        self.w.close()

    def spin(self, s=0.6):
        import time
        end = time.time() + s
        while time.time() < end:
            self.app.processEvents()

    def test_window_and_dialogs_stay_on_screen(self):
        from PySide6.QtWidgets import QDialog
        area = self.w.screen().availableGeometry()
        self.w.resize(area.width() * 3, area.height() * 3)
        self.w.move(area.right() - 10, area.bottom() - 10)
        self.spin()
        self.assertTrue(area.contains(self.w.frameGeometry()), (area, self.w.frameGeometry()))
        d = QDialog(self.w)
        d.resize(400, area.height() * 4)   # 縦に長い窓
        d.show()
        self.spin()
        self.assertTrue(area.contains(d.frameGeometry()), (area, d.frameGeometry()))
        d.close()
        dock = self.w.panels["layers"][0]
        dock.setFloating(True)
        dock.resize(300, area.height() * 3)
        self.spin()
        self.assertTrue(area.contains(dock.frameGeometry()), (area, dock.frameGeometry()))

    def test_every_panel_scrolls(self):
        from PySide6.QtWidgets import QScrollArea
        for key, (dock, _a) in self.w.panels.items():
            box = dock.widget()
            self.assertIsInstance(box, QScrollArea, key)
            self.assertEqual(box.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded, key)

    def test_tab_hides_and_restores(self):
        self.w.toggle_all()
        self.assertFalse(self.w.tools.isVisible())
        self.w.toggle_all()
        self.assertTrue(self.w.tools.isVisible())
        self.assertTrue(self.w.panels["chat"][0].isVisible())

    def test_keys_can_be_changed_and_saved(self):
        from PySide6.QtCore import QSettings
        from chatdraw import keys
        store = QSettings(str(Path(self.w.layout_store.fileName()).with_name("keys-test.ini")), QSettings.IniFormat)
        store.clear()
        keys.apply(self.w, store)
        d = keys.KeyDialog(self.w, store)
        names = [d.table.item(r, 0).data(Qt.UserRole) for r in range(d.table.rowCount())]
        row = names.index("ファイル/新規キャンバス" if "ファイル/新規キャンバス" in names else "新規キャンバス")
        d.table.setCurrentCell(row, 0)
        d._store_row("Ctrl+Alt+K")
        d.save()
        self.assertEqual(d.actions[names[row]].shortcut().toString(), "Ctrl+Alt+K")
        self.assertEqual(store.value(keys.PREFIX + names[row]), "Ctrl+Alt+K")
        # 重なる割り当ては保存しない
        d2 = keys.KeyDialog(self.w, store)
        other = names.index("道具/ペン")
        d2.table.setCurrentCell(other, 0)
        d2._store_row("Ctrl+Alt+K")
        self.assertFalse(d2._check())
        store.clear()

    def test_progress_moves_stays_and_tells(self):
        a = self.w.activity
        seen = []
        a.changed.connect(lambda t, p: seen.append(p))
        a.begin("テスト", "新規")
        v0 = a.bar.value()
        self.spin(0.3)
        self.assertNotEqual(a.bar.value(), v0)              # 工程の数が分かる前でも帯が動く
        self.assertIn("CharacterDesigner", self.w.windowTitle())
        a.status("描いています 3/10", 3, 10)
        self.assertIn("30%", self.w.windowTitle())
        a.end("描きました", None, record=False)
        self.w.hide_progress_if_idle(0)
        self.spin(0.3)
        self.assertTrue(self.w.panels["progress"][0].isVisible())   # 終わっても消えない
        self.assertEqual(self.w.windowTitle(), "CharacterDesigner")
        self.assertEqual(seen[0], -1)
        self.assertEqual(seen[-1], -2)

    def test_key_filter_does_not_assign_hidden_row(self):
        from PySide6.QtCore import QSettings
        from chatdraw import keys
        store = QSettings(str(Path(self.w.layout_store.fileName()).with_name("keys-test2.ini")), QSettings.IniFormat)
        store.clear()
        d = keys.KeyDialog(self.w, store)
        d.table.setCurrentCell(0, 0)
        d.search.setText("この名前の操作は無い")
        self.assertEqual(d.table.currentRow(), -1)
        before = d.table_now()
        d._store_row("Ctrl+Alt+J")
        self.assertEqual(d.table_now(), before)
        store.clear()

    def test_mode_buttons_follow_family(self):
        """世代で使えない機能のボタンを止める（ここで落ちて「描く」が動かなくなったことがある）"""
        self.w.studio.painter.model = "black-forest-labs/FLUX.2-klein-4B"
        self.w.check_ai()
        btns = self.w.ai_panel.mode_buttons[1]
        self.assertFalse(btns[1].isEnabled())
        self.assertFalse(btns[2].isEnabled())
        self.w.studio.painter.model = "cagliostrolab/animagine-xl-4.0"
        self.w.check_ai()
        self.assertTrue(btns[1].isEnabled())

    def test_cursor_styles(self):
        from PySide6.QtCore import Qt as Q
        from chatdraw.canvas import CURSOR_STYLES
        self.w.canvas.set_tool("pen")
        for st in CURSOR_STYLES:
            self.w.canvas.set_cursor_style(st)
            self.assertTrue(self.w.canvas.cursor_ring.isVisible())
        self.w.canvas.set_cursor_style("筆の輪だけ")
        self.assertEqual(self.w.canvas.viewport().cursor().shape(), Q.BlankCursor)

    def test_model_dir_choice(self):
        import importlib
        import chatdraw.paths as paths
        with TemporaryDirectory() as home, TemporaryDirectory() as models:
            old = os.environ.get("CD_HOME")
            os.environ["CD_HOME"] = home
            try:
                paths.set_model_dir(models)
                fresh = importlib.reload(paths)
                self.assertEqual(fresh.LLM_HOME, Path(models))
                self.assertEqual(fresh.HUB, Path(models) / "huggingface")
                fresh.set_model_dir("")
                self.assertEqual(importlib.reload(paths).chosen_model_dir(), "")
            finally:
                if old is None:
                    os.environ.pop("CD_HOME", None)
                else:
                    os.environ["CD_HOME"] = old
                importlib.reload(paths)


class ManualModelTest(unittest.TestCase):
    """手で置いた模型（.safetensors と diffusers のフォルダー）を一覧に出し、取らずに使う。ヘルプの文書が開ける"""
    def setUp(self):
        from unittest import mock
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        manual = root / "manual"
        (manual / "my-xl").mkdir(parents=True)
        (manual / "my-xl" / "model_index.json").write_text('{"_class_name": "StableDiffusionXLPipeline"}', encoding="utf-8")
        (manual / "small.safetensors").write_bytes(b"0" * 1024)
        self.patch = mock.patch("chatdraw.paths.LLM_HOME", root)
        self.patch.start()
        self.root = root

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_listed_and_ready(self):
        from chatdraw.models import all_images, image_model, is_local, manual_images
        from chatdraw.setup import has_image
        found = {Path(m.repo).name: m for m in manual_images()}
        self.assertEqual(set(found), {"my-xl", "small.safetensors"})
        self.assertEqual(found["my-xl"].family, "sdxl")
        self.assertEqual(found["small.safetensors"].family, "unknown")   # 中の重みの名前が無いので見分けない
        self.assertTrue(all(has_image(m) for m in found.values()))
        self.assertTrue(is_local(found["my-xl"].repo))
        self.assertFalse(is_local("cagliostrolab/animagine-xl-4.0"))
        self.assertEqual(image_model(found["my-xl"].repo).family, "sdxl")
        self.assertGreater(len(all_images()), len(manual_images()))

    def test_setup_uses_local_without_fetching_image(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.setup import SetupDialog
        QApplication.instance() or QApplication([])
        d = SetupDialog(None, None, first=True)
        d.start = lambda update: None   # 取る所は動かさない
        d.use_local(str(self.root / "manual" / "my-xl"))
        image, _words = d.to_fetch()
        self.assertIsNone(image)
        self.assertEqual(d.chosen()[0].repo, str((self.root / "manual" / "my-xl").resolve()))

    def test_family_from_contents(self):
        """フォルダーは部品の名前、1 つのファイルは重みの名前で世代を見分ける（大きさでは決めない）"""
        import json
        import struct
        from chatdraw.models import local_family
        root = self.root / "manual"
        (root / "my-flux").mkdir()
        (root / "my-flux" / "model_index.json").write_text('{"_class_name": "FluxPipeline"}', encoding="utf-8")
        self.assertEqual(local_family(root / "my-flux"), "flux1")

        def fake(name, keys):
            head = json.dumps({k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys}).encode()
            (root / name).write_bytes(struct.pack("<Q", len(head)) + head + b"00")
            return root / name
        self.assertEqual(local_family(fake("xl.safetensors", ["conditioner.embedders.1.model.ln_final.weight"])), "sdxl")
        self.assertEqual(local_family(fake("v15.safetensors", ["cond_stage_model.transformer.x"])), "sd15")
        self.assertEqual(local_family(fake("flux.safetensors", ["double_blocks.0.img_attn.qkv.weight"])), "flux1")
        self.assertEqual(local_family(fake("other.safetensors", ["foo"])), "unknown")

    def test_setup_keeps_local_choice(self):
        """手で置いた模型を使っている人が窓を開き直しても、おまかせに書き換えない。札を選べばそちらに替わる"""
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.settings import Settings
        from chatdraw.setup import AUTO, SetupDialog
        QApplication.instance() or QApplication([])
        st = Settings(QSettings(str(self.root / "s.ini"), QSettings.IniFormat))
        path = str((self.root / "manual" / "my-xl").resolve())
        st.set("image_model", path)
        st.store.setValue("setup_done", 1)
        d = SetupDialog(st, None, first=False)
        d.apply()
        self.assertEqual(st.get("image_model"), path)
        d.image_radios[AUTO].click()
        self.assertIsNone(d.local)
        d.select("no/such-model")   # 一覧に無い名前でも落ちない

    def test_help_docs_open(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.helpview import DOCS, HelpDialog
        QApplication.instance() or QApplication([])
        for key in DOCS:
            d = HelpDialog(key)
            self.assertGreater(len(d.view.toPlainText()), 500, key)
        d = HelpDialog("install")
        self.assertIn("手で置く", d.view.toPlainText())


class SmallScreenTest(unittest.TestCase):
    """ノートの画面（1280×720）に、どの配置でもウィンドウが収まる"""
    def test_every_preset_fits_1280x720(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw import layouts
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        w.resize(1280, 720)
        w.show()
        for name, fn in layouts.PRESETS.items():
            w.apply_layout(fn)
            for _ in range(5):
                app.processEvents()
            mw, mh = w.minimumSizeHint().toTuple()
            self.assertLessEqual(mw, 1280, name)
            self.assertLessEqual(mh, 680, name)                       # タイトルの帯とタスクバーの分を残す


class TwoStageTest(unittest.TestCase):
    """2 段で描く仕組みの段の分け方と縛りの渡し方（模型は読まない）"""

    def test_render_passes_only_named_controls(self):
        from PIL import Image
        from chatdraw import twostage
        seen = {}

        class Pipe:
            def __call__(self, **kw):
                seen.update(kw)
                return type("R", (), {"images": [Image.new("RGB", (8, 8))]})()
        shapes = {k: Image.new("RGB", (16, 16)) for k in ("pose", "depth", "lines")}
        twostage.render(Pipe(), "p", "n", shapes, {"name": "x", "pose": 0.7, "depth": 0.4, "end": 0.7}, 1, (8, 8), 2, 5.0)
        self.assertEqual(seen["control_mode"], [0, 1])
        self.assertEqual(seen["controlnet_conditioning_scale"], [0.7, 0.4])
        self.assertEqual(seen["control_guidance_end"], 0.7)

    def test_draw_skips_compose_when_given_and_stops_after_compose(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from unittest import mock
        from PIL import Image
        from chatdraw import twostage
        with tempfile.TemporaryDirectory() as d:
            comp = Path(d) / "given.png"
            Image.new("RGB", (8, 8)).save(comp)
            calls = []
            with mock.patch.object(subprocess, "run", side_effect=lambda a, **k: calls.append(a[4])):
                twostage.draw("s", "t", 1, "c", "r", keep=Path(d) / "k", composition=str(comp), stage="finish")
                self.assertEqual(calls, ["finish"])   # 構図をとばした
                self.assertTrue((Path(d) / "k" / "1-composition.png").exists())
                calls.clear()
                twostage.draw("s", "t", 1, "c", "r", keep=Path(d) / "k2", stage="compose")
                self.assertEqual(calls, ["compose"])   # 仕上げはしない


class TwoStageAppTest(unittest.TestCase):
    """アプリの描く経路（Studio）が、描き方の設定と手元の模型で 2 段を選ぶか"""

    def _studio(self, way):
        import tempfile
        from pathlib import Path
        from chatdraw.engine import Studio
        s = Studio(out=Path(tempfile.mkdtemp()))
        s.way = way
        return s

    def test_way_one_and_rough_never_use_two_stage(self):
        s = self._studio("one")
        self.assertIsNone(s._two_stage_models(None, None))
        s.way = "two"
        self.assertIsNone(s._two_stage_models(object(), None))   # ラフから描くときは 1 つの模型

    def test_auto_falls_back_and_two_explains(self):
        from unittest import mock
        from chatdraw import twostage
        s = self._studio("auto")
        with mock.patch.object(twostage, "pick", return_value=None):
            self.assertIsNone(s._two_stage_models(None, None))
            s.way = "two"
            with self.assertRaises(ValueError):
                s._two_stage_models(None, None)

    def test_pick_prefers_sentence_model_and_current_sdxl(self):
        from chatdraw import twostage
        from chatdraw.models import image_model
        have = [image_model("black-forest-labs/FLUX.2-klein-4B"), image_model("cagliostrolab/animagine-xl-4.0")]
        comp, render = twostage.pick(have, "cagliostrolab/animagine-xl-4.0")
        self.assertEqual((comp.family, render.repo), ("flux2", "cagliostrolab/animagine-xl-4.0"))
        self.assertIsNone(twostage.pick(have[1:], ""))

    def test_draw_two_saves_with_stage_record(self):
        import json
        from unittest import mock
        from PIL import Image
        from chatdraw import twostage
        from chatdraw.models import image_model
        s = self._studio("two")
        s.words.to_prompt = lambda text, tags=True: "1girl, smile" if tags else "A woman smiling."
        two = (image_model("black-forest-labs/FLUX.2-klein-4B"), image_model("cagliostrolab/animagine-xl-4.0"))

        def fake(sentence, tags, seed, c, r, size, keep, variant, say, stopped):
            keep.mkdir(parents=True)
            p = keep / f"3-{variant['name']}-s{seed}.png"
            Image.new("RGB", (8, 8)).save(p)
            self.assertEqual((sentence, tags), ("A woman smiling.", "1girl, smile"))
            return p
        with mock.patch.object(twostage, "pick", return_value=two), mock.patch.object(twostage, "parts_ready", return_value=True), \
                mock.patch.object(twostage, "run_stages", side_effect=fake), \
                mock.patch("chatdraw.choose.installed_images", return_value=[]):
            prompt, path = s.draw("笑う女の人", 3)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual((meta["way"], meta["compose_model"]), ("two", "black-forest-labs/FLUX.2-klein-4B"))

    def test_run_stages_reports_where_it_stopped(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from chatdraw import twostage

        class P:
            stdout = iter(["構図 1/4 10 秒\n", "Traceback\n", "MemoryError\n"])
            def poll(self): return 1
            def wait(self): return 1
            def kill(self): pass
        said = []
        with mock.patch("subprocess.Popen", return_value=P()):
            with self.assertRaises(RuntimeError) as e:
                twostage.run_stages("s", "t", 1, "c", "r", (8, 8), Path(tempfile.mkdtemp()), twostage.VARIANTS[0], say=said.append)
        self.assertIn("MemoryError", str(e.exception))
        self.assertIn("構図 1/4 10 秒", said)


class CpuDtypeTest(unittest.TestCase):
    """CPU で読む型を、bf16 の速さとメモリの量で選ぶか"""

    def test_choice(self):
        import torch
        from unittest import mock
        from chatdraw import engine
        with mock.patch.object(engine, "bf16_fast", return_value=True):
            self.assertEqual(engine.cpu_dtype(7), torch.bfloat16)
        with mock.patch.object(engine, "bf16_fast", return_value=False):
            with mock.patch.object(engine, "total_ram_gb", return_value=32):
                self.assertEqual(engine.cpu_dtype(7), torch.float32)    # 遅い CPU でもメモリに入れば float32
            with mock.patch.object(engine, "total_ram_gb", return_value=16):
                self.assertEqual(engine.cpu_dtype(7), torch.bfloat16)   # 入らなければ bf16（遅いが動く）
                self.assertIn("時間がかかります", engine.dtype_note(torch.bfloat16))

    def test_measure_and_ram(self):
        from chatdraw import engine
        self.assertIsInstance(engine.bf16_fast(), bool)
        self.assertGreater(engine.total_ram_gb(), 0)


class UsabilityFixTest(unittest.TestCase):
    """使いにくいと言われた所: 頼みと違う絵、頼みの言葉の履歴、描いた絵の重なり"""

    def test_japanese_terms(self):
        from chatdraw.jaterms import merge, tags_from
        self.assertEqual(tags_from("白いビキニの女性が海で笑顔")[:2], ["white bikini", "1girl"])
        self.assertIn("red hair", tags_from("赤い髪の女の子"))
        self.assertEqual(merge("1girl, beach", ["1girl", "white bikini"]), "1girl, beach, white bikini")   # 抜けた語だけ足す

    def _window(self, d):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
        w.settings.store.remove(w.PROMPT_KEY)
        w.settings.store.remove(w.FAV_KEY)
        w._load_prompts()
        return app, w

    def _draw(self, app, w, text):
        n = len(w.images)
        w.entry.setText(text)
        w.send()
        for _ in range(300):
            app.processEvents()
            if len(w.images) > n and not w.thread:
                break
            w.thread and w.thread.wait(10)

    def _chips(self, w):
        return [w.tips.itemAt(i).widget().text() for i in range(w.tips.count()) if w.tips.itemAt(i).widget()]

    def test_recent_words_replace_examples_and_favorites_stay(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        with TemporaryDirectory() as d:
            app, w = self._window(d)
            w.settings.store.remove(w.FAV_KEY)
            w._load_prompts()
            self.assertEqual(self._chips(w)[:2], list(w.EXAMPLES[:2]))      # まだ何も頼んでいないときだけ例
            self._draw(app, w, "ビキニの女性")
            self._draw(app, w, "海の女性")
            self._draw(app, w, "ビキニの女性")
            self.assertEqual(self._chips(w), ["ビキニの女性", "海の女性"])    # 例の所が直近の言葉になる（新しい順、重ねない）
            w.entry.setText("海の女性")
            w._toggle_fav()                                                  # ☆ で固定
            self.assertEqual(self._chips(w), ["★ 海の女性", "ビキニの女性"])  # お気に入りが先頭
            self.assertEqual(w.fav_button.text(), "★")
            for i in range(30):
                w._remember_prompt(f"言葉 {i}")
            self.assertIn("★ 海の女性", self._chips(w))                       # 直近が増えてもお気に入りは消えない
            self.assertEqual(len(w.recent_prompts()), w.PROMPT_MAX)
            w.entry.clear()
            w.eventFilter(w.entry, QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier))
            self.assertEqual(w.entry.text(), "海の女性")                       # ↑ はお気に入りから
            w.forget_prompt("海の女性")
            self.assertNotIn("★ 海の女性", self._chips(w))
            w.settings.store.remove(w.PROMPT_KEY)
            w.settings.store.remove(w.FAV_KEY)

    def test_new_drawings_replace_and_undo_restores(self):
        with TemporaryDirectory() as d:
            app, w = self._window(d)
            self._draw(app, w, "1girl")
            self._draw(app, w, "1girl, smile")
            names = [l.name for l in w.canvas.layers]
            self.assertEqual(len(names), 2)                     # 絵 1 枚と描くためのレイヤー。前の絵は重ならない
            self.assertTrue(names[0].startswith("AI の絵"))
            self.assertEqual(w.canvas.current, 1)               # 次の線は空のレイヤーに描く
            first = w.canvas.layers[0].name
            w.canvas.undo()
            self.assertNotEqual(w.canvas.layers[0].name, first)  # 元に戻すで前の絵に戻る
            w.settings.store.remove(w.PROMPT_KEY)

    def test_layer_added_on_top_not_under_strokes(self):
        from PySide6.QtGui import QImage
        with TemporaryDirectory() as d:
            app, w = self._window(d)
            p = Path(d) / "a.png"
            img = QImage(64, 64, QImage.Format_ARGB32)
            img.fill(0xffff0000)
            img.save(str(p))
            w.canvas.select(0)
            w.canvas.add_image_layer(str(p), "AI の直し")
            self.assertEqual(w.canvas.current, len(w.canvas.layers) - 1)
            self.assertEqual(w.canvas.layers[-1].name, "AI の直し")


class ButtonTipTest(unittest.TestCase):
    """ボタンの説明はボタンに書かず、カーソルを合わせたときに出す"""

    def test_ai_panel_buttons_are_one_line(self):
        from PySide6.QtWidgets import QAbstractButton, QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path("/tmp")))
        buttons = w.ai_panel.findChildren(QAbstractButton)
        self.assertTrue(buttons)
        for b in buttons:
            self.assertNotIn("\n", b.text(), b.text())
        for b in w.ai_panel.preset_group.buttons():
            self.assertIn(":", b.toolTip())   # 説明はツールチップに
