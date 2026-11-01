"""絵の質に関わる、模型の外の処理の試験。

- 背景を頼まれなかったときに場面を足す（背景がワンパターンにならない）
- 描かれなかった頼みを、次の回で描く言葉の前に出す
- 手・足・顔の直しで崩れが増えたら、崩れの一番少ない絵に戻す（1 つの模型でも 2 段でも）
- 2 段で描く流れも、検品を通らなければ種を変えて構図から描き直す
- 2 段の直しで、囲みの外の画素を 1 画素も変えない
- 指の向きによらず指を数え、数えられない手・読めない顔を崩れとして扱う
- 実際の絵（library/ の絵）で、読めない手を「読めなかった」の 1 行で隠さず、小さな顔を見逃さない

模型は読まない（描く所は偽物に替える）。実際の絵の検品は、手元に検品の模型があるときだけ通す。
"""
import json
import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "gen"))
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from chatdraw import engine, handcheck, twostage  # noqa: E402
import hands  # noqa: E402
from chatdraw import finishers  # noqa: E402

SDXL = "Laxhar/noobai-XL-Vpred-1.0"   # 範囲の直しができる世代（sdxl）の模型
LIB = ROOT / "library" / "feedback"


class Background(unittest.TestCase):
    def test_adds_scene_when_not_asked(self):
        out = engine.vary_background("1girl, solo, smile", 7)
        self.assertTrue(out.startswith("1girl, solo, smile, "), out)
        self.assertTrue(engine.has_background(out))

    def test_keeps_asked_background(self):
        for p in ("1girl, white background", "1girl, simple background", "1girl, beach, sunset", "1girl, indoors"):
            self.assertEqual(engine.vary_background(p, 3), p)

    def test_varies_by_seed_and_repeats_with_same_seed(self):
        got = {engine.vary_background("1girl", s) for s in range(40)}
        self.assertGreaterEqual(len(got), 8, got)   # 12 の場面のうち、種 40 個で 8 以上が出る
        self.assertEqual(engine.vary_background("1girl", 5), engine.vary_background("1girl", 5))

    def test_sentence_form(self):
        out = engine.vary_background("A girl smiling.", 1, tags=False)
        self.assertTrue(out.startswith("A girl smiling, "), out)
        self.assertTrue(out.endswith("."))


class Emphasize(unittest.TestCase):
    def test_missing_moves_forward_after_people(self):
        p = "1girl, solo, smile, red dress, holding umbrella"
        self.assertEqual(engine.emphasize(p, ["holding umbrella", "red dress"]),
                         "1girl, solo, red dress, holding umbrella, smile")

    def test_nothing_missing(self):
        self.assertEqual(engine.emphasize("1girl, smile", []), "1girl, smile")
        self.assertEqual(engine.emphasize("1girl, smile", ["hat"]), "1girl, smile")


class FakePainter:
    model = SDXL
    stop = False
    avoid = ""

    def __init__(self):
        self.prompts, self.redraws = [], 0

    def paint(self, prompt, seed, **kw):
        self.prompts.append((prompt, seed))
        return Image.new("RGB", (64, 64), (seed % 255, 0, 0))

    def redraw(self, prompt, seed, image, mask, strength=0.45, **kw):
        self.redraws += 1
        return Image.new("RGB", image.size, (0, self.redraws, 0))


def hand_result(n):
    return {"readable": True, "bad": [f"手 1: 崩れ {i}" for i in range(n)],
            "hands": [{"box": [10, 10, 30, 30], "bad": ["x"] * n, "seen": True}] if n else
                     [{"box": [10, 10, 30, 30], "bad": [], "seen": True}], "feet": [], "faces": []}


class FixKeepsBest(unittest.TestCase):
    def test_worse_fix_is_undone(self):
        # 描いた絵は崩れ 2 件。直すと 5 件に増え、その次からは 3 件のまま。崩れ 2 件の元の絵を返す
        painter = FakePainter()
        studio = engine.Studio(painter=painter, out=Path("."))
        counts = {}

        def check(image, asked=""):
            key = image.getpixel((0, 0))
            if key not in counts:
                counts[key] = 2 if not counts else (5 if len(counts) == 1 else 3)
            return hand_result(counts[key])
        first = Image.new("RGB", (64, 64), (9, 9, 9))
        with mock.patch.dict(os.environ, {"CD_CHECK": "on"}), mock.patch.object(handcheck, "check", side_effect=check):
            out = studio._fix_hands(first, "1girl", 1, lambda m: None)
        self.assertIs(out, first)
        self.assertEqual(studio.hand_rounds[-1]["bad"], hand_result(2)["bad"])
        self.assertEqual(painter.redraws, studio.FIX_ROUNDS)

    def test_better_fix_is_used(self):
        painter = FakePainter()
        studio = engine.Studio(painter=painter, out=Path("."))

        def check(image, asked=""):
            return hand_result(0 if image.getpixel((0, 0))[1] >= 1 else 2)
        with mock.patch.dict(os.environ, {"CD_CHECK": "on"}), mock.patch.object(handcheck, "check", side_effect=check):
            out = studio._fix_hands(Image.new("RGB", (64, 64)), "1girl", 1, lambda m: None)
        self.assertGreaterEqual(out.getpixel((0, 0))[1], 1)   # 直した絵（崩れ 0 のあとの細部の描き直しを含む）
        self.assertEqual(studio.hand_rounds[-1]["bad"], [])


class AskedComesFirst(unittest.TestCase):
    def test_missing_request_is_moved_forward_next_try(self):
        painter = FakePainter()
        with TemporaryDirectory() as t:
            studio = engine.Studio(painter=painter, out=Path(t))
            studio.way = "one"
            asked = iter([{"readable": True, "missing": ["holding umbrella"], "extra": []},
                          {"readable": True, "missing": [], "extra": []}])

            def fix(image, prompt, seed, say):
                studio.hand_rounds = [{"round": 0, "bad": []}]
                return image
            with mock.patch.object(studio, "_fix_hands", side_effect=fix), \
                    mock.patch("chatdraw.requestcheck.check", side_effect=lambda *a, **k: next(asked)), \
                    mock.patch.object(studio, "_inspect"):
                studio.draw("1girl, solo, smile, holding umbrella", 4)
        self.assertEqual(len(painter.prompts), 2)
        first, second = painter.prompts[0][0], painter.prompts[1][0]
        self.assertTrue(first.startswith("1girl, solo, smile, holding umbrella, "), first)   # 背景を後ろに足した
        self.assertTrue(second.startswith("1girl, solo, holding umbrella, smile"), second)
        self.assertNotEqual(painter.prompts[0][1], painter.prompts[1][1])


class TwoStageRedraws(unittest.TestCase):
    def test_redraws_until_passed(self):
        calls = []

        def run(sentence, tags, seed, comp, render, size, keep, variant, say=None, stopped=None):
            calls.append((sentence, tags, seed))
            keep.mkdir(parents=True, exist_ok=True)
            p = keep / f"3-{variant['name']}-s{seed}.png"
            Image.new("RGB", (32, 32)).save(p)
            passed = len(calls) == 2
            (keep / f"result-{variant['name']}.json").write_text(json.dumps(
                {"passed": passed, "checked": True, "bad": [] if passed else ["手 1: 指が多い"],
                 "missing": [] if passed else ["red dress"]}), encoding="utf-8")
            return p
        comp = types.SimpleNamespace(name="c", repo="c/c")
        render = types.SimpleNamespace(name="r", repo="r/r")
        with TemporaryDirectory() as t:
            studio = engine.Studio(painter=FakePainter(), out=Path(t))
            with mock.patch.object(twostage, "run_stages", side_effect=run), mock.patch.object(studio, "_inspect"):
                tags, saved = studio._draw_two("1girl, smile, red dress", 10, (comp, render), "", None, lambda m: None, None)
            meta = finishers.sidecar(saved)
        self.assertEqual(len(calls), 2)
        self.assertEqual([c[2] for c in calls], [10, 1010])
        self.assertTrue(calls[1][1].startswith("1girl, red dress, smile"), calls[1][1])
        self.assertTrue(meta["passed"])
        self.assertEqual(len(meta["redraws"]), 2)

    def test_stops_when_not_checked(self):
        def run(sentence, tags, seed, comp, render, size, keep, variant, say=None, stopped=None):
            keep.mkdir(parents=True, exist_ok=True)
            p = keep / f"3-{variant['name']}-s{seed}.png"
            Image.new("RGB", (32, 32)).save(p)
            return p   # 検品の結果を残さない（検品の部品が無い）
        ns = types.SimpleNamespace(name="x", repo="x/x")
        with TemporaryDirectory() as t:
            studio = engine.Studio(painter=FakePainter(), out=Path(t))
            with mock.patch.object(twostage, "run_stages", side_effect=run) as m, mock.patch.object(studio, "_inspect"):
                studio._draw_two("1girl", 1, (ns, ns), "", None, lambda m: None, None)
        self.assertEqual(m.call_count, 1)


class TwoStageFixOutside(unittest.TestCase):
    def test_outside_mask_unchanged_and_best_kept(self):
        """2 段の直し（twostage.fix_hands）で、囲みの外の画素は 1 画素も変わらない。直しで崩れが増えれば元の絵を返す"""
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch が無い")
        src = Image.fromarray(np.random.RandomState(0).randint(0, 255, (128, 96, 3), dtype=np.uint8))
        seen = []

        class FakeInpaint:
            def __init__(self, **kw):
                pass

            def __call__(self, image, mask_image, width, height, **kw):
                return types.SimpleNamespace(images=[Image.new("RGB", image.size, (255, 255, 255))])
        diffusers = types.ModuleType("diffusers")
        diffusers.StableDiffusionXLInpaintPipeline = FakeInpaint
        pipe = types.SimpleNamespace(components={})
        box = [30, 40, 60, 70]

        def check(image, asked=""):
            seen.append(image)   # 直しても崩れは 1 件のまま減らない
            return {"readable": True, "bad": ["手 1: x"], "hands": [{"box": box, "bad": ["x"], "seen": True}],
                    "feet": [], "faces": []}
        with TemporaryDirectory() as t, mock.patch.dict(sys.modules, {"diffusers": diffusers}), \
                mock.patch.object(handcheck, "check", side_effect=check), mock.patch.object(twostage, "FIX_ROUNDS", 2):
            out = twostage.fix_hands(pipe, src, "1girl", "", 1, 4, 5.0, Path(t), "v")
            fixed = seen[1]
        self.assertIs(out, src)   # 崩れが減らなかったので元の絵
        a, b = np.asarray(src), np.asarray(fixed)
        # 囲み（枠の中心から枠の長い辺の 0.6 倍の円）の外は、元の絵とバイト単位で同じ
        cx, cy, rr = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, max(box[2] - box[0], box[3] - box[1]) * 0.6
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        outside = (xx - cx) ** 2 + (yy - cy) ** 2 > (rr + 1) ** 2
        self.assertTrue((a[outside] == b[outside]).all(), int((a[outside] != b[outside]).any(axis=1).sum()))
        self.assertFalse((a == b).all())   # 囲みの中は直した


SKIN, BG, LINE = (230, 180, 150), (255, 255, 255), (60, 40, 40)


def down_hand(xs, width=34):
    """下を向いた 4 本の指の作り絵と関節 21 点（腕を下に垂らした手）。上向きの作り絵を上下に返した物"""
    im = Image.new("RGB", (448, 448), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((90, 28, 360, 148), fill=SKIN)
    for x in xs:
        d.rectangle((x - width // 2, 138, x + width // 2, 328), fill=SKIN, outline=LINE, width=2)
    lm = np.zeros((21, 2))
    lm[0] = (225, 28)
    lm[1:5] = [(80, 68), (70, 108), (60, 148), (55, 188)]
    for k, x in zip((5, 9, 13, 17), xs if len(xs) == 4 else [150, 200, 250, 300]):
        lm[k:k + 4] = [(x, 148), (x, 208), (x, 268), (x, 318)]
    return im, lm


class CountAnyDirection(unittest.TestCase):
    def test_counts_hand_pointing_down(self):
        im, lm = down_hand([150, 200, 250, 300])
        r = hands.count_fingers(np.asarray(im, float), lm, np.array(SKIN, float))
        self.assertEqual(r["count"], 4, r)


def measured(im, lm):
    with mock.patch.object(hands, "landmarks", return_value=(im, lm, 0.95)):
        return hands.measure(im)[1]


class UnreadableIsBad(unittest.TestCase):
    def test_three_close_fingers_is_bad(self):
        # 親指の外に 3 本しか描かれていない手（4 本指の手）。指どうしが近く、前は「重なって隠れている」として通した
        im, lm = down_hand([170, 210, 250])
        lm[5:9] = [(170, 148), (170, 208), (170, 268), (170, 318)]
        lm[9:13] = [(195, 148), (195, 208), (195, 268), (195, 318)]
        lm[13:17] = [(225, 148), (225, 208), (225, 268), (225, 318)]
        lm[17:21] = [(250, 148), (250, 208), (250, 268), (250, 318)]
        bad = measured(im, lm)
        self.assertTrue(any(b.startswith(("指を数え", "指が足りない")) for b in bad), bad)

    def test_four_clear_fingers_have_no_count_flaw(self):
        im, lm = down_hand([150, 200, 250, 300])
        bad = measured(im, lm)
        self.assertFalse([b for b in bad if b.startswith("指")], bad)


class SmallFace(unittest.TestCase):
    def test_small_unreadable_face_is_bad_with_box(self):
        import facecheck
        kp = {"nose": (100, 60), "left_eye": (104, 56), "right_eye": (96, 56)}
        im = Image.new("RGB", (200, 300), (240, 240, 240))
        with mock.patch.object(facecheck, "_read_tags", return_value={"1girl": 0.9}):
            r = facecheck.check_face(im, keypoints=kp)
        self.assertTrue(r["bad"], r)
        self.assertIsNotNone(r["box"])

    def test_small_readable_face_is_judged(self):
        import facecheck
        kp = {"nose": (100, 60), "left_eye": (104, 56), "right_eye": (96, 56)}
        im = Image.new("RGB", (200, 300), (240, 240, 240))
        with mock.patch.object(facecheck, "_read_tags", return_value={"blue eyes": 0.8}):
            r = facecheck.check_face(im, keypoints=kp)
        self.assertTrue(r["readable"], r)
        self.assertEqual(r["bad"], [])

    def test_small_bad_face_goes_to_fix_regions(self):
        face = {"box": [90, 40, 110, 70], "readable": False, "bad": ["顔: 小さくて目を読めない（読めない顔は崩れとして直す）"]}
        with mock.patch.object(handcheck, "_face", return_value=face):
            res = handcheck._add_face({"readable": False, "bad": [], "hands": []}, Image.new("RGB", (8, 8)), "")
        self.assertEqual(handcheck.bad_regions(res), [([90, 40, 110, 70], "face")])


def checker_ready() -> bool:
    try:
        h = handcheck._hands()
        h._litert()
        return handcheck.ensure_models(fetch=False)
    except Exception:
        return False


@unittest.skipUnless(checker_ready(), "手の検品の模型か部品が手元に無い")
class RealImages(unittest.TestCase):
    """library/ の実際の絵で、崩れを見つけるかを数で確かめる"""

    def setUp(self):   # ほかの試験が止めた検品（CD_CHECK=off）を、この試験の間だけ動かす
        p = mock.patch.dict(os.environ, {"CD_CHECK": "on"})
        p.start()
        self.addCleanup(p.stop)

    def test_unreadable_hands_are_not_hidden(self):
        # 傘の絵の 6 枚目は、見つけた手 3 つとも形が読めない。前は「手を読めませんでした」の 1 行で崩れを隠した
        res = handcheck.check(LIB / "hands/2026-10-20/umbrella/umbrella-6-s46.jpg", fetch=False)
        hand_bad = [b for b in res["bad"] if b.startswith("手 ")]
        self.assertGreaterEqual(len(hand_bad), 2, res["bad"])
        line = handcheck.summary(res)
        self.assertIn("崩れ", line)
        self.assertNotIn("読めませんでした", line)
        self.assertEqual(len([r for r in handcheck.bad_regions(res) if r[1] == "hand"]), len(hand_bad))

    def test_rejected_hand_is_caught(self):
        # 利用者が「指が崩れた手が頭の上に浮く」で戻した絵（r87）。検品が手の崩れを見つけ、直す所に挙げる
        res = handcheck.check(LIB / "body/2026-10-26/r87/r87-armsup-s87100.jpg", fetch=False)
        self.assertTrue([b for b in res["bad"] if b.startswith("手 ")], res["bad"])
        self.assertTrue([r for r in handcheck.bad_regions(res) if r[1] == "hand"])
