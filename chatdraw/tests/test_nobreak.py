"""加工が元の絵を壊さない: 整える・指定した箇所の周辺を整える・ディテール追加・まとめて綺麗にする・塗りのむらを均す。

前は「顔を整える」がどの絵も同じ顔・同じ目の色に描き直し、「まとめて綺麗にする」が色の付いた絵を白い地の線画に変え、
「塗りのむらを均す」が細い線（服のひだ）を途切れさせ、粒消しがシャツのボタンを消した。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from chatdraw import facefeat, finishers, shortcuts

ROOT = Path(__file__).resolve().parents[2]


def figure(size=(128, 128)) -> Image.Image:
    """顔（肌の丸）と青い目、茶色の髪、ざらつきのある服の絵"""
    rng = np.random.default_rng(0)
    a = np.full((size[1], size[0], 3), 235, np.float32)
    a[64:, :] = (90, 110, 70)                                              # 服
    a[64:, :] += rng.normal(0, 3, (size[1] - 64, size[0], 1))             # 服の塗りのむら
    for x in range(8, size[0], 12):
        a[70:, x] = (60, 75, 45)                                           # 1 画素の細いひだ
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    d.rectangle((30, 0, 98, 18), fill=(110, 70, 40))                      # 髪
    d.ellipse((34, 14, 94, 62), fill=(245, 210, 190))                     # 顔
    for cx in (52, 76):
        d.ellipse((cx - 5, 28, cx + 5, 38), fill=(40, 90, 200))           # 目
    return im


def labels(size=(128, 128)) -> Image.Image:
    lab = Image.new("L", size, 0)
    d = ImageDraw.Draw(lab)
    d.rectangle((30, 0, 98, 13), fill=facefeat.HAIR)
    d.ellipse((34, 14, 94, 62), fill=facefeat.FACE)
    return lab


def box_mask(size, box):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle(box, fill=255)
    return m


def outside_same(a, b, mask) -> bool:
    d = np.asarray(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).max(2)
    return not (d[np.asarray(mask) < 128] > 0).any()


class FakeSeg(unittest.TestCase):
    """部位分けの模型の代わりに、描いた絵の部位をそのまま返す（facefeat の測り方と戻し方を確かめる）"""

    def setUp(self):
        p = mock.patch.object(facefeat, "seg_small", side_effect=lambda im: labels(im.size))
        p.start()
        self.addCleanup(p.stop)


class FeatureKeepTest(FakeSeg):
    def test_measures_eyes_and_hair(self):
        f = facefeat.features(figure())
        self.assertTrue(f["measured"])
        self.assertEqual(len(f["eyes"]), 2)
        self.assertGreater(f["eye"][2], f["eye"][0])   # 目は青い
        self.assertLess(np.abs(f["hair"] - (110, 70, 40)).max(), 1)

    def test_changed_eye_color_goes_back(self):
        src = figure()
        out = src.copy()
        d = ImageDraw.Draw(out)
        for cx in (52, 76):
            d.ellipse((cx - 5, 28, cx + 5, 38), fill=(150, 60, 40))     # どの絵も同じ色の目にされた
        back, rep = facefeat.keep(src, out)
        self.assertEqual(rep["back"], ["顔（目の色と形）"])
        self.assertGreater(rep["before"]["eye"], facefeat.EYE_COLOR)
        self.assertLess(rep["after"]["eye"], 1.0)
        self.assertIn("元の絵に戻しました", facefeat.note(rep, "整える"))

    def test_changed_hair_goes_back_but_not_outside_mask(self):
        src = figure()
        out = src.copy()
        ImageDraw.Draw(out).rectangle((30, 0, 98, 13), fill=(240, 240, 120))
        mask = box_mask(src.size, (0, 0, 64, 127))
        out = finishers.keep_outside(src, out, mask)
        back, rep = facefeat.keep(src, out, mask)
        self.assertIn("髪の色", rep["back"])
        self.assertTrue(outside_same(src, back, mask))
        self.assertEqual(back.getpixel((40, 5)), src.getpixel((40, 5)))

    def test_unchanged_is_untouched(self):
        src = figure()
        out, rep = facefeat.keep(src, src.copy())
        self.assertEqual(rep["back"], [])
        self.assertIsNone(ImageChops.difference(src, out).getbbox())

    def test_no_model_says_not_measured(self):
        with mock.patch.object(facefeat, "seg_small", return_value=None):
            _out, rep = facefeat.keep(figure(), figure())
        self.assertFalse(rep["measured"])


class TidyTest(FakeSeg):
    def test_tidy_is_renamed_and_keeps_face(self):
        f = finishers.REGISTRY["face"]
        self.assertEqual(f.label, "整える")
        self.assertTrue(f.ready())                       # 模型を使わない
        self.assertNotEqual(f.group, "redraw")
        src = figure()
        out = finishers.run("face", src)
        lab = np.asarray(labels(src.size))
        d = np.asarray(ImageChops.difference(src, out)).max(2)
        self.assertEqual(int(d[lab == facefeat.FACE].max()), 0)   # 顔の画素は 1 つも変えない
        self.assertLess(facefeat.compare(facefeat.features(src), facefeat.features(out)).get("eye", 0), 1.0)

    def test_around_needs_region_and_keeps_outside(self):
        src = figure()
        with self.assertRaises(finishers.Unavailable) as e:
            finishers.run("around", src)
        self.assertIn("囲んで", str(e.exception))
        mask = box_mask(src.size, (0, 70, 60, 127))
        out = finishers.run("around", src, mask)
        self.assertTrue(outside_same(src, out, mask))
        self.assertIsNotNone(ImageChops.difference(src, out).getbbox())   # 囲みの中は整えた

    def test_detail_keeps_shape_color_and_outside(self):
        src = figure()
        f = finishers.REGISTRY["detail"]
        self.assertTrue(f.extra.get("effect"))           # 結果は変わった画素だけの、一番上の新しいレイヤー
        mask = box_mask(src.size, (0, 64, 127, 127))
        out = finishers.run("detail", src, mask)
        self.assertTrue(outside_same(src, out, mask))
        q = finishers.scores(src, out)
        self.assertGreater(q["ssim"], 0.95)
        self.assertLess(q["color"], 3.0)


class CleanKeepsThinLinesTest(unittest.TestCase):
    def test_thin_folds_stay(self):
        src = figure()
        out = finishers._clean_apply(src)
        a, b = np.asarray(src, np.float32), np.asarray(out, np.float32)
        for x in range(8, 128, 12):
            self.assertLess(np.abs(a[72:, x] - b[72:, x]).max(), finishers.CLEAN_CAP + 1, x)

    def test_defaults_drop_breaking_steps(self):
        steps = dict((c[0], c[2]) for c in shortcuts.COMBOS)
        self.assertNotIn("ink", steps["combo:tidy"])     # 色の絵を線画に変えた
        for n in ("heal", "sharpen"):
            self.assertNotIn(n, finishers.RETOUCH_SAFE)
            self.assertNotIn(n, finishers.RETOUCH_FULL)
        for n in ("fin:face", "fin:around", "fin:detail"):
            self.assertIn(n, shortcuts.DEFAULT_SHOWN)


@unittest.skipUnless(facefeat.ready(), "部位分けの模型が取れていない")
class RealSampleTest(unittest.TestCase):
    """本物の部位分けで、見本の顔の寄りに整える・まとめて綺麗にするを掛けても、目の色と髪の色が変わらない"""

    def test_face_closeup(self):
        src = Image.open(ROOT / "library/eyes/eyes-blue.jpg").convert("RGB")
        f0 = facefeat.features(src)
        self.assertIn("eye", f0)
        lab = facefeat.seg(src)
        for run in (lambda: finishers.run("face", src), lambda: finishers.run_chain(("clean", "retouch"), src)):
            out = run()
            d = facefeat.compare(f0, facefeat.features(out, lab))
            self.assertLess(d["eye"], facefeat.EYE_COLOR)
            self.assertLess(d.get("hair", 0), facefeat.HAIR_COLOR)
            self.assertGreater(finishers.scores(src, out)["ssim"], 0.98)


if __name__ == "__main__":
    unittest.main()
