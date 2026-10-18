"""背景と人物の光の食い違い（measure.scene_light）。作り物の絵で、逆光の場面に正面から照らされた顔を外れにするかを見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:   # 画像生成の部品（.cache/gen/lib）が無い環境では飛ばす
    HAS_SCIPY = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

L = {"face": 11, "hair": 2}


def scene(window_x, face_v, body_v=0.6, rim=False, window_y=60, wall=0.25, glow=0.7):
    """暗い壁に明るい窓（window_y は窓の高さ）。人物は縦長の箱（顔・体）。rim なら輪郭に明るい縁"""
    h, w = 400, 300
    rgb = np.full((h, w, 3), wall)
    y, x = np.mgrid[0:h, 0:w]
    rgb += (np.exp(-(((x - window_x) / 30) ** 2 + ((y - window_y) / 30) ** 2)) * glow)[..., None]
    seg = np.zeros((h, w), dtype=np.uint8)
    seg[100:380, 110:190] = 4
    seg[60:110, 125:175] = 11
    rgb[seg == 4] = body_v
    rgb[seg == 11] = face_v
    if rim:
        rgb[100:380, 110:113] = 0.95
        rgb[100:380, 187:190] = 0.95
    return np.clip(rgb, 0, 1), seg


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（sh tools/gen/setup.sh）")
class SceneLightTest(unittest.TestCase):
    def test_backlit_scene_with_front_lit_face(self):
        rgb, seg = scene(150, face_v=0.9, body_v=0.85)
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_front"], 1)

    def test_backlit_scene_with_face_in_shadow(self):
        rgb, seg = scene(150, face_v=0.35, body_v=0.4, rim=True)
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_front"], 0)

    def test_light_at_the_side_is_not_backlight(self):
        rgb, seg = scene(285, face_v=0.9, body_v=0.85)
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_front"], 0)

    def test_glow_at_the_feet_on_dark_wall_is_not_backlight(self):
        # 暗い背景の足元の光（床の照り返し、光の輪）は人物の後ろの光源ではない
        rgb, seg = scene(150, face_v=0.9, body_v=0.85, window_y=390, wall=0.1, glow=0.88)
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_front"], 0)

    def test_bright_floor_on_gray_wall_is_not_backlight(self):
        # 灰色の背景で、足元の床だけが明るいのも光源ではない
        rgb, seg = scene(150, face_v=0.9, body_v=0.85, window_y=390, wall=0.45, glow=0.4)
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_front"], 0)

    def test_white_spot_on_backlit_face(self):
        # 肌に囲まれた白い点（鼻筋の照り返し）は外れ。暗い瞳に囲まれた白い点（目のハイライト）は数えない
        rgb, seg = scene(150, face_v=0.4, body_v=0.45, rim=True)
        rgb[84:88, 148:152] = 0.98
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_spot"], 1)
        rgb, seg = scene(150, face_v=0.4, body_v=0.45, rim=True)
        rgb[80:92, 144:156] = 0.05
        rgb[84:88, 148:152] = 0.98
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_spot"], 0)

    def test_white_spot_with_side_light_is_not_flagged(self):
        rgb, seg = scene(285, face_v=0.4, body_v=0.45)
        rgb[84:88, 148:152] = 0.98
        self.assertEqual(measure.scene_light(rgb, seg, L)["backlit_spot"], 0)


if __name__ == "__main__":
    unittest.main()
