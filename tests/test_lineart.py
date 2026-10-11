"""線画の清書（tools/gen/lineart.py clean）の試験。"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import lineart  # noqa: E402

try:
    import skimage  # noqa: F401
except ImportError:
    skimage = None


@unittest.skipIf(skimage is None, "scikit-image が無い（.cache/gen/lib に入る）")
class Clean(unittest.TestCase):
    def run_clean(self, img):
        with tempfile.TemporaryDirectory() as d:
            Image.fromarray(img).save(f"{d}/in.png")
            lineart.clean(f"{d}/in.png", f"{d}/out.png")
            return np.asarray(Image.open(f"{d}/out.png"))

    def test_thin_faint_line_kept_broad_shadow_removed(self):
        img = np.full((120, 120), 215, np.uint8)       # 灰色の地
        img[20:100, 10:50] = 160                       # 広い灰色の影
        img[60, 60:110] = 150                          # 薄く細い線（目の線のような）
        out = self.run_clean(img)
        self.assertTrue((out[40:80, 20:40] > 200).all())   # 影は白くなる
        self.assertLess(out[60, 70:100].mean(), 80)          # 細い線は残る
        self.assertTrue((out[:10] == 255).all())             # 地は白

    def test_thick_dark_line_is_filled(self):
        img = np.full((120, 120), 215, np.uint8)
        img[40:52, 10:110] = 40                        # 太さ 12 の濃い線
        out = self.run_clean(img)
        self.assertLess(out[46, 20:100].mean(), 30)          # 中が抜けない


try:
    import scipy  # noqa: F401
except ImportError:
    scipy = None


@unittest.skipIf(scipy is None, "scipy が無い（.cache/gen/lib に入る）")
class FlatFill(unittest.TestCase):
    def test_color_stays_inside_lines(self):
        line = np.full((60, 60), 255, np.uint8)
        line[30, :] = 0                                  # 上下を分ける線
        ref = np.zeros((60, 60, 3), np.uint8)
        ref[:30] = (200, 0, 0)
        ref[31:] = (0, 0, 200)
        ref[25:35, :10] = (0, 200, 0)                    # 参考の絵の色が線をまたいでずれている所
        out, n = lineart.flat_fill(line, ref)
        self.assertEqual(n, 2)
        self.assertEqual(tuple(out[5, 5]), (200, 0, 0))     # 面ごとに1色
        self.assertEqual(tuple(out[27, 3]), (200, 0, 0))    # ずれた色は面の色に揃う
        self.assertEqual(tuple(out[30, 30]), (0, 0, 0))     # 線は黒のまま


    def test_color_by_parts_ignores_position(self):
        line = np.full((60, 60), 255, np.uint8)
        line[30, :] = 0
        line_parts = np.zeros((60, 60), np.uint8)
        line_parts[:30] = 2                              # 上の面は髪
        line_parts[31:] = 11                             # 下の面は顔
        ref = np.zeros((60, 60, 3), np.uint8)
        ref_parts = np.zeros((60, 60), np.uint8)
        ref[:20] = (250, 220, 200); ref_parts[:20] = 11  # 参考では顔が上
        ref[20:] = (90, 50, 20); ref_parts[20:] = 2      # 髪が下（位置は線画と逆）
        out = lineart.color_by_parts(line, line_parts, ref, ref_parts)
        self.assertEqual(tuple(out[5, 5]), (90, 50, 20))       # 髪の面には髪の色
        self.assertEqual(tuple(out[50, 50]), (250, 220, 200))  # 顔の面には顔の色


    def test_partner_part_when_missing_in_reference(self):
        line = np.full((60, 60), 255, np.uint8)
        line[30, :] = 0
        line_parts = np.zeros((60, 60), np.uint8)
        line_parts[:30] = 4                              # 線画: 上は上着
        line_parts[31:] = 6                              # 下はズボン
        ref = np.zeros((60, 60, 3), np.uint8)
        ref_parts = np.zeros((60, 60), np.uint8)
        ref[:30] = (240, 240, 240); ref_parts[:30] = 4   # 参考: 上着は白
        ref[30:] = (220, 140, 70); ref_parts[30:] = 7    # 作業着は「ワンピース」に分けられ、ズボンが無い
        ref_parts[59, :3] = 6                            # ズボンが数画素だけある
        out = lineart.color_by_parts(line, line_parts, ref, ref_parts)
        self.assertEqual(tuple(out[50, 50]), (220, 140, 70))   # ズボンの面にワンピースの色

    def test_middle_color_is_a_real_color(self):
        px = np.array([[255, 255, 255]] * 3 + [[220, 140, 70]] * 2, np.uint8)
        self.assertIn(tuple(lineart.middle_color(px)), {(255, 255, 255), (220, 140, 70)})


    def test_open_line_between_face_and_hair(self):
        line = np.full((60, 60), 255, np.uint8)
        line[30, 10:] = 0                                # 顔と髪のあいだの線が左で途切れている
        line_parts = np.zeros((60, 60), np.uint8)
        line_parts[:30] = 2                              # 上は髪（大きい）
        line_parts[30:] = 11                             # 下は顔
        ref = np.zeros((60, 60, 3), np.uint8)
        ref_parts = np.zeros((60, 60), np.uint8)
        ref[:30] = (90, 50, 20); ref_parts[:30] = 2
        ref[30:] = (250, 200, 170); ref_parts[30:] = 11
        out = lineart.color_by_parts(line, line_parts, ref, ref_parts)
        self.assertEqual(tuple(out[50, 30]), (250, 200, 170))  # 顔は髪の色にならない


    def test_part_missing_in_reference_takes_neighbor_not_white(self):
        line = np.full((60, 60), 255, np.uint8)
        line[30, :] = 0
        line_parts = np.zeros((60, 60), np.uint8)
        line_parts[:, :] = 5                             # 上はスカート
        line_parts[31:] = 12                             # 下は脚（参考では隠れて無い）
        line_parts[:, :6] = 0                            # 左端は人物の外
        line[:, 6] = 0                                   # 人物の外形の線
        ref = np.zeros((60, 60, 3), np.uint8)
        ref_parts = np.zeros((60, 60), np.uint8)
        ref[10:] = (30, 30, 30); ref_parts[10:] = 5      # 参考はスカートだけ
        out = lineart.color_by_parts(line, line_parts, ref, ref_parts)
        self.assertEqual(tuple(out[50, 30]), (30, 30, 30))     # 脚は白でなく隣の色
        self.assertEqual(tuple(out[50, 0]), (255, 255, 255))   # 人物の外は白


if __name__ == "__main__":
    unittest.main()
