"""人が描いている途中に見える工程の絵と、筆が動くタイムラプス（chatdraw/humanpaint.py）。
前は工程 2 のサムネイルがもう色も影も背景も付いた完成の絵で、あとの工程は完成の絵に少し手を入れるだけに見えた。
白紙から始まり、ラフと線画には色が無く、最後だけが模型の絵になることを確かめる"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from chatdraw import humanpaint as hp  # noqa: E402


def picture(size=(160, 240)):
    """色の付いた背景に、黒い線で縁取った人物（赤いマフラー、肌、紺の服、影）"""
    w, h = size
    im = Image.new("RGB", size, (150, 130, 120))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, h // 2], fill=(170, 160, 200))
    d.ellipse([w * 0.35, h * 0.05, w * 0.65, h * 0.28], fill=(250, 220, 200), outline=(20, 20, 20), width=2)
    d.rectangle([w * 0.3, h * 0.3, w * 0.7, h * 0.75], fill=(40, 40, 90), outline=(20, 20, 20), width=2)
    d.rectangle([w * 0.5, h * 0.3, w * 0.7, h * 0.75], fill=(25, 25, 60))
    d.rectangle([w * 0.35, h * 0.28, w * 0.65, h * 0.36], fill=(200, 30, 30), outline=(20, 20, 20), width=2)
    d.rectangle([w * 0.38, h * 0.75, w * 0.48, h * 0.98], fill=(250, 220, 200), outline=(20, 20, 20), width=2)
    d.rectangle([w * 0.52, h * 0.75, w * 0.62, h * 0.98], fill=(250, 220, 200), outline=(20, 20, 20), width=2)
    return im


def parts_of(im):
    """偽の部位分け: 人物の所を 4（上の服）、脚を 12 にする"""
    w, h = im.size
    p = np.zeros((h, w), np.uint8)
    p[int(h * 0.05):int(h * 0.75), int(w * 0.3):int(w * 0.7)] = 4
    p[int(h * 0.75):int(h * 0.98), int(w * 0.38):int(w * 0.62)] = 12
    return p


def sat(im):
    a = np.asarray(im.convert("RGB")).astype(int)
    return float((a.max(-1) - a.min(-1)).mean())


class StagesTest(unittest.TestCase):
    def test_order_starts_white_and_ends_with_model_image(self):
        im = picture()
        st = hp.stages(im, parts_of(im))
        names = [n for n, _ in st]
        self.assertEqual(names[0], "白紙")
        self.assertEqual(names[-1], "仕上げ")
        for want in ("ラフ", "線画", "下塗り", "影 1 段", "影 2 段", "光", "背景", "ディテール"):
            self.assertIn(want, names)
        self.assertLess(names.index("ラフ"), names.index("線画"))
        self.assertLess(names.index("線画"), names.index("下塗り"))
        self.assertLess(names.index("光"), names.index("背景"))
        d = dict(st)
        self.assertEqual(np.asarray(d["白紙"]).min(), 255)
        self.assertEqual(d["仕上げ"].tobytes(), im.tobytes())   # 最後の絵は模型の絵のまま（質を落とさない）
        self.assertLess(sat(d["線画"]), 3)                      # 線画には色が無い
        self.assertLess(sat(d["ラフ"]), sat(im) / 2)
        # 下塗りの時点では背景はまだ白い（人物から先に塗る）
        bg = np.asarray(d["下塗り"])[2:10, 2:10]
        self.assertEqual(int(bg.min()), 255)

    def test_without_parts_background_stage_is_skipped_or_kept(self):
        st = hp.stages(picture(), None)
        self.assertEqual(st[0][0], "白紙")
        self.assertEqual(st[-1][0], "仕上げ")

    def test_phase_images_never_show_the_finished_picture_early(self):
        im = picture()
        p = parts_of(im)
        for i in range(11):
            shown = hp.for_phase(i, im, p)
            self.assertNotEqual(shown.tobytes(), im.tobytes(), i)
        self.assertEqual(np.asarray(hp.for_phase(0, im, p)).min(), 255)
        self.assertLess(sat(hp.for_phase(1, im, p)), 5)   # サムネイルは色の無いラフ


class AtariTest(unittest.TestCase):
    """アタリは最後の絵の体の点の位置に置く（前はあとの絵の体の位置とずれていた）"""

    def test_atari_lines_sit_on_body_points(self):
        pts = {"nose": (80, 40), "left_eye": (75, 35), "right_eye": (85, 35), "left_shoulder": (60, 80), "right_shoulder": (100, 80),
               "left_hip": (65, 150), "right_hip": (95, 150), "left_knee": (65, 190), "left_ankle": (65, 230)}
        at = np.asarray(hp.atari((160, 240), pts).convert("L"))
        for x, y in [(60, 80), (100, 80), (65, 190), (65, 230)]:
            self.assertLess(int(at[y - 3:y + 4, x - 3:x + 4].min()), 230, (x, y))
        self.assertEqual(int(at[5:15, 140:155].min()), 255)   # 体の無い所には線が無い
        self.assertIsNone(hp.atari((160, 240), {"nose": (1, 1)}))
        st = [n for n, _ in hp.stages(picture(), parts_of(picture()), pts)]
        self.assertEqual(st[:3], ["白紙", "アタリ", "ラフ"])

    def test_transition_draws_over_previous(self):
        im = picture()
        line = hp.lineart(im)
        fr = hp.transition(hp._blank(im.size), line, n=6)
        self.assertGreaterEqual(len(fr), 3)
        self.assertEqual(fr[-1].tobytes(), line.tobytes())
        self.assertEqual(fr[0].size, im.size)


class CleanTest(unittest.TestCase):
    def test_isolated_dot_is_removed(self):
        im = Image.new("RGB", (60, 60), (200, 180, 160))
        im.putpixel((30, 30), (0, 0, 0))
        im.putpixel((31, 30), (0, 0, 0))
        out, rep = hp.clean(im)
        self.assertGreaterEqual(rep["specks"], 2)
        self.assertEqual(out.getpixel((30, 30)), (200, 180, 160))
        self.assertFalse(rep["seams_readable"])

    def test_seam_inside_one_part_is_found(self):
        im = Image.new("RGB", (60, 120), (255, 255, 255))
        ImageDraw.Draw(im).rectangle([20, 60, 40, 110], fill=(20, 20, 20))   # 靴下が上は白、下は黒
        im2 = im.copy()
        ImageDraw.Draw(im2).rectangle([20, 10, 40, 110], fill=(240, 240, 240))
        p = np.zeros((120, 60), np.uint8)
        p[10:110, 20:41] = 12
        self.assertTrue(hp.seams(im, p))
        self.assertFalse(hp.seams(im2, p))


class TimelapseTest(unittest.TestCase):
    def test_strokes_follow_a_line(self):
        m = np.zeros((40, 40), bool)
        m[5, 5:35] = True
        lines = hp.strokes(m)
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0]), 30)

    def test_frames_build_up_from_white_to_final(self):
        im = picture()
        with TemporaryDirectory() as d:
            got = hp.build(im, Path(d), parts_of(im))
            self.assertTrue(Path(got["timelapse"]).exists())
            self.assertGreater(got["frames"], 60)   # 工程の区切りの数枚ではなく、筆が動く分の枚数がある
            with Image.open(got["timelapse"]) as g:
                first = g.convert("RGB")
                self.assertEqual(np.asarray(first).min(), 255)   # 白い紙から始まる
            self.assertTrue(all(Path(p).exists() for _n, p in got["stages"]))


if __name__ == "__main__":
    unittest.main()
