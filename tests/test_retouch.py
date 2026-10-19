import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))

HAS = all(importlib.util.find_spec(m) for m in ("scipy", "skimage"))


def scene():
    """背景の灰色に、2 段の塗りの人物（四角）と黒い線"""
    a = np.full((240, 200, 3), 200.0)
    a[40:220, 50:150] = (210, 150, 140)
    a[40:220, 100:150] = (160, 100, 95)
    a[40:220, 48:52] = 20
    a[40:220, 148:152] = 20
    return a


@unittest.skipUnless(HAS, "scipy と skimage が無い（sh tools/gen/setup.sh で入る）")
class Retouch(unittest.TestCase):
    def check(self, name, img):
        import retouch
        out, rep = retouch.apply(img, name)
        self.assertTrue(rep["used"], rep)
        self.assertLess(rep["after"], rep["before"], rep)
        return out

    def test_heal_removes_specks(self):
        a = scene()
        for y, x in ((60, 70), (100, 120), (150, 80), (190, 130), (90, 20), (200, 180)):
            a[y:y + 3, x:x + 3] = 15
        self.check("heal", a)

    def test_denoise(self):
        a = scene() + np.random.default_rng(0).normal(0, 8, (240, 200, 1))
        self.check("denoise", np.clip(a, 0, 255))

    def test_white_balance_removes_yellow_cast(self):
        a = scene() * np.array([1.08, 1.04, 0.85])
        self.check("white_balance", np.clip(a, 0, 255))

    def test_levels_on_dull_picture(self):
        self.check("levels", scene() * 0.6 + 50)

    def test_dehaze(self):
        a = scene()
        a[:, :90] *= 0.35                         # 暗い所が無いと暗いチャンネルの事前知識が効かない
        self.check("dehaze", a * 0.6 + 0.4 * 230)

    def test_defringe_purple_edges(self):
        a = scene()
        a[40:220, 52:54] = (150, 60, 200)
        a[40:220, 146:148] = (60, 160, 60)
        self.check("defringe", a)

    def test_deburr_spikes_and_notches(self):
        a = scene()
        for y in (60, 100, 140, 180):
            a[y:y + 2, 152:158] = (160, 100, 95)   # 細い小さな出っ張り
            a[y + 10:y + 12, 48:54] = 200          # 細い小さな切れ込み
        out = self.check("deburr", a)
        self.assertLess(abs(out[61, 156] - 200).sum(), 30)

    def test_dejag_staircase(self):
        a = np.full((200, 200, 3), 230.0)
        for i in range(0, 180, 6):              # 6 画素ごとの階段の斜め線
            a[10 + i:16 + i, 10 + i:22 + i] = 20
        self.check("dejag", a)

    def test_sharpen_blurred_edges(self):
        from scipy.ndimage import gaussian_filter
        a = np.stack([gaussian_filter(scene()[..., c], 2.5) for c in range(3)], -1)
        self.check("sharpen", a)

    def test_line_guard_catches_cut_strands_and_thickened_lines(self):
        import retouch
        a = np.full((300, 300, 3), 230.0)
        for x in range(20, 280, 12):
            a[20:280, x:x + 3] = 20                 # 細い線の束
        cut = a.copy()
        for y in range(40, 280, 30):
            cut[y:y + 4] = 230                      # 束を点線に切る
        self.assertIn("切れる", retouch.line_broken(a, cut))
        thick = a.copy()
        for x in range(20, 280, 12):
            thick[20:280, x - 1:x + 4] = 20         # 線を太らせる
        self.assertIn("太さ", retouch.line_broken(a, thick))
        self.assertEqual(retouch.line_broken(a, a), "")

    def test_rejects_step_that_does_not_help(self):
        import retouch
        out, rep = retouch.apply(scene(), "white_balance")
        self.assertFalse(rep["used"])
        self.assertTrue(np.array_equal(out, scene()))


if __name__ == "__main__":
    unittest.main()
