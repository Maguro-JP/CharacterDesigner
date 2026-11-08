"""肌の粒のざらつき（measure.skin_grain）: 平らな肌色は上限より低く、細かい粒を足した肌は高くなり、粒の所だけを囲むか"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402


def picture(noise: float = 0.0, half: bool = False):
    a = np.full((768, 768, 3), 0.5, np.float32)
    a[100:700, 200:600] = (0.92, 0.74, 0.62)   # 肌色の板
    if noise:
        rng = np.random.default_rng(0)
        n = rng.normal(0, noise, (768, 768, 1)).astype(np.float32)
        if half:
            n[:, :400] = 0                       # 右半分だけに粒
        a[100:700, 200:600] += n[100:700, 200:600]
    return (np.clip(a, 0, 1) * 255).astype(np.uint8)


class SkinGrainTest(unittest.TestCase):
    def test_flat_skin_is_low(self):
        self.assertLess(measure.skin_grain(picture()), measure.SKIN_GRAIN_MAX)

    def test_grainy_skin_is_high(self):
        self.assertGreater(measure.skin_grain(picture(0.03)), measure.SKIN_GRAIN_MAX)

    def test_no_skin_is_unmeasured(self):
        self.assertIsNone(measure.skin_grain(np.full((256, 256, 3), 128, np.uint8)))

    def test_boxes_only_cover_grain(self):
        boxes = measure.skin_grain_boxes(picture(0.03, half=True))
        self.assertTrue(boxes)
        self.assertTrue(all(x0 >= 384 for x0, _y0, _x1, _y1 in boxes))


if __name__ == "__main__":
    unittest.main()
