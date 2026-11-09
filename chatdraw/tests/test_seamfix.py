"""赤ペンの直しの境目（chatdraw/seamfix.py）、描けるまで続ける決まり（chatdraw/persist.py）、
直した結果にもう一度赤ペンを重ねて直す流れの試験。絵の模型は偽物に替えて、本物と同じ Studio.fix と画面の経路を通す"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp, mktemp

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from chatdraw import seamfix  # noqa: E402
from chatdraw.engine import Studio  # noqa: E402
from chatdraw.persist import Persist  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_idle  # noqa: E402


def hair(size=(200, 160)):
    """髪の毛のような斜めの線が、直す所を横切る絵"""
    img = Image.new("RGB", size, (235, 190, 170))
    d = ImageDraw.Draw(img)
    for x in range(-60, size[0], 11):
        d.line((x, 0, x + 60, size[1]), fill=(90, 50, 40), width=2)
    return img


def disc(size, box):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse(box, fill=255)
    return m


class Shifted(FakePainter):
    """直す所を、明るさをずらし線を 2 画素ずらして描く偽の模型（模型の直しで実際に出た、境目の段差と線の食い違い）"""

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        self.calls.append(("redraw", prompt, seed))
        a = np.asarray(image.convert("RGB")).astype(np.int16)
        moved = np.roll(a, 2, axis=1) + 28
        out = Image.fromarray(np.clip(moved, 0, 255).astype(np.uint8))
        return Image.composite(out, image.convert("RGB"), mask)


class SeamTest(unittest.TestCase):
    def test_adjust_grows_only_to_nearby_lines(self):
        img = hair()
        m = disc(img.size, (70, 50, 130, 110))
        adj = seamfix.adjust_mask(img, m, reach=6)
        a, b = np.asarray(m) > 127, np.asarray(adj) > 127
        self.assertTrue(b[a].all())                                     # 囲んだ所は全部直す
        self.assertTrue((b & ~a).any())                                 # 線の際まで広がった
        self.assertFalse((b & ~seamfix._dilate(a, 6)).any())             # 囲みの近く（6 画素）より外へは広げない
        flat = Image.new("RGB", img.size, (235, 190, 170))
        self.assertEqual(np.asarray(seamfix.adjust_mask(flat, m, reach=6)).astype(bool).sum(), a.sum())   # 線が無ければ広げない

    def test_harmonize_keeps_outside_and_reduces_step(self):
        img = hair()
        m = disc(img.size, (60, 40, 140, 120))
        bad = Shifted().redraw("", 0, img, m)
        before = seamfix.measure(img, bad, m)
        out, tried = seamfix.settle(img, bad, m)
        after = seamfix.measure(img, out, m)
        outside = np.asarray(m) <= 127
        self.assertTrue((np.asarray(out)[outside] == np.asarray(img)[outside]).all())   # 囲みの外は 1 画素も変えない
        self.assertLess(after["color"], before["color"])
        self.assertLess(after["shift"], before["shift"])
        self.assertGreater(after["ssim"], before["ssim"])
        self.assertTrue(after["ok"], after)
        inner = seamfix._erode(np.asarray(m) > 127, tried[-1]["band"] + 2)
        self.assertTrue((np.asarray(out)[inner] == np.asarray(bad)[inner]).all())   # 帯の奥は模型の直しのまま

    def test_fix_reports_seam_numbers_and_keeps_far_outside(self):
        img = hair()
        m = disc(img.size, (60, 40, 140, 120))
        studio = Studio(FakeWords(), Shifted(), Path(mkdtemp()))
        _, path = studio.fix(img, [(m, "目を直して")], 3)
        layer = Image.open(path)
        seam = studio.last_seam[-1]
        self.assertTrue(seam["ok"], seam)
        far = ~seamfix._dilate(np.asarray(m) > 127, 8)
        self.assertTrue((np.asarray(layer)[..., 3][far] == 0).all())   # 広げた所より外は透かしたまま（下の絵を隠さない）


class PersistTest(unittest.TestCase):
    def test_stops_only_when_same_flaw_survives_every_hand(self):
        p = Persist(["a", "b", "c"])
        seen = []
        for _ in p.rounds():
            seen.append(p.hand())
            if not p.go_on(["指が 6 本"]):
                break
        self.assertEqual(seen, ["a", "a", "b", "c"])   # 1 回目が基準。減らないので手を替え、3 つの手を全部試して止まる
        self.assertIn("減らなかった", p.reason)

    def test_keeps_going_while_improving(self):
        p = Persist(["a"])
        self.assertTrue(p.go_on(["1", "2", "3"]))
        self.assertTrue(p.go_on(["1", "2"]))
        self.assertTrue(p.go_on(["1"]))      # 減り続ける間は止めない（上限なし）
        self.assertFalse(p.go_on([]))

    def test_stop_button(self):
        flag = {"stop": False}
        p = Persist(["a"], stopped=lambda: flag["stop"])
        self.assertTrue(p.go_on(["x"]))
        flag["stop"] = True
        self.assertFalse(p.go_on(["y"]))

    def test_draw_has_no_round_limit(self):
        self.assertIsNone(Studio.REDRAW_TRIES)
        self.assertIsNone(Studio.FIX_ROUNDS)
        from chatdraw import twostage
        self.assertIsNone(twostage.COMPOSE_TRIES)
        self.assertIsNone(twostage.FIX_ROUNDS)


class RepeatRedPenTest(unittest.TestCase):
    """直した結果に、もう一度赤ペンを重ねて直す。レイヤーが重なっても壊れず、元に戻すで 1 回ずつ戻る"""

    def setUp(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        self.app = QApplication.instance() or QApplication([])
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, Path(mkdtemp())))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)
        self.w.canvas.new_canvas(200, 160)

    def tearDown(self):
        self.w.dirty = False
        self.w.close()

    def circle(self, cx, cy, r):
        import math
        from PySide6.QtCore import QPointF
        pen = self.w.canvas.redpen
        pen.begin(QPointF(cx + r, cy))
        for k in range(1, 41):
            a = 2 * math.pi * k / 40
            pen.add(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        pen.end()

    def fix(self, cx, cy, r, text):
        self.circle(cx, cy, r)
        self.w.canvas.marked.emit()
        self.w.entry.setText(text)
        self.w.send()
        wait_idle(self.app, self.w)

    def test_fix_again_on_fixed_layer_and_undo_each(self):
        from chatdraw.app import qimage_to_pil
        c = self.w.canvas
        start = len(c.layers)
        first0 = qimage_to_pil(c.flatten()).convert("RGB")
        self.fix(60, 60, 25, "手を直して")
        self.assertEqual(len(c.layers), start + 1)
        after1 = qimage_to_pil(c.flatten()).convert("RGB")
        self.fix(70, 65, 20, "もう少し細く")             # 1 回目に直した所に重ねて、もう一度直す
        self.assertEqual(len(c.layers), start + 2)
        self.assertEqual(c.redpen.marks, [])
        self.assertEqual(len([x for x in self.painter.calls if x[0] == "redraw"]), 2)
        c.tool = "pen"
        c.undo()                                        # 元に戻すは 1 回ずつ
        self.assertEqual(len(c.layers), start + 1)
        self.assertIsNone(_diff(qimage_to_pil(c.flatten()).convert("RGB"), after1))
        c.undo()
        self.assertEqual(len(c.layers), start)
        self.assertIsNone(_diff(qimage_to_pil(c.flatten()).convert("RGB"), first0))


def _diff(a, b):
    from PIL import ImageChops
    return ImageChops.difference(a, b).getbbox()


if __name__ == "__main__":
    unittest.main()
