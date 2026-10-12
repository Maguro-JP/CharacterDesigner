"""色の置き換え・色調補正・色合わせ（tools/gen/imgproc.py の recolor / grade / match）の試験。模型は使わない。"""
import colorsys
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import imgproc  # noqa: E402


def scarf(tmp: str) -> str:
    """灰色の布（明るい面と影の面）と、肌色の顔と、白地"""
    im = Image.new("RGB", (120, 120), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 60, 110], fill=(150, 150, 155))   # 布の明るい面
    d.rectangle([60, 10, 90, 110], fill=(90, 90, 95))      # 布の影の面
    d.ellipse([92, 20, 118, 46], fill=(240, 200, 170))     # 顔
    p = str(Path(tmp) / "in.png")
    im.save(p)
    return p


class Recolor(unittest.TestCase):
    def test_gray_cloth_becomes_red_and_keeps_shading(self):
        with tempfile.TemporaryDirectory() as t:
            out = str(Path(t) / "out.png")
            info = imgproc.recolor(scarf(t), out, "#969696", "#c02020", tol=40)
            a = np.asarray(Image.open(out).convert("RGB")).astype(int)
            lit, shade, face, paper = a[50, 30], a[50, 75], a[33, 105], a[5, 5]
            for px in (lit, shade):
                self.assertGreater(px[0], px[1] + 40)          # 赤くなった
            self.assertGreater(lit.sum(), shade.sum() + 60)    # 明るい面と影の面の差は残る
            self.assertEqual(tuple(face), (240, 200, 170))     # 範囲の外の色は変えない
            self.assertEqual(tuple(paper), (255, 255, 255))    # 白地も変えない
            self.assertGreater(info["changed"], 0.2)

    def test_box_limits_the_change(self):
        with tempfile.TemporaryDirectory() as t:
            out = str(Path(t) / "out.png")
            imgproc.recolor(scarf(t), out, "#969696", "#c02020", tol=40, box=(0, 0, 40, 120))
            a = np.asarray(Image.open(out).convert("RGB")).astype(int)
            self.assertGreater(a[50, 20][0], a[50, 20][1] + 40)    # 枠の中は赤
            self.assertEqual(tuple(a[50, 50]), (150, 150, 155))    # 同じ灰色でも枠の外は元のまま

    def test_light_gray_does_not_tint_the_white_paper(self):
        with tempfile.TemporaryDirectory() as t:
            src, out = str(Path(t) / "in.png"), str(Path(t) / "out.png")
            im = Image.new("RGB", (40, 40), "white")
            ImageDraw.Draw(im).rectangle([0, 0, 19, 39], fill=(203, 201, 206))
            im.save(src)
            imgproc.recolor(src, out, "#cbc9ce", "#d23a30", tol=20)
            a = np.asarray(Image.open(out)).astype(int)
            self.assertGreater(a[20, 5][0], a[20, 5][1] + 40)
            self.assertEqual(tuple(a[20, 35]), (255, 255, 255))

    def test_nothing_near_the_color_changes_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            out = str(Path(t) / "out.png")
            info = imgproc.recolor(scarf(t), out, "#00ff00", "#c02020", tol=20)
            self.assertEqual(info["changed"], 0.0)
            self.assertTrue(np.array_equal(np.asarray(Image.open(out)), np.asarray(Image.open(Path(t) / "in.png"))))


class Grade(unittest.TestCase):
    def test_brightness_saturation_and_warmth(self):
        with tempfile.TemporaryDirectory() as t:
            src = str(Path(t) / "in.png")
            Image.new("RGB", (8, 8), (120, 100, 90)).save(src)
            out = str(Path(t) / "out.png")
            imgproc.grade(src, out, brightness=1.2)
            self.assertGreater(np.asarray(Image.open(out)).mean(), 105)
            imgproc.grade(src, out, saturation=0.0)
            r, g, b = np.asarray(Image.open(out))[0, 0]
            self.assertLessEqual(max(r, g, b) - min(r, g, b), 1)   # 彩度 0 は灰色
            imgproc.grade(src, out, warmth=0.3)
            r2, _, b2 = np.asarray(Image.open(out)).astype(int)[0, 0]
            self.assertGreater(r2 - b2, 120 - 90)                  # 暖かくすると赤が青より強まる

    def test_identity_keeps_the_image(self):
        with tempfile.TemporaryDirectory() as t:
            p = scarf(t)
            out = str(Path(t) / "out.png")
            imgproc.grade(p, out)
            diff = np.abs(np.asarray(Image.open(out)).astype(int) - np.asarray(Image.open(p)).astype(int))
            self.assertLessEqual(diff.max(), 1)


class Match(unittest.TestCase):
    def test_moves_toward_the_reference_colors(self):
        with tempfile.TemporaryDirectory() as t:
            src, ref, out = (str(Path(t) / n) for n in ("in.png", "ref.png", "out.png"))
            rng = np.random.default_rng(0)
            Image.fromarray(rng.integers(60, 120, (32, 32, 3)).astype("uint8")).save(src)          # 暗く地味
            warm = np.stack([rng.integers(200, 250, (32, 32)), rng.integers(140, 180, (32, 32)), rng.integers(60, 90, (32, 32))], -1)
            Image.fromarray(warm.astype("uint8")).save(ref)                                         # 明るく暖かい
            info = imgproc.match(src, ref, out, amount=1.0)
            a = np.asarray(Image.open(out)).astype(float).reshape(-1, 3).mean(0)
            r = warm.reshape(-1, 3).mean(0)
            self.assertLess(np.abs(a - r).max(), 12)
            self.assertLess(info["after"], info["before"])
            half = str(Path(t) / "half.png")
            imgproc.match(src, ref, half, amount=0.5)
            h = np.asarray(Image.open(half)).astype(float).reshape(-1, 3).mean(0)
            s = np.asarray(Image.open(src)).astype(float).reshape(-1, 3).mean(0)
            self.assertTrue(np.all(np.minimum(s, r) - 3 <= h) and np.all(h <= np.maximum(s, r) + 3))   # 半分は間に来る


if __name__ == "__main__":
    unittest.main()
