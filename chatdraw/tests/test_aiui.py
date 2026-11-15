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
            self.assertEqual(names, ["指示", "作風", "直す・仕上げ", "詳しい設定"])   # 頼む → 描く → 直す → 仕上げ
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
            self.assertFalse(w.mic_button.isHidden())   # 使えない環境でも出し、何を入れれば使えるかをツールチップに出す
            self.assertEqual(w.mic_button.toolTip(), voice.tooltip())
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


class InstructTabTest(unittest.TestCase):
    """指示のタブの並び（模型、描くワード、描くワードの登録、禁止ワード、禁止ワードの登録）と、登録のボタン"""

    def _order(self, w):
        tl = w.ai_panel.sections["描く内容"].body
        seen = []
        for i in range(tl.count()):
            it = tl.itemAt(i)
            wdg = it.widget()
            if wdg is None and it.layout() is not None:   # 横の並びは中の最初の部品で見る
                inner = it.layout().itemAt(0)
                wdg = inner.widget() if inner is not None else None
            if wdg is None:
                continue
            for name, target in (("模型", w.model_label), ("描くワード", w.entry), ("描くワードの登録", w.tips_scroll),
                                 ("禁止ワード", w.ai_panel.negative), ("禁止ワードの登録", w.neg_tips_box)):
                if wdg is target:
                    seen.append(name)
            if isinstance(wdg, __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel) and wdg.objectName() == "sectionHead":
                seen.append("見出し:" + wdg.text())
        return seen

    def test_order_and_heads(self):
        with TemporaryDirectory() as d:
            w = window(d)
            self.assertEqual(self._order(w), ["見出し:絵の模型", "模型", "見出し:描くワード", "描くワード", "描くワードの登録",
                                              "見出し:禁止ワード", "禁止ワード", "禁止ワードの登録"])
            self.assertFalse(hasattr(w, "fixed_negative"))                    # 固定値の表示は無い
            w.close()

    def test_no_okiniiri_word_in_prompt_ui(self):
        with TemporaryDirectory() as d:
            w = window(d)
            self.assertNotIn("お気に入り", w.fav_button.toolTip())
            src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
            for line in src.splitlines():
                if "お気に入り" in line and ("addAction" in line or "addMenu" in line or "setToolTip" in line or "showMessage" in line):
                    self.assertIn("★", line)                                   # 残るのは絵の ★（作品の印）だけ
            w.close()

    def test_negative_presets(self):
        with TemporaryDirectory() as d:
            w = window(d)
            w.settings.store.remove(w.NEG_KEY)
            w._load_negatives()
            self.assertEqual(w.neg_tips.count(), 0)
            w.ai_panel.negative.setText("帽子、文字")
            w._toggle_neg_fav()                                                 # ☆ で登録
            self.assertEqual(w.negative_presets(), ["帽子、文字"])
            self.assertEqual(w.neg_fav_button.text(), "★")
            w.ai_panel.negative.setText("眼鏡")
            w.pin_negative("眼鏡")
            self.assertEqual(w.neg_tips.count(), 2)
            w.ai_panel.negative.clear()
            w.neg_tips.itemAt(0).widget().click()                              # 押すと欄に入る
            self.assertEqual(w.ai_panel.negative.text(), "帽子、文字")
            w.neg_tips.itemAt(1).widget().click()                              # 二つ目は足す
            self.assertEqual(w.ai_panel.negative.text(), "帽子、文字、眼鏡")
            w.neg_tips.itemAt(1).widget().click()                              # 同じ言葉は重ねない
            self.assertEqual(w.ai_panel.negative.text(), "帽子、文字、眼鏡")
            w2 = window(d)                                                      # 設定に残るので開き直しても消えない
            self.assertEqual(w2.negative_presets(), ["帽子、文字", "眼鏡"])
            self.assertEqual(w2.neg_tips.count(), 2)
            w2.close()
            w.unpin_negative("眼鏡")
            self.assertEqual(w.negative_presets(), ["帽子、文字"])
            w.settings.store.remove(w.NEG_KEY)                                  # 利用者の設定に残さない
            w.close()

    def test_buttons_wrap_to_width(self):
        """登録・履歴のボタンは横に流さず、欄の横幅で折り返す。高さは中身に合わせる"""
        from chatdraw.tests.test_panels import spin
        with TemporaryDirectory() as d:
            w = window(d)
            w.show()
            for i in range(12):
                w._remember_prompt(f"長い頼みの言葉 その {i} 赤いマフラーの女の子")
            spin(5)                                                             # 足したボタンが出てから測る
            box = w.tips_scroll
            lay = w.tips
            one = lay.heightForWidth(10000)
            narrow = lay.heightForWidth(220)
            self.assertGreater(narrow, one * 3)                                # 狭いと何行にもなる
            box.resize(220, narrow)
            lay.setGeometry(box.rect())
            spin(3)
            for i in range(lay.count()):
                g = lay.itemAt(i).geometry()
                self.assertLessEqual(g.right(), 220, i)                         # 横にはみ出さない
            for i in range(12):
                w.forget_prompt(f"長い頼みの言葉 その {i} 赤いマフラーの女の子")
            w.close()


class SaveFolderTest(unittest.TestCase):
    def test_saved_in_date_folder(self):
        import time
        with TemporaryDirectory() as d:
            w = window(d)
            day = time.strftime("%Y-%m-%d")
            p = w._finished_path("nobg")
            self.assertEqual(p.parent.name, day)
            self.assertTrue(p.parent.is_dir())
            self.assertEqual(w._logo_folder("logo").parent.parent.name, day)
            from PIL import Image
            saved = w.studio._save(Image.new("RGB", (8, 8)), 7, {})
            self.assertEqual(saved.parent, w.studio.out / day)
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
