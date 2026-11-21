"""検品不能を合格として扱わない回帰試験。"""
import unittest
from unittest import mock

from PIL import Image

from chatdraw import origqc


class UnmeasuredQualityCheckTest(unittest.TestCase):
    def test_missing_dependencies_are_not_a_pass(self):
        image = Image.new("RGB", (512, 512), "white")
        with mock.patch.object(origqc, "missing", return_value=["torch"]):
            result = origqc.check(image)
        self.assertFalse(result["readable"])
        self.assertFalse(result["measured"])
        self.assertEqual(result["bad"], [])
        self.assertTrue(result["notes"])

    def test_too_small_image_is_not_a_pass(self):
        image = Image.new("RGB", (64, 64), "white")
        with mock.patch.object(origqc, "missing", return_value=[]):
            result = origqc.check(image)
        self.assertFalse(result["readable"])
        self.assertFalse(result["measured"])
        self.assertTrue(result["notes"])


if __name__ == "__main__":
    unittest.main()
