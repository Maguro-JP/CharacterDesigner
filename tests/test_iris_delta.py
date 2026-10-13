"""左右の瞳の色違い（measure.iris_delta）。作り物の目で、茶と灰・茶と紺を外れにし、同じ色や明るさだけの差は通すかを見る"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

LIMIT = next(c["max"] for c in json.loads(measure.NORMS.read_text(encoding="utf-8"))["checks"]
             if c["path"] == "eyes.iris_delta")


def face_with_eyes(left, right):
    """肌色の地に、瞳の色の円を2つ置く。円の中心は黒（まつ毛と瞳孔）"""
    h, w = 80, 120
    rgb = np.full((h, w, 3), (0.95, 0.82, 0.74))
    y, x = np.mgrid[0:h, 0:w]
    blobs = []
    for cx, color in ((35, left), (85, right)):
        r = np.hypot(x - cx, y - 40)
        rgb[r < 9] = color
        rgb[r < 3] = (0.05, 0.04, 0.04)
        blobs.append({"cx": float(cx), "cy": 40.0, "w": 18.0, "h": 18.0})
    return rgb, blobs[0], blobs[1]


BROWN, GRAY, NAVY = (0.45, 0.28, 0.18), (0.42, 0.43, 0.45), (0.15, 0.18, 0.40)


class IrisDeltaTest(unittest.TestCase):
    def delta(self, a, b):
        rgb, left, right = face_with_eyes(a, b)
        return measure.iris_delta(rgb, left, right)

    def test_same_color_passes(self):
        self.assertLess(self.delta(BROWN, BROWN), LIMIT)

    def test_brightness_only_passes(self):
        # 片目だけ影に入って暗い。色は同じなので外れにしない
        dark = tuple(c * 0.7 for c in BROWN)
        self.assertLess(self.delta(BROWN, dark), LIMIT)

    def test_brown_and_gray_fails(self):
        # 彩度の高い画素だけを見る測り方では、灰色の瞳が抜けて見逃した
        self.assertGreater(self.delta(BROWN, GRAY), LIMIT)

    def test_brown_and_navy_fails(self):
        self.assertGreater(self.delta(BROWN, NAVY), LIMIT)


if __name__ == "__main__":
    unittest.main()
