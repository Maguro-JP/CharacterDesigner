"""「女性」の頼みに、体つきの言葉と体の打ち消しを勝手に足さない（chatdraw/body.py）。
足していたときは、頼んでいない体つきで描かれ、体が崩れた。mature female も足さない"""
import unittest

from chatdraw import body, jaterms


class BodyTest(unittest.TestCase):
    def test_no_body_words_added(self):
        self.assertEqual(body.TAGS, "adult woman")
        self.assertEqual(body.NEGATIVE, "")

    def test_woman_is_only_translated(self):
        tags = jaterms.tags_from("白いビキニの女性")
        self.assertNotIn("mature female", tags)
        self.assertNotIn("slender body", tags)


if __name__ == "__main__":
    unittest.main()
