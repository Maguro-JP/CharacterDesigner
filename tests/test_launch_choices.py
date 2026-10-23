"""初回の起動で取る物を選ばせる（app/launch.py の choose）の試験"""
import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import launch  # noqa: E402


class Choose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(launch, "CHOICES", Path(self.tmp.name) / "choices.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_asks_once_and_remembers(self):
        with mock.patch.object(builtins, "input", side_effect=["2", "2"]):
            self.assertEqual(launch.choose(False, False), {"image_model": False, "llm": "small"})
        with mock.patch.object(builtins, "input", side_effect=AssertionError("2回目は聞かない")):
            self.assertEqual(launch.choose(False, False), {"image_model": False, "llm": "small"})

    def test_yes_takes_everything_and_choose_asks_again(self):
        self.assertEqual(launch.choose(False, True), {"image_model": True, "llm": "default"})
        with mock.patch.object(builtins, "input", side_effect=["1", "3"]):
            self.assertEqual(launch.choose(True, False), {"image_model": True, "llm": "no"})


if __name__ == "__main__":
    unittest.main()
