"""模型の外の検品の試験: 薄く出た余分な指、くっついた指、ぼやけた足の指、頼んでいない 2 人目、基準から外れた体。
小さな作り絵と、模型の読みの差し替えで確かめる（模型は読まない）。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
sys.path.insert(0, str(ROOT))
import hands  # noqa: E402
import feet  # noqa: E402

SKIN, BG, LINE = (230, 180, 150), (255, 255, 255), (60, 40, 40)


def hand(xs, widths, ghost=None):
    """上を向いた 4 本の指（xs の中心、widths の幅）と手のひらの作り絵（448 画素）と、関節 21 点"""
    im = Image.new("RGB", (448, 448), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((90, 300, 360, 420), fill=SKIN)
    for x, w in zip(xs, widths):
        d.rectangle((x - w // 2, 120, x + w // 2, 310), fill=SKIN, outline=LINE, width=2)
    if ghost:   # 下の色の透けた薄い指（手の色 35%）
        gx, gw = ghost
        col = tuple(int(b + 0.35 * (s - b)) for s, b in zip(SKIN, BG))
        d.rectangle((gx - gw // 2, 140, gx + gw // 2, 300), fill=col)
    lm = np.zeros((21, 2))
    lm[0] = (225, 420)
    lm[1:5] = [(80, 380), (70, 340), (60, 300), (55, 260)]
    for k, x in zip((5, 9, 13, 17), [150, 200, 250, 300] if len(xs) != 4 else xs):
        lm[k:k + 4] = [(x, 300), (x, 240), (x, 180), (x, 130)]
    return np.asarray(im, float), lm


class Fingers(unittest.TestCase):
    def test_four_clear_fingers(self):
        a, lm = hand([150, 200, 250, 300], [34] * 4)
        r = hands.count_fingers(a, lm, np.array(SKIN, float))
        self.assertEqual(r["count"], 4)
        self.assertEqual(r["ghost"], 0)
        self.assertFalse(r.get("fused"))

    def test_fused_fingers(self):
        # 人差し指と中指が 1 本の塊（幅 84 = 指 2.5 本分）
        a, lm = hand([175, 250, 300], [84, 34, 34])
        r = hands.count_fingers(a, lm, np.array(SKIN, float))
        self.assertTrue(r.get("fused"), r)
        self.assertIsNone(r["count"])

    def test_ghost_finger_between(self):
        a, lm = hand([120, 200, 250, 300], [34] * 4, ghost=(160, 20))
        r = hands.count_fingers(a, lm, np.array(SKIN, float))
        self.assertEqual(r["count"], 4, r)
        self.assertEqual(r["ghost"], 1, r)

    def test_wide_gap_without_ghost(self):
        a, lm = hand([120, 200, 250, 300], [34] * 4)
        r = hands.count_fingers(a, lm, np.array(SKIN, float))
        self.assertEqual(r["ghost"], 0, r)


def lines(blur=0):
    im = Image.new("RGB", (400, 400), BG)
    d = ImageDraw.Draw(im)
    for x in range(20, 400, 25):
        d.line((x, 0, x, 400), fill=LINE, width=2)
    return im.filter(ImageFilter.GaussianBlur(blur)) if blur else im


class Toes(unittest.TestCase):
    def test_blur_lowers_sharpness(self):
        sharp, soft = feet.sharpness(lines(), (0, 0, 100, 100)), feet.sharpness(lines(4), (0, 0, 100, 100))
        self.assertLess(soft, 0.5 * sharp)

    def check(self, blur, asked=""):
        from chatdraw import handcheck
        im = lines()
        if blur:
            im.paste(lines(blur).crop((150, 250, 250, 350)), (150, 250))
        found = [{"side": "left", "box": [150, 250, 250, 350], "count": 5, "evidence": {}}]
        with mock.patch.object(handcheck, "ensure_feet_model", return_value=True), \
                mock.patch.object(feet, "count_toes", return_value=found):
            return handcheck.check_feet(im, False, asked)

    def test_blurry_toes_are_a_defect(self):
        got, bad, _ = self.check(4)
        self.assertTrue(bad and "ぼやけ" in bad[0], bad)
        self.assertLess(got[0]["sharp"], 0.6)

    def test_sharp_toes_pass(self):
        got, bad, _ = self.check(0)
        self.assertEqual(bad, [])

    def test_shoes_skip_blur(self):
        _, bad, _ = self.check(4, "1girl, boots")
        self.assertEqual(bad, [])


class People(unittest.TestCase):
    def test_second_person_when_solo(self):
        from chatdraw import requestcheck
        self.assertEqual(requestcheck.people("1girl, solo, bikini", {"1girl": 0.99, "2girls": 0.8}), ["2girls 0.8"])
        self.assertEqual(requestcheck.people("1girl, solo", {"1girl": 0.99, "multiple views": 0.87, "solo": 0.01}),
                         ["multiple views 0.87"])
        self.assertEqual(requestcheck.people("1girl, solo", {"1girl": 0.99, "solo": 0.05}), ["solo 0.05"])

    def test_asked_many_or_solo_drawn(self):
        from chatdraw import requestcheck
        self.assertEqual(requestcheck.people("2girls, beach", {"2girls": 0.9}), [])
        self.assertEqual(requestcheck.people("1girl, 1boy", {"1girl": 0.9, "1boy": 0.9}), [])
        self.assertEqual(requestcheck.people("1girl, solo", {"1girl": 0.99, "solo": 0.96}), [])
        self.assertIn("頼んだ人数", requestcheck.summary({"readable": True, "missing": [], "people": ["2girls 0.8"]}))


class Body(unittest.TestCase):
    def test_exaggerated_tags(self):
        from chatdraw import body, bodycheck
        bad = bodycheck.from_tags({"huge breasts": 0.68, "thick thighs": 0.54, "large breasts": 0.9}, body.WOMAN)
        self.assertEqual(len(bad), 2, bad)
        self.assertEqual(bodycheck.from_tags({"huge breasts": 0.11, "thick thighs": 0.3}, body.WOMAN), [])
        self.assertEqual(bodycheck.from_tags({"huge breasts": 0.9}, "1girl, huge breasts"), [])   # 頼んだ体は崩れにしない

    def test_silhouette_widths(self):
        from chatdraw import bodycheck
        im = Image.new("RGB", (300, 400), BG)
        d = ImageDraw.Draw(im)
        d.polygon([(110, 100), (190, 100), (175, 160), (165, 180), (200, 230), (100, 230), (135, 180), (125, 160)], fill=SKIN)
        kp = {"left_shoulder": (115, 100), "right_shoulder": (185, 100), "left_hip": (120, 200), "right_hip": (180, 200)}
        m = bodycheck.measure(im, kp)
        self.assertGreater(m["hip_waist"], 1.5, m)
        self.assertNotIn("reason", m)


if __name__ == "__main__":
    unittest.main()
