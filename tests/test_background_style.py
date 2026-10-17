"""白い背景を頼んだ絵の四隅（measure.background）と、写実への寄り（measure.style）が基準で外れになるかを見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

WHITE = "full body, simple white background"


def paths(m):
    return {b["path"] for b in measure.judge(m)}


class BackgroundTest(unittest.TestCase):
    def test_grey_background_when_white_asked(self):
        rgb = np.full((400, 300, 3), 0.55)
        m = {"background": measure.background(rgb, WHITE)}
        self.assertIn("background.corner_lum", paths(m))

    def test_tinted_background_when_white_asked(self):
        rgb = np.full((400, 300, 3), 0.9)
        rgb[..., 2] = 0.8
        rgb[..., 0] = 0.95
        m = {"background": measure.background(rgb, WHITE)}
        self.assertIn("background.corner_sat", paths(m))

    def test_white_background_passes(self):
        rgb = np.full((400, 300, 3), 0.97)
        rgb[150:400, 100:200] = 0.3   # 人物が下の辺にかかっても隅は白い
        self.assertEqual(paths({"background": measure.background(rgb, WHITE)}), set())

    def test_scene_background_not_judged(self):
        rgb = np.full((400, 300, 3), 0.3)
        self.assertEqual(paths({"background": measure.background(rgb, "night street")}), set())


class StyleTest(unittest.TestCase):
    def test_realistic_tags_flagged(self):
        self.assertIn("style.realism", paths({"style": measure.style({"realistic": 0.38, "photorealistic": 0.2})}))

    def test_anime_tags_pass(self):
        self.assertEqual(paths({"style": measure.style({"realistic": 0.02})}), set())

    def test_no_tags_not_judged(self):
        self.assertEqual(paths({"style": measure.style(None)}), set())


if __name__ == "__main__":
    unittest.main()
