"""手首の点がずれて枠から手が外れたとき、枠をずらして読み直す（4096 の剣士で手らしさ 0.01 → 0.98）。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402


class HandShift(unittest.TestCase):
    def test_low_presence_box_is_shifted(self):
        im = Image.new("RGB", (400, 400), "white")
        boxes = [{"side": "right", "box": (200, 200, 300, 300), "angle": 0.0, "score": 0.9}]
        calls = []

        def fake(crop):
            calls.append(crop.size)
            # 9 回目（右下にずらした枠）だけ手が写っているとする
            return ({"presence": 0.95 if len(calls) == 9 else 0.01}, [], None)
        with mock.patch.object(qc, "hand_boxes", return_value=boxes), mock.patch("hands.measure", side_effect=fake):
            r = qc.hands_auto([], im)
        self.assertTrue(r["readable"])
        self.assertEqual(r["hands"][0]["box"], (275, 275, 375, 375))

    def test_readable_box_is_not_shifted(self):
        im = Image.new("RGB", (400, 400), "white")
        boxes = [{"side": "left", "box": (10, 10, 110, 110), "angle": 0.0, "score": 0.9}]
        with mock.patch.object(qc, "hand_boxes", return_value=boxes), \
                mock.patch("hands.measure", return_value=({"presence": 0.9}, [], None)) as m:
            qc.hands_auto([], im)
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
