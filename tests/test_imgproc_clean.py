"""ノイズ除去とぼかし除去（tools/gen/imgproc.py の denoise / sharpen）の試験。模型は使わない。"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import imgproc  # noqa: E402

try:
    import skimage  # noqa: F401  描く部品（.cache/gen/lib）に入っている
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False


def two_tone() -> np.ndarray:
    """左が暗く右が明るい、はっきりした境目の絵"""
    a = np.full((64, 64, 3), 200.0)
    a[:, :32] = 60.0
    return a


@unittest.skipUnless(HAS_SKIMAGE, "描く部品（skimage）が無い")
class Clean(unittest.TestCase):
    def test_denoise_flattens_noise_and_keeps_the_edge(self):
        with tempfile.TemporaryDirectory() as t:
            src, out = str(Path(t) / "in.png"), str(Path(t) / "out.png")
            noisy = two_tone() + np.random.default_rng(0).normal(0, 20, (64, 64, 3))
            Image.fromarray(np.clip(noisy, 0, 255).astype("uint8")).save(src)
            info = imgproc.denoise(src, out)
            a = np.asarray(Image.open(out)).astype(float)
            self.assertLess(a[:, 40:].std(), noisy[:, 40:].std() / 2)          # 明るい面のざらつきが半分以下
            self.assertGreater(a[:, 36:].mean() - a[:, :28].mean(), 120)        # 境目の明暗差は残る
            self.assertLess(info["noise_after"], info["noise_before"])

    def test_sharpen_steepens_a_blurred_edge(self):
        with tempfile.TemporaryDirectory() as t:
            src, out = str(Path(t) / "in.png"), str(Path(t) / "out.png")
            Image.fromarray(two_tone().astype("uint8")).filter(ImageFilter.GaussianBlur(3)).save(src)
            info = imgproc.sharpen(src, out)
            b = np.asarray(Image.open(src)).astype(float)[32, :, 0]
            a = np.asarray(Image.open(out)).astype(float)[32, :, 0]
            self.assertGreater(np.abs(np.diff(a)).max(), np.abs(np.diff(b)).max() * 1.3)   # 境目が急になる
            self.assertLess(abs(a[5] - b[5]), 3)                                           # 平らな所は変えない
            self.assertGreater(info["edge_after"], info["edge_before"])


if __name__ == "__main__":
    unittest.main()
