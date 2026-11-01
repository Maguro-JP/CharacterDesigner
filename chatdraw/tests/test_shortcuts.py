"""右クリックのショートカット。アプリの右クリックのメニューを作り、項目を押して（QAction.trigger）最後まで流す。
模型の要る物は偽の模型で流れを確かめ、模型の要らない物は本物の加工で結果の画素を確かめる"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402

# 模型を使わず、本物の加工で画素が変わるはずの物
PIXEL_CHANGES = ("fin:clean", "fin:ink", "fin:air_holy", "fin:air_komorebi", "fin:air_haze", "fin:mat_metal", "fin:mat_gem",
                 "fin:mat_slime", "app:lineart", "app:pixel", "app:nobg")
# 工程ごとに良くなった時だけ掛けるので、小さな絵では変わらないこともある。全部の工程を通ったことを確かめる
RETOUCH = ("fin:retouch", "fin:retouch_full")
# 模型の要る物（偽の模型で流す）と、拡大の重みの要る物（偽の重みで流す）
MODEL_ITEMS = ("fin:face", "fin:refine", "app:chibi", "grow:lr", "grow:tb", "grow:all", "fin:upscale_anime", "app:upscale2x")


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def figure(size=(96, 128)) -> Image.Image:
    im = Image.new("RGB", size, (240, 230, 220))
    d = ImageDraw.Draw(im)
    d.ellipse((20, 10, 76, 120), fill=(200, 80, 80), outline=(20, 20, 20), width=3)
    d.line((30, 40, 66, 90), fill=(20, 20, 20), width=2)
    for y in range(0, size[1], 7):   # ざらつきと黒い粒（直す所）
        d.point([(x, y) for x in range(0, size[0], 5)], fill=(120, 120, 120))
    d.point([(8, 8), (88, 120)], fill=(0, 0, 0))
    return im


class Base(unittest.TestCase):
    def setUp(self):
        from PySide6.QtCore import QSettings
        from chatdraw import shortcuts
        from chatdraw.app import Window
        self.qa = app()
        self.tmp = TemporaryDirectory()
        d = Path(self.tmp.name)
        self.src = d / "a.png"
        figure().save(self.src)
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, d))
        self.w.settings.set("output_dir", str(d / "out"))
        self.ini = str(d / "s.ini")
        self.w._shortcut_store = shortcuts.Store(QSettings(self.ini, QSettings.IniFormat))
        self.w.edit_image(str(self.src))

    def tearDown(self):
        self.wait()
        self.w.close()
        self.tmp.cleanup()

    def base(self):
        """重ねた絵（透明さも残す）"""
        from chatdraw.app import qimage_to_pil_rgba
        return qimage_to_pil_rgba(self.w.canvas.flatten())

    def wait(self, sec: float = 60):
        end = time.time() + sec
        while time.time() < end:
            self.qa.processEvents()
            if self.w.thread is None and not getattr(self.w, "bg_pending", 0):
                return
            time.sleep(0.02)
        self.fail("処理が終わりませんでした")

    def actions(self, menu=None):
        """右クリックのメニューの項目を、小さなメニューの中まで集める（id → QAction）"""
        if menu is None:
            menu = self._menu = self.w.build_canvas_menu()   # 押すまで手放さない
            self._keep = []
        out = {}
        acts = menu.actions()
        self._keep.append(acts)   # 項目の包みを手放すと、小さなメニューも一緒に消えた（PySide6 6.12）
        for a in acts:
            sub = a.menu()
            if sub is not None:
                for k, v in self.actions(sub).items():
                    out.setdefault(k, v)
            elif a.objectName():
                out.setdefault(a.objectName(), a)
        return out

    def submenu(self, title: str):
        self._menu = self.w.build_canvas_menu()
        self._keep = [self._menu.actions()]
        for a in self._keep[0]:
            if a.text() == title:
                return a.menu()

    def press(self, sid: str):
        """右クリックのメニューを作り、その項目を押して、終わるまで待つ"""
        act = self.actions()[sid]
        self.assertTrue(act.isEnabled(), f"{sid} が押せません: {act.toolTip()}")
        act.trigger()
        self.wait()


class GroupTest(unittest.TestCase):
    def test_clean_is_split_by_kind(self):
        from chatdraw import finishers, shortcuts
        groups = {f.name: f.group for f in finishers.REGISTRY.values()}
        self.assertEqual({n for n, g in groups.items() if g == "clean"}, {"retouch", "clean", "retouch_full"})
        self.assertEqual({n for n, g in groups.items() if g == "texture"}, {"mat_metal", "mat_gem", "mat_slime"})
        self.assertEqual({n for n, g in groups.items() if g == "air"}, {"air_holy", "air_komorebi", "air_haze"})
        self.assertEqual(groups["face"], "redraw")
        self.assertEqual(groups["refine"], "redraw")
        self.assertEqual(groups["upscale_anime"], "enlarge")
        self.assertEqual(groups["ink"], "ink")
        self.assertTrue(set(groups.values()) <= set(shortcuts.GROUP_LABEL))


class StoreTest(unittest.TestCase):
    def test_register_rename_remove_and_keep_after_restart(self):
        from PySide6.QtCore import QSettings
        from chatdraw import shortcuts
        with TemporaryDirectory() as d:
            ini = str(Path(d) / "s.ini")
            st = shortcuts.Store(QSettings(ini, QSettings.IniFormat))
            a = st.add("目", "目を大きく")
            b = st.add("", "背景を夕焼けに")
            self.assertEqual([p["name"] for p in st.prompts()], ["目", "背景を夕焼けに"])
            st.rename(a, "大きな目")
            st.set_favorite(b, True)
            st.count(a)
            with self.assertRaises(ValueError):
                st.add("空", "  ")
            again = shortcuts.Store(QSettings(ini, QSettings.IniFormat))   # 次の起動（更新のあと）も残る
            self.assertEqual(again.prompts()[0], dict(id=a, name="大きな目", text="目を大きく"))
            self.assertEqual(again.favorites(), [b])
            self.assertEqual(again.uses(), {a: 1})
            again.remove(b)
            self.assertEqual([p["id"] for p in again.prompts()], [a])
            self.assertEqual(again.favorites(), [])

    def test_order_favorites_then_used_then_default(self):
        from PySide6.QtCore import QSettings
        from chatdraw import shortcuts
        with TemporaryDirectory() as d:
            st = shortcuts.Store(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
            items = [shortcuts.Shortcut(i, i, "clean", "", True, "", lambda: None) for i in "abcde"]
            st.set_favorite("d", True)
            st.set_favorite("b", True)
            for _ in range(3):
                st.count("e")
            st.count("c")
            self.assertEqual([s.id for s in st.order(items)], ["d", "b", "e", "c", "a"])

    def test_broken_value_reads_as_empty(self):
        from PySide6.QtCore import QSettings
        from chatdraw import shortcuts
        with TemporaryDirectory() as d:
            qs = QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat)
            qs.setValue(shortcuts.KEY_PROMPTS, "{壊れた")
            qs.setValue(shortcuts.KEY_USES, "[1]")
            st = shortcuts.Store(qs)
            self.assertEqual(st.prompts(), [])
            self.assertEqual(st.uses(), {})


class MenuTest(Base):
    def test_every_item_is_in_the_menu_and_disabled_ones_say_why(self):
        from chatdraw import shortcuts
        acts = self.actions()
        ids = {s.id for s in shortcuts.all_items(self.w, self.w.shortcut_store())}
        self.assertEqual(ids - set(acts), set())
        for sid, a in acts.items():
            if sid in ids:
                self.assertTrue(a.toolTip(), sid)
        from chatdraw import finishers
        with mock.patch.object(finishers, "_has", return_value=False):
            acts = self.actions()
        self.assertFalse(acts["app:upscale2x"].isEnabled())   # torch は押したときに取れないので、押せない形で理由を出す
        self.assertIn("まだ入っていません", acts["app:upscale2x"].toolTip())
        for sid in ("fin:retouch", "fin:ink", "fin:mat_metal"):   # 小さな部品は押したときに取りに行くので押せる
            self.assertTrue(acts[sid].isEnabled(), sid)
            self.assertIn("部品を取って", acts[sid].toolTip(), sid)
        with mock.patch.object(finishers, "_has", return_value=False), \
                mock.patch.object(finishers, "_gen_dir", return_value=Path("/nonexistent/tools/gen")):
            acts = self.actions()
        self.assertFalse(acts["fin:retouch"].isEnabled())   # 台本が無ければ取っても使えないので押せない
        self.assertIn("入っていません", acts["fin:retouch"].toolTip())

    def test_every_builtin_is_pressed_in_these_tests(self):
        """アプリにある項目を足したら、押して流す試験にも足す（押して確かめていない項目を出さない）"""
        from chatdraw import shortcuts
        pressed = set(PIXEL_CHANGES) | set(RETOUCH) | set(MODEL_ITEMS)
        self.assertEqual({s.id for s in shortcuts.builtins(self.w)}, pressed)

    def test_no_model_disables_model_items_with_reason(self):
        self.painter.ready = lambda: False
        acts = self.actions()
        for sid in ("fin:face", "fin:refine", "app:chibi", "grow:lr", "grow:tb", "grow:all"):
            self.assertFalse(acts[sid].isEnabled(), sid)
            self.assertIn("模型", acts[sid].toolTip(), sid)
        sid = self.w.add_prompt_shortcut("目を大きく", "目")
        self.assertFalse(self.actions()[sid].isEnabled())
        self.assertIsNone(self.w.run_shortcut(sid))   # 押せても止めずに理由を出す
        self.assertEqual(self.painter.calls, [])

    def test_favorite_and_used_come_first(self):
        st = self.w.shortcut_store()
        st.set_favorite("fin:mat_gem", True)
        self.press("app:lineart")
        self.press("app:lineart")
        self.press("fin:clean")
        top = [a for a in self.w.build_canvas_menu().actions() if a.objectName()]
        self.assertEqual([a.objectName() for a in top[:3]], ["fin:mat_gem", "app:lineart", "fin:clean"])
        self.assertTrue(top[0].text().startswith("★ 質感: "))
        self.assertEqual(st.uses(), {"app:lineart": 2, "fin:clean": 1})

    def test_clean_menu_only_has_cleaning(self):
        sub = self.submenu("綺麗にする")
        self.assertEqual([a.objectName() for a in sub.actions()], ["fin:retouch", "fin:clean", "fin:retouch_full"])


class EverywhereTest(Base):
    """どこで右クリックしても、使えるメニューが出る（押しても何も出ない所を作らない）"""

    def texts(self, m):
        self._keep = [m, m.actions()]
        return [a.text() for a in self._keep[1]]

    def test_every_panel_has_a_menu(self):
        from PySide6.QtCore import Qt
        for key, (d, _a) in self.w.panels.items():
            with self.subTest(key=key):
                self.assertEqual(d.contextMenuPolicy(), Qt.CustomContextMenu)
                t = self.texts(self.w.area_menu(key))
                for want in ("新しく描く（書く欄へ）", "画像を開く…", "ショートカット"):
                    self.assertIn(want, t)

    def test_empty_history_and_library_and_chat(self):
        from PySide6.QtCore import QPoint
        self.w.history.clear()
        self.assertIn("画像を開く…", self.texts(self.w._history_menu(QPoint(5, 5), run=False)))
        lib = self.w.library_panel
        lib.works.clear()
        self.assertIn("ショートカット", self.texts(lib._menu(lib.works, QPoint(5, 5), run=False)))
        chat = self.w.chat if hasattr(self.w, "chat") else None
        if chat is not None and hasattr(chat, "menu"):
            self.assertIn("文をコピー", self.texts(chat.menu()))

    def test_new_drawing_from_menu(self):
        m = self.w.area_menu("history")
        self._keep = [m, m.actions()]
        next(a for a in self._keep[1] if a.text() == "新しく描く（書く欄へ）").trigger()
        self.assertEqual(self.w.mode.currentIndex(), 0)


class ModelFreeTest(Base):
    def test_each_item_changes_pixels(self):
        from chatdraw import finishers
        for sid in PIXEL_CHANGES:
            with self.subTest(sid=sid):
                self.w.edit_image(str(self.src))
                before, n = self.base(), len(self.w.canvas.layers)
                self.press(sid)
                after = self.base()
                self.assertTrue(len(self.w.canvas.layers) != n or sid == "app:nobg", sid)
                self.assertIsNotNone(ImageChops.difference(before, after).getbbox(alpha_only=False), sid)
        for sid in RETOUCH:
            with self.subTest(sid=sid):
                self.w.edit_image(str(self.src))
                n = len(self.w.canvas.layers)
                self.press(sid)
                self.assertEqual(len(self.w.canvas.layers), n + 1)
                want = finishers.RETOUCH_FULL if sid.endswith("full") else finishers.RETOUCH_SAFE
                self.assertEqual([r["step"] for r in finishers.LAST_REPORT["steps"]], list(want))

    def test_remove_background_makes_corners_clear_and_keeps_figure(self):
        self.press("app:nobg")
        out = self.base()
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(out.getpixel((48, 64))[3], 255)

    def test_remove_background_inside_region_only(self):
        from PySide6.QtCore import QRect
        self.w.canvas.set_selection(QRect(0, 0, 48, 128))   # 左半分だけ
        self.press("app:nobg")
        out = self.base()
        self.assertEqual(out.getpixel((2, 2))[3], 0)
        self.assertEqual(out.getpixel((93, 2))[3], 255)   # 囲みの外の背景は残る


class ModelTest(Base):
    def test_redraw_finishers_with_fake_model(self):
        for sid in ("fin:face", "fin:refine"):
            with self.subTest(sid=sid):
                self.w.edit_image(str(self.src))
                n = len(self.w.canvas.layers)
                self.press(sid)
                self.assertEqual(len(self.w.canvas.layers), n + 1)
                self.assertEqual(self.painter.calls[-1][0], "redraw")
                self.assertEqual(self.base().convert("RGB").getpixel((48, 64)), (255, 255, 255))   # 偽の模型は白く塗る

    def test_grow_items(self):
        for sid, size in (("grow:lr", (96 + 256, 128)), ("grow:tb", (96, 128 + 256)), ("grow:all", (96 + 256, 128 + 256))):
            with self.subTest(sid=sid):
                self.w.edit_image(str(self.src))
                self.press(sid)
                self.assertEqual(self.w.canvas.size_px(), size)

    def test_chibi(self):
        n = len(self.w.canvas.layers)
        self.press("app:chibi")
        self.assertEqual(len(self.w.canvas.layers), n + 1)
        self.assertEqual(self.painter.calls[-1][0], "redraw")

    def test_upscale_items_with_fake_weights(self):
        from chatdraw import finishers, upscale

        def fake(img, k=2, on_step=None):
            if on_step:
                on_step(1, 1)
            return img.resize((img.width * k, img.height * k))
        with mock.patch.object(finishers, "_has", return_value=True), \
                mock.patch.object(finishers, "_upscale_ready", return_value=True), \
                mock.patch.object(upscale, "upscale", side_effect=fake), mock.patch.object(upscale, "ready", return_value=True):
            self.press("fin:upscale_anime")
            self.assertEqual(self.w.canvas.size_px(), (192, 256))
            self.w.edit_image(str(self.src))
            self.w.canvas.undo_stack.clear()   # 拡大の前の「保存しますか」を出さない
            self.press("app:upscale2x")
            self.assertEqual(self.w.canvas.size_px(), (192, 256))


class PromptTest(Base):
    def test_register_from_menu_and_fix_whole_picture(self):
        self.w.entry.setText("背景を夕焼けに")
        with mock.patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("夕焼け", True)):
            self.actions()   # メニューを作れること
            user = self.submenu("指示で直す")
            next(a for a in user.actions() if a.text() == "今の指示を登録…").trigger()
        (p,) = self.w.shortcut_store().prompts()
        self.assertEqual((p["name"], p["text"]), ("夕焼け", "背景を夕焼けに"))
        self.w.entry.clear()
        before, calls = self.base(), len(self.painter.calls)
        self.press(p["id"])
        self.assertTrue(any(c[0] == "redraw" for c in self.painter.calls[calls:]))
        self.assertEqual(self.w.last_text, "背景を夕焼けに")
        self.assertIsNotNone(ImageChops.difference(before, self.base()).getbbox(alpha_only=False))
        self.assertIsNone(self.w.canvas.selection)   # 絵全体のために選んだ所は戻す

    def test_fix_inside_region_only(self):
        from PySide6.QtCore import QRect
        sid = self.w.add_prompt_shortcut("目を大きく", "目")
        self.w.canvas.set_selection(QRect(30, 40, 30, 30))
        before = self.base().convert("RGB")
        self.press(sid)
        after = self.base().convert("RGB")
        box = ImageChops.difference(before, after).getbbox()
        self.assertIsNotNone(box)
        self.assertTrue(box[0] >= 30 and box[1] >= 40 and box[2] <= 60 and box[3] <= 70, box)

    def test_dialog_favorite_rename_remove(self):
        dlg = self.w.open_shortcuts()
        sid = dlg.add_prompt("目を大きく", "目")
        self.assertEqual(dlg.current(), sid)
        dlg.toggle()
        dlg.rename("大きな目")
        top = [a for a in self.w.build_canvas_menu().actions() if a.objectName()]
        self.assertEqual((top[0].objectName(), top[0].text()), (sid, "★ 大きな目"))
        dlg.select("fin:clean")
        self.assertFalse(dlg.rem.isEnabled())   # アプリにある加工は消せない
        dlg.toggle()
        self.assertIn("fin:clean", self.w.shortcut_store().favorites())
        dlg.select(sid)
        dlg.remove()
        self.assertEqual(self.w.shortcut_store().prompts(), [])
        self.assertNotIn(sid, self.actions())
        dlg.close()


class EffectLayerTest(Base):
    def test_effect_is_own_layer_and_hiding_restores_original(self):
        for sid in ("fin:air_komorebi", "fin:mat_gem"):
            with self.subTest(sid=sid):
                self.w.edit_image(str(self.src))
                before, n = self.base(), len(self.w.canvas.layers)
                self.press(sid)
                top = self.w.canvas.layers[-1]
                self.assertEqual(len(self.w.canvas.layers), n + 1)
                self.assertTrue(top.name.startswith("エフェクト: "))
                self.assertIsNotNone(ImageChops.difference(before, self.base()).getbbox(alpha_only=False))
                top.visible = False   # 表示を切ると元の絵のまま（元の絵の画素は変えていない）
                self.assertIsNone(ImageChops.difference(before, self.base()).getbbox(alpha_only=False))


class StrengthTest(unittest.TestCase):
    def test_strength_follows_the_picture(self):
        from chatdraw import finishers
        bright, dark = Image.new("RGB", (64, 64), (250, 250, 245)), Image.new("RGB", (64, 64), (30, 30, 40))
        self.assertLess(finishers.strength_for(bright, "air"), finishers.strength_for(dark, "air"))
        vivid, dull = Image.new("RGB", (64, 64), (255, 0, 0)), Image.new("RGB", (64, 64), (128, 120, 120))
        self.assertLess(finishers.strength_for(vivid, "texture"), finishers.strength_for(dull, "texture"))
        for im in (bright, dark, vivid, dull, figure()):
            for k in ("air", "texture"):
                self.assertTrue(0.3 <= finishers.strength_for(im, k) <= 0.8)


class FetchPartsTest(Base):
    def test_missing_parts_are_fetched_on_press_then_applied(self):
        """部品が無いときも押せて、押すと取りに行き、取れたら続けて掛ける（pip は偽物、仕上げは本物）"""
        from chatdraw import finishers, setup
        real = finishers._has
        state = {"have": False}
        calls = []

        def has(*mods):
            if any(m in ("scipy", "skimage") for m in mods):
                return state["have"] and real(*mods)
            return real(*mods)

        def pip(args, *a, **k):
            calls.append(args)
            state["have"] = True
        with mock.patch.object(finishers, "_has", side_effect=has), mock.patch.object(setup, "run_pip", side_effect=pip):
            acts = self.actions()
            self.assertTrue(acts["fin:ink"].isEnabled(), acts["fin:ink"].toolTip())
            n = len(self.w.canvas.layers)
            self.press("fin:ink")
        self.assertEqual(len(calls), 1)
        self.assertIn("scikit-image", calls[0])
        self.assertIn("scipy", calls[0])
        self.assertEqual(len(self.w.canvas.layers), n + 1)

    def test_failed_fetch_ends_and_frees_buttons(self):
        from chatdraw import finishers, setup
        with mock.patch.object(finishers, "_has", side_effect=lambda *m: not any(x in ("scipy", "skimage") for x in m)), \
                mock.patch.object(setup, "run_pip", side_effect=RuntimeError("部品を入れられませんでした")):
            self.press("fin:ink")
        self.assertIsNone(self.w.thread)
        self.assertTrue(self.w.button.isEnabled())
        self.assertIsNone(self.w.activity.started)


if __name__ == "__main__":
    unittest.main()
