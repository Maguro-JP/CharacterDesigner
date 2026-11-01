"""既存の絵をあとから直す流れと、仕上げ（綺麗化）の道具。絵の模型は偽物に替えて流れだけを確かめる"""
import json
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

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def figure(size=(96, 128)) -> Image.Image:
    im = Image.new("RGB", size, (240, 230, 220))
    d = ImageDraw.Draw(im)
    d.ellipse((20, 10, 76, 120), fill=(200, 80, 80), outline=(20, 20, 20), width=3)
    for y in range(0, size[1], 7):   # ざらつき（仕上げで変わる所）
        d.point([(x, y) for x in range(0, size[0], 5)], fill=(120, 120, 120))
    return im


def box_mask(size, box) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle(box, fill=255)
    return m


def outside_same(a, b, mask) -> bool:
    """囲みの外の画素がすべて同じか"""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    outside = ImageChops.multiply(diff, ImageChops.invert(mask.convert("L")))
    return outside.getbbox() is None


class EditExistingTest(unittest.TestCase):
    def test_open_existing_and_fix_keeps_outside(self):
        from chatdraw.app import Window, qimage_to_pil
        app()
        with TemporaryDirectory() as d:
            src = Path(d) / "old.png"
            figure().save(src)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d) / "out"))
            w.edit_image(str(src))
            self.assertEqual(w.mode.currentIndex(), 2)   # 直す形で開く
            base = qimage_to_pil(w.canvas.flatten()).convert("RGB")
            self.assertEqual(base.size, (96, 128))
            self.assertIsNone(ImageChops.difference(base, Image.open(src).convert("RGB")).getbbox())
            mask = box_mask(base.size, (30, 40, 60, 70))
            _, path = w.studio.fix(base, [(mask, "目を直して")], 7, check=False)
            after = Image.open(path).convert("RGB")
            self.assertTrue(outside_same(base, after, mask))
            self.assertIsNotNone(ImageChops.difference(base, after).getbbox())   # 囲みの中は変わった
            w.close()

    def test_sidecar_json_restores_request(self):
        from chatdraw.app import Window
        app()
        with TemporaryDirectory() as d:
            src = Path(d) / "20261101-1-42.png"
            figure().save(src)
            src.with_suffix(".json").write_text(json.dumps(
                dict(text="赤いマフラーの騎士", seed=42, model="some/model"), ensure_ascii=False), encoding="utf-8")
            w = Window(Studio(FakeWords(), FakePainter(), Path(d) / "out"))
            w.edit_image(str(src))
            self.assertEqual(w.entry.text(), "赤いマフラーの騎士")
            self.assertEqual(w.ai_panel.seed.value(), 42)
            self.assertEqual(w.fix_model, "some/model")
            # 取得していない模型なら、止めずに今の模型で直す
            self.assertIs(w._fix_studio(), w.studio)
            w.close()

    def test_missing_file_does_not_raise(self):
        from chatdraw.app import Window
        app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.edit_image(str(Path(d) / "none.png"))
            w.close()


class FinishersTest(unittest.TestCase):
    def test_mask_outside_is_identical(self):
        from chatdraw import finishers
        im = figure()
        mask = box_mask(im.size, (10, 10, 50, 60))
        out = finishers.run("clean", im, mask)
        self.assertEqual(out.size, im.size)
        self.assertTrue(outside_same(im, out, mask))
        self.assertIsNotNone(ImageChops.difference(im, out).getbbox())

    def test_soft_mask_edge_does_not_leak(self):
        from PIL import ImageFilter
        from chatdraw import finishers
        im = figure()
        soft = box_mask(im.size, (10, 10, 50, 60)).filter(ImageFilter.GaussianBlur(4))
        out = finishers.run("clean", im, soft)
        self.assertTrue(outside_same(im, out, finishers.binary(soft, im.size)))

    def test_resized_result_is_fitted_back(self):
        from chatdraw import finishers
        im = figure()
        mask = box_mask(im.size, (0, 0, 40, 40))
        big = finishers.keep_outside(im, im.resize((192, 256)).point(lambda v: 255 - v), mask)
        self.assertEqual(big.size, im.size)
        self.assertTrue(outside_same(im, big, mask))

    def test_unavailable_gives_reason(self):
        from chatdraw import finishers
        finishers.use_painter(None)
        with mock.patch.object(finishers, "_upscale_ready", return_value=False):
            listed = {f["name"]: f for f in finishers.available()}
            self.assertTrue(listed["clean"]["ready"])
            for name in ("upscale_anime", "face", "refine"):
                self.assertFalse(listed[name]["ready"])
                self.assertTrue(listed[name]["reason"])
            with self.assertRaises(finishers.Unavailable) as e:
                finishers.run("refine", figure())
            self.assertTrue(str(e.exception))
        for f in listed.values():   # 目録の道具は許諾と出典を持つ
            self.assertTrue(f["license"] and f["source"])

    def test_redraw_finisher_keeps_outside(self):
        from chatdraw import finishers
        finishers.use_painter(FakePainter())
        try:
            im = figure()
            mask = box_mask(im.size, (20, 20, 60, 60))
            out = finishers.run("face", im, mask)
            self.assertTrue(outside_same(im, out, mask))
        finally:
            finishers.use_painter(None)

    def test_app_finish_without_tool_does_not_stop(self):
        from chatdraw import finishers
        from chatdraw.app import Window
        app()
        with TemporaryDirectory() as d:
            src = Path(d) / "a.png"
            figure().save(src)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.settings.set("output_dir", str(Path(d) / "out"))
            w.edit_image(str(src))
            with mock.patch.object(finishers, "_upscale_ready", return_value=False):
                self.assertIsNone(w.finish_with("upscale_anime"))   # 理由を出して止めない
            n = len(w.canvas.layers)
            self.assertIsNotNone(w.finish_with("clean"))
            self.assertEqual(len(w.canvas.layers), n + 1)   # 元の絵は残し、新しいレイヤーに置く
            w.close()

    def test_menu_finish_runs_in_background(self):
        """メニューから押した仕上げは裏の糸で回る。画面の糸を止めずに、終わったら新しいレイヤーに置く"""
        import time as _t
        from chatdraw.app import Window
        qa = app()
        with TemporaryDirectory() as d:
            src = Path(d) / "a.png"
            figure().save(src)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.settings.set("output_dir", str(Path(d) / "out"))
            w.edit_image(str(src))
            n = len(w.canvas.layers)
            self.assertIsNone(w.finish_with("clean", background=True))   # すぐ戻る
            end = _t.time() + 20
            while len(w.canvas.layers) == n and _t.time() < end:
                qa.processEvents()
                _t.sleep(0.02)
            self.assertEqual(len(w.canvas.layers), n + 1)
            self.assertIsNone(w.thread)   # 裏の糸は片付いている
            w.close()

    def test_inpaint_models_only(self):
        from chatdraw import finishers
        from chatdraw.models import all_images, family
        every = all_images()
        have = [m.repo for m in every]
        got = finishers.inpaint_models(every, have)
        self.assertTrue(all(family(m.family).inpaint for m in got))
        self.assertEqual(finishers.inpaint_models(every, []), [])


class EmbedAndOutpaintTest(unittest.TestCase):
    def test_png_embed_restores_without_json(self):
        from chatdraw import finishers
        from chatdraw.app import Window
        app()
        with TemporaryDirectory() as d:
            src = Path(d) / "lone.png"
            im = figure()
            im.save(src)
            finishers.embed(src, dict(text="青い髪の魔法使い", seed=9, model="x/y"))
            self.assertFalse(src.with_suffix(".json").exists())
            self.assertIsNone(ImageChops.difference(im, Image.open(src).convert("RGB")).getbbox())   # 画素は同じ
            self.assertEqual(finishers.sidecar(src)["seed"], 9)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d) / "out"))
            w.edit_image(str(src))
            self.assertEqual(w.entry.text(), "青い髪の魔法使い")
            self.assertEqual(w.ai_panel.seed.value(), 9)
            w.close()

    def test_no_embed_gives_empty(self):
        from chatdraw import finishers
        with TemporaryDirectory() as d:
            src = Path(d) / "plain.png"
            figure().save(src)
            self.assertEqual(finishers.sidecar(src), {})

    def test_outpaint_keeps_original_pixels(self):
        from chatdraw import finishers
        im = figure()
        out = finishers.outpaint(im, 16, 8, 24, 0, painter=FakePainter())
        self.assertEqual(out.size, (im.width + 40, im.height + 8))
        self.assertIsNone(ImageChops.difference(out.crop((16, 8, 16 + im.width, 8 + im.height)), im).getbbox())

    def test_outpaint_without_model_says_why(self):
        from chatdraw import finishers
        finishers.use_painter(None)
        with self.assertRaises(finishers.Unavailable) as e:
            finishers.outpaint(figure(), 8, 0, 8, 0)
        self.assertTrue(str(e.exception))
        with self.assertRaises(ValueError):
            finishers.outpaint(figure(), painter=FakePainter())

    def test_app_outpaint_replaces_canvas(self):
        from chatdraw.app import Window
        app()
        with TemporaryDirectory() as d:
            src = Path(d) / "a.png"
            figure().save(src)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.settings.set("output_dir", str(Path(d) / "out"))
            w.edit_image(str(src))
            path = w.outpaint_canvas(64, 0, 64, 0)
            self.assertIsNotNone(path)
            self.assertEqual(w.canvas.size_px(), (96 + 128, 128))
            self.assertEqual(Path(path).suffix, ".png")
            w.close()


if __name__ == "__main__":
    unittest.main()
