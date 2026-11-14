"""赤ペンの直しのレイヤー・確定のボタン・印の右クリック。
1. 赤ペンの直しのレイヤーを消したら、画面の画素・履歴・ライブラリー・出力の置き場・作業の保存・仮の置き場に何も残らないか。
   0.5.19 までの版が出力の置き場に書いた直しだけの絵（直した所のほかは透明）は、履歴とライブラリーから外れてごみ箱へ移るか
2. 赤ペンの指示の欄の「確定」を押すと、Enter と同じく指示が入って欄が閉じるか
3. 赤ペンの印の右クリックから加工を押すと、その印の囲みの中だけが変わるか（囲みの外は 1 画素も変えない）
直しは本物と同じ経路（赤ペンで囲む → Window.send の直す形 → 裏の糸の Job → Studio.fix）で、小さな偽の模型で流す"""
import glob
import json
import os
import sys
import tempfile
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

from PIL import Image, ImageChops  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def scene_pixels(c):
    """キャンバスの画面に出ている物（レイヤー・赤ペン・重ねた途中の絵）を、絵の大きさで描いた画素"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    w, h = c.size_px()
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    c.scene().render(p, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
    p.end()
    return bytes(img.constBits())


class Base(unittest.TestCase):
    def setUp(self):
        import tempfile
        # 前の試験の回（止めた回など）が残した仮のファイルは数えない。この回に増えた物だけを見る
        self._tmp_before = set(Path(tempfile.gettempdir()).glob("cd-redpen-*.png"))
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.out = self.d / "out"
        self.home = mock.patch("chatdraw.paths.HOME", self.d / "home")
        self.home.start()
        self.quiet = []
        for q in self.quiet:
            q.start()
        self.a, self.b = self.out / "a.png", self.out / "b.png"
        self.out.mkdir()
        figure().save(self.a)
        Image.new("RGB", (96, 128), (30, 60, 200)).save(self.b)
        self.w = self.window()

    def window(self):
        from chatdraw.app import Window
        from chatdraw.library import Library
        w = Window(Studio(FakeWords(), FakePainter(), self.out))
        self.old_place = w.settings.store.value("result_place")
        w.settings.set("result_place", "上のレイヤー")
        w.library = Library(self.d / "lib")
        return w

    def tearDown(self):
        self.close(self.w)
        self.home.stop()
        for q in self.quiet:
            q.stop()
        self.tmp.cleanup()

    def close(self, w):
        if self.old_place is None:
            w.settings.store.remove("result_place")
        else:
            w.settings.set("result_place", self.old_place)
        w.dirty = False
        w.close()

    def wait(self, w, sec=120):
        end = time.time() + sec
        while (w.thread is not None or getattr(w, "bg_pending", 0)) and time.time() < end:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.qapp.processEvents()

    def redpen_fix(self, w):
        """赤ペンで囲んで指示を書き、「描く」で直す（アプリの経路そのまま）"""
        c = w.canvas
        c.set_tool("redpen")
        pen = c.redpen
        pen.begin(QPointF(20, 20))
        for x, y in ((60, 20), (60, 60), (20, 60), (20, 21)):
            pen.add(QPointF(x, y))
        pen.end()
        pen.set_text(1, "目を大きく")
        w.mode.setCurrentIndex(2)
        w.entry.setText("目を大きく")
        with mock.patch.object(w, "_keep_original", lambda text: text):
            w.send()
        t0 = time.time()
        self.wait(w)
        print(f"直しの時間 {time.time() - t0:.1f} 秒")
        self.assertIsNone(w.thread, "直しが終わらない")


class RedPen3Test(Base):

    def settle(self, w, sec=300):   # 綺麗にするは重い。ほかの試験と同時に流すと 60 秒を超えた
        end = time.time() + sec
        while (w.thread is not None or getattr(w, "bg_pending", 0)) and time.time() < end:
            self.qapp.processEvents()
        self.qapp.processEvents()

    def files(self):
        return sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file() and ".trash" not in p.parts
                      and ".library" not in p.parts and p.name != "chat.json")   # chat.json は会話の記録

    def press_yes(self, w):
        from PySide6.QtCore import QTimer
        left = [100]

        def push():
            box = getattr(w, "_confirm_box", None)
            if box is None:
                left[0] -= 1
                if left[0] > 0:
                    QTimer.singleShot(20, push)
                return
            next(b for b in box.buttons() if b.text() == "消す").click()
        QTimer.singleShot(20, push)

    # ---- 1. 消したあとのゴミ ----
    def test_delete_leaves_nothing(self):
        from PySide6.QtWidgets import QAbstractButton
        w = self.w
        w.show_history_image(str(self.a))
        self.settle(w)
        c = w.canvas
        before_px, before_layers = scene_pixels(c), len(c.layers)
        before_files = self.files()
        temp_before = set(glob.glob(str(Path(tempfile.gettempdir()) / "cd-redpen-*")))
        hist_before = w.history.count()
        lib_before = len(w.library.items)
        self.redpen_fix(w)
        self.assertEqual(sum(1 for l in c.layers if l.redpen), 1, [l.name for l in c.layers])
        self.assertNotEqual(scene_pixels(c), before_px, "直しが画面に出ていない")
        panel = w.layer_panel
        panel.refresh()
        panel.list.setCurrentRow(panel.row_of(next(i for i, l in enumerate(c.layers) if l.redpen)))
        self.press_yes(w)
        next(b for b in panel.findChildren(QAbstractButton) if b.text() == "－").click()
        self.qapp.processEvents()
        after_px = scene_pixels(c)
        ov = getattr(c, "overlay", None)
        print("消したあとのレイヤー:", [l.name for l in c.layers], "重ね絵:", bool(ov and ov.isVisible()))
        self.assertEqual(len(c.layers), before_layers)
        self.assertFalse(ov is not None and ov.isVisible(), "途中の絵の重ね絵が残っている")
        self.assertEqual(after_px, before_px, "消したあとも画面に直しの画素が残っている")
        self.assertEqual(w.history.count(), hist_before, "履歴に直しの絵が入った")
        self.assertEqual(len(w.library.items), lib_before, "ライブラリーに直しの絵が入った")
        temp_after = set(glob.glob(str(Path(tempfile.gettempdir()) / "cd-redpen-*")))
        self.assertEqual(temp_after - temp_before, set(), "仮の置き場に直しの絵が残っている")
        # 別の絵へ移る（作業の保存が書かれる）→ 戻る。保存にも直しのレイヤーが無い
        w.show_history_image(str(self.b))
        if hasattr(w, "wait_io"):
            w.wait_io()
        self.settle(w)
        info = Path(str(self.a) + ".work.json")
        if info.exists():
            rows = json.loads(info.read_text(encoding="utf-8"))["layers"]
            print("作業の保存のレイヤー:", rows)
            self.assertFalse(any(r.get("redpen") for r in rows), rows)
        w.show_history_image(str(self.a))
        self.settle(w)
        self.assertFalse(any(l.redpen for l in c.layers))
        new = [f for f in self.files() if f not in before_files and not f.endswith((".work.json", ".layers.ora"))]
        print("出力の置き場に増えたファイル:", new)
        self.assertEqual(new, [], "出力の置き場に直しの絵か .parts.png が残っている")

    # ---- 1b. 欄の「－」と Delete キーで消しても戻ってこない（test_redlayer の 2 つの道を今の欄に合わせて戻した） ----
    def delete_by(self, how):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QAbstractButton
        w = self.w
        w.show_history_image(str(self.a))
        self.redpen_fix(w)
        c = w.canvas
        idx = [i for i, l in enumerate(c.layers) if l.redpen]
        self.assertEqual(len(idx), 1, [l.name for l in c.layers])
        panel = w.layer_panel
        panel.refresh()
        panel.list.setCurrentRow(panel.row_of(idx[0]))
        self.assertEqual(c.current, idx[0])
        n = len(c.layers)
        self.press_yes(w)
        if how == "minus":
            next(b for b in panel.findChildren(QAbstractButton) if b.text() == "－").click()
        else:
            w.show()
            panel.list.setFocus()
            QCoreApplication.processEvents()
            QTest.keyClick(panel.list, Qt.Key_Delete)
        QCoreApplication.processEvents()
        names = [l.name for l in c.layers]
        print(how, "消したあと:", names)
        self.assertEqual(len(c.layers), n - 1, names)
        self.assertFalse(any(l.redpen for l in c.layers), names)
        w.show_history_image(str(self.b))
        w.show_history_image(str(self.a))
        self.assertFalse(any(l.redpen for l in c.layers), [l.name for l in c.layers])
        self.close(w)
        self.w = w = self.window()
        w.show_history_image(str(self.a))
        self.assertFalse(any(l.redpen for l in w.canvas.layers), [l.name for l in w.canvas.layers])

    def test_delete_minus(self):
        self.delete_by("minus")

    def test_delete_key(self):
        self.delete_by("key")

    def test_old_redpen_files_go_to_trash(self):
        from chatdraw.finishers import KEY
        from chatdraw.library import Library
        from PIL import PngImagePlugin
        day = self.out / "2026-10-01"
        day.mkdir()
        old = day / "20261001-120000-7.png"   # 0.5.19 の engine._save と同じ名前の形と埋めた mode
        info = PngImagePlugin.PngInfo()
        info.add_itxt(KEY, json.dumps({"mode": "直す", "text": "目を大きく"}, ensure_ascii=False))
        Image.new("RGBA", (96, 128)).save(old, pnginfo=info)
        Image.new("L", (96, 128)).save(str(old) + ".parts.png")
        self.close(self.w)
        lib = Library(self.d / "lib")
        lib.items = [dict(id=k, kind="work", path=str(p), rating=0, tags=[], note="", text="", added="") for k, p in (("x", old), ("y", self.a))]
        lib.save()
        self.w = w = self.window()
        w.history.clear()
        w.activity.add(str(old), "")   # 0.5.19 の画面で履歴に並んでいた形
        w.images.append(str(old))
        w.settings.store.remove(w.SWEPT_KEY)
        w.sweep_old_redpen()
        self.settle(w)
        print("ごみ箱:", [e.get("label") for e in w.trash.entries()], "残ったファイル:", self.files())
        self.assertFalse(old.exists(), "前の版の直しの絵が出力の置き場に残っている")
        self.assertFalse(Path(str(old) + ".parts.png").exists(), "部位分けの残りが残っている")
        self.assertTrue(self.a.exists())
        self.assertEqual([i["id"] for i in w.library.items], ["y"])
        self.assertEqual([w.history.item(r).data(Qt.UserRole) for r in range(w.history.count())], [])
        self.assertNotIn(str(old), w.images)
        entries = w.trash.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["label"], "前の版の赤ペンの直し")
        # 戻せる（消すのは利用者がごみ箱で選んだときだけ）
        self.assertTrue(w.restore_trash(entries[0]["key"]))
        self.assertTrue(old.exists())

    # ---- 2. 確定のボタン ----
    def test_confirm_button(self):
        w = self.w
        w.show_history_image(str(self.a))
        c = w.canvas
        c.set_tool("redpen")
        pen = c.redpen
        pen.begin(QPointF(20, 20))
        for x, y in ((60, 20), (60, 60), (20, 60), (20, 21)):
            pen.add(QPointF(x, y))
        pen.end()
        w.show()
        w.edit_note(1)
        self.qapp.processEvents()
        self.assertTrue(w.note_box.isVisible())
        self.assertEqual(w.note_ok.text(), "確定")
        self.assertIn("Enter", w.note_ok.toolTip())
        w.note_edit.setText("笑顔に")
        from PySide6.QtTest import QTest
        QTest.mouseClick(w.note_ok, Qt.LeftButton)
        self.qapp.processEvents()
        print("確定のあと:", pen.texts, "欄:", w.note_box.isVisible())
        self.assertEqual(pen.texts[0], "笑顔に")
        self.assertFalse(w.note_box.isVisible())

    # ---- 3. 印の右クリックから、その囲みの中だけに加工 ----
    def mark(self, pen, x0, y0, x1, y1):
        pen.begin(QPointF(x0, y0))
        for x, y in ((x1, y0), (x1, y1), (x0, y1), (x0, y0 + 1)):
            pen.add(QPointF(x, y))
        pen.end()

    def test_mark_menu_only_inside(self):
        from chatdraw.app import gray_to_pil, qimage_to_pil, qimage_to_pil_rgba
        w = self.w
        w.show_history_image(str(self.a))
        self.settle(w)
        c = w.canvas
        c.set_tool("redpen")
        pen = c.redpen
        self.mark(pen, 15, 15, 50, 50)
        self.mark(pen, 55, 70, 90, 120)
        inside = gray_to_pil(pen.masks()[0]).convert("L").point(lambda v: 255 if v else 0)
        w.show()
        self.qapp.processEvents()
        n1 = pen.marks[0][0] + QPointF(-13 / c.zoom(), -13 / c.zoom())
        gpos = c.viewport().mapToGlobal(c.mapFromScene(n1))
        w.MARK_SHORTCUTS = {"app:lineart", "fin:clean"}   # 出す物の選り分けは別の試験で見る。ここは囲みの中だけかを見る
        sid_user = w.shortcut_store().add("目を大きく", "目を大きく")
        m = w.build_canvas_menu(gpos)
        sub = next(a.menu() for a in m.actions() if a.menu() and a.text() == "赤ペン 1 の中だけ加工")
        names = [a.text() for g in sub.actions() if g.menu() for a in g.menu().actions()]
        print("赤ペン 1 の加工:", names)
        self.assertIn("線画にする", names)
        self.assertIn("言葉で指示…", [a.text() for a in sub.actions()])
        self.assertIn(f"mark1:{sid_user}", [a.objectName() for a in sub.actions()])   # 登録した言葉の指示も並ぶ
        for sid in ("app:lineart", "fin:clean"):
            with self.subTest(sid=sid):
                act = next((a for g in sub.actions() if g.menu() for a in g.menu().actions() if a.objectName() == f"mark1:{sid}"), None)
                self.assertIsNotNone(act, sid)
                if not act.isEnabled():
                    print(sid, "は使えない:", act.toolTip())
                    continue
                base = qimage_to_pil(c.flatten()).convert("RGBA")
                n = len(c.layers)
                act.trigger()
                self.settle(w)
                self.assertEqual(len(c.layers), n + 1, [l.name for l in c.layers])
                top = qimage_to_pil_rgba(c.layers[-1].image)
                after = qimage_to_pil(c.flatten()).convert("RGBA")
                diff = ImageChops.difference(base, after).convert("L").point(lambda v: 255 if v else 0)
                outside = ImageChops.multiply(diff, ImageChops.invert(inside))
                changed_in = ImageChops.multiply(diff, inside).getbbox()
                out_alpha = ImageChops.multiply(top.getchannel("A"), ImageChops.invert(inside)).getbbox()
                print(sid, "囲みの外で変わった所:", outside.getbbox(), "囲みの中で変わった所:", changed_in,
                      "新しいレイヤーの囲みの外の画素:", out_alpha)
                self.assertIsNone(outside.getbbox(), "囲みの外が変わった")
                self.assertIsNone(out_alpha, "新しいレイヤーが囲みの外にも画素を持つ")
                if sid == "app:lineart":   # 線画は必ず中が変わる（綺麗にするは整った絵では変わらないことがある）
                    self.assertIsNotNone(changed_in, "囲みの中が変わっていない")
                c.layers.pop(c.current)   # 次の加工は元の絵から比べる
                c.current = len(c.layers) - 1
                c.rebuild()
        self.assertEqual(getattr(w, "_mark_only", 0), 0)
        w.shortcut_store().remove(sid_user)

    def test_mark_menu_instruction_order(self):
        """印の右クリックで登録した指示を選ぶと、欄に指示が入る → 確定 → 直し 1 回、の順に進む"""
        from unittest import mock
        w = self.w
        w.show_history_image(str(self.a))
        self.settle(w)
        c = w.canvas
        c.set_tool("redpen")
        pen = c.redpen
        self.mark(pen, 15, 15, 50, 50)
        self.mark(pen, 55, 70, 90, 120)
        w.show()
        self.qapp.processEvents()
        sid = w.shortcut_store().add("目を大きく", "目を大きく")
        order = []
        real_done, real_fix = w._note_done, w.fix_with_text
        n1 = pen.marks[0][0] + QPointF(-13 / c.zoom(), -13 / c.zoom())
        m = w.build_canvas_menu(c.viewport().mapToGlobal(c.mapFromScene(n1)))
        sub = next(a.menu() for a in m.actions() if a.menu() and a.text() == "赤ペン 1 の中だけ加工")
        act = next(a for a in sub.actions() if a.objectName() == f"mark1:{sid}")

        def done():
            order.append(("欄", w.note_edit.text()))
            real_done()
            order.append(("確定", pen.texts[0], w.note_box.isVisible()))

        def fix(text, mark=0):
            order.append(("直し", text, mark))
            return real_fix(text, mark=mark)
        w.edit_note(1)   # 欄を作る
        w.note_box.hide()
        w.note_ok.clicked.disconnect()
        w.note_ok.clicked.connect(done)
        calls = len(w.studio.painter.calls)
        with mock.patch.object(w, "fix_with_text", fix), mock.patch.object(w, "_keep_original", lambda t: t):
            act.trigger()
            self.assertEqual([o[0] for o in order], ["欄", "確定"], "確定の前に直しが始まった")
            end = time.time() + 30
            while len(order) < 3 and time.time() < end:
                self.qapp.processEvents()
            self.wait(w)
        print("順序:", order)
        self.assertEqual(order[0], ("欄", "目を大きく"))
        self.assertEqual(order[1], ("確定", "目を大きく", False))
        self.assertEqual(order[2], ("直し", "目を大きく", 1))
        self.assertEqual(len(order), 3)
        self.assertEqual(len(w.studio.painter.calls) - calls, 1, "直しが 1 回ではない")
        self.assertEqual(sum(1 for l in c.layers if l.redpen), 1)
        w.shortcut_store().remove(sid)

    def test_text_fix_only_that_mark(self):
        """登録した言葉の指示・「言葉で指示…」は、右クリックした印の囲みの中だけを直す（ほかの印は直さず、残す）"""
        from unittest import mock
        from chatdraw.app import gray_to_pil, qimage_to_pil_rgba
        w = self.w
        w.show_history_image(str(self.a))
        self.settle(w)
        c = w.canvas
        c.set_tool("redpen")
        pen = c.redpen
        self.mark(pen, 10, 10, 40, 40)
        self.mark(pen, 50, 80, 90, 120)
        pen.set_text(2, "髪を整える")
        second = gray_to_pil(pen.masks()[1]).convert("L").point(lambda v: 255 if v else 0)
        w.show()
        dlg = w.open_text_instruction(1)
        self.assertIn("赤ペン 1", dlg.where.text())
        dlg.edit.setText("目を大きく")
        with mock.patch.object(w, "_keep_original", lambda text: text):
            dlg.run.click()
            self.wait(w)
        self.settle(w)
        layers = [l for l in c.layers if l.redpen]
        self.assertEqual(len(layers), 1, [l.name for l in c.layers])
        alpha = qimage_to_pil_rgba(layers[0].image).getchannel("A")
        from PIL import ImageChops
        on_second = ImageChops.multiply(alpha.point(lambda v: 255 if v else 0), second).getbbox()
        print("直しのレイヤーの画素:", alpha.getbbox(), "赤ペン 2 の所:", on_second, "残った印:", pen.texts, pen.shown())
        self.assertIsNotNone(alpha.getbbox())
        self.assertIsNone(on_second, "右クリックしていない印の所まで直した")
        self.assertEqual(pen.texts, ["髪を整える"], "直した印だけを消し、ほかの印は残す")
        self.assertEqual(pen.shown(), [1], "隠したほかの印が戻っていない")


if __name__ == "__main__":
    unittest.main()
