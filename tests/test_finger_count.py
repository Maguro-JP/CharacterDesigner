"""指の数の検品（tools/gen/hands.py の count_fingers）。手の模型は点をいつも 5 本に置くので、
手の色の筋で数える。描いた手で 4 本・5 本（6 本指）・指を閉じた手を見分けるかを確かめる"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))


def hand(n: int, gap: int = 6, width: int = 14):
    """肌色の手のひら（下）と、その上に n 本の指（白地の上の縦の筋）。指の付け根は y=260、指先は y=120"""
    a = np.full((448, 448, 3), 255.0)
    skin = np.array([240.0, 200.0, 180.0])
    x0 = 224 - (n * width + (n - 1) * gap) // 2
    a[260:400, x0 - 10:x0 + n * (width + gap) + 10] = skin
    for i in range(n):
        x = x0 + i * (width + gap)
        a[120:262, x:x + width] = skin
    lm = np.zeros((21, 2))
    xs = [x0 + i * (width + gap) + width / 2 for i in range(n)]
    four = [xs[0], xs[len(xs) // 3], xs[(2 * len(xs)) // 3], xs[-1]]
    for f, x in zip((5, 9, 13, 17), four):
        for j in range(4):
            lm[f + j] = (x, 260 - j * 46)
    return a, lm, skin


class FingerCountTest(unittest.TestCase):
    def test_counts(self):
        from hands import count_fingers
        for n in (4, 5):
            a, lm, skin = hand(n)
            self.assertEqual(count_fingers(a, lm, skin)["count"], n)

    def test_closed_fingers_are_not_counted(self):
        from hands import count_fingers
        a, lm, skin = hand(4, gap=0)
        self.assertIsNone(count_fingers(a, lm, skin)["count"])   # 隙間が無い手は数えない（数え違いで落とさない）


if __name__ == "__main__":
    unittest.main()
