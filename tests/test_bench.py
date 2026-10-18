import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import bench  # noqa: E402


class Bench(unittest.TestCase):
    def test_cases_point_at_stored_images_with_prompt_and_seed(self):
        b = json.loads((ROOT / "casts" / "bench-stage1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(b["cases"]), 46)
        for c in b["cases"]:
            self.assertTrue((ROOT / c["image"]).exists(), c["image"])
            self.assertTrue(c["prompt"] and c["seed"] > 0)
            self.assertIn(f"-s{c['seed']}", c["id"])

    def test_compare_rejects_more_problems(self):
        base = {"cases": {"a": {"problems": 1}, "b": {"problems": 0}}}
        same = {"variant": "x", "cases": {"a": {"problems": 0}, "b": {"problems": 1}}}
        worse = {"variant": "y", "cases": {"a": {"problems": 2}, "b": {"problems": 0, "seconds": 10}}}
        self.assertFalse(bench.compare(base, same)[1])
        text, bad = bench.compare(base, worse)
        self.assertTrue(bad)
        self.assertIn("崩れ 1 → 2", text)


if __name__ == "__main__":
    unittest.main()
