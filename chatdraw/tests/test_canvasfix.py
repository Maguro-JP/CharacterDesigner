"""赤ペンの印ごとのレイヤーの行、右クリックの「囲んだ所を直す」、レイヤーの重なり順、レイヤーの削除と保存、作成枚数の欄"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, Qt  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.layerpanel import ROLE_INDEX  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def mark(pen, x, y):
    pen.begin(QPointF(x, y))
    for i in range(12):
        pen.add(QPointF(x + 5 * i, y + 3 * i))
    pen.end()


class CanvasFixTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        self.w.layout_store.setValue("confirm/delete_marks", "yes")   # 消す前の窓は答えを覚えた形にする
        self.src = self.d / "a.png"
        figure().save(self.src)

    def tearDown(self):
        self.w.layout_store.remove("confirm/delete_marks")
        self.w.close()
        self.tmp.cleanup()

    def pen_rows(self):
        lst = self.w.layer_panel.list
        return [lst.item(r) for r in range(lst.count()) if lst.item(r).data(ROLE_INDEX) < 0]

    def test_redpen_rows(self):
        c = self.w.canvas
        c.replace_with_image(str(self.src))
        mark(c.redpen, 10, 10)
        mark(c.redpen, 100, 100)
        c.redpen.set_text(1, "手を直して")
        self.w.layer_panel.refresh()
        rows = self.pen_rows()
        self.assertEqual([r.text() for r in rows], ["赤ペン 2", "赤ペン 1: 手を直して"])
        self.assertIn("手を直して", rows[1].toolTip())
        rows[1].setCheckState(Qt.Unchecked)   # 隠すと、その印だけ隠れて直さない
        self.assertEqual(c.redpen.hidden, [True, False])
        self.assertEqual(c.redpen.shown(), [2])
        self.assertEqual(len(self.w.fix_regions("")), 1)
        self.w.layer_panel.refresh()
        self.pen_rows()[0].setText("赤ペン 2: 帽子を青に")   # 行の名前で指示を書き直す
        self.assertEqual(c.redpen.texts[1], "帽子を青に")
        self.w.layer_panel.refresh()
        self.w.layer_panel.list.setCurrentItem(self.pen_rows()[0])
        self.assertEqual(c.redpen.focus, 2)   # 選んだ印だけ指示の札を出す
        self.w.layer_panel._delete()
        self.assertEqual(len(c.redpen.marks), 1)
        self.assertEqual(c.redpen.texts, ["手を直して"])

    def test_fix_from_menu(self):
        c = self.w.canvas
        c.replace_with_image(str(self.src))
        mark(c.redpen, 10, 10)
        menu = self.w.build_canvas_menu()
        act = next(a for a in menu.actions() if a.text() == "囲んだ所を直す")
        with mock.patch.object(self.w, "send") as send:
            act.trigger()
        self.assertEqual(self.w.mode.currentIndex(), 2)
        send.assert_called_once()

    def test_layer_order(self):
        c = self.w.canvas
        c.replace_with_image(str(self.src), "AI の絵")
        self.assertEqual([la.name for la in c.layers], ["レイヤー 1", "AI の絵"])
        self.assertEqual(c.layers[0].image.pixelColor(5, 5).alpha(), 0)
        self.assertEqual(c.current, 1)
        c.add_layer()
        self.assertEqual(c.layers[-1].name, "レイヤー 2")
        c.place_result(str(self.src), "新しい絵", replace=True)
        self.assertEqual([la.name for la in c.layers], ["レイヤー 1", "新しい絵"])
        self.assertGreater(c.redpen.zValue(), len(c.layers))

    def test_delete_and_save_layers(self):
        c = self.w.canvas
        c.replace_with_image(str(self.src), "AI の絵")
        c.delete_layer()
        self.assertEqual([la.name for la in c.layers], ["レイヤー 1"])
        c.undo()
        self.assertEqual(len(c.layers), 2)
        one = self.w.save_layer_png(str(self.d / "one.png"))
        self.assertTrue(Path(one).exists())
        out = self.d / "layers"
        out.mkdir()
        files = self.w.export_layers_png(str(out))
        self.assertEqual([Path(f).name for f in files], ["01-レイヤー 1.png", "02-AI の絵.png"])
        c.select(1)
        c.delete_layer()
        c.delete_layer()   # 1 枚だけなら絵を消して透明にする
        self.assertEqual(len(c.layers), 1)
        self.assertEqual(c.layers[0].image.pixelColor(50, 50).alpha(), 0)

    def test_count_field(self):
        p = self.w.ai_panel
        self.assertEqual(p.count(), 1)
        p.count_spin.setValue(3)
        self.assertEqual(p.count(), 3)
        self.assertEqual(len(p.seeds()), 3)
        p.count_buttons[1][2].click()
        self.assertEqual(p.count_spin.value(), 4)


if __name__ == "__main__":
    unittest.main()
