"""レイヤーの操作を、利用者と同じ経路（ボタン、右クリック、Delete キー、メニュー）で押して落ちないか。
前はレイヤーを消したあとの描き直しで落ちた（消したレイヤーの絵を空にしてから場面を作り直し、場面の索引が壊れた）。
落ちる不具合は描き直しのときに出るので、操作のたびに画面を実際に描かせる"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


class LayerCrashTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        for k in ("delete_layer", "delete_marks"):   # 消す前の窓は答えを覚えた形にする（窓の試験は test_menuaudit）
            self.w.layout_store.setValue(f"confirm/{k}", "yes")
        self.w.show()
        self.src = self.d / "a.png"
        figure().save(self.src)
        self.w.edit_image(str(self.src))
        self.c, self.lp = self.w.canvas, self.w.layer_panel
        self.pump()
        self.n0 = len(self.c.layers)   # 絵を開くと、絵と描く用の 2 枚になる

    def tearDown(self):
        from chatdraw import confirm
        confirm.forget(self.w)
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def pump(self):
        for _ in range(3):
            self.qapp.processEvents()
            self.c.viewport().repaint()
            self.lp.list.viewport().repaint()
        self.w.grab()

    def add(self, n=1):
        for _ in range(n):
            self.lp.buttons["add"].click()
            self.pump()

    def menu(self, row, text):
        """右クリックの窓を開いて、text で始まる項目を押す"""
        item = self.lp.list.item(row)
        pos = self.lp.list.visualItemRect(item).center()
        acts = [x for x in self.lp.context_menu(pos).actions() if x.text().startswith(text)]
        self.assertTrue(acts, text)
        acts[0].trigger()
        self.pump()

    def draw_mark(self):
        pen = self.c.redpen
        pen.begin(QPointF(10, 10))
        pen.add(QPointF(30, 30))
        pen.add(QPointF(50, 40))
        pen.end()
        self.pump()

    def test_delete_button_down_to_last(self):
        self.add(3)
        for left in [self.n0 + 2 - k for k in range(self.n0 + 2)] + [1, 1]:
            self.lp.buttons["delete"].click()
            self.pump()
            self.assertEqual(len(self.c.layers), left)
        self.c.undo()
        self.pump()
        self.assertEqual(len(self.c.layers), 2)   # 最後の 1 枚は消さずに透明にし、元に戻すでその前の 2 枚に戻る

    def test_delete_then_undo_redo(self):
        self.add(2)
        self.lp.buttons["delete"].click()
        self.pump()
        for _ in range(3):
            self.c.undo()
            self.pump()
        for _ in range(3):
            self.c.redo()
            self.pump()

    def test_delete_key(self):
        self.add(2)
        self.w.activateWindow()
        self.lp.list.setFocus()
        self.pump()
        QTest.keyClick(self.lp.list, Qt.Key_Delete)
        self.pump()
        self.assertEqual(len(self.c.layers), self.n0 + 1)

    def test_context_menu_delete_selected_and_other(self):
        self.add(3)
        self.menu(self.lp.row_of(0), "レイヤーを消す")   # 選んでいない一番下の行
        self.assertEqual(len(self.c.layers), self.n0 + 2)
        self.menu(self.lp.row_of(self.c.current), "レイヤーを消す")
        self.assertEqual(len(self.c.layers), self.n0 + 1)

    def test_menu_bar_delete(self):
        self.add(1)
        acts = [a for m in self.w.menuBar().actions() if m.menu() for a in m.menu().actions()
                if a.text() == "レイヤーを消す"]
        self.assertTrue(acts)
        acts[0].trigger()
        self.pump()
        self.assertEqual(len(self.c.layers), self.n0)

    def test_redpen_rows(self):
        self.draw_mark()
        self.draw_mark()
        self.assertEqual(self.lp.list.count(), len(self.c.layers) + 2)
        self.lp.list.setCurrentRow(0)
        self.pump()
        self.assertTrue(self.lp.list.currentItem().text().startswith("赤ペン"))   # 作り直しても赤ペンの行のまま
        self.lp.buttons["delete"].click()
        self.pump()
        self.assertEqual(len(self.c.redpen.marks), 1)
        self.menu(0, "赤ペン 1 を消す")
        self.assertEqual(len(self.c.redpen.marks), 0)
        self.draw_mark()
        self.menu(0, "赤ペンの印を全部消す")
        self.assertEqual(len(self.c.redpen.marks), 0)
        self.draw_mark()
        item = self.lp.list.item(0)
        item.setCheckState(Qt.Unchecked)
        self.pump()
        self.assertTrue(self.c.redpen.hidden[0])

    def test_ai_layer_row(self):
        self.c.add_image_layer(str(self.src), "AI の絵")
        self.pump()
        self.assertEqual(self.c.layers[self.c.current].name, "AI の絵")
        self.menu(self.lp.row_of(self.c.current), "レイヤーを消す")
        self.assertNotIn("AI の絵", [x.name for x in self.c.layers])
        self.c.undo()
        self.pump()
        self.assertIn("AI の絵", [x.name for x in self.c.layers])

    def test_other_layer_operations(self):
        self.add(3)
        for key in ("up_b", "down_b", "down_b"):
            self.lp.buttons[key].click()
            self.pump()
        for key in ("up", "down", "lock", "lock"):
            self.lp.buttons[key].trigger()
            self.pump()
        self.menu(self.lp.row_of(self.c.current), "下と結合")
        self.assertEqual(len(self.c.layers), self.n0 + 2)
        self.menu(self.lp.row_of(self.c.current), "1 つ上へ")
        self.menu(self.lp.row_of(self.c.current), "1 つ下へ")
        self.menu(self.lp.row_of(self.c.current), "ロック")
        item = self.lp.list.item(self.lp.row_of(1))
        item.setCheckState(Qt.Unchecked)
        self.pump()
        self.assertFalse(self.c.layers[1].visible)
        item = self.lp.list.item(self.lp.row_of(1))
        item.setText("名前")
        self.pump()
        self.assertEqual(self.c.layers[1].name, "名前")
        self.c.move_layer_to(0, 2)   # ドラッグの並べ替えが呼ぶ所
        self.pump()
        self.menu(0, "見えているレイヤーを結合")
        self.assertEqual(len(self.c.layers), 1)
        self.lp.buttons["delete"].click()
        self.pump()
        for _ in range(6):
            self.c.undo()
            self.pump()


if __name__ == "__main__":
    unittest.main()
