import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))


class LightPlan(unittest.TestCase):
    def test_every_mood_has_a_plan_and_shadow_side_is_dark(self):
        import atmosphere
        import lightplan
        for mood in atmosphere.MOODS:
            p = lightplan.plan_of(mood)
            self.assertIn(mood, lightplan.PLANS, mood)
            self.assertEqual(p["shadow"], 0.0)
            self.assertTrue(-180 <= p["az"] <= 180 and 0 <= p["el"] <= 90)

    def test_backlit_moods_have_rim_light_behind(self):
        import lightplan
        p = lightplan.plan_of("holy")
        self.assertGreater(abs(p["az"]), 90)
        self.assertGreater(p["rim"], 0)

    def test_unknown_mood_falls_back_to_day(self):
        import lightplan
        self.assertEqual(lightplan.plan_of("nope")["az"], lightplan.PLANS["day"]["az"])


@unittest.skipUnless(importlib.util.find_spec("torch") and (ROOT / ".cache/gen/upscale/RealESRGAN_x4plus_anime_6B.pth").exists(),
                     "拡大の重みが無い（sh tools/gen/setup.sh で入る）")
class Upscale(unittest.TestCase):
    def test_reaches_long_side_and_keeps_ratio(self):
        from PIL import Image
        import upscale
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "a.png", Path(d) / "b.png"
            im = Image.new("RGB", (60, 90), "white")
            im.paste((20, 20, 20), (20, 30, 40, 60))
            im.save(src)
            w, h = upscale.upscale(src, out, long=300)
        self.assertEqual(h, 300)
        self.assertAlmostEqual(w / h, 60 / 90, delta=0.02)


if __name__ == "__main__":
    unittest.main()
