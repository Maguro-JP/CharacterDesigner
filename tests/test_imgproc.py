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

try:
    import skimage  # noqa: F401  輪郭の抽出に使う。描く部品（.cache/gen/lib）に入っている
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False


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


@unittest.skipUnless(HAS_SKIMAGE, "scikit-image が無い（sh tools/gen/setup.sh で入る）")
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


@unittest.skipUnless(HAS_SKIMAGE, "描く部品（scipy など）が無い")
class Solid(unittest.TestCase):
    """影の付け方の、立体の計算（モデルを使わない所）"""

    def test_dome_of_disk_is_round_and_highest_in_center(self):
        yy, xx = np.mgrid[0:120, 0:120]
        disk = (yy - 60) ** 2 + (xx - 60) ** 2 < 50 ** 2
        h = imgproc.inflate_dome(disk)
        self.assertEqual(h[~disk].max(), 0)
        self.assertGreater(h[60, 60], h[60, 30])           # 中心が一番高い
        self.assertAlmostEqual(h[60, 40], h[40, 60], delta=0.05)   # 向きによらず同じ（円い山）

    def test_normals_face_outward_at_edges(self):
        yy, xx = np.mgrid[0:120, 0:120]
        disk = (yy - 60) ** 2 + (xx - 60) ** 2 < 50 ** 2
        n = imgproc.normals(imgproc.inflate_dome(disk) * 30)
        self.assertLess(n[60, 15, 0], -0.3)    # 左の縁は左を向く
        self.assertGreater(n[60, 105, 0], 0.3) # 右の縁は右を向く
        self.assertGreater(n[15, 60, 1], 0.3)  # 上の縁は上を向く（y は上向き）
        self.assertGreater(n[60, 60, 2], 0.95) # 中心は手前を向く

    def test_tall_block_casts_shadow_away_from_light(self):
        h = np.zeros((60, 60)); h[20:40, 25:35] = 30.0   # 高い柱
        h[:, :] += 1.0
        light = np.array([-1.0, 0.0, 0.4]); light /= np.linalg.norm(light)   # 左から低い光
        s = imgproc.cast_shadow(h, light, reach=30)
        self.assertEqual(s[30, 45], 1)   # 柱の右（光と反対）は影
        self.assertEqual(s[30, 10], 0)   # 柱の左（光の側）は影にならない


@unittest.skipUnless(HAS_SKIMAGE, "skimage が無い")
class NotanTest(unittest.TestCase):
    """明暗の塊: 3段の大きな面だけの絵は塊3つ・細切れ無し、砂嵐は細切れだらけになる"""

    def run_notan(self, im):
        whole = lambda src, img: np.ones((img.height, img.width), bool)  # 人物の切り抜き（モデル）を使わない
        orig, imgproc._person_alpha = imgproc._person_alpha, whole
        try:
            with tempfile.TemporaryDirectory() as d:
                im.save(f"{d}/a.png")
                return imgproc.notan(f"{d}/a.png", f"{d}/b.png")
        finally:
            imgproc._person_alpha = orig

    def test_three_masses(self):
        im = Image.new("RGB", (300, 300), (230, 230, 230))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 100, 299, 199], fill=(128, 128, 128)); d.rectangle([0, 200, 299, 299], fill=(30, 30, 30))
        r = self.run_notan(im)
        self.assertEqual(r["masses"], 3)
        self.assertEqual(r["fragment_ratio"], 0.0)

    def test_noise_is_fragmented(self):
        rng = np.random.default_rng(0)
        r = self.run_notan(Image.fromarray(rng.integers(0, 255, (300, 300, 3), dtype="uint8")))
        self.assertGreater(r["fragment_ratio"], 0.5)


@unittest.skipUnless(HAS_SKIMAGE, "scipy と skimage が無い（描く部品 .cache/gen/lib に入っている）")
class LineWeightTest(unittest.TestCase):
    """外形を太く（6px）、内側を細く（2px）描いた図形は ratio が 1 を十分に超える"""

    def test_thick_outline(self):
        im = Image.new("RGB", (300, 300), (240, 240, 240))
        d = ImageDraw.Draw(im)
        d.ellipse([40, 40, 260, 260], fill=(230, 200, 180), outline=(20, 20, 20), width=6)
        d.line([100, 150, 200, 150], fill=(20, 20, 20), width=2)
        d.line([150, 100, 150, 200], fill=(20, 20, 20), width=2)
        mask = np.zeros((300, 300), bool)
        yy, xx = np.mgrid[:300, :300]
        mask[(yy - 150) ** 2 + (xx - 150) ** 2 <= 110 ** 2] = True
        orig, imgproc._person_alpha = imgproc._person_alpha, lambda src, img: mask
        try:
            with tempfile.TemporaryDirectory() as t:
                im.save(f"{t}/a.png")
                r = imgproc.line_weight(f"{t}/a.png")
        finally:
            imgproc._person_alpha = orig
        self.assertGreater(r["ratio"], 1.5, r)


class MatchRingTest(unittest.TestCase):
    """描き直した絵の明るさを、範囲のすぐ外の輪で元の絵に合わせる（継ぎ目の明るさの差を消す）"""

    def test_shift_to_surroundings(self):
        import edit
        im = Image.new("RGB", (64, 64), (100, 120, 140))
        gen = Image.new("RGB", (64, 64), (160, 150, 140))
        mask = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(mask).rectangle([20, 20, 40, 40], fill=255)
        self.assertEqual(edit._match_ring(gen, im, mask).getpixel((30, 30)), (100, 120, 140))


class LineartTest(unittest.TestCase):
    """線画の抽出: 塗りの面は白に、境目は黒い線になる"""

    def test_edges_become_lines(self):
        import tempfile
        import imgproc
        im = Image.new("RGB", (80, 80), "white")
        ImageDraw.Draw(im).rectangle([20, 20, 60, 60], fill=(200, 60, 60))
        with tempfile.TemporaryDirectory() as d:
            src, out = f"{d}/a.png", f"{d}/b.png"
            im.save(src)
            r = imgproc.lineart(src, out)
            g = Image.open(out)
            self.assertEqual(g.getpixel((40, 40)), 255)   # 面の中は白
            self.assertEqual(g.getpixel((5, 5)), 255)
            self.assertTrue(any(g.getpixel((x, 40)) == 0 for x in range(16, 25)))   # 境目に線
            self.assertGreater(r["line_ratio"], 0)
