"""右クリックのメニューと AI プリセットの精査の試験（右クリックの編集・並び、プリセット）。
項目を全部押す試験は、画面の基本と赤ペンの機能と一緒に戻す（ここでは見ない）。

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


class OrderTest(Base):
    def test_no_duplicate_names_in_one_menu(self):
        self.draw_once()
        self.mark()
        h = self.w.history
        for m in (self.w.build_canvas_menu(), self.w._history_menu(h.visualItemRect(h.item(0)).center(), run=False)):
            top = [a.text() for a in m.actions() if not a.isSeparator()]
            self.assertEqual(len(top), len(set(top)), top)


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



class PresetEditTest(Base):
    """自分のプリセットを作る・直す。描くワード・禁止ワード・枚数・種を固定し、当てると欄に入って、その言葉で描く"""

    def test_make_edit_apply_and_draw(self):
        p = self.w.ai_panel
        p.edit_preset  # noqa: B018  作風のタブのボタンから開く窓
        self.assertTrue(p.new_button.toolTip())
        dlg = p.edit_preset(run=False)
        dlg.name.setText("白地の騎士")
        dlg.size.setCurrentText("横")
        dlg.count.setValue(2)
        dlg.seed.setValue(1234)
        dlg.words.setPlainText("knight, silver armor")
        dlg.negative.setText("hat")
        p.finish_edit(dlg)
        own = p.own_presets()["白地の騎士"]
        self.assertEqual((own["size"], own["count"], own["seed"], own["words"], own["negative"]),
                         ("横", 2, 1234, "knight, silver armor", "hat"))
        # 名前を変えて直す（前の名前は残さない）
        dlg = p.edit_preset("白地の騎士", run=False)
        self.assertEqual(dlg.words.toPlainText(), "knight, silver armor")
        dlg.name.setText("騎士")
        p.finish_edit(dlg, "白地の騎士")
        self.assertNotIn("白地の騎士", p.own_presets())
        self.assertIn("騎士", p.own_presets())
        self.assertIn("編集…", [a.text() for a in p.own_menu("騎士").actions()])
        # 当てると欄に入る
        self.w.entry.setText("")
        self.assertTrue(p.apply_name("騎士"))
        self.assertEqual(self.w.entry.text(), "knight, silver armor")
        self.assertEqual(p.negative.text(), "hat")
        self.assertEqual(p.count(), 2)
        self.assertEqual(p.seeds(), [1234, 1235])
        before = len(self.painter.calls)
        self.w.send()
        self.pump()
        self.assertGreater(len(self.painter.calls), before, "描いていない")
        self.assertIn("knight", str(self.painter.calls[before]))

    def test_pin_draw_words_to_preset(self):
        """描くワードの右クリックから、その言葉をプリセットに固定する"""
        dlg = self.w.preset_from_words("red scarf girl, smiling", run=False)
        self.assertEqual(dlg.words.toPlainText(), "red scarf girl, smiling")
        self.w.ai_panel.finish_edit(dlg)
        self.assertEqual(self.w.ai_panel.own_presets()[dlg.name.text().strip()]["words"], "red scarf girl, smiling")

if __name__ == "__main__":
    unittest.main()
