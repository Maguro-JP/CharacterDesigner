"""頼んでいない色の物（measure.stray_color）: 灰の背景と肌色だけの絵は低く、鮮やかな色のにじみがある絵は高くなるかを見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402


def picture(stain=0):
    a = np.full((200, 100, 3), 200, dtype=np.uint8)
    a[40:180, 30:70] = (171, 132, 110)  # 写実の段で測った肌の色
    if stain:
        a[60:60 + stain, 75:95] = (40, 200, 230)  # 水色の光の漏れ
    return a


class StrayColorTest(unittest.TestCase):
    def test_skin_and_grey_only(self):
        self.assertLess(measure.stray_color(picture()), 2.0)

    def test_cyan_leak(self):
        self.assertGreater(measure.stray_color(picture(40)), 2.0)


if __name__ == "__main__":
    unittest.main()
