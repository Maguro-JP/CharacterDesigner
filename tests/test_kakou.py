"""画風と加工の目録（tools/gen/catalog.py）と、漫画・線画・トーン・パースの試験。"""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import catalog  # noqa: E402
import tones  # noqa: E402

try:
    import skimage  # noqa: F401
except ImportError:
    skimage = None


def animal(w=192, h=128):
    """明るい地の上の、暗い胴と明るい顔の生き物（被写体の切り出しと明暗の段が両方かかる形）"""
    im = Image.new("RGB", (w, h), (235, 232, 225))
    d = ImageDraw.Draw(im)
    d.ellipse([50, 30, 150, 100], fill=(90, 60, 40))
    d.ellipse([120, 20, 170, 70], fill=(200, 170, 140))
    for x in (65, 85, 115, 135):
        d.rectangle([x, 90, x + 8, 118], fill=(40, 30, 25))
    return im


class TestCatalog(unittest.TestCase):
    def test_every_kakou_runs_and_keeps_size(self):
        im = animal()
        for n, (_, _, f) in catalog.ALL.items():
            out = f(im)
            self.assertEqual(out.size, im.size, n)
            self.assertEqual(out.mode, "RGB", n)

    def test_names_unique_and_effects_not_in_gafu(self):
        names = [n for d in catalog.KAKOU.values() for n in d]
        self.assertEqual(len(names), len(set(names)))
        prompts = " ".join(p for rows in catalog.GAFU.values() for _, _, p in rows)
        for word in ("speed lines", "fisheye", "focus lines", "vignette", "glitch"):
            self.assertNotIn(word, prompts)

    def test_markdown_lists_all(self):
        md = catalog.markdown()
        for n in catalog.ALL:
            self.assertIn(f"| {n} |", md)


class TestLineVsManga(unittest.TestCase):
    """線画は線だけ（大きな黒い面を持たない）、漫画はベタとトーンを持つ"""

    def black_area(self, im):
        g = np.asarray(im.convert("L")) < 60
        return g.mean()

    def test_lineart_has_no_beta(self):
        """暗い胴を、線画は線の内側を白のまま残し、漫画はベタで塗る"""
        inside = (slice(55, 75), slice(70, 100))     # 胴の真ん中（輪郭の線から離れた所）
        for n in catalog.KAKOU["線画"]:
            g = np.asarray(catalog.ALL[n][2](animal()).convert("L"))[inside]
            self.assertGreater(g.mean(), 200, n)
        g = np.asarray(catalog.ALL["manga_shonen"][2](animal()).convert("L"))[inside]
        self.assertLess(g.mean(), 128)

    def test_manga_is_black_and_white_with_more_ink(self):
        line = self.black_area(catalog.ALL["lineart"][2](animal()))
        for n in ("manga_shonen", "manga_gekiga"):
            out = np.asarray(catalog.ALL[n][2](animal()).convert("L"))
            self.assertTrue(set(np.unique(out)) <= {0, 255}, n)
            self.assertGreater((out < 60).mean(), line, n)


class TestTones(unittest.TestCase):
    def test_density_follows_value(self):
        """どのトーンも、渡した濃さが大きいほど墨が多い"""
        for n in tones.TONES:
            a = [tones.render(n, v, 120, 120).mean() for v in (0.1, 0.5, 0.9)]
            self.assertLess(a[0], a[2], n)

    def test_fine_is_finer_than_coarse(self):
        def cells(name):
            row = tones.render(name, 0.3, 1200, 1200)[600]
            return int(np.abs(np.diff(row)).sum())
        self.assertGreater(cells("dot_fine"), cells("dot_mid"))
        self.assertGreater(cells("dot_mid"), cells("dot_coarse"))


@unittest.skipIf(skimage is None, "skimage が無い")
class TestPerspective(unittest.TestCase):
    def corridor(self, tilt=0.0):
        """中央の 1 点へ向かう床と壁の線、縦の柱（tilt 度だけ傾ける）"""
        w, h = 640, 420
        im = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(im)
        vp = (320, 160)
        for x in range(-400, 1100, 90):
            d.line([vp, (x, h)], fill="black", width=3)
            d.line([vp, (x, 0)], fill="black", width=3)
        dx = np.tan(np.radians(tilt)) * h
        for x in (60, 160, 480, 580):
            d.line([(x, 0), (x + dx, h)], fill="black", width=5)
        return im

    def test_one_point(self):
        import perspective
        m = perspective.measure(self.corridor())
        self.assertTrue(m["vp"])
        self.assertAlmostEqual(m["vp"][0]["x"], 0.5, delta=0.05)
        self.assertAlmostEqual(m["vp"][0]["y"], 160 / 420, delta=0.05)
        self.assertGreater(m["converge"], 0.8)

    def test_tilt_is_measured(self):
        import perspective
        self.assertLess(perspective.measure(self.corridor(0))["vertical_tilt"], 1.0)
        self.assertGreater(perspective.measure(self.corridor(6))["vertical_tilt"], 4.0)


if __name__ == "__main__":
    unittest.main()
