"""描く板の道具（空気感・ブラシ・線の清書）の、模型を使わない部分"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import atmosphere  # noqa: E402
import brushes  # noqa: E402

try:
    import skimage  # noqa: F401
except ImportError:
    skimage = None


class Atmosphere(unittest.TestCase):
    def setUp(self):
        self.img = Image.new("RGB", (64, 48), (90, 110, 130))

    def test_every_mood_keeps_size_and_changes_pixels(self):
        for mood in atmosphere.MOODS:
            out = atmosphere.apply(self.img, mood, 0.8)
            self.assertEqual(out.size, self.img.size, mood)
            diff = np.abs(np.asarray(out.convert("RGB"), int) - np.asarray(self.img, int)).sum()
            self.assertGreater(diff, 0, mood)

    def test_zero_strength_is_identity(self):
        out = atmosphere.apply(self.img, "holy", 0.0)
        self.assertTrue((np.asarray(out.convert("RGB")) == np.asarray(self.img)).all())

    def test_same_seed_same_result_and_unknown_mood(self):
        a = np.asarray(atmosphere.apply(self.img, "dust", 0.7, seed=3))
        b = np.asarray(atmosphere.apply(self.img, "dust", 0.7, seed=3))
        self.assertTrue((a == b).all())
        with self.assertRaises(ValueError):
            atmosphere.apply(self.img, "nope")


@unittest.skipIf(skimage is None, "scikit-image が無い")
class Brushes(unittest.TestCase):
    def test_line_becomes_one_stroke_and_renders(self):
        line = np.zeros((40, 60), bool)
        line[20, 5:55] = True
        paths = brushes.strokes(line)
        self.assertEqual(len(paths), 1)
        self.assertGreaterEqual(len(paths[0]), 40)
        name = next(iter(brushes.table()["brushes"]))
        im = brushes.render((60, 40), paths, name)
        self.assertEqual(im.size, (60, 40))
        self.assertGreater(np.asarray(im)[..., 3].astype(int).sum(), 0)   # 色は一定で、筆跡は不透明度に出る


@unittest.skipIf(skimage is None, "scikit-image が無い")
class Inking(unittest.TestCase):
    def test_rough_lines_become_ink_layer(self):
        import inking
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "rough.png", Path(d) / "ink.png"
            im = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
            dr = ImageDraw.Draw(im)
            for dy in (0, 2, 3):   # 重ねて描いたラフ線
                dr.line((10, 30 + dy, 70, 28 + dy), fill=(0, 0, 0, 255), width=2)
            im.save(src)
            r = inking.ink(str(src), str(out))
            self.assertTrue(out.exists())
            self.assertIsInstance(r, dict)
            self.assertGreater(np.asarray(Image.open(out))[..., 3].sum(), 0)


if __name__ == "__main__":
    unittest.main()
