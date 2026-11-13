"""赤ペンで囲み、指示を書き、「囲んだ所を直す」を押す経路を、窓から通す（偽の模型）。
直しの結果は一番上の新しいレイヤーにだけ置いて選び、描いた絵の履歴とライブラリーには載せない。囲みの外は変えない。
直しは 1 回で終える（検品が通るまで直し続けない）"""
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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg, wait_idle  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


class RedPenFixTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        src = self.d / "a.png"
        figure().save(src)
        self.w.resize(1200, 800)
        self.w.show()
        self.w.canvas.replace_with_image(str(src))
        QTest.qWait(50)
        self.w.tool_actions["redpen"].trigger()

    def tearDown(self):
        self.w.closing_checked = True
        self.w.close()
        self.tmp.cleanup()

    def mark(self, note="笑顔に", dx=0):
        c = self.w.canvas
        vp = c.viewport()
        start = c.mapFromScene(c.sceneRect().center()) + QPoint(-30 + dx, -30)
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
        for i in range(1, 16):
            QTest.mouseMove(vp, start + QPoint(4 * i, 4 * i))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 60))
        QTest.qWait(20)
        self.w.note_edit.setText(note)   # 日本語は keyClicks で打てないので欄に入れる
        QTest.keyClick(self.w.note_edit, Qt.Key_Return)

    def press(self):
        QTest.mouseClick(self.w.button, Qt.LeftButton)
        wait_idle(self.qapp, self.w, 60)
        wait_bg(self.qapp, self.w)

    def test_fix_goes_to_top_layer_only(self):
        from chatdraw.app import qimage_to_pil
        from PIL import ImageChops
        c = self.w.canvas
        before = qimage_to_pil(c.flatten()).convert("RGB")
        hist, lib, imgs = self.w.history.count(), len(self.w.library.works()), list(self.w.images)
        n = len(c.layers)
        said = []
        self.w.notify = lambda title, *a, **k: said.append(title)
        self.mark()
        mask = self.w.fix_regions("")[0][0].resize(before.size)
        self.assertEqual(self.w.mode.currentIndex(), 2)
        self.press()
        self.assertEqual(len(c.layers), n + 1, said)
        self.assertEqual(c.current, len(c.layers) - 1)      # 一番上を選ぶ
        self.assertTrue(c.layers[c.current].visible)         # 見える
        self.assertEqual(self.w.history.count(), hist)       # 描いた絵の履歴に載せない
        self.assertEqual(len(self.w.library.works()), lib)   # ライブラリーに載せない
        self.assertEqual(self.w.images, imgs)
        after = qimage_to_pil(c.flatten()).convert("RGB")
        diff = ImageChops.difference(before, after).convert("L").point(lambda v: 255 if v else 0)
        outside = ImageChops.multiply(diff, ImageChops.invert(mask.convert("L")))
        self.assertIsNone(outside.getbbox())                 # 囲みの外は 1 画素も変えない
        self.assertIsNotNone(diff.getbbox())                 # 直しが見える
        redraws = [x for x in self.painter.calls if x[0] == "redraw"]
        self.assertEqual(len(redraws), 1)                    # 1 回で終える
        self.assertFalse([t for t in said if "描けませんでした" in t])

    def test_flaws_do_not_repeat(self):
        """崩れが見つかっても直し続けず、1 回で返して見える形で置く"""
        import chatdraw.engine as eng
        old = eng.flaws
        eng.flaws = lambda *a, **k: ["1 か所目: 崩れ"]
        try:
            self.mark()
            self.press()
        finally:
            eng.flaws = old
        c = self.w.canvas
        self.assertEqual(len([x for x in self.painter.calls if x[0] == "redraw"]), 1)
        self.assertTrue(c.layers[c.current].visible)

    def test_failure_is_one_line_without_cannot_draw(self):
        said = []
        self.w.notify = lambda title, kind="", body="", **k: said.append(f"{title} {body}")

        def boom(*a, **k):
            raise RuntimeError("模型が落ちた")
        self.painter.redraw = boom
        self.mark()
        self.press()
        self.assertTrue(said)
        self.assertFalse([t for t in said if "描けませんでした" in t], said)
        self.assertTrue(any("模型が落ちた" in t for t in said), said)


    def process(self, sid, hide_first=False):
        """赤ペンで囲み、加工を右クリックのショートカットと同じ道（run_shortcut）で掛ける"""
        from chatdraw.app import qimage_to_pil
        from PIL import ImageChops
        c = self.w.canvas
        before = qimage_to_pil(c.flatten()).convert("RGB")
        self.mark("")
        mask = self.w._region_mask().resize(before.size)
        if hide_first:   # 隠した印の所は加工しない
            c.redpen.set_shown(1, False) if hasattr(c.redpen, "set_shown") else None
        hist, n = self.w.history.count(), len(c.layers)
        said = []
        self.w.notify = lambda title, kind="", body="", **k: said.append(f"{title} {body}")
        self.w.run_shortcut(sid)
        wait_idle(self.qapp, self.w, 120)
        wait_bg(self.qapp, self.w)
        self.assertEqual(len(c.layers), n + 1, said)
        self.assertEqual(c.current, len(c.layers) - 1)
        self.assertTrue(c.layers[c.current].visible)
        self.assertEqual(self.w.history.count(), hist)
        after = qimage_to_pil(c.flatten()).convert("RGB")
        diff = ImageChops.difference(before, after).convert("L").point(lambda v: 255 if v else 0)
        inside = mask.convert("L").point(lambda v: 255 if v else 0)   # 囲みの縁のぼかしも中に数える
        outside = ImageChops.multiply(diff, ImageChops.invert(inside))
        self.assertIsNone(outside.getbbox(), (said, outside.getbbox(), inside.getbbox()))   # 囲みの外は 1 画素も変えない
        return said

    def test_process_effect_inside_marks(self):
        self.process("fin:mat_metal")

    def test_process_clean_inside_marks(self):
        self.process("fin:clean")


    def hidden_second(self, run):
        """印を 2 つ付けて 2 つ目を隠すと、直し・加工は 1 つ目の所だけを変える"""
        from chatdraw.app import qimage_to_pil, gray_to_pil
        from PIL import ImageChops
        c = self.w.canvas
        before = qimage_to_pil(c.flatten()).convert("RGB")
        self.mark("笑顔に", dx=-60)
        first = gray_to_pil(c.redpen.masks()[0]).resize(before.size).convert("L").point(lambda v: 255 if v else 0)
        self.mark("笑顔に", dx=60)
        c.redpen.set_hidden(2, True)
        self.w.notify = lambda *a, **k: None
        run()
        wait_idle(self.qapp, self.w, 120)
        wait_bg(self.qapp, self.w)
        after = qimage_to_pil(c.flatten()).convert("RGB")
        diff = ImageChops.difference(before, after).convert("L").point(lambda v: 255 if v else 0)
        self.assertIsNone(ImageChops.multiply(diff, ImageChops.invert(first)).getbbox())

    def test_hidden_mark_is_not_fixed(self):
        self.hidden_second(lambda: QTest.mouseClick(self.w.button, Qt.LeftButton))

    def test_hidden_mark_is_not_processed(self):
        self.hidden_second(lambda: self.w.run_shortcut("fin:mat_metal"))


if __name__ == "__main__":
    unittest.main()
