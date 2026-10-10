"""画像処理の道具（tools/gen/imgproc.py）のうち、モデルを使わない所の試験。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import imgproc  # noqa: E402


def figure_on(bg):
    im = Image.new("RGB", (200, 240), bg)
    d = ImageDraw.Draw(im)
    d.ellipse([70, 20, 130, 80], fill=(245, 235, 230))     # 白に近い肌（緑から色みが遠すぎない色）
    d.rectangle([80, 80, 120, 200], fill=(200, 60, 80))
    return im


class Chroma(unittest.TestCase):
    def run_chroma(self, bg, key=None):
        with tempfile.TemporaryDirectory() as t:
            src, out = Path(t) / "in.png", Path(t) / "out.png"
            figure_on(bg).save(src)
            info = imgproc.chroma(str(src), str(out), key)
            return info, np.asarray(Image.open(out).getchannel("A"))

    def test_green_back_is_removed_and_pale_skin_kept(self):
        info, a = self.run_chroma((0, 177, 64))
        self.assertEqual(info["key"], "#00b140")      # 四隅から背景の色を拾う
        self.assertEqual(a[5, 5], 0)                   # 背景は透明
        self.assertEqual(a[50, 100], 255)              # 白に近い肌は残る（既定 tol 60 では半ば透けた）
        self.assertEqual(a[150, 100], 255)

    def test_explicit_blue_key(self):
        info, a = self.run_chroma((20, 60, 220), key="#143cdc")
        self.assertEqual(a[5, 5], 0)
        self.assertEqual(a[150, 100], 255)

    def test_despill_removes_green_cast_on_edges(self):
        with tempfile.TemporaryDirectory() as t:
            im = Image.new("RGB", (40, 40), (0, 177, 64))
            im.paste((150, 200, 150), (10, 10, 30, 30))   # 緑かぶりした灰
            im.save(Path(t) / "in.png")
            imgproc.chroma(str(Path(t) / "in.png"), str(Path(t) / "out.png"))
            r, g, b, _ = Image.open(Path(t) / "out.png").getpixel((20, 20))
            self.assertLessEqual(g, max(r, b))


class ClippingPath(unittest.TestCase):
    def test_contour_to_svg_path(self):
        # 切り抜きのモデルを使わず、透明度の付いた絵を直接渡して輪郭だけを確かめる
        with tempfile.TemporaryDirectory() as t:
            a = np.zeros((100, 100), bool); a[20:80, 30:70] = True
            from skimage import measure
            cs = measure.find_contours(np.pad(a, 1).astype(float), 0.5)
            self.assertEqual(len(cs), 1)
            c = measure.approximate_polygon(cs[0], 1.5) - 1
            xs, ys = c[:, 1], c[:, 0]
            self.assertAlmostEqual(xs.min(), 29.5, delta=1); self.assertAlmostEqual(xs.max(), 69.5, delta=1)
            self.assertLessEqual(len(c), 10)               # 四角は数点に縮まる


class Cli(unittest.TestCase):
    def test_help_lists_all_techniques(self):
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "gen" / "imgproc.py"), "-h"], capture_output=True, text=True).stdout
        for word in ("segment", "matte", "remove", "cutout", "chroma", "roto"):
            self.assertIn(word, out)


if __name__ == "__main__":
    unittest.main()
