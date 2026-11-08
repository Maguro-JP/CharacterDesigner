"""右クリックのメニューと AI プリセットの精査の試験。

全部の右クリックのメニュー（キャンバス、レイヤーの欄、履歴、ライブラリー、欄の見出し、帯の中身）の項目を、
本物と同じ経路で 1 つずつ押し、例外が出ないことを確かめる。窓（ファイルを選ぶ・文字を書く・確かめ）は開かずに「やめる」で返す。
AI プリセットは偽の模型で 1 つずつ実際に描き、最後まで描けて、決まった言葉が頼みに足されることを確かめる"""
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg, wait_idle  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def no_dialogs():
    """押した項目が開く窓を、開かずに「やめる」で返す（試験が止まらないように）"""
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QColorDialog, QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox
    from PySide6.QtGui import QColor
    st = ExitStack()
    for obj, name, val in ((QMenu, "exec", None), (QDialog, "exec", 0), (QMessageBox, "exec", 0),
                           (QInputDialog, "getText", ("", False)), (QInputDialog, "getInt", (0, False)),
                           (QInputDialog, "getItem", ("", False)), (QInputDialog, "getDouble", (0.0, False)),
                           (QInputDialog, "getMultiLineText", ("", False)),
                           (QFileDialog, "getOpenFileName", ("", "")), (QFileDialog, "getOpenFileNames", ([], "")),
                           (QFileDialog, "getSaveFileName", ("", "")), (QFileDialog, "getExistingDirectory", ""),
                           (QColorDialog, "getColor", QColor()), (QDesktopServices, "openUrl", True)):
        st.enter_context(mock.patch.object(obj, name, return_value=val))
    return st


_KEEP = []   # 作ったメニューを試験の間手放さない（手放すと、小さなメニューの中の項目が先に消えた）


def walk(menu, path=()):
    """メニューの項目を、小さなメニューの中まで (道, 項目) で並べる"""
    _KEEP.append(menu)
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        p = path + (a.text(),)
        if a.menu() is not None:
            out += walk(a.menu(), p)
        else:
            out.append((p, a))
    return out


def find(menu, path):
    """道をたどって項目を探す。たどった小さなメニューは手放さない"""
    cur, act = menu, None
    for i, name in enumerate(path):
        act = next((x for x in cur.actions() if not x.isSeparator() and x.text() == name), None)
        if act is None:
            return None
        if i < len(path) - 1:
            cur = act.menu()
            if cur is None:
                return None
            _KEEP.append(cur)
    return act


class Base(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        self.w.show()
        self.src = self.d / "a.png"
        figure().save(self.src)

    def tearDown(self):
        from chatdraw import confirm
        wait_idle(self.qapp, self.w, 60)
        confirm.forget(self.w)
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def pump(self):
        wait_idle(self.qapp, self.w, 300)
        wait_bg(self.qapp, self.w, 30)
        self.qapp.processEvents()

    def draw_once(self, text="雪の城の前の騎士"):
        self.w.entry.setText(text)
        self.w.send()
        self.pump()

    def mark(self):
        pen = self.w.canvas.redpen
        pen.begin(QPointF(10, 10))
        pen.add(QPointF(40, 30))
        pen.add(QPointF(50, 50))
        pen.end()
        self.qapp.processEvents()


class EveryMenuItemTest(Base):
    """右クリックの項目を全部押す。押すたびにメニューを作り直す（押した項目が欄を作り直し、前の項目が消えるため）"""

    def setUp(self):
        super().setUp()
        # 加工の項目（綺麗にする・拡大など）は、押したときの確かめ（使えるか、処理の途中か、回数を数える）までは本物の
        # run_shortcut を通し、加工そのもの（姿勢の模型などを読む重い処理）だけを止める。加工の中身は test_shortcuts が流す
        from chatdraw import shortcuts
        real = shortcuts.all_items
        self.ran = []

        def items(w, store):
            out = real(w, store)
            for s in out:
                s.run = (lambda sid=s.id: self.ran.append(sid))
            return out
        p = mock.patch.object(shortcuts, "all_items", items)
        p.start()
        self.addCleanup(p.stop)

    def press_all(self, name, build, setup=None):
        if setup:
            setup()
        paths = [p for p, _ in walk(build())]
        self.assertTrue(paths, name)
        pressed = 0
        with no_dialogs():
            for p in paths:
                with self.subTest(menu=name, item=" > ".join(p)):
                    if setup:
                        setup()
                    m = build()
                    a = find(m, p)
                    if a is None:   # 前の項目で状態が変わり、出なくなった（例: 印を全部消したあとの印の項目）
                        continue
                    if not a.isEnabled():
                        self.assertTrue(a.toolTip() or a.menu() is not None or p[-1].startswith(("元に戻す", "やり直す")),
                                        f"押せない理由がツールチップに無い: {p}")
                        continue
                    a.trigger()
                    self.pump()
                    pressed += 1
                    for top in self.qapp.topLevelWidgets():   # 押して開いた窓（比べる、ごみ箱など）は閉じる
                        if top is not self.w and top.isWindow() and top.isVisible() and top.windowType() != Qt.ToolTip:
                            top.close()
        return pressed

    def test_canvas_menu(self):
        self.draw_once()

        def setup():
            if not self.w.canvas.redpen.marks:
                self.mark()
        n = self.press_all("キャンバス", lambda: self.w.build_canvas_menu(), setup)
        self.assertGreater(n, 20)
        self.assertTrue(self.ran, "加工の項目を押しても run_shortcut まで届いていない")

    def test_canvas_menu_with_selection(self):
        from PySide6.QtCore import QRectF
        self.draw_once()

        def setup():
            c = self.w.canvas
            if c.selection is None and hasattr(c, "set_selection_rect"):
                c.set_selection_rect(QRectF(5, 5, 30, 30))
        self.press_all("キャンバス（選択）", lambda: self.w.build_canvas_menu(), setup)

    def test_layer_menu(self):
        self.w.edit_image(str(self.src))
        self.pump()
        lp, c = self.w.layer_panel, self.w.canvas

        def setup():
            while len(c.layers) < 3:
                c.add_layer()
            if not c.redpen.marks:
                self.mark()
            lp.refresh()
        self.w.layout_store.setValue("confirm/delete_layer", "yes")
        self.w.layout_store.setValue("confirm/delete_marks", "yes")
        for label, row in (("レイヤー", lambda: lp.row_of(c.current)), ("赤ペン", lambda: 0)):
            def build(row=row):
                setup()
                return lp.context_menu(lp.list.visualItemRect(lp.list.item(row())).center())
            self.press_all("レイヤーの欄・" + label, build, setup)
        self.press_all("レイヤーの欄・空き", lambda: lp.context_menu(QPoint(-5, -5)), setup)

    def test_history_and_library_menu(self):
        self.draw_once()
        self.draw_once("海辺の魔法使い")
        h = self.w.history

        def hist():
            if h.count() == 0:
                self.draw_once()
            return self.w._history_menu(h.visualItemRect(h.item(0)).center(), run=False)
        self.press_all("履歴", hist)
        self.press_all("履歴・空き", lambda: self.w._history_menu(QPoint(-5, -5), run=False))
        lib = self.w.library_panel
        lib.refresh()

        def libm():
            lib.refresh()
            if lib.works.count() == 0:
                self.draw_once()
                lib.refresh()
            return lib._menu(lib.works, lib.works.visualItemRect(lib.works.item(0)).center(), run=False)
        if lib.works.count():
            self.press_all("ライブラリー", libm)
        self.press_all("ライブラリー・空き", lambda: lib._menu(lib.works, QPoint(-5, -5), run=False))

    def test_panel_menus(self):
        for key in self.w.panels:
            self.press_all(f"欄 {key}", lambda k=key: self.w.area_menu(k))
            d = self.w.panels[key][0]
            bar = d.titleBarWidget()
            if hasattr(bar, "place_menu"):
                self.press_all(f"欄の見出し {key}", lambda b=bar: b.place_menu())
                d.setFloating(False)
                d.show()

    def test_bar_contents(self):
        """帯の中身: 頼んだ言葉・禁止ワード・自分のプリセット・単語・リボン・帯の出し入れ"""
        self.draw_once("赤いマフラー")
        self.w.pin_prompt("青い帽子")
        self.press_all("頼んだ言葉", lambda: self.w.build_chip_menu("赤いマフラー", False))
        self.press_all("登録した言葉", lambda: self.w.build_chip_menu("青い帽子", True),
                       lambda: self.w.pin_prompt("青い帽子"))
        self.press_all("禁止ワード", lambda: self.w.build_neg_chip_menu("lowres"),
                       lambda: self.w.pin_negative("lowres"))
        p = self.w.ai_panel
        self.press_all("自分のプリセット", lambda: p.own_menu("試し"),
                       lambda: "試し" in p.own_presets() or p.save_preset("試し", p.current()))
        self.press_all("リボン", self.w._ribbon_menu)
        self.press_all("帯の出し入れ", self.w.createPopupMenu)
        row = self.w.word_row
        self.press_all("単語", lambda: row.menu(None, QPoint(0, 0), "1girl", run=False))
        dlg = row.open_dialog()
        if getattr(dlg, "dict_rows", None):
            tag = dlg.dict_rows[0]["tag"]
            self.press_all("単語辞書", lambda: dlg.table_menu(tag))
        dlg.close()


class OrderTest(Base):
    def test_delete_items_are_last_below_separator(self):
        """消す物は区切り線の下、一番下にある"""
        self.draw_once()
        self.mark()
        h = self.w.history
        menus = {"キャンバス": self.w.build_canvas_menu(),
                 "履歴": self.w._history_menu(h.visualItemRect(h.item(0)).center(), run=False),
                 "レイヤー": self.w.layer_panel.context_menu(
                     self.w.layer_panel.list.visualItemRect(self.w.layer_panel.list.item(
                         self.w.layer_panel.row_of(self.w.canvas.current))).center())}
        for name, m in menus.items():
            with self.subTest(menu=name):
                acts = m.actions()
                dels = [i for i, a in enumerate(acts) if "消す" in a.text() and not a.isSeparator()]
                self.assertTrue(dels, name)
                first = dels[0]
                self.assertTrue(acts[first - 1].isSeparator(), name)
                self.assertTrue(all("消す" in a.text() for a in acts[first:]), [a.text() for a in acts[first:]])

    def test_no_duplicate_names_in_one_menu(self):
        self.draw_once()
        self.mark()
        h = self.w.history
        for m in (self.w.build_canvas_menu(), self.w._history_menu(h.visualItemRect(h.item(0)).center(), run=False)):
            top = [a.text() for a in m.actions() if not a.isSeparator()]
            self.assertEqual(len(top), len(set(top)), top)


class LayerDeleteConfirmTest(Base):
    def test_drawn_layer_asks_and_remembers(self):
        from chatdraw.tests.test_confirm import answer
        c, lp = self.w.canvas, self.w.layer_panel
        self.w.edit_image(str(self.src))
        self.pump()
        n = len(c.layers)
        c.add_layer()   # 何も描いていないレイヤーは聞かずに消す
        lp.delete_layer()
        self.assertEqual(len(c.layers), n)
        self.assertIsNone(getattr(self.w, "_confirm_box", None))
        c.add_image_layer(str(self.src), "AI の絵")
        seen = []
        answer(self.w, "やめる", seen=seen)
        lp.delete_layer()
        self.assertEqual(len(c.layers), n + 1)   # やめたら消さない
        self.assertIn("AI の絵", seen[0])
        answer(self.w, "消す", again=True)
        lp.delete_layer()
        self.assertEqual(len(c.layers), n)
        c.add_image_layer(str(self.src), "AI の絵 2")
        lp.buttons["delete"].click()   # 「次から聞かない」を選んだので、窓を出さずに消す
        self.assertEqual(len(c.layers), n)
        c.undo()
        self.assertEqual(len(c.layers), n + 1)   # 元に戻すで戻せる


class RichMenuTest(Base):
    """普通の絵のアプリにある項目が右クリックにあり、押すと効く"""

    def test_canvas_items(self):
        from PySide6.QtCore import QRect
        self.w.edit_image(str(self.src))
        self.pump()
        c = self.w.canvas
        g = c.viewport().mapToGlobal(c.mapFromScene(QPointF(20, 20)))
        m = self.w.build_canvas_menu(g)
        texts = [p for p, _ in walk(m)]
        for want in (("コピー",), ("貼り付け",), ("色を拾う",), ("ここを AI で直す",), ("言葉で指示…",),
                     ("選択範囲", "選択を反転"), ("選択範囲", "レイヤーに切り出す"), ("表示を回す", "右に回す"),
                     ("表示を回す", "回転を戻す")):
            self.assertIn(want, texts)
        self.assertFalse(find(m, ("選択範囲", "選択を反転")).isEnabled())   # 選んでいないときは押せない
        c.set_selection(QRect(5, 5, 20, 20))
        n = len(c.layers)
        self.assertTrue(c.selection_to_layer())
        self.assertEqual(len(c.layers), n + 1)
        self.assertTrue(c.invert_selection())
        self.assertIsNotNone(c.selection_shape)
        c.set_selection(None)
        with mock.patch.object(self.w, "send") as send:
            find(self.w.build_canvas_menu(g), ("ここを AI で直す",)).trigger()
        send.assert_called_once()
        self.assertEqual(self.w.mode.currentIndex(), 2)
        self.assertIsNotNone(c.selection)

    def test_layer_items(self):
        self.w.edit_image(str(self.src))
        self.pump()
        lp, c = self.w.layer_panel, self.w.canvas
        m = lp.context_menu(lp.list.visualItemRect(lp.list.item(lp.row_of(c.current))).center())
        n = len(c.layers)
        find(m, ("複製",)).trigger()
        self.assertEqual(len(c.layers), n + 1)
        self.assertTrue(c.layers[c.current].name.endswith("の写し"))
        m = lp.context_menu(lp.list.visualItemRect(lp.list.item(lp.row_of(c.current))).center())
        find(m, ("不透明度", "50%")).trigger()
        self.assertAlmostEqual(c.layers[c.current].opacity, 0.5, places=2)
        for want in (("下と結合",), ("名前を変える",)):
            self.assertIsNotNone(find(m, want))


class EditContextMenuTest(Base):
    """右クリックの項目を、設定から隠す・並べ替える・言葉の指示を足す"""

    def test_hide_reorder_and_add_prompt(self):
        from chatdraw.menuedit import CTX
        ed = self.w.menus_editor
        self.assertIn(CTX + "キャンバス", ed.context_names())
        entries = ed.entries(CTX + "キャンバス")
        keys = [k for k, _t, _on in entries]
        self.assertIn("言葉で指示…", keys)
        order = ["タイムラプスを見る…"] + [k for k in keys if k != "タイムラプスを見る…"]
        ed.set(CTX + "キャンバス", order, ["言葉で指示…"])
        top = [a.text() for a in self.w.build_canvas_menu().actions() if not a.isSeparator()]
        self.assertEqual(top[0], "タイムラプスを見る…")
        self.assertNotIn("言葉で指示…", top)
        with no_dialogs(), mock.patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("目だけ", True)):
            self.w.entry.setText("目を大きく")
            dlg = self.w.edit_menus()
            dlg.pick.setCurrentText(CTX + "キャンバス")
            self.assertTrue(dlg.add_prompt.isVisibleTo(dlg))
            dlg.add_prompt.click()
        self.assertIn("目だけ", [a.text() for a in self.w.build_canvas_menu().actions()])
        ed.reset()
        top = [a.text() for a in self.w.build_canvas_menu().actions()]
        self.assertIn("言葉で指示…", top)


class PresetTest(Base):
    def test_every_preset_draws_to_the_end(self):
        from chatdraw import aipanel
        p = self.w.ai_panel
        self.w.edit_image(str(self.src))   # ラフから描くプリセットのためにキャンバスに線を置く
        self.pump()
        for name, *_ in aipanel.PRESETS + [(k,) for k in aipanel.MERGED]:
            with self.subTest(preset=name):
                before = len(self.painter.calls)
                self.assertTrue(p.apply_name(name))
                self.w.entry.setText("赤いマフラーの子")
                self.w.send()
                self.pump()
                self.assertGreater(len(self.painter.calls), before, "描いていない")
                prompt = self.painter.calls[-1][1] if self.painter.calls[-1][0] == "redraw" else self.painter.calls[-1][0]
                self.assertIn("1girl, red scarf", prompt)   # 頼んだ言葉が残っている
                to, style = aipanel.MERGED.get(name, (name, None))
                for tag in filter(None, aipanel.PROMPT_SUFFIX.get(to, "").split(", ")):
                    self.assertIn(tag, prompt)
                if style:
                    self.assertEqual(p.style, style)

    def test_presets_do_not_overlap_or_override_request(self):
        from chatdraw import aipanel
        keys = [(m, s, st, k, aipanel.PROMPT_SUFFIX.get(n, "")) for n, _sub, m, s, st, k in aipanel.PRESETS]
        self.assertEqual(len(keys), len(set(keys)), "同じ中身のプリセットがある")
        names = [n for n, *_ in aipanel.PRESETS]
        self.assertNotIn("赤ペンで直す", names)
        for n, tags in aipanel.PROMPT_SUFFIX.items():
            self.assertIn(n, names)
            for bad in ("looking at viewer", "expressive", "smile", "1girl", "1boy"):   # 頼みの中身を決める言葉は足さない
                self.assertNotIn(bad, tags, n)


if __name__ == "__main__":
    unittest.main()
