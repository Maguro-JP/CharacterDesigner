"""確かめの担当が「効いていない」とした右クリックと加工（docs/knowledge/function-check.md）の直しが戻らないかを見る普段の試験。

- 囲んだ所を直すで指示が無いとき、黙らず何をすればよいかを出し、指示の欄を開く
- 線と塗りを整えるが、にじみの無い絵でも画素を変える
- ディテール追加・宝石・霞と遠近が、顔（目）を変えない（目の色の差 1.5 以下、囲みの外 0 画素）
- 線画・ドット絵・透過・ちびキャラ・レイヤーのまま 2 倍が、囲みがあれば囲みの中だけに掛かる（囲みの外 0 画素）
- 線画の画風を、色を除いたことによる形の変わりで止めない"""
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
from PySide6.QtCore import QPointF, QRect  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402

BOX = (20, 20, 60, 70)


def changed(a, b):
    return np.abs(np.asarray(a.convert("RGB"), np.int16) - np.asarray(b.convert("RGB"), np.int16)).max(2) > 2


def box_mask(size, box=BOX):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle(box, fill=255)
    return m


class WindowFixTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        d = Path(self.tmp.name)
        self.home = mock.patch("chatdraw.paths.HOME", d / "home")
        self.home.start()
        (d / "out").mkdir()
        self.src = d / "out" / "a.png"
        figure().save(self.src)
        self.w = Window(Studio(FakeWords(), FakePainter(), d / "out"))
        self.old_place = self.w.settings.store.value("result_place")
        self.w.settings.set("result_place", "上のレイヤー")
        self.w.settings.set("output_dir", str(d / "out"))
        self.w.show_history_image(str(self.src))
        self.notes = []
        self.w.notify = lambda text, kind="info", detail="", on_click=None: self.notes.append((text, kind, detail))

    def tearDown(self):
        if self.old_place is None:
            self.w.settings.store.remove("result_place")
        else:
            self.w.settings.set("result_place", self.old_place)
        self.w.dirty = False
        self.w.close()
        self.home.stop()
        self.tmp.cleanup()

    def flat(self):
        from chatdraw.app import qimage_to_pil
        return qimage_to_pil(self.w.canvas.flatten()).convert("RGB")

    def mark(self, box=BOX):
        pen = self.w.canvas.redpen
        x0, y0, x1, y1 = box
        pen.begin(QPointF(x0, y0))
        for x, y in ((x1, y0), (x1, y1), (x0, y1), (x0, y0 + 1)):
            pen.add(QPointF(x, y))
        pen.end()

    def region(self, size):
        """赤ペンの印から作る囲み（印の線より少し広い）。加工はこの中だけを変えてよい"""
        from chatdraw.finishers import binary
        return np.asarray(binary(self.w._region_mask(), size)) > 0

    def wait(self, sec=60):
        end = time.time() + sec
        while (self.w.thread is not None or getattr(self.w, "bg_pending", 0)) and time.time() < end:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.qapp.processEvents()

    def test_fix_without_text_tells_and_opens(self):
        self.mark()
        self.w.entry.setText("")
        self.w.ai_panel.tabs.setCurrentIndex(self.w.ai_panel.tabs.count() - 1)
        self.w.fix_marked()
        self.assertIsNone(self.w.thread, "指示が無いのに直しを始めた")
        self.assertTrue(self.notes, "何も知らせない")
        self.assertIn("言葉で指示", self.notes[-1][2])
        self.assertTrue(self.w.ai_panel.sections["指示"].is_open(), "指示の欄を開かない")

    def test_fix_without_text_on_selection(self):
        self.w.canvas.set_selection(QRect(*BOX[:2], 30, 30))
        self.w.entry.setText("")
        self.w.fix_marked()
        self.assertIsNone(self.w.thread)
        self.assertTrue(self.notes, "選択範囲で囲んだときに何も知らせない")

    def _region_only(self, run):
        self.mark()   # 赤ペンの印も絵の上に出るので、印を付けたあとの絵と比べる
        before = self.flat()
        inside = self.region(before.size)
        run()
        self.wait()
        after = self.flat()
        ch = changed(before, after)
        return int((ch & inside).sum()), int((ch & ~inside).sum())

    def test_lineart_in_region(self):
        inside, outside = self._region_only(self.w.make_lineart)
        print(f"線画: 囲みの中 {inside} 画素、外 {outside} 画素")
        self.assertGreater(inside, 0)
        self.assertEqual(outside, 0)

    def test_pixel_in_region(self):
        inside, outside = self._region_only(self.w.make_pixel)
        print(f"ドット絵: 囲みの中 {inside} 画素、外 {outside} 画素")
        self.assertGreater(inside, 0)
        self.assertEqual(outside, 0)

    def test_transparent_in_region(self):
        # 切り抜きの模型は重いので、四隅の地を透明にする方（部品が無いときの道）で流す
        import builtins
        real = builtins.__import__

        def no_layers(name, *a, **k):
            if name == "layers":
                raise ImportError(name)
            return real(name, *a, **k)
        with mock.patch("builtins.__import__", no_layers):
            self.mark()
            self.w.make_transparent()
            self.wait()
        top = next(l for l in self.w.canvas.layers if l.name == "透過")
        from chatdraw.app import qimage_to_pil_rgba
        alpha = np.asarray(qimage_to_pil_rgba(top.image).getchannel("A"))
        outside = ~self.region(alpha.shape[::-1])
        self.assertEqual(int(alpha[outside].max()), 0, "透過のレイヤーが囲みの外を覆う")

    def test_clip_to_region(self):
        img = Image.new("RGB", (96, 128), (0, 0, 0))
        out = self.w._clip_to_region(img, box_mask(img.size))
        a = np.asarray(out.getchannel("A"))
        self.assertEqual(int(a[0, 0]), 0)
        self.assertEqual(int(a[40, 40]), 255)
        self.assertEqual(self.w._clip_to_region(img, None).getchannel("A").getextrema(), (255, 255))

    def test_chibi_in_region(self):
        made = Path(self.tmp.name) / "chibi.png"
        Image.new("RGB", (96, 128), (0, 200, 0)).save(made)
        self.mark()
        before = self.flat()
        inside = self.region(before.size)
        self.w._chibi_mask = self.w._region_mask()
        self.w.job_kind = "chibi"
        self.w.batch, self.w.batch_items = [], []
        with mock.patch.object(self.w, "_stale", lambda: False):
            self.w.on_one("", str(made))
        ch = changed(before, self.flat())
        self.assertGreater(int((ch & inside).sum()), 0)
        self.assertEqual(int((ch & ~inside).sum()), 0)

    def test_upscale_layers_in_region(self):
        from chatdraw import confirm, upscale
        self.mark()
        before = self.flat()
        inside = self.region(before.size)
        fake = lambda img, k, on_step=None: img.resize((img.width * k, img.height * k), Image.BICUBIC).point(lambda v: 255 - v)
        with mock.patch.object(upscale, "upscale", fake), mock.patch.object(confirm, "ask", lambda *a, **k: "go"):
            self.w.upscale_canvas()
            self.wait()
        after = self.flat()
        self.assertEqual(after.size, (before.width * 2, before.height * 2))
        back = after.resize(before.size, Image.BOX)
        ch = changed(before, back)
        print(f"レイヤーのまま 2 倍: 囲みの中 {int((ch & inside).sum())} 画素、外 {int((ch & ~inside).sum())} 画素")
        self.assertGreater(int((ch & inside).sum()), 0)
        self.assertEqual(int((ch & ~inside).sum()), 0)


class FinisherFixTest(unittest.TestCase):
    def test_retouch_changes_pixels(self):
        from chatdraw import finishers
        if not finishers.REGISTRY["retouch"].ready():
            self.skipTest("線と塗りの部品が無い")
        im = figure()
        out = finishers.run("retouch", im)
        n = int(changed(im, out).sum())
        print(f"線と塗りを整える: {n} 画素")
        self.assertGreater(n, 0, "線と塗りを整えるが 1 画素も変えない")

    def test_face_kept(self):
        from chatdraw import facefeat, finishers
        from chatdraw.tests.test_finish_quality import SAMPLE
        if not facefeat.ready():
            self.skipTest("部位分けの模型が無い")
        im = Image.open(SAMPLE).convert("RGB").resize((256, 384), Image.LANCZOS)
        mask = box_mask(im.size, (90, 20, 160, 100))
        f0 = facefeat.features(im)
        for name in ("detail", "mat_gem", "air_haze"):
            out = finishers.run(name, im, mask)
            if finishers.REGISTRY[name].extra.get("effect"):   # 画面と同じく、変わった画素だけのレイヤーを重ねて見る
                out = Image.alpha_composite(im.convert("RGBA"), finishers.effect_layer(im, out)).convert("RGB")
            ch = changed(im, out)
            d = facefeat.compare(f0, facefeat.features(out))
            print(f"{name}: {int(ch.sum())} 画素、囲みの外 {int((ch & ~(np.asarray(mask) > 0)).sum())}、顔 {d}")
            self.assertEqual(int((ch & ~(np.asarray(mask) > 0)).sum()), 0)
            self.assertLessEqual(d.get("eye", 0), 1.5, name)
            self.assertLessEqual(d.get("move", 0), 0.03, name)


class RestyleCheckTest(unittest.TestCase):
    def test_lineart_style_not_stopped_by_drift(self):
        from chatdraw import restyle
        im = Image.new("RGB", (128, 128), (30, 30, 30))
        ImageDraw.Draw(im).rectangle((0, 0, 63, 127), fill=(240, 240, 240))
        out = Image.new("RGB", (128, 128), (255, 255, 255))
        self.assertIn("形が変わりすぎる", restyle.check(im, out, "anime")["why"])
        self.assertNotIn("形が変わりすぎる", restyle.check(im, out, "lineart")["why"])


if __name__ == "__main__":
    unittest.main()
