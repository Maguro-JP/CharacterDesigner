"""版の番号が 1 か所（VERSION）にあり、画面と変わったことの記録がそれに合っているか。"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionTest(unittest.TestCase):
    def test_one_version_everywhere(self):
        v = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        # 版を上げたら、変わったことの記録に同じ版の節を足す
        heads = re.findall(r"^## (\d+\.\d+\.\d+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
        self.assertEqual(heads[0], v)


if __name__ == "__main__":
    unittest.main()
