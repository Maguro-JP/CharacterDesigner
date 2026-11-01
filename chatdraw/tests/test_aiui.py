"""AI の欄の並び（描く人の流れの順）と、絵の全体表示の試験。

全体表示: 起動したとき・絵を開いたとき・描けたとき・広げたとき・拡大したときは、絵の全体が窓に収まる。
利用者が自分で拡大・縮小したあとは、窓の大きさが変わっても勝手に全体へ戻さない。
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.tests.test_aitabs import app, window  # noqa: E402


def picture(d, w=1600, h=2400) -> Path:
    from PIL import Image
    p = Path(d) / f"pic{w}x{h}.png"
    Image.new("RGB", (w, h), (200, 180, 160)).save(p)
    return p


def fits(c) -> bool:
    """絵の全体が見えていて、縦か横のどちらかが窓いっぱい（1 画素の誤差まで）"""
    r = c.mapFromScene(c.scene().sceneRect()).boundingRect()
    v = c.viewport().rect()
    inside = v.adjusted(-2, -2, 2, 2).contains(r)
    full = abs(r.width() - v.width()) <= 3 or abs(r.height() - v.height()) <= 3
    return inside and full


class FitTest(unittest.TestCase):
    def setUp(self):
        self.d = TemporaryDirectory()
        self.w = window(self.d.name)
        self.c = self.w.canvas

    def tearDown(self):
        self.w.closing_checked = True   # 試験では保存を聞かずに閉じる
        self.w.close()
        self.d.cleanup()

    def show(self, size=(1200, 800)):
        self.w.resize(*size)
        self.w.show()
        app().processEvents()

    def test_startup_fits_after_window_shown(self):
        # 窓が出る前に絵を開いても、窓が出た大きさで全体表示になる
        self.c.replace_with_image(str(picture(self.d.name)), "絵")
        self.show()
        self.assertTrue(self.c.auto_fit)
        self.assertTrue(fits(self.c))

    def test_open_draw_grow_fit(self):
        self.show()
        self.c.set_zoom(3.0)
        self.assertFalse(self.c.auto_fit)
        self.w.show_history_image(str(picture(self.d.name)))           # 絵を開いた
        self.assertTrue(fits(self.c))
        self.c.set_zoom(3.0)
        self.w.place(str(picture(self.d.name, 1216, 832)))             # 描けた
        self.assertTrue(fits(self.c))
        self.c.set_zoom(3.0)
        self.w.mode.setCurrentIndex(1)
        self.w.place(str(picture(self.d.name, 1216, 832)))             # 元の絵に重ねて描けた
        self.assertTrue(fits(self.c))
        self.w.mode.setCurrentIndex(0)
        self.c.set_zoom(3.0)
        from PIL import Image
        self.w._place_outpaint(Image.new("RGB", (1472, 832)), "", 128, 0, 128, 0)   # 広げた
        self.assertTrue(fits(self.c))

    def test_user_zoom_is_kept_on_resize(self):
        self.c.replace_with_image(str(picture(self.d.name)), "絵")
        self.show()
        self.c.set_zoom(2.0)
        self.w.resize(900, 700)
        app().processEvents()
        self.assertAlmostEqual(self.c.zoom(), 2.0, places=2)           # 利用者が決めた拡大のまま
        self.assertFalse(self.c.auto_fit)
        self.c.fit()                                                  # 「全体を表示」で全体表示に戻る
        self.w.resize(1300, 900)
        app().processEvents()
        self.assertTrue(fits(self.c))

    def test_actual_and_wheel_stop_auto_fit(self):
        self.c.replace_with_image(str(picture(self.d.name)), "絵")
        self.show()
        self.c.actual()
        self.assertFalse(self.c.auto_fit)
        self.c.fit()
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        e = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
        self.c.wheelEvent(e)
        self.assertFalse(self.c.auto_fit)


class AiPanelOrderTest(unittest.TestCase):
    def test_flow_order_and_entries(self):
        with TemporaryDirectory() as d:
            w = window(d)
            p = w.ai_panel
            names = [p.tabs.tabText(i) for i in range(p.tabs.count())]
            self.assertEqual(names, ["描く内容", "作風", "模型", "直す・仕上げ", "詳しい設定"])   # 頼む → 描く → 直す → 仕上げ
            fin = p.sections["直す・仕上げ"]
            for b in (p.again, p.upscale_button, p.chibi_button, p.lineart_button, p.pixel_button):
                self.assertTrue(fin.isAncestorOf(b))
                self.assertTrue(b.toolTip())                                   # 説明はツールチップ
            self.assertTrue(p.sections["作風"].isAncestorOf(p.save_button))     # 設定の保存はプリセットの所
            self.assertFalse(p.sections["詳しい設定"].isAncestorOf(p.again))    # 入口は 1 つ
            w.close()

    def test_no_dead_widgets(self):
        """押しても何も変わらない部品を出さない"""
        with TemporaryDirectory() as d:
            w = window(d)
            p = w.ai_panel
            self.assertFalse(p.ref_scale.isEnabled())
            p.use_ref.setChecked(True)
            self.assertTrue(p.ref_scale.isEnabled())
            p.use_ref.setChecked(False)
            if w.lora_pick.count() == 1:
                self.assertTrue(w.lora_pick.isHidden())                       # LoRA を置いていなければ選ぶ欄を出さない
            if not w.lora_pick.currentData():
                self.assertTrue(w.lora_strength.isHidden())
            from chatdraw import voice
            self.assertEqual(w.mic_button.isHidden(), not voice.available())
            w.close()

    def test_negative_reaches_every_path(self):
        """禁止ワードは書いた時点で絵の模型に渡り、描かずに広げる・ちびキャラにするときも効く"""
        with TemporaryDirectory() as d:
            w = window(d)
            w.ai_panel.negative.setText("hat, text")
            self.assertIn("hat", w.studio.painter.avoid)
            self.assertIn("text", w.studio.painter.avoid)
            w.ai_panel.negative.setText("")
            self.assertNotIn("hat", w.studio.painter.avoid)
            w.close()


class AiMenuFreshTest(unittest.TestCase):
    def test_menu_recounts_on_open_and_on_change(self):
        """AI のメニューの模型の一覧は、開くたびに数え直し、ブロックなどが変わると作り直す"""
        from unittest import mock
        from chatdraw import ratings
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):   # 利用者の model_prefs.json に触れない
            w = window(d)
            w._have_images = {"stale/model"}
            w.ai_menu.aboutToShow.emit()
            self.assertNotIn("stale/model", w._have_images or set())        # 開いたときに数え直した
            names = lambda: [a.text() for a in w.ai_menu.actions()]
            from chatdraw.models import catalog_images, pick
            listed = pick(catalog_images(), "推奨（確かめ済み）", have=w.installed_images(catalog_images()))
            if listed:
                m = listed[0]
                self.assertTrue(any(m.name in t for t in names()))
                ratings.set_blocked(m.repo, True)
                self.assertFalse(any(t.startswith(m.name) or t.startswith("★ " + m.name) for t in names()))
                ratings.set_blocked(m.repo, False)
                self.assertTrue(any(m.name in t for t in names()))
            w._ai_menu_stale = True                                         # 開いている間に変わった分は閉じたあとに作り直す
            w._ai_menu_hidden()
            self.assertFalse(w._ai_menu_stale)
            w.closing_checked = True
            w.close()

    def test_menu_items_not_duplicated(self):
        """同じ働きの項目を 2 か所に置かない"""
        with TemporaryDirectory() as d:
            w = window(d)
            texts = []

            def walk(m):
                for a in m.actions():
                    if a.menu():
                        walk(a.menu())
                    elif a.text():
                        texts.append(a.text())
            for a in w.menuBar().actions():
                walk(a.menu())
            self.assertEqual(texts.count("並びを初めの形に戻す"), 1)
            self.assertNotIn("整列（初期の配置に戻す）", texts)
            w.closing_checked = True
            w.close()


if __name__ == "__main__":
    unittest.main()
