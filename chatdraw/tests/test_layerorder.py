"""レイヤーの重ね方。一番下に透明のレイヤー 1、その上に AI の絵、その上に足したレイヤー・加工の結果・赤ペンを
足した順に重ね、どれも選ぶ・隠す・消す・並べ替える・結合する・元に戻すがレイヤーとして効くか。
前は白い「背景」や AI の絵が一番下にあり、空のレイヤーが上に来て、赤ペンは並びの外にいた"""
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

from PIL import Image  # noqa: E402

from chatdraw.tests.test_editing import app  # noqa: E402


def names(c):
    from chatdraw.canvas import REDPEN
    return ["赤ペン" if x is REDPEN else x.name for x in c.stack()]


def rows(panel):
    """レイヤーの欄の行（上から）。赤ペンは「赤ペン」とだけ書く"""
    out = []
    for r in range(panel.list.count()):
        t = panel.list.item(r).text()
        out.append("赤ペン" if t.startswith("赤ペン") else t)
    return out


class CanvasOrderTest(unittest.TestCase):
    """キャンバスと欄だけで、描く → 足す → 加工 → 赤ペンの順に重ねる"""

    def setUp(self):
        from chatdraw.canvas import Canvas
        from chatdraw.layerpanel import LayerPanel
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.c = Canvas()
        self.panel = LayerPanel(self.c)
        self.c.new_canvas(64, 64)

    def tearDown(self):
        self.tmp.cleanup()

    def png(self, name, color, size=(64, 64)):
        p = self.d / name
        Image.new("RGB", size, color).save(p)
        return str(p)

    def mark(self):
        from PySide6.QtCore import QPointF
        c = self.c
        tool = c.tool
        c.set_tool("redpen")
        c._press(QPointF(4, 4), 1.0)
        for x, y in ((40, 4), (40, 40), (4, 40)):
            c.redpen.add(QPointF(x, y))
        c.redpen.end()
        c.set_tool(tool)

    def build(self):
        """描く → 足す → 加工 → 赤ペン"""
        c = self.c
        c.replace_with_image(self.png("ai.png", (0, 0, 255)), "AI の絵")
        c.add_layer()
        c.place_result(self.png("fx.png", (0, 255, 0)), "加工")
        self.mark()

    def test_new_canvas_is_one_transparent_layer(self):
        c = self.c
        self.assertEqual(names(c), ["レイヤー 1"])
        self.assertEqual(c.layers[0].image.pixelColor(10, 10).alpha(), 0)   # 白い背景ではなく透明
        self.assertEqual(c.current, 0)

    def test_ai_picture_goes_above_layer_one(self):
        c = self.c
        c.replace_with_image(self.png("ai.png", (0, 0, 255)), "AI の絵")
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵"])
        self.assertEqual(c.layers[0].image.pixelColor(10, 10).alpha(), 0)
        self.assertEqual(c.current, 1)
        # 大きさの違う絵に置き換えても、透明のレイヤー 1 は一番下で、絵と同じ大きさ
        c.place_result(self.png("big.png", (255, 0, 0), (80, 96)), "拡大", replace=True)
        self.assertEqual(names(c), ["レイヤー 1", "拡大"])
        self.assertEqual((c.layers[0].image.width(), c.layers[0].image.height()), (80, 96))

    def test_order_draw_add_effect_redpen(self):
        c = self.c
        self.build()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工", "赤ペン"])
        self.assertEqual(rows(self.panel), ["赤ペン", "加工", "レイヤー 2", "AI の絵", "レイヤー 1"])
        # 赤ペンは画面でも並びの場所に重なる（z は下のレイヤーの数 - 0.5）
        self.assertEqual(c.redpen.zValue(), 3.5)
        self.assertEqual([it.zValue() for it in c.items], [0, 1, 2, 3])
        # 赤ペンのあとに足したものは、赤ペンの上に重なる
        c.add_layer()
        self.assertEqual(names(c)[-2:], ["赤ペン", "レイヤー 3"])
        self.assertEqual(c.layers[c.current].name, "レイヤー 3")
        c.add_image_layer(self.png("x.png", (9, 9, 9)), "重ねた絵")
        self.assertEqual(names(c)[-1], "重ねた絵")

    def test_select_and_hide(self):
        c, p = self.c, self.panel
        self.build()
        p.list.setCurrentRow(0)   # 一番上の行 = 赤ペン
        self.assertTrue(c.redpen_current)
        self.assertIn("赤ペン", p.active.text())
        p.list.setCurrentRow(2)   # レイヤー 2
        self.assertFalse(c.redpen_current)
        self.assertEqual(c.layers[c.current].name, "レイヤー 2")
        # 隠す（欄のチェック）。赤ペンもレイヤーも同じ操作
        from PySide6.QtCore import Qt
        p.list.item(0).setCheckState(Qt.Unchecked)
        self.qapp.processEvents()
        self.assertFalse(c.redpen.isVisible())
        p.list.item(1).setCheckState(Qt.Unchecked)
        self.qapp.processEvents()
        self.assertFalse(c.layers[3].visible)
        self.assertEqual(c.flatten().pixelColor(10, 10).name(), "#0000ff")   # 加工を隠すと下の AI の絵が見える

    def test_reorder_and_undo(self):
        c = self.c
        self.build()
        c.select_redpen()
        c.move_layer(-1)   # 赤ペンを加工の下へ
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "赤ペン", "加工"])
        self.assertTrue(c.redpen_current)
        self.assertEqual(c.redpen.zValue(), 2.5)
        c.undo()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工", "赤ペン"])
        # 絵のレイヤーは赤ペンを 1 つずつ越える
        c.select(3)
        c.move_layer(1)
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "赤ペン", "加工"])
        self.assertEqual(c.layers[c.current].name, "加工")
        # ドラッグと同じ、並びの場所での移動。レイヤー 1 を一番上へ
        c.move_entry_to(0, 4)
        self.assertEqual(names(c), ["AI の絵", "レイヤー 2", "赤ペン", "加工", "レイヤー 1"])
        c.undo()
        c.undo()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工", "赤ペン"])
        c.redo()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "赤ペン", "加工"])

    def test_drag_in_panel_moves_redpen(self):
        c, p = self.c, self.panel
        self.build()
        p._moved(None, 0, 0, None, 3)   # 一番上の行（赤ペン）を 3 行目の前へ落とす
        self.qapp.processEvents()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "赤ペン", "レイヤー 2", "加工"])
        self.assertEqual(rows(p), ["加工", "レイヤー 2", "赤ペン", "AI の絵", "レイヤー 1"])

    def test_delete_and_undo(self):
        c, p = self.c, self.panel
        self.build()
        p.list.setCurrentRow(0)
        p._delete()                      # 赤ペンを選んで「－」で印を全部消す
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工"])
        self.assertEqual(c.redpen.marks, [])
        c.undo()                         # 元に戻すで印ごと戻る
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工", "赤ペン"])
        self.assertEqual(len(c.redpen.marks), 1)
        c.select(2)
        c.delete_layer()                 # 絵のレイヤーを消すと、下のレイヤーを選ぶ
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "加工", "赤ペン"])
        self.assertEqual(c.layers[c.current].name, "AI の絵")
        c.undo()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工", "赤ペン"])
        c.select(0)
        c.delete_layer()                 # レイヤー 1 も普通のレイヤーとして消せる
        self.assertEqual(names(c), ["AI の絵", "レイヤー 2", "加工", "赤ペン"])
        c.undo()
        self.assertEqual(names(c)[0], "レイヤー 1")

    def test_merge(self):
        c = self.c
        self.build()
        c.select_redpen()
        c.merge_down()                   # 赤ペンの印を下の「加工」に描き込む
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工"])
        self.assertEqual(c.layers[c.current].name, "加工")
        red = c.layers[3].image.pixelColor(22, 4)
        self.assertGreater(red.red(), 200)
        self.assertLess(red.green(), 120)
        c.undo()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "加工", "赤ペン"])
        self.assertEqual(c.layers[3].image.pixelColor(22, 4).name(), "#00ff00")
        # すぐ下が赤ペンのレイヤーは結合せず、理由を出す
        c.add_layer()
        said = []
        c.refused.connect(said.append)
        c.merge_down()
        self.assertEqual(len(c.layers), 5)
        self.assertTrue(said)
        # 下のレイヤーと結合
        c.select(3)
        c.merge_down()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "赤ペン", "レイヤー 3"])
        # 見えているレイヤーを結合しても、赤ペンは絵に焼き込まず上に残る
        c.merge_visible()
        self.assertEqual(names(c), ["結合した絵", "赤ペン"])
        c.undo()
        self.assertEqual(names(c), ["レイヤー 1", "AI の絵", "レイヤー 2", "赤ペン", "レイヤー 3"])

    def test_pen_on_redpen_layer_is_refused(self):
        from PySide6.QtCore import QPointF
        c = self.c
        self.build()
        c.select_redpen()
        said = []
        c.refused.connect(said.append)
        c.set_tool("pen")
        before = [layer.image.copy() for layer in c.layers]
        c._press(QPointF(10, 10), 1.0)
        self.assertTrue(said)
        self.assertEqual([layer.image for layer in c.layers], before)

    def test_model_gets_white_where_transparent(self):
        """一番下が透明でも、模型に渡す絵の描いていない所は白（黒ではない）"""
        from chatdraw.app import qimage_to_pil
        self.assertEqual(qimage_to_pil(self.c.flatten()).getpixel((10, 10)), (255, 255, 255))


class WindowOrderTest(unittest.TestCase):
    """アプリの窓で、描く → 足す → 加工 → 赤ペンの並びを欄に出し、窓を写して並びを見る"""

    def test_window_layer_panel(self):
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        qapp = app()
        with TemporaryDirectory() as d:
            d = Path(d)
            w = Window(Studio(FakeWords(), FakePainter(), d))
            try:
                w.resize(1400, 900)
                w.show()
                c = w.canvas
                c.new_canvas(64, 64)
                self.assertEqual(names(c), ["レイヤー 1"])
                ai, fx = d / "ai.png", d / "fx.png"
                Image.new("RGB", (64, 64), (0, 0, 255)).save(ai)
                Image.new("RGB", (64, 64), (0, 255, 0)).save(fx)
                c.replace_with_image(str(ai), "AI の絵")
                c.add_layer()
                c.place_result(str(fx), "加工")
                CanvasOrderTest.mark(self_like(c))
                qapp.processEvents()
                self.assertEqual(rows(w.layer_panel), ["赤ペン", "加工", "レイヤー 2", "AI の絵", "レイヤー 1"])
                shot = w.grab()
                self.assertFalse(shot.isNull())
                out = os.environ.get("CD_SHOT_DIR")
                if out:   # 手元で並びを目で見るときだけ書く
                    shot.save(str(Path(out) / "layer-order-window.png"))
                    w.layer_panel.grab().save(str(Path(out) / "layer-order-panel.png"))
            finally:
                w.dirty = False
                w.close()


def self_like(canvas):
    """CanvasOrderTest.mark を窓のキャンバスで使うための入れ物"""
    from types import SimpleNamespace
    return SimpleNamespace(c=canvas)


if __name__ == "__main__":
    unittest.main()
