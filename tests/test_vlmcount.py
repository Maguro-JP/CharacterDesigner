"""小さな VLM で指を数える入口の試験。模型が無い機械では、数える試験をとばす"""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
sys.path.insert(0, str(ROOT))
import vlmcount  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "fingercount"


class Parse(unittest.TestCase):
    def test_number(self):
        self.assertEqual(vlmcount._number("TOTAL: 6"), 6)
        self.assertEqual(vlmcount._number("5"), 5)
        self.assertEqual(vlmcount._number("I see four fingers."), 4)
        self.assertIsNone(vlmcount._number("unclear"))

    def test_fixtures(self):
        truth = json.loads((FIX / "truth.json").read_text())
        for k in truth:
            if not k.startswith("_"):
                self.assertTrue((FIX / f"{k}.png").exists(), k)

    def test_flag_off(self):
        os.environ.pop("CD_VLM_COUNT", None)
        from chatdraw import handcheck
        self.assertIsNone(handcheck.vlm_digits(FIX / "win7_wave.png"))


@unittest.skipUnless(importlib.util.find_spec("transformers") and os.environ.get("CD_VLM_TEST") == "1",
                     "VLM の模型が無い（CD_VLM_TEST=1 と transformers で動く）")
class Count(unittest.TestCase):
    def test_six_toes(self):
        r = vlmcount.count_digits(FIX / "bk_foot_l.png", "foot")
        self.assertIn(r["verdict"], ("too_many", "odd"))
