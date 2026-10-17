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


ASK = "1woman, long dark brown hair, green eyes, white sweater, long navy skirt, brown boots, white background"


class ColorsTest(unittest.TestCase):
    """頼んだ色と描かれた色の照合。タグの確からしさは、戻した2枚（w-2101・w-2102）で読めた値"""

    def test_asked_colors_parsed(self):
        self.assertEqual(measure.asked_colors(ASK), [("brown", "hair"), ("green", "eyes"), ("white", "sweater"), ("blue", "skirt"), ("brown", "boots")])

    def test_white_skirt_for_navy_flagged(self):
        c = measure.colors(ASK, {"brown hair": 0.958, "green eyes": 0.886, "white skirt": 0.18, "blue skirt": 0.001, "brown footwear": 0.028, "black footwear": 0.912})
        self.assertIn("colors.mismatch", paths({"colors": c}))
        self.assertEqual({i["item"] for i in c["items"]}, {"skirt", "boots"})

    def test_brown_eyes_for_green_flagged(self):
        c = measure.colors(ASK, {"brown hair": 0.929, "brown eyes": 0.889, "green eyes": 0.003, "white sweater": 0.548, "green skirt": 0.364, "brown footwear": 0.309, "black footwear": 0.638})
        self.assertEqual({i["item"] for i in c["items"]}, {"eyes", "skirt"})   # 茶も 0.31 で読めた靴は近い色の揺れとして数えない

    def test_matching_colors_pass(self):
        c = measure.colors(ASK, {"brown hair": 0.9, "green eyes": 0.9, "white sweater": 0.6, "blue skirt": 0.5, "brown footwear": 0.5})
        self.assertEqual(paths({"colors": c}), set())

    def test_no_tags_not_judged(self):
        self.assertEqual(paths({"colors": measure.colors(ASK, None)}), set())


if __name__ == "__main__":
    unittest.main()
