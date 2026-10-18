"""素材の棚（assets）: 出典とライセンスの無い素材は使わない。名前の形で場所を外へ向けさせない"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import assets  # noqa: E402


class Shelf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (assets.LORA, assets.POSE)
        assets.LORA, assets.POSE = d / "lora", d / "pose"
        self.src = d / "doll.png"
        Image.new("RGB", (8, 8), "white").save(self.src)

    def tearDown(self):
        assets.LORA, assets.POSE = self.saved
        self.tmp.cleanup()

    def test_pose_needs_license_and_good_name(self):
        with self.assertRaises(ValueError):
            assets.add_pose(str(self.src), "doll", license=" ")
        for bad in ("../x", "Doll", "a/b", "", "x" * 49):
            with self.assertRaises(ValueError):
                assets.add_pose(str(self.src), bad, license="own")
        got = assets.add_pose(str(self.src), "doll-1", license="own")
        self.assertTrue(got["usable"])
        self.assertEqual(assets.get_pose("doll-1"), assets.POSE / "doll-1.png")
        self.assertIsNone(assets.get_pose("../doll-1"))

    def test_lora_without_license_is_listed_but_not_usable(self):
        assets.LORA.mkdir(parents=True)
        (assets.LORA / "paint.safetensors").write_bytes(b"0")
        self.assertFalse(assets.list_loras()[0]["usable"])
        self.assertIsNone(assets.get("paint"))
        (assets.LORA / "paint.json").write_text(json.dumps({"license": "CC0"}))
        self.assertEqual(assets.get("paint")["license"], "CC0")
        self.assertIsNone(assets.get("../paint"))


if __name__ == "__main__":
    unittest.main()
