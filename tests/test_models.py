"""絵を描く模型の一覧と切り替え（tools/gen/models.py）の試験。模型の本体は読まず、先頭だけの偽の .safetensors を作る。"""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import models  # noqa: E402


def fake_safetensors(path: Path, keys):
    head = json.dumps({k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys}).encode()
    path.write_bytes(struct.pack("<Q", len(head)) + head + b"\0\0")


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [mock.patch.object(models, "MODELS_DIR", d / "models"),
                        mock.patch.object(models, "CONFIG", d / "models.json")]
        for p in self.patches:
            p.start()
        (d / "models").mkdir()
        fake_safetensors(d / "models" / "my-xl.safetensors",
                         ["conditioner.embedders.1.model.ln_final.weight", "model.diffusion_model.out.0.weight"])
        fake_safetensors(d / "models" / "old-15.safetensors", ["cond_stage_model.transformer.x", "model.diffusion_model.y"])
        (d / "models" / "danger.ckpt").write_bytes(b"x")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_dropped_file_appears_in_list(self):
        self.assertEqual(sorted(models.local_models()), ["my-xl", "old-15"])

    def test_sdxl_file_is_usable(self):
        c = models.check("my-xl")
        self.assertTrue(c["usable"], c)
        self.assertEqual(c["family"], "sdxl")

    def test_sd15_is_refused_with_reason(self):
        c = models.check("old-15")
        self.assertFalse(c["usable"])
        self.assertIn("SDXL", c["reason"])

    def test_ckpt_is_refused(self):
        c = models.check(str(Path(self.tmp.name) / "models" / "danger.ckpt"))
        self.assertFalse(c["usable"])
        self.assertIn(".safetensors", c["reason"])

    def test_use_assigns_style_and_resolves(self):
        models.use("anime", "my-xl")
        self.assertEqual(models.for_style("anime"), str(Path(self.tmp.name) / "models" / "my-xl.safetensors"))

    def test_unknown_style_says_how_to_assign(self):
        with self.assertRaises(KeyError) as e:
            models.for_style("real")
        self.assertIn("use real", str(e.exception))

    def test_env_overrides_for_one_run(self):
        with mock.patch.dict("os.environ", {"CD_DRAW_MODEL": "my-xl"}):
            self.assertTrue(models.for_style("anime").endswith("my-xl.safetensors"))
