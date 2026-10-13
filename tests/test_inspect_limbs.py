"""検品の手足の数え方（edit.inspect）。部位分けの結果は絵の隣の .parts.png を作り物で置き、模型を使わずに見る"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import edit  # noqa: E402


def judged(labels):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "a.png"
        im = Image.new("RGB", (40, 60), "white")
        im.paste((40, 30, 30), (12, 8, 28, 52))     # 白の背景に人物の塊を1つ置く（背景を切ったあとに人物が残るように）
        im.save(src)
        time.sleep(0.01)
        lab = np.zeros((60, 40), np.uint8)
        for k, name in enumerate(labels):
            lab[10 + k * 5:15 + k * 5, 10:30] = edit.LABELS[name]
        Image.fromarray(lab, "L").save(str(src) + ".parts.png")
        return edit.inspect(str(src), objects=False, edges=False)


class LimbsTest(unittest.TestCase):
    def test_legs_covered_by_overalls_are_not_missing(self):
        # つなぎの服で脚の肌が 0 画素でも、ズボンと靴が見えていれば脚はある
        self.assertNotIn("脚が無い", judged(["face", "left_arm", "pants", "left_shoe"]))

    def test_no_legs_at_all(self):
        self.assertIn("脚が無い", judged(["face", "left_arm", "upper"]))


if __name__ == "__main__":
    unittest.main()
