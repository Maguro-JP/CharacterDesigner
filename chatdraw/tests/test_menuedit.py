"""メニューと帯の編集・帯の固定・よく使う帯・同じ働きの操作の共用・欄の中の右クリック・窓の枠のテーマの試験"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QContextMenuEvent  # noqa: E402
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QMenu, QPlainTextEdit,  # noqa: E402
                               QLabel, QScrollBar, QTextEdit, QWidget)
from chatdraw.tests.test_panels import done, fresh  # noqa: E402
from chatdraw.tests.test_uifix import spin  # noqa: E402

KEYS = ("menus/prefs", "bars/locked", "bars/quickbar", "bars/tools", "bars/panelbar", "bars/bottombar", "ribbon/order")


def clean(w):
    for k in KEYS:
        w.layout_store.remove(k)


def titles(w):
    return [a.text() for a in w.menuBar().actions()]


class MenuEditTest(unittest.TestCase):
    def test_hide_and_reorder_menus_and_items_and_keep(self):
        from chatdraw.menuedit import TOP
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                ed = w.menus_editor
                names = titles(w)
                self.assertIn("ヘルプ", names)
                order = ["ヘルプ"] + [n for n in names if n != "ヘルプ"]
                ed.set(TOP, order, ["ロゴ・スタンプ"])
                self.assertEqual(titles(w)[0], "ヘルプ")
                self.assertNotIn("ロゴ・スタンプ", titles(w))
                # 項目: 「編集」のやり直すを先に、赤ペンの印を全部消すを隠す。キーは効いたまま
                items = [k for k, _t, _on in ed.entries("編集")]
                ed.set("編集", ["やり直す"] + [k for k in items if k != "やり直す"], ["赤ペンの印を全部消す"])
                edit = ed.top_menus()["編集"]
                texts = [a.text() for a in edit.actions()]
                self.assertEqual(texts[0], "やり直す")
                self.assertNotIn("赤ペンの印を全部消す", texts)
                self.assertIn(w.shared["redpen_clear"], w.actions())
                # 作り直すメニュー（テーマ）は、開くたびに並びを当てる
                view = [k for k, _t, _on in ed.entries("表示")]
                ed.set("表示", list(reversed(view)), [])
                ed.top_menus()["表示"].aboutToShow.emit()
                self.assertEqual(ed.top_menus()["表示"].actions()[0].text().replace("&", ""), view[-1])
                # 新しい窓（次の起動・新しい版）でも覚えている
                w2 = fresh(d)
                self.assertEqual(titles(w2)[0], "ヘルプ")
                self.assertNotIn("ロゴ・スタンプ", titles(w2))
                self.assertEqual(w2.menus_editor.top_menus()["編集"].actions()[0].text(), "やり直す")
                w2.menus_editor.reset()
                self.assertEqual(titles(w2), names)
                done(w2)
            finally:
                clean(w)
                done(w)

    def test_dialog_unchecks_and_moves(self):
        from chatdraw.menuedit import MenuEditor
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                dlg = MenuEditor(w, w.menus_editor)
                dlg.pick.setCurrentText("選択範囲")
                dlg.list.setCurrentRow(1)
                dlg.findChildren(type(dlg.pick.parent()), "")  # 窓が作れる
                from chatdraw.menuedit import _move
                _move(dlg.list, -1)
                dlg.list.item(1).setCheckState(Qt.Unchecked)
                dlg._ok()
                acts = [a.text() for a in w.menus_editor.top_menus()["選択範囲"].actions()]
                self.assertEqual(acts[0], "選択を解除")
                self.assertNotIn("すべてを選択", acts)
                self.assertIn(w.shared["select_all"], w.actions())   # Ctrl+A は効いたまま
            finally:
                clean(w)
                done(w)


class BarEditTest(unittest.TestCase):
    def test_quick_bar_has_common_actions(self):
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                acts = w.quick_bar.actions()
                for a in (w.shared["undo"], w.shared["redo"], w.tool_actions["redpen"], w.shared["draw"], w.emergency_stop):
                    self.assertIn(a, acts)
                self.assertTrue(all(a.toolTip() for a in acts if not a.isSeparator()))
            finally:
                clean(w)
                done(w)

    def test_add_remove_separator_reorder_and_keep(self):
        from chatdraw.menuedit import SEP, BarEditor
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                be = w.bars_editor
                keys = ["redo", SEP, "undo", "tool:eraser", SEP, "stop"]
                be.set("よく使う帯", keys)
                self.assertEqual(be.ids(w.quick_bar), keys)
                w2 = fresh(d)
                self.assertEqual(w2.bars_editor.ids(w2.quick_bar), keys)
                w2.bars_editor.reset("よく使う帯")
                self.assertNotEqual(w2.bars_editor.ids(w2.quick_bar), keys)
                done(w2)
                # 編集の窓: 足す・区切り・外す
                dlg = BarEditor(w, be)
                dlg.pick.setCurrentText("下の帯")
                n = dlg.list.count()
                dlg.pool.setCurrentIndex(dlg.pool.findData("tool:pen"))
                dlg._add()
                dlg._sep()
                self.assertEqual(dlg.list.count(), n + 2)
                dlg.list.setCurrentRow(0)
                dlg._remove()
                dlg._ok()
                ids = be.ids(w.bottom_bar)
                self.assertIn("tool:pen", ids)
                self.assertNotIn("undo", ids)
                self.assertIn("zoom_slider", ids)   # 拡大率の棒も帯の物として残る
            finally:
                clean(w)
                done(w)

    def test_lock_stops_moving(self):
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                w.lock_bars_action.setChecked(True)
                for bar in (w.tools, w.quick_bar, w.panel_bar, w.bottom_bar, w.options):
                    self.assertFalse(bar.isMovable(), bar.objectName())
                self.assertFalse(w.ribbon.tabBar().isMovable())
                w2 = fresh(d)
                self.assertFalse(w2.tools.isMovable())
                self.assertTrue(w2.lock_bars_action.isChecked())
                w2.lock_bars_action.setChecked(False)
                self.assertTrue(w2.tools.isMovable())
                self.assertTrue(w2.ribbon.tabBar().isMovable())
                done(w2)
            finally:
                clean(w)
                done(w)

    def test_ribbon_tab_order_kept(self):
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                first = w.ribbon.tabText(0)
                w.ribbon.tabBar().moveTab(0, w.ribbon.count() - 1)
                w2 = fresh(d)
                self.assertEqual(w2.ribbon.tabText(w2.ribbon.count() - 1), first)
                done(w2)
            finally:
                clean(w)
                done(w)

    def test_popup_menu_offers_editing(self):
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                m = w.createPopupMenu()
                for a in (w.edit_bars_action, w.edit_menus_action, w.lock_bars_action):
                    self.assertIn(a, m.actions())
            finally:
                clean(w)
                done(w)


class SharedActionTest(unittest.TestCase):
    def test_menu_ribbon_and_bar_use_same_action(self):
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                from PySide6.QtWidgets import QToolButton
                ribbon = {b.defaultAction() for b in w.ribbon.findChildren(QToolButton) if b.defaultAction()}
                menus = {a for m in w.menus_editor.top_menus().values() for a in m.actions()}
                for k in ("new", "open", "save", "undo", "redo", "select_all", "deselect", "fit", "actual", "rotate_right", "tour"):
                    self.assertIn(w.shared[k], ribbon, k)
                    self.assertIn(w.shared[k], menus, k)
                for k in ("undo", "redo", "fit", "rotate_right", "rotate_reset"):
                    self.assertIn(w.shared[k], w.bottom_bar.actions(), k)
                # 同じ見出しの別の QAction がメニューとリボンに分かれていない
                ribbon_texts = {a.text() for a in ribbon}
                twins = [a.text() for a in menus if a.text() in ribbon_texts and a not in ribbon and not a.isSeparator()]
                self.assertEqual(twins, [])
            finally:
                clean(w)
                done(w)


OWN_MENU = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QScrollBar)   # Qt が自分のメニューを出す部品


class AreaMenuTest(unittest.TestCase):
    def test_right_click_anywhere_in_every_panel_shows_menu(self):
        """欄（AI の欄のタブを外へ出した欄も）の中の、どの部品を右クリックしてもメニューが出る"""
        with TemporaryDirectory() as d:
            w = fresh(d)
            try:
                name = w.ai_tabs.order()[-1]
                w.ai_tabs.pull_out(name, None)
                spin()
                docks = [dk for dk, _a in w.panels.values()] + list(w.ai_tabs.docks.values())
                missed = []
                for dock in docks:
                    dock.show()
                    spin(2)
                    for wd in [dock] + dock.findChildren(QWidget):
                        # 押せない部品には右クリックが届かない。文字を選べる見出しは Qt の写しのメニューを出す
                        if not wd.isVisible() or not wd.isEnabled() or isinstance(wd, OWN_MENU) or isinstance(wd, QMenu) or (
                                isinstance(wd, QLabel) and wd.textInteractionFlags() & Qt.TextSelectableByMouse):
                            continue
                        if any(isinstance(p, OWN_MENU) for p in _parents(wd, dock)):
                            continue
                        shown = []
                        # Qt が中で開くメニュー（文字を選べる見出しなど）は止まって待つので、開いたら数えて閉じる
                        guard = QTimer()
                        guard.timeout.connect(lambda: (QApplication.activePopupWidget() or QApplication.activeModalWidget()) and (
                            shown.append(1), (QApplication.activePopupWidget() or QApplication.activeModalWidget()).close()))
                        guard.start(20)
                        with mock.patch.object(QMenu, "exec", lambda m, *a, **k: shown.append(m)), \
                                mock.patch.object(QMenu, "popup", lambda m, *a, **k: shown.append(m)):
                            e = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(2, 2), wd.mapToGlobal(QPoint(2, 2)))
                            QApplication.sendEvent(wd, e)
                        guard.stop()
                        if not shown:
                            missed.append(f"{dock.objectName()}:{type(wd).__name__}:{wd.objectName()}")
                self.assertEqual(missed, [])
            finally:
                w.ai_tabs.reset()
                clean(w)
                done(w)


def _parents(wd, stop):
    p = wd.parentWidget()
    while p is not None and p is not stop:
        yield p
        p = p.parentWidget()


class TitleBarTest(unittest.TestCase):
    def test_title_bar_follows_theme_on_windows(self):
        from chatdraw import themes
        app = QApplication.instance() or QApplication([])
        calls = []
        w = QWidget()
        w.show()
        with mock.patch.object(themes.sys, "platform", "win32"), \
                mock.patch.object(themes, "_set_dwm", lambda h, a, v: calls.append((a, v)) or True):
            themes.apply(app, "ナイト" if "ナイト" in themes.all_names() else themes.DEFAULT)
            self.assertIn(20, [a for a, _v in calls])
            calls.clear()
            from PySide6.QtWidgets import QDialog
            dlg = QDialog()
            dlg.show()   # 後から開く窓にも、前に出たときに当たる
            app.focusWindowChanged.emit(dlg.windowHandle())
            self.assertIn(20, [a for a, _v in calls])
            dlg.close()
        w.close()
        self.assertFalse(themes.title_bar(QWidget()))   # Windows でなければ触らない


if __name__ == "__main__":
    unittest.main()
