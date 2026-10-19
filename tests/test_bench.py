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


class Tile(unittest.TestCase):
    def test_spans_cover_with_overlap(self):
        import tile
        for n in (1024, 2800, 4096):
            xs = tile.spans(n)
            self.assertEqual(xs[0], 0)
            self.assertEqual(xs[-1] + tile.SIDE, max(n, tile.SIDE))
            for a, b in zip(xs, xs[1:]):
                self.assertGreaterEqual(a + tile.SIDE - b, tile.OVERLAP)
        self.assertEqual(tile.LONG, 4096)

    def test_drift_ignores_detail_but_sees_shape(self):
        import numpy as np
        from PIL import Image
        import tile
        rng = np.random.default_rng(0)
        base = np.full((1024, 1024), 200, np.uint8)
        base[300:700, 400:600] = 60
        fine = np.clip(base + rng.normal(0, 25, base.shape), 0, 255).astype(np.uint8)   # 描き込み（細かい模様）
        moved = np.full((1024, 1024), 200, np.uint8)
        moved[300:700, 650:850] = 60                                                      # 形が動いた
        a = Image.fromarray(base)
        self.assertLess(tile.drift(a, Image.fromarray(fine)), tile.DRIFT)
        self.assertGreater(tile.drift(a, Image.fromarray(moved)), tile.DRIFT)


class PoseDrift(unittest.TestCase):
    def test_crouch_turned_standing_is_caught_at_pose_scale(self):
        import numpy as np
        from PIL import Image
        import hires
        import tile
        crouch = np.full((1824, 1248), 220, np.uint8)
        crouch[900:1700, 350:900] = 60          # しゃがんだ形: 低く横に広い
        stand = np.full((1824, 1248), 220, np.uint8)
        stand[200:1750, 500:750] = 60           # 立ち姿: 高く細い
        a = Image.fromarray(crouch)
        self.assertGreater(tile.drift(a, Image.fromarray(stand), scale=hires.POSE_SCALE), tile.DRIFT)
        self.assertLess(tile.drift(a, a, scale=hires.POSE_SCALE), tile.DRIFT)


if __name__ == "__main__":
    unittest.main()
