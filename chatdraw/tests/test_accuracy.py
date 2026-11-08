"""全部の機能の精度の台（chatdraw/accuracy.py）の軽い物を流し、数字が下限を割らないかを見る。

下限は直したあとの数字。直しで上がったら下限も上げる（下がった変更を入れないため）。
加工は 1 回 2 分ほどかかるので、ここでは流さない（tools/gen/accuracy_bench.py で流す）。
"""
import unittest

from chatdraw import accuracy
from tools.gen import accuracy_bench

FLOOR = {"描く言葉": 100.0, "場所の言葉": 100.0, "チャットの読み取り": 100.0, "担当編集者のサボりの検品": 100.0, "赤ペンの直し": 94.2}


class AccuracyTest(unittest.TestCase):
    def test_floors(self):
        for name, floor in FLOOR.items():
            with self.subTest(name=name):
                r = accuracy.LIGHT[name]()
                self.assertTrue(0 <= r["score"] <= 100)
                self.assertGreaterEqual(r["score"], floor, r)

    def test_redpen_keeps_outside(self):
        r = accuracy.redpen()
        self.assertEqual(r["outside"], 0)
        self.assertEqual(r["eye"], 0.0)

    def test_table_marks_drop(self):
        old = {"拡大": dict(score=80.0, prev="", date="d")}
        text = accuracy_bench.render(old, {"拡大": dict(score=70.0)}, "2026-11-08 12:00")
        self.assertIn("| 拡大 | 70.0 ▼ | 80.0 |", text)
        self.assertEqual(accuracy_bench.read_table(text)["拡大"]["score"], 70.0)


if __name__ == "__main__":
    unittest.main()
