"""検品と描き直しが、同じ理由で何度も回らないこと（chatdraw/persist.py、engine.hand_unread、handcheck の使い回し）。

0.5.20 では、部品が無くて検品できない絵や、手の写っていない絵を、止めるボタンを押すまで描き直していた。
崩れの言葉の並びが種ごとに少しずつ変わり、「同じ崩れ」と数えられなかったのが原因。
"""
import os
import unittest

from PIL import Image

from chatdraw import engine, handcheck
from chatdraw.persist import Persist


class UncheckedOnceTest(unittest.TestCase):
    def test_unchecked_redraws_once_then_reports(self):
        p = Persist([1.0, 0.85, 1.2, 0.7])
        miss = [engine.unchecked("数字の作画監督", "部品がありません")]
        self.assertTrue(p.go_on(miss))       # 1 回だけ描き直す
        self.assertFalse(p.go_on(miss))      # 変わらなければ、止めて崩れとして知らせる
        self.assertIn("検品できなかった", p.reason)

    def test_unchecked_does_not_hide_real_flaws(self):
        p = Persist(["a", "b"])
        miss = engine.unchecked("体の数と目")
        self.assertTrue(p.go_on([miss, "指が 6 本"]))
        self.assertTrue(p.go_on([miss, "指が 5 本で太い"]))   # 本当の崩れが残る間は、検品できなかった物があっても続ける
        self.assertFalse(p.go_on([miss]))    # 残りは検品できなかった物だけで、1 回描き直しても変わらない

    def test_no_progress_switches_hand_and_stops(self):
        p = Persist(["a", "b"])
        hands = []
        for i in p.rounds():
            hands.append(p.hand())
            # 言葉は毎回違う（種が違う）が、数は減らない。前はこれで止まらなかった
            if not p.go_on([f"指の崩れ {i}", "目の崩れ"]):
                break
        self.assertEqual(hands, ["a", "a", "b"])
        self.assertIn("減らなかった", p.reason)


class HandUnreadTest(unittest.TestCase):
    def setUp(self):
        self.env = os.environ.pop("CD_CHECK", None)

    def tearDown(self):
        if self.env is not None:
            os.environ["CD_CHECK"] = self.env

    def test_no_hands_in_picture_is_not_a_flaw(self):
        self.assertEqual(engine.hand_unread({"readable": False, "bad": [], "hands": []}), [])

    def test_missing_parts_and_unreadable_hand_are_flaws(self):
        self.assertTrue(engine.hand_unread({"readable": False, "bad": [], "hands": [], "reason": "部品がありません"}))
        self.assertTrue(engine.hand_unread({"readable": False, "bad": [], "hands": [{"seen": False}]}))


class HandcheckMemoTest(unittest.TestCase):
    def test_same_pixels_are_measured_once(self):
        calls = []
        real = handcheck._check
        handcheck._check = lambda im, fetch=True, asked="": calls.append(1) or {"readable": True, "bad": [], "hands": []}
        env = os.environ.pop("CD_CHECK", None)
        try:
            handcheck._MEMO.clear()
            a = Image.new("RGB", (32, 32), (10, 20, 30))
            r1 = handcheck.check(a)
            r1["bad"].append("書き換え")             # 返した結果を書き換えても、使い回す側は変わらない
            r2 = handcheck.check(a.copy())
            handcheck.check(Image.new("RGB", (32, 32), (11, 20, 30)))
            self.assertEqual(len(calls), 2)
            self.assertEqual(r2["bad"], [])
        finally:
            handcheck._check = real
            handcheck._MEMO.clear()
            if env is not None:
                os.environ["CD_CHECK"] = env


class ReleaseRateTest(unittest.TestCase):
    def test_memory_is_returned_at_most_every_30s(self):
        from chatdraw import membudget as mb
        calls = []
        start = mb.Budget(10.0, 0.0, 12.0, 0.0)
        w = mb.Watch(start, sample=lambda: (0.4, 0.0), release=lambda: calls.append(1))
        for _ in range(50):          # 0.2 秒ごとの見張りが 50 回、危ないと見ても
            w.poll()
        self.assertEqual(len(calls), 1)   # 返すのは 1 度だけ（前は 50 回で、描く 1 工程が 18 倍に延びた）


if __name__ == "__main__":
    unittest.main()
