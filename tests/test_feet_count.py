"""足の指の数の検品（tools/gen/feet.py の count_toes）。

作った足（模型を使わない）で 4・5・6 本を数え分けるか、横向きの足を数えずに「読めない」とするか、
描いた全身の絵 2 枚（4 つの足）で数が合うかを確かめる。描いた絵と模型が無い環境では、その試験だけ飛ばす。
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
HAVE_SCIPY = importlib.util.find_spec("scipy") is not None

# 描いた絵と、目で数えた指の数（絵の左の足, 右の足）。置き場は CD_FEET_DIR で替えられる
GT_DIR = Path(os.environ.get("CD_FEET_DIR", "/tmp/claude-0/-home-user-CharacterDesigner/"
                             "8c6ecf16-92f2-5f55-bf0b-fbdaede0577a/scratchpad"))
GT = {"bk-comp.png": (6, 5), "bk-3-pose-depth-s7.png": (5, 5)}


def foot(n: int, W: int = 400, H: int = 400):
    """正面から見た足（指先が下）。肌の甲の下に n 本の指を並べ、指と指の間と輪郭に線画の線を引く。
    親指は絵の左、ほかの指より太い。返す: 絵、足の点"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), (235, 230, 215))
    d = ImageDraw.Draw(im)
    skin, line = (250, 215, 190), (60, 40, 40)
    x0, x1, top, base = 120, 280, 60, 300
    widths = [1.6] + [1.0] * (n - 1)
    unit = (x1 - x0) / sum(widths)
    d.polygon([(x0 + 20, top), (x1 - 20, top), (x1, base), (x0, base)], fill=skin, outline=line)
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w * unit)
    tips = []
    for i in range(n):
        a, b = xs[i], xs[i + 1]
        tip = base + 50 - 4 * i   # 小指ほど短い
        d.rounded_rectangle((a, base - 30, b, tip), radius=(b - a) / 2, fill=skin, outline=line, width=2)
        tips.append(((a + b) / 2, tip))
    d.rectangle((x0 + 2, base - 32, x1 - 2, base - 18), fill=skin)   # 甲と指の継ぎ目の線を消す
    for i in range(1, n):
        d.line((xs[i], base - 24, xs[i], base + 30), fill=line, width=2)
    kp = {"left_big_toe": tips[0], "left_small_toe": tips[-1], "left_ankle": ((x0 + x1) / 2, top - 20)}
    return im, kp


@unittest.skipUnless(HAVE_SCIPY, "scipy が無い")
class SyntheticFeetTest(unittest.TestCase):
    def test_counts(self):
        import feet
        for n in (4, 5, 6):
            im, kp = foot(n)
            r = feet.count_toes(im, kp)
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0]["count"], n, r[0]["evidence"])

    def test_side_view_unreadable(self):
        """親指の先と小指の先が重なる横向きの足は、数を出さない"""
        import feet
        im, kp = foot(5)
        kp["left_small_toe"] = (kp["left_big_toe"][0] + 3, kp["left_big_toe"][1])
        r = feet.count_toes(im, kp)
        self.assertIsNone(r[0]["count"])

    def test_two_feet_kept_apart(self):
        """左右の足は別々に数える（2 つの足を 1 つと数えない）"""
        import feet
        from PIL import Image
        a, ka = foot(5)
        b, kb = foot(6)
        im = Image.new("RGB", (800, 400))
        im.paste(a, (0, 0))
        im.paste(b, (400, 0))
        kp = {k: v for k, v in ka.items()}
        kp.update({k.replace("left", "right"): (x + 400, y) for k, (x, y) in kb.items()})
        r = feet.count_toes(im, kp)
        self.assertEqual([f["count"] for f in r], [5, 6])


@unittest.skipUnless(HAVE_SCIPY, "scipy が無い")
class DrawnFeetTest(unittest.TestCase):
    def test_ground_truth(self):
        import feet
        if not feet.MODEL.exists():
            self.skipTest("全身の点の模型が無い")
        for name, want in GT.items():
            p = GT_DIR / name
            if not p.exists():
                self.skipTest(f"描いた絵が無い（{p}）")
            r = feet.count_toes(p)
            self.assertEqual(len(r), 2, name)
            self.assertEqual(tuple(f["count"] for f in r), want, (name, [f["evidence"] for f in r]))


if __name__ == "__main__":
    unittest.main()
