"""白い背景を頼んだ絵の四隅（measure.background）と、写実への寄り（measure.style）が基準で外れになるかを見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

# 共通の基準だけで試す。利用者の判定から学んだ基準（config/norms.user.json）で結果が変わらないように
measure.USER_NORMS = Path(__file__).parent / "no-user-norms.json"

try:
    import scipy  # noqa: F401  描く部品（.cache/gen/lib）に入っている
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

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


LADY = "woman solo, long black hair, black long-sleeved dress, black boots, white background"


class HairStyleTest(unittest.TestCase):
    """頼んだ髪の長さ・髪型とタグの照合。確からしさは 5 周目の4枚（long black hair を頼んだ絵）で読めた値"""

    def test_asked_styles_parsed(self):
        self.assertEqual(measure.asked_hair_styles(LADY), ["long hair"])
        self.assertEqual(measure.asked_hair_styles("1girl, very long silver hair, hair down"), ["very long hair", "hair down"])
        self.assertEqual(measure.asked_hair_styles("1girl, black bob cut"), ["bob cut"])

    def test_bun_and_bob_for_long_flagged(self):
        for tags, seen in (({"long hair": 0.39, "hair bun": 0.385, "ponytail": 0.17}, "hair bun"),         # 506 まとめ髪
                           ({"long hair": 0.03, "short hair": 0.601}, "short hair"),                       # 508 ボブ
                           ({"long hair": 0.04, "short hair": 0.482}, "short hair"),                       # 512 ボブ
                           ({"long hair": 0.323, "short hair": 0.131, "ponytail": 0.105}, "short hair")):  # 505 まとめ髪
            c = measure.colors(LADY, {"black hair": 0.9, **tags})
            self.assertIn("colors.mismatch", paths({"colors": c}))
            self.assertEqual([(i["item"], i["seen"]) for i in c["items"]], [("hairstyle", seen)])

    def test_long_hair_passes(self):
        c = measure.colors(LADY, {"black hair": 0.9, "long hair": 0.57, "short hair": 0.12})   # 510 の長い髪
        self.assertEqual(paths({"colors": c}), set())

    def test_long_hair_for_short_flagged(self):
        c = measure.colors("1girl, black bob cut", {"black hair": 0.9, "long hair": 0.8})
        self.assertEqual([(i["asked"], i["seen"]) for i in c["items"]], [("bob cut", "long hair")])

    def test_no_style_asked_not_judged(self):
        c = measure.colors("1girl, black hair", {"black hair": 0.9, "short hair": 0.9})
        self.assertEqual(c["mismatch"], 0)

    def test_ff_prompt_found(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a-1.png.json").write_text(json.dumps({"prompt": LADY}), encoding="utf-8")
            self.assertEqual(measure._prompt_of(Path(d) / "a-1.ff.png"), LADY)


@unittest.skipUnless(HAS_SCIPY, "描く部品（scipy）が無い")
class DarkHairSpecTest(unittest.TestCase):
    """光の帯の無いほぼ黒の髪は、彩度が跳ねても指定の黒から外れたと数えない。明るく色づいた髪は数える"""

    def _hair(self, color):
        rgb = np.ones((120, 120, 3), dtype=np.float32)
        seg = np.zeros((120, 120), dtype=np.uint8)
        seg[20:100, 20:100] = 1
        rgb[20:100, 20:100] = color
        return measure.hair(rgb, seg, {"hair": 1}, "#000000")["spec_off"]

    def test_near_black_with_tint_passes(self):
        self.assertLess(self._hair((0.02, 0.03, 0.08)), 0.2)   # 彩度 0.75 だが明るさ 0.08

    def test_pink_hair_flagged(self):
        self.assertGreater(self._hair((0.9, 0.5, 0.7)), 0.2)


if __name__ == "__main__":
    unittest.main()
