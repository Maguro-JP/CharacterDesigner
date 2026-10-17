"""直して検品し直す道具（tools/gen/loop.py）の試験。描き直しと検品は偽物に差し替え、
「崩れ→箱→描き直し→再検品→止まる」が回ること、直らない崩れを記録して止まることを確かめる。"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import loop  # noqa: E402

try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

POINTS = [{"name": n, "x": x, "y": y, "score": 0.9} for n, x, y in (
    ("left_wrist", 40, 30), ("left_elbow", 50, 60), ("right_wrist", 150, 150), ("right_elbow", 140, 120),
    ("left_shoulder", 70, 80), ("right_shoulder", 130, 80), ("left_hip", 80, 160), ("right_hip", 120, 160))]


def red_inside(im, mask, *a):
    """偽の描き直し: 範囲を赤で塗る。範囲の外は元のまま"""
    return Image.composite(Image.new("RGB", im.size, (255, 0, 0)), im, mask)


def fake_check(fixed_when_red):
    """左上の腕の範囲が赤く塗られていれば崩れが消える検品。fixed_when_red=False なら何をしても消えない"""
    def check(src, prompt):
        red = np.asarray(Image.open(src))[40, 45].tolist() == [255, 0, 0]
        flaws = [] if (red and fixed_when_red) else [{"key": "missing:one hand waving", "kind": "missing",
                                                      "detail": "one hand waving"}]
        return {"auto": {}, "flaws": flaws, "count": len(flaws)}
    return check


class LoopTest(unittest.TestCase):
    def run_loop(self, fixed, rounds=4):
        calls = []

        def draw(im, mask, prompt, negative, strength, seed):
            calls.append((mask.getbbox(), prompt))
            return red_inside(im, mask)
        with tempfile.TemporaryDirectory() as d:
            src = f"{d}/a.png"
            Image.new("RGB", (200, 200), (200, 200, 200)).save(src)
            rep = loop.run(src, f"{d}/out", "one hand waving", rounds, draw=draw, seed=1,
                           checker=fake_check(fixed), points_of=lambda p: POINTS)
            last = np.asarray(Image.open(rep["rounds"][-1]["image"]))
            self.assertTrue(Path(f"{d}/out/loop.json").exists())
        return rep, calls, last

    def test_flaw_is_fixed_and_loop_stops(self):
        rep, calls, last = self.run_loop(True)
        self.assertEqual([h["count"] for h in rep["rounds"]], [1, 0])
        self.assertEqual(rep["best_count"], 0)
        self.assertTrue(rep["best"].endswith("round-1.png"))
        # 片手の動作は上がっている方（左）の腕の範囲だけを描き直す。範囲の外は元のまま
        x0, y0, x1, y1 = calls[0][0]
        self.assertLess(x1, 100)
        self.assertTrue(calls[0][1].startswith("one hand waving, one hand waving"))
        self.assertEqual(last[190, 190].tolist(), [200, 200, 200])

    def test_unfixed_flaw_is_recorded_and_stops(self):
        rep, calls, _ = self.run_loop(False, rounds=4)
        self.assertIn("missing:one hand waving", rep["unfixable"])
        # 0 周目と 1・2 周目で減らなかった時点で直せないと記録し、3 周目は描き直さない
        self.assertEqual(len(calls), 2)
        self.assertTrue(rep["best"].endswith("round-0.png"))


class PlanTest(unittest.TestCase):
    def test_wear_goes_to_torso_and_floating_keeps_box(self):
        f = {"key": "missing:red trim", "kind": "missing", "detail": "red trim"}
        pl = loop.plan(f, "x.png", "bikini", POINTS, (200, 200))
        x0, y0, x1, y1 = pl["boxes"][0]
        self.assertTrue(x0 < 70 and x1 > 130 and y0 < 80 and y1 > 160)
        fl = {"key": "floating", "kind": "floating", "detail": {"floating": [{"box": [5, 5, 20, 20], "area": 0.01}]}}
        self.assertEqual(loop.plan(fl, "x.png", "", POINTS, (200, 200))["boxes"], [(5, 5, 20, 20)])

    def test_unknown_flaw_is_skipped(self):
        f = {"key": "measure:hair.blown", "kind": "measure", "detail": {}}
        self.assertIsNone(loop.plan(f, "x.png", "", POINTS, (200, 200)))

    @unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
    def test_text_box_finds_bottom_letters(self):
        a = np.full((200, 200, 3), 180, "uint8")
        for x in range(120, 190, 8):
            a[185:192, x:x + 3] = 20
        b = loop.text_box(a)
        self.assertIsNotNone(b)
        self.assertTrue(b[1] > 170 and b[0] > 100)


if __name__ == "__main__":
    unittest.main()
