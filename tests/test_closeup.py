import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import numpy as np
    import closeup
except ImportError:  # numpy が無い環境
    np = None


@unittest.skipIf(np is None, "numpy が無い")
class CloseupBoxTest(unittest.TestCase):
    def seg(self):
        s = np.zeros((1216, 832), np.uint8)
        s[100:260, 300:500] = 2    # 髪
        s[150:300, 330:470] = 11   # 顔
        s[320:700, 250:580] = 4    # 上着
        s[700:1050, 300:530] = 6   # ズボン
        s[1050:1150, 300:530] = 9  # 靴
        return s

    def test_parts_are_square_and_inside(self):
        b = closeup.boxes(self.seg(), [{"id": "ledger", "box": [560, 600, 640, 760]}, {"id": "none"}])
        self.assertEqual(set(b), {"eyes", "hair", "outfit-upper", "outfit-lower", "outfit-shoes", "item-ledger"})
        for x0, y0, x1, y1 in b.values():
            self.assertEqual(x1 - x0, y1 - y0)
            self.assertTrue(0 <= x0 and 0 <= y0 and x1 <= 832 and y1 <= 1216)

    def test_eyes_band_is_upper_face(self):
        x0, y0, x1, y1 = closeup.boxes(self.seg())["eyes"]
        # 顔の 25〜60%（187〜240）の中心を含み、顔の下端の口元までは主に入れない
        self.assertLess(y0, 190); self.assertGreater(y1, 240)
        self.assertLess((y0 + y1) / 2, 240)

    def test_unreadable_face_is_left_out(self):
        s = self.seg(); s[s == 11] = 0
        self.assertNotIn("eyes", closeup.boxes(s))


if __name__ == "__main__":
    unittest.main()
