"""背景だけを描くモード（tools/gen/background.py）。画像生成の模型とタグの模型は読まず、偽物で確かめる。"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import background  # noqa: E402

WORLD = {"id": "citadel", "name": "城塞", "tags": "snowy fantasy, night", "desc": "",
         "locations": [{"id": "gate", "name": "城門", "tags": "castle gate, torches", "desc": "", "avoid": "barrels"}]}


class SceneWords(unittest.TestCase):
    def test_location_first_then_world_and_avoid(self):
        with mock.patch("bible.load", return_value=WORLD):
            scene, neg = background.scene_words("citadel", "gate")
        self.assertEqual(scene, "castle gate, torches, snowy fantasy, night")
        self.assertIn("1girl", neg)
        self.assertTrue(neg.endswith("barrels"))

    def test_unknown_location_stops(self):
        with mock.patch("bible.load", return_value=WORLD):
            with self.assertRaises(SystemExit):
                background.scene_words("citadel", "hall")


class PersonTags(unittest.TestCase):
    def test_counts_and_names(self):
        tags = {"1girl": 0.9, "2boys": 0.5, "6+girls": 0.4, "solo": 0.8, "scenery": 0.95, "no humans": 0.9,
                "person": 0.2, "girl": 0.5}
        self.assertEqual(set(background.person_tags(tags)), {"1girl", "2boys", "6+girls", "solo"})

    def test_empty_scene(self):
        self.assertEqual(background.person_tags({"scenery": 0.9, "sky": 0.8}), {})


class Draw(unittest.TestCase):
    def test_writes_qc_with_horizon(self):
        from PIL import Image
        fake_layers = types.SimpleNamespace(
            BG_NEGATIVE="1girl, person",
            background=lambda scene, seed, size, negative, check: (lambda im: (check(im), im)[1])(Image.new("RGB", size, "gray")),
            horizon=lambda im: 0.4567)
        fake_tagger = types.SimpleNamespace(read=lambda p: {"scenery": 0.9, "1girl": 0.6})
        # パースの測り方は skimage を読む。patch.dict は中で読んだ模組を後で消し、後の試験の numpy を壊したので、ここでは差し替える
        fake_persp = types.SimpleNamespace(measure=lambda im: {"vertical_tilt": 7.0, "horizon_gap": None, "converge": 0.5})
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"layers": fake_layers, "tagger": fake_tagger, "perspective": fake_persp}), \
                mock.patch("bible.load", return_value=WORLD):
            res = background.draw("citadel", "gate", d, count=2, seed=3)
            self.assertEqual(len(res), 2)
            qc = json.loads(Path(res[1]["qc"]).read_text(encoding="utf-8"))
            self.assertTrue(res[1]["qc"].endswith("citadel-gate-1003.qc.json"))
            self.assertFalse(qc["pass"])
            self.assertEqual(qc["person_tags"], {"1girl": 0.6})
            self.assertEqual(qc["horizon"], 0.4567)
            self.assertEqual(qc["size"], [1216, 832])
            self.assertEqual(qc["perspective"]["warnings"], ["縦の線が傾いている（7.0 度）"])
            self.assertEqual(Image.open(res[0]["image"]).size, (1216, 832))


if __name__ == "__main__":
    unittest.main()


class HorizonFromGroundTest(unittest.TestCase):
    """地平線は地面の奥行きの直線が 0 になる行。空の端（建物の上）を地平線と読まない"""

    def test_ground_line_beats_sky_edge(self):
        from unittest import mock
        import numpy as np
        from PIL import Image
        import layers
        h, w = 400, 300
        rows = np.arange(h, dtype=float)[:, None]
        d = np.clip((rows - 280) * 0.02, 0, None) * np.ones((1, w))   # 地平線は 280 行（0.7）
        d[40:280] = 1.0          # 建物（空の端は 40 行で、前の測り方は 0.1 と読む）
        d[:40] = 0.0
        with mock.patch.object(layers, "depth_map", return_value=d):
            self.assertAlmostEqual(layers.horizon(Image.new("RGB", (w, h))), 0.7, places=2)

    def test_no_ground_falls_back(self):
        from unittest import mock
        import numpy as np
        from PIL import Image
        import layers
        d = np.ones((400, 300))
        d[:120] = 0.0            # 空が上 3 割。地面の直線は読めない（平ら）
        with mock.patch.object(layers, "depth_map", return_value=d):
            self.assertAlmostEqual(layers.horizon(Image.new("RGB", (300, 400))), 119 / 400, places=3)
