"""AI の自動選択、赤ペンの丸・四角・全体・自動選択、チャットと描くワードの分け方。
1. 絵の上を自動選択の道具で 1 回押すと、押した所の物が選ばれるか（選んだ画素の数と位置）。模型が無い・取れないときは
   部位分けか色の続きで代わりに選び、どの道で選んだかを知らせるか
2. 赤ペンの丸・四角・全体・自動選択で印が付き、その印で直すと印の中だけが変わるか（印の外は 1 画素も変えない）。
   直しのあとに境目を合わせ（seamfix.settle）、全体を 1 回だけ測って知らせるか（seamfix.whole_check。繰り返しに繋げない）
3. チャットで描いても描くワードの欄が変わらないか。「描くワードに〜を足して」では欄が変わり、何をどう変えたかを 1 行で返すか
道具は絵の上をマウスで押して動かして離す（本物と同じ経路）。直しは Window.send → 裏の糸の Job → Studio.fix を、小さな偽の模型で流す。
SAM 2 の模型が手元にあれば、模型の道も本物で流す（無ければその試験だけ飛ばす）"""
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

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app  # noqa: E402


def blobs(w=160, h=120):
    """白地に赤い丸と青い四角の絵（押した所の物がどれか、画素で決まる）"""
    im = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(im)
    d.ellipse((20, 20, 70, 90), fill=(220, 30, 30))
    d.rectangle((100, 30, 140, 80), fill=(30, 60, 220))
    return im


def mouse(c, pts):
    """絵の座標の点の列を、ビューの上の押す・動かす・離すにして流す"""
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    vp = c.viewport()
    at = [c.mapFromScene(x, y) for x, y in pts]
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at[0])
    for p in at[1:]:
        ev = QMouseEvent(QEvent.MouseMove, QPointF(p), QPointF(vp.mapToGlobal(p)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(vp, ev)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at[-1])


def gray(q):
    """QImage（白黒）を bool の配列に"""
    from chatdraw.app import gray_to_pil
    return np.asarray(gray_to_pil(q)) > 127


class PickTest(unittest.TestCase):
    """模型を使わない代わりの道（色の続き）と、選んだ所を形にする所"""

    def test_color_fallback_picks_clicked_object(self):
        from chatdraw import autosel
        im = blobs()
        with mock.patch("chatdraw.facefeat.seg_small", lambda image: None):
            p = autosel.pick(im, point=(45, 55), use_model=False)
        self.assertEqual(p.how, "color")
        self.assertIn("部位分けも使えません", p.why)
        ys, xs = np.nonzero(p.mask)
        print(f"色の続き: {p.count} 画素、x {xs.min()}〜{xs.max()}、y {ys.min()}〜{ys.max()}")
        self.assertTrue(20 <= xs.min() and xs.max() <= 70 and 20 <= ys.min() and ys.max() <= 90)
        self.assertGreater(p.count, 2000)
        self.assertFalse(p.mask[55, 120], "青い四角まで選んだ")

    def test_offline_uses_parts(self):
        """模型を取れないときは理由を持って部位分けで選ぶ"""
        from chatdraw import autosel
        im = blobs()
        lab = Image.new("L", im.size, 0)
        ImageDraw.Draw(lab).rectangle((100, 30, 140, 80), fill=4)   # 上の服（4）とする部位分け
        with mock.patch.dict(os.environ, {"CD_AUTOSEL_OFFLINE": "1"}), mock.patch.object(autosel, "model_dir", lambda: None), \
                mock.patch("chatdraw.facefeat.seg_small", lambda image: lab):
            p = autosel.pick(im, point=(120, 50))
        self.assertEqual((p.how, p.label), ("parts", "upper"))
        self.assertIn("取りに行かない", p.why)
        self.assertEqual(p.count, 41 * 51)
        self.assertIn("部位分け", autosel.describe(p))

    def test_path_keeps_pixels(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from chatdraw import autosel
        m = np.zeros((50, 60), bool)
        m[10:30, 5:25] = True
        m[15:20, 10:15] = False   # 穴
        m[40:45, 50:55] = True    # 飛び地
        r = autosel.to_path(m).boundingRect()
        self.assertEqual((r.left(), r.top(), r.right(), r.bottom()), (5, 10, 55, 45))

    @unittest.skipUnless(os.environ.get("CD_AUTOSEL_MODEL") == "1", "SAM 2 の模型の試験は CD_AUTOSEL_MODEL=1 のときだけ流す（重い）")
    def test_sam_model(self):
        from chatdraw import autosel, membudget
        if autosel.model_dir() is None:
            self.skipTest("SAM 2 の模型が手元に無い")
        t = time.time()
        p = autosel.pick(blobs(), point=(45, 55))
        ys, xs = np.nonzero(p.mask)
        print(f"SAM 2: {p.how} {p.count} 画素、x {xs.min()}〜{xs.max()}、y {ys.min()}〜{ys.max()}、{time.time() - t:.1f} 秒")
        self.assertEqual(p.how, "sam", p.why)
        self.assertTrue(18 <= xs.min() and xs.max() <= 72 and 18 <= ys.min() and ys.max() <= 92)
        self.assertNotIn("autosel", membudget.loaded_names(), "使い終えた模型を降ろしていない")
        self.assertIsNone(autosel._MODEL)


class WindowBase(unittest.TestCase):
    def setUp(self):
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.out = self.d / "out"
        self.out.mkdir()
        self.home = mock.patch("chatdraw.paths.HOME", self.d / "home")
        self.home.start()
        from chatdraw.app import Window
        from chatdraw.library import Library
        w = Window(Studio(FakeWords(), FakePainter(), self.out))
        self.old_place = w.settings.store.value("result_place")
        w.settings.set("result_place", "上のレイヤー")
        w.library = Library(self.d / "lib")
        self.w = w

    def tearDown(self):
        w = self.w
        if self.old_place is None:
            w.settings.store.remove("result_place")
        else:
            w.settings.set("result_place", self.old_place)
        w.dirty = False
        w.close()
        self.home.stop()
        self.tmp.cleanup()

    def wait(self, w, sec=120):
        end = time.time() + sec
        while (w.thread is not None or getattr(w, "bg_pending", 0)) and time.time() < end:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.qapp.processEvents()


class WindowTest(WindowBase):
    def open_blobs(self, w):
        path = self.out / "blobs.png"
        blobs().save(path)
        w.show_history_image(str(path))
        self.wait(w)
        w.canvas.set_zoom(1.0)
        self.qapp.processEvents()
        return w.canvas

    def no_model(self):
        """模型を取れない環境と同じにする（部位分けも無い形で、色の続きの道を通す）"""
        from chatdraw import autosel
        ps = [mock.patch.dict(os.environ, {"CD_AUTOSEL_OFFLINE": "1"}), mock.patch.object(autosel, "model_dir", lambda: None),
              mock.patch("chatdraw.facefeat.seg_small", lambda image: None)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def tool(self, w, key):
        w.tool_actions[key].trigger()
        self.assertEqual(w.canvas.tool, key)

    # ---- 1. 自動選択の道具 ----
    def test_click_selects_object(self):
        self.no_model()
        w = self.w
        c = self.open_blobs(w)
        self.tool(w, "autosel")
        mouse(c, [(120, 55)])
        self.wait(w)
        m = c.selection_mask()
        self.assertIsNotNone(m, "選ばれていない")
        a = gray(m)
        ys, xs = np.nonzero(a)
        print(f"自動選択の道具: {a.sum()} 画素、x {xs.min()}〜{xs.max()}、y {ys.min()}〜{ys.max()}")
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (100, 140, 30, 80))
        self.assertEqual(int(a.sum()), 41 * 51)
        self.assertIn("自動選択", w.statusBar().currentMessage())
        self.assertIn("自動選択", w.chat.bubbles()[-1].text)   # 代わりの道で選んだことを黙らない

    # ---- 2. 赤ペンの囲み方 ----
    def test_redpen_ellipse_rect_all_auto(self):
        self.no_model()
        w = self.w
        c = self.open_blobs(w)
        pen = c.redpen
        w.shared["redpen_shape:ellipse"].trigger()
        self.assertEqual((c.tool, c.redpen_shape), ("redpen", "ellipse"))
        self.assertTrue(w.redpen_shape_bar.isVisible())
        mouse(c, [(10, 10), (40, 40), (80, 100)])
        w.shared["redpen_shape:rect"].trigger()
        mouse(c, [(90, 20), (150, 90)])
        w.shared["redpen_all"].trigger()
        w.shared["redpen_shape:auto"].trigger()
        mouse(c, [(45, 55)])
        self.wait(w)
        self.assertEqual(len(pen.marks), 4, "丸・四角・全体・自動選択の印が 4 つ付いていない")
        ms = [gray(q) for q in pen.masks()]
        counts = [int(m.sum()) for m in ms]
        print(f"赤ペンの印の画素: 丸 {counts[0]}、四角 {counts[1]}、全体 {counts[2]}、自動選択 {counts[3]}")
        self.assertTrue(ms[0][55, 45] and not ms[0][12, 12] and not ms[0][55, 120])   # 丸の中と、角と外
        self.assertTrue(ms[1][50, 120] and not ms[1][50, 85])
        self.assertEqual(counts[2], 160 * 120)
        ys, xs = np.nonzero(ms[3])
        self.assertTrue(20 <= xs.min() and xs.max() <= 70 and 20 <= ys.min() and ys.max() <= 90)
        self.assertFalse(ms[3][55, 120])
        # 元に戻す・やり直すで形の印も戻る
        pen.undo()
        self.assertEqual(len(pen.marks), 3)
        pen.redo()
        self.assertEqual(int(gray(pen.masks()[3]).sum()), counts[3])
        # 右クリックの「赤ペンの囲み方」にも同じ操作がある
        m = w.build_canvas_menu(c.viewport().mapToGlobal(c.mapFromScene(45, 55)))
        menu_texts = [a.text() for a in m.actions()] + [x.text() for a in m.actions() if a.menu() for x in a.menu().actions()]
        for label in ("赤ペンの囲み方", "赤ペン: 丸", "赤ペン: 四角", "赤ペン: 自動選択", "赤ペン: 全体", "ここを自動選択で印にする"):
            self.assertIn(label, menu_texts)

    def test_fix_changes_only_inside_auto_mark(self):
        """自動選択の印で直すと、印の中だけが変わる（偽の模型の直しを本物の経路で流す）"""
        self.no_model()
        w = self.w
        c = self.open_blobs(w)
        from chatdraw.app import qimage_to_pil
        before = np.asarray(qimage_to_pil(c.flatten()).convert("RGB"), np.int16)
        w.shared["redpen_shape:auto"].trigger()
        mouse(c, [(120, 55)])
        self.wait(w)
        self.assertEqual(len(c.redpen.marks), 1)
        inside = gray(c.redpen.masks()[0])
        c.redpen.set_text(1, "青を緑に")
        w.mode.setCurrentIndex(2)
        w.entry.setText("青を緑に")
        with mock.patch.object(w, "_keep_original", lambda text: text):
            w.send()
        self.wait(w)
        self.assertIsNone(w.thread, "直しが終わらない")
        after = np.asarray(qimage_to_pil(c.flatten()).convert("RGB"), np.int16)
        diff = np.abs(after - before).sum(-1) > 0
        print(f"自動選択の印で直した: 中の変わった画素 {int((diff & inside).sum())}、外の変わった画素 {int((diff & ~inside).sum())}")
        self.assertGreater(int((diff & inside).sum()), 0, "印の中が変わっていない")
        self.assertEqual(int((diff & ~inside).sum()), 0, "印の外が変わった")
        studio = w.job_studio
        self.assertTrue(studio.last_seam, "自動選択の印の境目を測っていない")
        print(f"境目の数字: {studio.last_seam[-1]}、全体の確かめ: {studio.last_whole.get('note')}")
        self.assertTrue(studio.last_whole.get("measured"), "全体を確かめていない")
        self.assertEqual(studio.last_whole["outside"], 0)
        self.assertEqual(len(studio.painter.calls), 1, "直しを 1 回で終えていない（繰り返しに繋がった）")


class WholeCheckTest(unittest.TestCase):
    """加工のあとの全体の確かめ。1 回だけ測って知らせ、絵は変えない"""

    def test_whole_check_measures_once(self):
        from chatdraw import seamfix
        before = blobs()
        after = before.copy()
        ImageDraw.Draw(after).rectangle((95, 25, 145, 85), fill=(30, 200, 60))
        mask = Image.new("L", before.size, 0)
        ImageDraw.Draw(mask).rectangle((95, 25, 145, 85), fill=255)
        st = seamfix.whole_check(before, after, mask)
        print(f"全体の確かめ: {st['note']}、境目 {st['seam']}")
        self.assertTrue(st["measured"])
        self.assertEqual(st["outside"], 0)
        leak = after.copy()
        leak.putpixel((5, 5), (0, 0, 0))
        self.assertEqual(seamfix.whole_check(before, leak, mask)["outside"], 1)

    def test_finisher_runs_whole_check(self):
        from chatdraw import finishers
        name = next((n for n, f in finishers.REGISTRY.items() if f.ready() and f.apply is not None and f.group in ("color", "clean")), None)
        if name is None:
            self.skipTest("手元で掛けられる加工が無い")
        im = blobs(256, 192)
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rectangle((90, 20, 200, 150), fill=255)
        out = finishers.run(name, im, mask)
        whole = finishers.LAST_QC.get("whole")
        self.assertIsNotNone(whole, f"{name} のあとに全体を確かめていない")
        self.assertEqual(whole["outside"], 0, "囲みの外が変わった")
        outside = np.asarray(Image.composite(Image.new("RGB", im.size), out.convert("RGB"), mask))
        base = np.asarray(Image.composite(Image.new("RGB", im.size), im, mask))
        self.assertEqual(int((outside != base).any(-1).sum()), 0)


if __name__ == "__main__":
    unittest.main()
