"""見逃した手を崩れた手として足す、と、検品を通った絵でも、手・足・顔の枠をすべて細部の描き直しに回す（chatdraw/handcheck.detail_regions）"""
import unittest

from chatdraw import handcheck


class DetailRegions(unittest.TestCase):
    def test_all_seen_parts_are_listed_even_when_not_bad(self):
        res = {"hands": [{"box": [1, 2, 3, 4], "bad": []}, {"box": [5, 6, 7, 8], "seen": False}],
               "feet": [{"box": [9, 9, 20, 20], "bad": []}], "faces": [{"box": [0, 0, 10, 10]}]}
        self.assertEqual(handcheck.detail_regions(res),
                         [([1, 2, 3, 4], "hand"), ([9, 9, 20, 20], "foot"), ([0, 0, 10, 10], "face")])
        self.assertEqual(handcheck.bad_regions(res), [])


if __name__ == "__main__":
    unittest.main()


class MissedHands(unittest.TestCase):
    def test_wrist_without_found_hand_becomes_bad_hand(self):
        from unittest import mock
        from PIL import Image
        im = Image.new("RGB", (400, 400))
        kp = {"left_wrist": (100, 200), "left_elbow": (100, 120), "right_wrist": (300, 200), "right_elbow": (300, 120)}
        out = {"hands": [{"box": [280, 200, 330, 260], "bad": [], "seen": True}], "bad": []}
        with mock.patch.object(handcheck, "_keypoints", return_value=kp):
            handcheck._add_missed_hands(out, im)
        self.assertEqual(len(out["hands"]), 2)            # 右手は見つかっていたので足さない。左手だけ足す
        self.assertTrue(out["hands"][1]["missed"])
        self.assertEqual(handcheck.bad_regions(out)[0][1], "hand")
        self.assertEqual(len(out["bad"]), 1)


class UnreadableIsBad(unittest.TestCase):
    """読めない足は、靴を頼んでいない限り崩れとして返す（つぶれた指が検品を逃れた）"""

    def test_unreadable_foot_is_bad_unless_shoes_asked(self):
        import sys
        import types
        from unittest import mock
        fake = types.SimpleNamespace(count_toes=lambda im: [{"box": [0, 0, 9, 9], "count": None}], public=lambda f: f)
        with mock.patch.object(handcheck, "ensure_feet_model", return_value=True), mock.patch.dict(sys.modules, {"feet": fake}):
            _f, bad, _ = handcheck.check_feet(None, asked="1girl, bikini, barefoot")
            self.assertEqual(len(bad), 1)
            _f, bad, _ = handcheck.check_feet(None, asked="1girl, boots")
            self.assertEqual(bad, [])
