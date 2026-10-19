"""頼みの言葉から棚の座る下絵を選ぶ（tools/gen/assets.py の pick_pose）の試験"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import assets  # noqa: E402


class PickPose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = assets.POSE
        assets.POSE = Path(self.tmp.name)
        for name, kind, lic in (("a", "chair", "CC0"), ("b", "chair", "CC0"), ("c", "hug_knees", "CC0"), ("d", "floor", "")):
            (assets.POSE / f"{name}.png").write_bytes(b"")
            (assets.POSE / f"{name}.json").write_text(json.dumps({"license": lic, "kind": kind}))

    def tearDown(self):
        assets.POSE = self.old
        self.tmp.cleanup()

    def test_kind_from_words(self):
        self.assertIn(assets.pick_pose("1girl, sitting, smile"), ("a", "b"))
        self.assertEqual(assets.pick_pose("1girl sitting on the floor hugging knees"), "c")
        self.assertNotEqual(assets.pick_pose("girl sitting", 0), assets.pick_pose("girl sitting", 1))

    def test_none_when_no_words_or_no_usable_pose(self):
        self.assertIsNone(assets.pick_pose("1girl, standing"))
        self.assertIsNone(assets.pick_pose("1girl sitting on the floor"))  # 床の下絵はライセンスが無いので使わない


if __name__ == "__main__":
    unittest.main()
