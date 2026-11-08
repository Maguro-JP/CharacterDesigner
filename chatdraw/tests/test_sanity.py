"""頼んでいない・物理的にあり得ない絵の打ち消しと検品（chatdraw/sanity.py）。
規則は模型なしで確かめ、描き直しの経路は偽の模型（FakePainter）で本物と同じ Studio.draw を通す"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from chatdraw import sanity


class NegativeTest(unittest.TestCase):
    def test_always_negates_extra_parts(self):
        neg = sanity.negative("1girl, solo, holding a ball")
        for w in ("extra arms", "extra legs", "extra heads", "extra eyes", "eyes on objects", "impossible anatomy"):
            self.assertIn(w, neg)

    def test_eye_color_only_when_not_asked(self):
        self.assertIn("yellow eyes", sanity.negative("1girl, long hair"))
        self.assertIn("golden eyes", sanity.negative("1girl, long hair"))
        self.assertNotIn("yellow eyes", sanity.negative("1girl, yellow eyes"))   # 頼んだ色は打ち消さない
        self.assertNotIn("golden eyes", sanity.negative("1girl, blue eyes"))
        self.assertFalse(sanity.eye_color_asked("1girl, golden hour, yellow dress"))   # 目でない黄色は目の色の頼みではない
        self.assertTrue(sanity.eye_color_asked("1girl, heterochromia"))

    def test_asked_part_is_not_negated(self):
        self.assertNotIn("third eye", sanity.negative("1girl, third eye"))
        self.assertIn("extra arms", sanity.negative("1girl, arms up"))   # 腕を頼んでも余分な腕は打ち消す

    def test_prompt_args_carries_negative(self):
        from chatdraw.engine import prompt_args
        from chatdraw.models import family, image_model

        class Pipe:
            tokenizer = None

            def __call__(self, prompt=None, negative_prompt=None, num_inference_steps=None, guidance_scale=None,
                         guidance_rescale=None, generator=None):
                pass
        a = prompt_args(image_model("cagliostrolab/animagine-xl-4.0"), family("sdxl"), "1girl, red ball", "hat", 24, 5.0, 1, Pipe())
        self.assertIn("extra arms", a["negative_prompt"])
        self.assertIn("eyes on objects", a["negative_prompt"])
        self.assertIn("yellow eyes", a["negative_prompt"])
        self.assertIn(", hat, ", a["negative_prompt"])   # 利用者の打ち消しは先に残す


class TagRulesTest(unittest.TestCase):
    def test_extra_parts_and_unasked_yellow(self):
        got = {"extra arms": 0.6, "yellow eyes": 0.8, "multiple heads": 0.1}
        bad = sanity.from_tags(got, "1girl, solo")
        self.assertTrue(any("腕が多い" in b for b in bad))
        self.assertTrue(any("頼んでいない目の色" in b for b in bad))
        self.assertFalse(any("頭" in b for b in bad))
        self.assertEqual(sanity.from_tags(got, "1girl, yellow eyes, extra arms"), [])

    def test_eyes_outside_face(self):
        self.assertTrue(sanity.eyes_outside({"blue eyes": 0.5, "1girl": 0.9}))
        self.assertEqual(sanity.eyes_outside({"blue eyes": 0.2, "closed eyes": 0.9}), [])

    def test_asked_people(self):
        self.assertEqual(sanity.asked_people("1girl, solo"), 1)
        self.assertEqual(sanity.asked_people("2girls, beach"), 2)


class CountPartsTest(unittest.TestCase):
    def test_three_arms(self):
        seg = np.zeros((200, 200), np.uint8)
        seg[20:60, 20:30] = 14
        seg[20:60, 170:180] = 15
        seg[120:180, 90:100] = 15   # 3 本目の腕
        seg[100:190, 60:70] = 12
        seg[100:190, 130:140] = 13
        r = sanity.count_parts(seg, 1)
        self.assertEqual(r["counts"]["腕"], 3)
        self.assertTrue(any(b.startswith("腕が多い") for b in r["extra"]))
        self.assertFalse(any(b.startswith("脚") for b in r["extra"]))

    def test_split_leg_is_joined(self):
        seg = np.zeros((200, 200), np.uint8)
        seg[100:140, 60:70] = 12
        seg[142:190, 60:70] = 12   # 靴下の縁で切れた 1 本の脚
        seg[100:190, 130:140] = 13
        self.assertEqual(sanity.count_parts(seg, 1)["counts"]["脚"], 2)


class BoneTest(unittest.TestCase):
    def test_r21_points(self):
        """腕が 3 本の絵（library/feedback/body/2026-10-20/r21）の体の点。上げた腕の肘から垂れた腕の手首へ骨が引かれた"""
        kp = {"left_shoulder": (484, 254), "left_elbow": (566, 116), "left_wrist": (538, 563),
              "right_shoulder": (320, 242), "right_elbow": (244, 98), "right_wrist": (355, 93)}
        self.assertGreater(sanity.bone_ratio(kp, sanity.ARM_CHAINS[0]), sanity.BONE_MOST)
        self.assertLess(sanity.bone_ratio(kp, sanity.ARM_CHAINS[1]), sanity.BONE_MOST)
        self.assertIsNone(sanity.bone_ratio({}, sanity.ARM_CHAINS[0]))

    def test_off_skeleton(self):
        seg = np.zeros((200, 200), np.uint8)
        seg[50:120, 40:46] = 14
        seg[50:120, 150:156] = 15
        seg[60:130, 95:101] = 15   # 骨の無い 3 本目の腕
        kp = {"left_shoulder": (43, 50), "left_elbow": (43, 85), "left_wrist": (43, 120),
              "right_shoulder": (153, 50), "right_elbow": (153, 85), "right_wrist": (153, 120)}
        self.assertEqual(sanity.off_skeleton(seg, kp, sanity.ARMS, sanity.ARM_CHAINS)["extra"], 1)
        seg[60:130, 95:101] = 0
        self.assertEqual(sanity.off_skeleton(seg, kp, sanity.ARMS, sanity.ARM_CHAINS)["extra"], 0)


class FakePainter:
    model = "fake"
    avoid = ""

    def __init__(self):
        self.avoids = []

    def ready(self):
        return True

    def paint(self, prompt, seed, on_step=None, **kw):
        from PIL import Image
        self.avoids.append(self.avoid)
        return Image.new("RGB", (64, 64), (200, 180, 160))


class Words:
    def ready(self):
        return True

    def to_prompt(self, text, tags=True):
        return text


class RedrawTest(unittest.TestCase):
    """余分な腕・顔の外の目を見つけたら、渡さずに種を変えて描き直し、次の回はその言葉を打ち消す"""

    def test_flaw_triggers_redraw(self):
        from chatdraw import finishers, requestcheck
        from chatdraw.engine import Studio
        s = Studio(Words(), FakePainter(), Path(tempfile.mkdtemp()))
        odd = iter([{"readable": True, "bad": ["腕が多い（手首から離れた手 1 つ）", "顔の外に目（blue eyes 0.50）"],
                     "avoid": ["extra arms", "eyes on objects"]},
                    {"readable": True, "bad": [], "avoid": []}])
        from chatdraw import handcheck, origqc
        # 手と作画監督は読めて崩れが無いことにする（読めない検品は崩れになるので、ここで見る体の数と目だけを動かす）
        with mock.patch.object(requestcheck, "check", lambda im, t: {"readable": True, "missing": []}), \
                mock.patch.object(handcheck, "check", lambda im, asked=None: {"readable": True, "bad": [], "hands": []}), \
                mock.patch.object(origqc, "check", lambda im, p, hair="": {"readable": True, "bad": [], "regions": [],
                                                                         "measured": True}), \
                mock.patch.object(sanity, "check", side_effect=lambda im, p, tags=None: next(odd)):
            _prompt, path = s.draw("1girl, solo", 7)
        meta = finishers.sidecar(path)
        self.assertEqual(len(meta["redraws"]), 2)
        self.assertIn("腕が多い（手首から離れた手 1 つ）", meta["redraws"][0]["bad"])
        self.assertEqual(meta["redraws"][1]["bad"], [])
        self.assertIn("extra arms", s.painter.avoids[1])   # 2 回目は見つけた崩れを打ち消して描いた

    def test_off_is_not_pass(self):
        with mock.patch.dict(os.environ, {"CD_CHECK": "off"}):
            r = sanity.check(Path(__file__), "1girl")
        self.assertFalse(r["readable"])


class CountBoxesTest(unittest.TestCase):
    """人の枠の数え方: 入れ子の枠（同じ人の上半身）と背景の小さな人影を数えない"""

    def test_nested_and_small(self):
        from chatdraw import sanity
        whole, upper = [41, 16, 398, 635], [41, 14, 396, 448]
        self.assertEqual(sanity.count_boxes([upper, whole]), 1)
        self.assertEqual(sanity.count_boxes([whole, [600, 10, 640, 60]]), 1)
        self.assertEqual(sanity.count_boxes([[0, 0, 300, 600], [320, 0, 620, 600]]), 2)
        self.assertEqual(sanity.count_boxes([]), 0)


if __name__ == "__main__":
    unittest.main()
