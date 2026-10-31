"""部分の描き直し（tools/gen/fix.py）が、描き直しのたびに跡の検品を走らせることの試験。描く所は偽物に差し替える。
模型を外から取りに行かない既定（HF_HUB_OFFLINE）も確かめる。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import fix  # noqa: E402

try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def stripes(w=256, h=256):
    a = np.full((h, w), 200, "uint8")
    for x in range(8, w, 24):
        a[16:h - 16, x:x + 3] = 20      # 上下に余白を残す（端で切れた絵と判定されないように）
    a[16:20, 8:w - 4] = 20              # 縞を横棒でつなぎ、1 つの形にする（離れた縞は宙に浮いた塊と判定される）
    return Image.fromarray(a).convert("RGB")


@unittest.skipUnless(HAS_SCIPY, "scipy が無い（.cache/gen/lib に入る）")
class FixReportTest(unittest.TestCase):
    def run_fix(self, draw):
        with tempfile.TemporaryDirectory() as d:
            src, out = f"{d}/src.png", f"{d}/out.png"
            stripes().save(src)
            rep = fix.fix(src, out, [(64, 64, 192, 192)], "test", draw=draw)
            saved = json.loads(Path(out + ".qc.json").read_text())
            self.assertTrue(Path(out + ".mask.png").exists())
        return rep, saved

    def test_blurry_repaint_is_reported(self):
        rep, saved = self.run_fix(lambda im, m, *a: Image.composite(im.filter(ImageFilter.GaussianBlur(4)), im, m))
        self.assertFalse(rep["clean"])
        self.assertTrue(rep["scars"])
        self.assertEqual(saved["clean"], False)

    def test_clean_repaint_passes(self):
        rep, _ = self.run_fix(lambda im, m, *a: im.copy())
        # 縞の画像には顔が無く、目の検品は「読めない」になる（それで clean は False）。跡と崩れが無いことだけを見る
        self.assertEqual((rep["seams"], rep["scars"], rep["problems"]), ([], [], []))


class BoxTest(unittest.TestCase):
    def test_reversed_box_is_rejected(self):
        with self.assertRaises(Exception):
            fix.parse_box("100,50,10,60")


def _child_env() -> dict:
    """子の処理の環境。PYTHONPATH の相対の道を絶対の道にする（子は tools/gen で動くので、相対のままだと部品が見つからなかった）"""
    env = {k: v for k, v in os.environ.items() if k not in ("HF_HUB_OFFLINE", "CD_FETCH")}
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.pathsep.join(str((ROOT / p).resolve()) if p and not os.path.isabs(p) else p
                                            for p in env["PYTHONPATH"].split(os.pathsep))
    return env


class OfflineDefaultTest(unittest.TestCase):
    def test_models_are_not_fetched_by_default(self):
        env = _child_env()
        for mod, want, extra in (("design", "1", {}), ("people", "1", {}), ("fix", "1", {}),
                                 ("design", "0", {"CD_FETCH": "1"})):
            r = subprocess.run([sys.executable, "-c", f"import {mod}, os; print(os.environ['HF_HUB_OFFLINE'])"],
                               cwd=ROOT / "tools" / "gen", env={**env, **extra}, capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), want, (mod, extra, r.stderr[-300:]))

    def test_fix_sets_cache_before_diffusers(self):
        # fix.py は diffusers を読む前に置き場所を決める。後だと手元の模型が見つからず、取りに行った
        env = {k: v for k, v in _child_env().items() if k != "HF_HOME"}
        r = subprocess.run([sys.executable, "-c", "import fix, os; print(os.environ['HF_HOME'])"],
                           cwd=ROOT / "tools" / "gen", env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), str(ROOT / ".cache" / "gen" / "hf"), r.stderr[-300:])


class CarriedFaceTest(unittest.TestCase):
    """顔に掛からない描き直しでは、元の絵の顔と目の外れを引き継ぐ"""

    def setUp(self):
        import json
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "a.png")
        bad = {"measure": {"path": "eyes.iris_delta", "value": 0.155}}
        other = {"measure": {"path": "hair.blown", "value": 0.2}}
        with open(self.src + ".qc.json", "w") as f:
            json.dump({"problems": [bad, other]}, f)
        # 顔の点（目と鼻）がおよそ x 400〜440、y 150〜170 にある
        self.points = [{"name": "nose", "x": 420, "y": 170, "score": 0.9},
                       {"name": "left_eye", "x": 400, "y": 150, "score": 0.9},
                       {"name": "right_eye", "x": 440, "y": 150, "score": 0.9}]

    def test_far_box_carries_eye_problem_only(self):
        got = fix.carried_face(self.src, [(300, 590, 420, 720)], self.points)
        self.assertEqual([g["measure"]["path"] for g in got], ["eyes.iris_delta"])

    def test_box_on_face_does_not_carry(self):
        self.assertEqual(fix.carried_face(self.src, [(370, 135, 460, 175)], self.points), [])

    def test_unreadable_face_carries(self):
        self.assertEqual(len(fix.carried_face(self.src, [(370, 135, 460, 175)], [])), 1)
