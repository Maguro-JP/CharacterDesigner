"""チャットの欄・レイヤー・描き終えた絵・ライブラリーの欄の回帰試験"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from chatdraw.tests.test_presetui import window  # noqa: E402


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def spin(n=30):
    a = app()
    for _ in range(n):
        a.processEvents()


def shown(d, size=(1280, 720)):
    w = window(d)
    w.resize(*size)
    w.show()
    spin()
    return w


def draw(w, text="雪の城の前の騎士"):
    a = app()
    w.entry.setText(text)
    w.send()
    for _ in range(600):
        a.processEvents()
        if w.images and not w.thread:
            break
        w.thread and w.thread.wait(10)
    spin()


class ChatPanelTest(unittest.TestCase):
    def test_input_stays_at_bottom_and_bubbles_fit_width(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            dock = w.panels["talk"][0]
            dock.show()
            dock.raise_()
            c = w.chat
            for i in range(30):
                c.add("user" if i % 2 else "ai", "長い文の吹き出し " * 12 + str(i))
            for width in (220, 420, 900):
                c.resize(width, 420)
                spin(5)
                self.assertGreater(c.input.geometry().top(), c.scroll.geometry().bottom() - 1)   # 書く欄は会話の下
                room = c.scroll.viewport().width()
                for b in c.bubbles():
                    self.assertLessEqual(b.width(), room)   # 狭い欄でも吹き出しが欄の外にはみ出さない
            self.assertTrue(c.bubbles()[0].time.text())   # 時刻が付く

    def test_typing_indicator_while_busy(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            c = w.chat
            c.set_busy(True)
            self.assertFalse(c.typing.isHidden())
            self.assertFalse(c.send_button.isEnabled())
            c.add("ai", "答え")
            items = [c.list.itemAt(i).widget() for i in range(c.list.count())]
            self.assertIs(items[-1], c.typing)   # 「入力中…」はいつも一番下
            c.set_busy(False)
            self.assertTrue(c.typing.isHidden())
            self.assertNotIn(c.typing, c.bubbles())

    def test_history_survives_restart_with_proposal_buttons(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            w.chat.add("user", "髪を長くしたい")
            b = w.chat.add("ai", "長い髪にしましょう")
            w.offer_prompt(b, "1girl, long hair")
            w.close()
            w2 = shown(d)
            texts = [x.text for x in w2.chat.bubbles()]
            self.assertIn("髪を長くしたい", texts)
            last = w2.chat.bubbles()[-1]
            self.assertEqual(last.proposal, "1girl, long hair")
            self.assertEqual(last.text.count("描く内容の案"), 1)   # 読み戻しで案の行が増えない
            self.assertEqual(last.buttons.count(), 2)              # 入れる・入れて描くのボタンが戻る
            self.assertEqual(w2.chat.turns[-1][0], "ai")


class LayerTest(unittest.TestCase):
    def test_lock_hide_rename_reorder_delete_thumbnails(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            c, p = w.canvas, w.layer_panel
            self.assertEqual(c.current, 1)
            self.assertIn(c.layers[1].name, p.active.text())
            self.assertFalse(p.list.item(0).icon().isNull())   # 縮小図
            self.assertTrue(p.list.item(0).font().bold())      # 描くレイヤーは太字
            c.set_tool("pen")
            c.color = QColor("#ff0000")
            refused = []
            c.refused.connect(refused.append)
            c.set_locked(1, True)
            self.assertTrue(c._press(QPointF(10, 10), 1.0))
            self.assertEqual(c.layers[1].image.pixelColor(10, 10).alpha(), 0)   # ロックしたレイヤーには描かない
            self.assertTrue(refused)
            c.set_locked(1, False)
            c._press(QPointF(10, 10), 1.0)
            c.end_stroke()
            self.assertGreater(c.layers[1].image.pixelColor(10, 10).alpha(), 0)   # 選んだレイヤーに描く
            self.assertEqual(c.layers[0].image.pixelColor(10, 10), QColor("white"))
            p.list.item(0).setText("線画")
            spin()
            self.assertEqual(c.layers[1].name, "線画")
            c.undo()
            self.assertNotEqual(c.layers[1].name, "線画")   # 名前を変えたのも元に戻せる
            c.add_layer()
            c.add_layer()
            self.assertEqual(len({l.name for l in c.layers}), len(c.layers))   # 同じ名前を作らない
            top = c.layers[c.current].name
            c.move_layer(-1)
            self.assertEqual(c.layers[c.current].name, top)
            self.assertEqual(p.list.currentItem().text(), top)
            n = len(c.layers)
            c.delete_layer()
            self.assertEqual(len(c.layers), n - 1)
            self.assertEqual([a.text() for a in p.more.menu().actions()][:2], ["1 つ上へ", "1 つ下へ"])   # 並べ替えはプルダウン
            p.buttons["lock"].trigger()
            self.assertTrue(c.layers[c.current].locked)
            p.buttons["lock"].trigger()
            p.list.item(0).setCheckState(Qt.Unchecked)
            self.assertFalse(c.layers[len(c.layers) - 1].visible)

    def test_ai_picture_replaces_and_undo_restores(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            c = w.canvas
            before = c.size_px()
            draw(w)
            self.assertEqual([l.name for l in c.layers], ["AI の絵 1", "レイヤー 1"])
            self.assertEqual(c.current, 1)   # 線は AI の絵の上の空のレイヤーに描く
            self.assertNotEqual(c.size_px(), before)
            c.undo()
            self.assertEqual(c.size_px(), before)


class FinalImageTest(unittest.TestCase):
    def test_late_preview_does_not_hide_final_and_history_selected(self):
        from PIL import Image
        with TemporaryDirectory() as d:
            w = shown(d)
            w.batch, w.batch_items, w.job_kind = [], [], "draw"
            path = Path(d) / "final.png"
            Image.new("RGB", (64, 96), "red").save(path)
            w.thread = object()   # 描いている途中
            w.on_one("p", str(path))
            w.show_preview(Image.new("RGB", (8, 8), "blue"))   # 絵の知らせのあとに届いた途中の絵
            self.assertTrue(w.canvas.overlay.isVisible())
            w.thread = None
            w.finish()
            self.assertFalse(w.canvas.overlay.isVisible())
            self.assertEqual(w.canvas.layers[0].image.pixelColor(5, 5), QColor("red"))
            self.assertEqual(w.history.currentItem().data(Qt.UserRole), str(path))
            w.show_preview(Image.new("RGB", (8, 8), "blue"))   # 描き終えたあとの途中の絵は出さない
            self.assertFalse(w.canvas.overlay.isVisible())

    def test_broken_check_result_still_places_picture(self):
        from PIL import Image
        with TemporaryDirectory() as d:
            w = shown(d)
            w.batch, w.batch_items, w.job_kind = [], [], "draw"
            w.studio.last_check = {"readable": True}   # 形の崩れた検品の結果（前は絵を置く前に落ちた）
            path = Path(d) / "final.png"
            Image.new("RGB", (64, 96), "red").save(path)
            w.on_one("p", str(path))
            self.assertEqual(w.canvas.layers[0].image.pixelColor(5, 5), QColor("red"))

    def test_missing_file_does_not_blank_canvas(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            size = w.canvas.size_px()
            w.show_history_image(str(Path(d) / "nai.png"))
            self.assertEqual(w.canvas.size_px(), size)


class LibraryOpenTest(unittest.TestCase):
    def test_library_behind_tab_comes_to_front(self):
        with TemporaryDirectory() as d:
            w = shown(d)
            w.arrange()
            spin()
            lib = w.panels["library"][0]
            self.assertFalse(w.panel_in_front("library"))   # 初めは履歴の裏のタブ
            w.panel_actions["library"].trigger()            # F12・欄の帯・ウィンドウのメニュー
            spin()
            self.assertTrue(w.panel_in_front("library"))
            self.assertTrue(w.panel_actions["library"].isChecked())
            self.assertGreater(w.library_panel.works.width(), 50)
            w.panel_actions["library"].trigger()
            spin()
            self.assertTrue(lib.isHidden())
            w.panel_actions["library"].trigger()
            spin()
            self.assertTrue(w.panel_in_front("library"))


if __name__ == "__main__":
    unittest.main()
