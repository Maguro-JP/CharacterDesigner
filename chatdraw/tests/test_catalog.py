"""模型の目録を広げた所: 絞り込みと並べ替え、Hugging Face の名前で足す確かめ（ネットワークは偽物）、目録の行の形"""
import io
import json
import os
import struct
import sys
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw import hfadd, models  # noqa: E402
from chatdraw.hfadd import AddError, probe  # noqa: E402


def header(keys):
    body = json.dumps({k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys}).encode()
    return struct.pack("<Q", len(body)) + body


def fake(api: dict, files: dict | None = None, error: int | None = None):
    """Hugging Face の偽物。api は模型の情報、files はファイルの中身"""
    def get(url, start=None, end=None):
        if error:
            raise urllib.error.HTTPError(url, error, "x", {}, io.BytesIO())
        if "/api/models/" in url:
            return json.dumps(api).encode()
        data = (files or {})[url.rsplit("/", 1)[1]]
        return data if start is None else data[start:end + 1]
    return get


class FilterTest(unittest.TestCase):
    def test_all_by_default_and_each_filter_narrows(self):
        every = models.pick(models.IMAGES)
        self.assertEqual(len(every), len(models.IMAGES))                 # 既定は全部（未確認の物も出す）
        self.assertEqual(every[0].score, max(m.score for m in models.IMAGES))   # 確かめ済みが先
        rec = models.pick(models.IMAGES, "推奨（確かめ済み）")
        self.assertTrue(rec and all(m.score >= models.PASS for m in rec))
        anime = models.pick(models.IMAGES, "アニメ・イラスト")
        self.assertIn("Animagine XL 4.0 Opt", [m.name for m in anime])
        self.assertNotIn("RealVisXL V5.0", [m.name for m in anime])
        self.assertIn("SG161222/RealVisXL_V5.0", [m.repo for m in models.pick(models.IMAGES, "リアル")])
        self.assertTrue(all(m.family in models.NEW for m in models.pick(models.IMAGES, "新しい世代")))
        small = models.pick(models.IMAGES, "すべて", "小さい順")
        self.assertEqual([m.gb for m in small], sorted(m.gb for m in small))


class CatalogTest(unittest.TestCase):
    def test_entries_are_complete_and_unique(self):
        raw = json.loads(Path(models.__file__).with_name("catalog.json").read_text(encoding="utf-8"))
        keys = [models._entry_key(e) for e in raw]
        self.assertEqual(len(keys), len(set(keys)))
        for e in raw:
            self.assertIn(e["format"], list(models.FILES) + ["single"], e["repo"])
            if e["format"] == "single":
                self.assertTrue(e["file"].endswith(".safetensors"), e["repo"])
        opt = models.image_model("cagliostrolab/animagine-xl-4.0/animagine-xl-4.0-opt.safetensors")
        self.assertEqual((opt.hub, opt.file, opt.files), ("cagliostrolab/animagine-xl-4.0", "animagine-xl-4.0-opt.safetensors",
                                                          {"allow_patterns": ["animagine-xl-4.0-opt.safetensors"]}))
        self.assertEqual(models.image_model("cagliostrolab/animagine-xl-4.0").name, "Animagine XL 4.0")   # 同じ置き場の別の版と混ざらない
        added = [e for e in raw if e.get("note", "").startswith("2026-10-31: Hugging Face の API")]
        self.assertGreaterEqual(len(added), 10)
        self.assertTrue(all(e["score"] == 0 and e["commercial"] for e in added))   # 新しく載せた物は未確認で、商用の札がある


class AddByNameTest(unittest.TestCase):
    def test_diffusers_repo(self):
        api = {"siblings": [{"rfilename": "model_index.json", "size": 1}, {"rfilename": "unet/diffusion_pytorch_model.safetensors", "size": 5_000_000_000},
                            {"rfilename": "vae/diffusion_pytorch_model.safetensors", "size": 300_000_000}],
               "cardData": {"license": "openrail++"}}
        e = probe("https://huggingface.co/owner/model", get=fake(api, {"model_index.json": b'{"_class_name": "StableDiffusionXLPipeline"}'}))
        self.assertEqual((e["repo"], e["family"], e["format"], e["gb"], e["score"]), ("owner/model", "sdxl", "full", 5.3, 0))
        self.assertIn("openrail++", e["commercial"])

    def test_single_file_family_from_header(self):
        api = {"siblings": [{"rfilename": "README.md"}, {"rfilename": "m.safetensors", "size": 6_900_000_000}]}
        e = probe("a/b", get=fake(api, {"m.safetensors": header(["conditioner.embedders.1.model.x"])}))
        self.assertEqual((e["format"], e["file"], e["family"], e["gb"]), ("single", "m.safetensors", "sdxl", 6.9))

    def test_refusals_say_why(self):
        cases = [
            ("not a name", fake({}), "持ち主/名前"),
            ("a/b", fake({}, error=401), "同意"),
            ("a/b", fake({}, error=404), "見つかりません"),
            ("a/b", fake({"gated": "auto", "siblings": []}), "同意"),
            ("a/b", fake({"siblings": [{"rfilename": "x.safetensors"}, {"rfilename": "y.safetensors"}]}), "複数"),
            ("a/b", fake({"siblings": [{"rfilename": "model_index.json"}]}, {"model_index.json": b'{"_class_name": "StableDiffusion3Pipeline"}'}),
             "読めません"),
            ("a/b", fake({"siblings": [{"rfilename": "m.safetensors", "size": 1}]}, {"m.safetensors": header(["foo"])}), "見分けられません"),
        ]
        for name, get, word in cases:
            with self.assertRaises(AddError, msg=name) as c:
                probe(name, get=get)
            self.assertIn(word, str(c.exception))

    def test_user_catalog_lives_in_data_dir_and_lists(self):
        api = {"siblings": [{"rfilename": "m.safetensors", "size": 2_100_000_000}]}
        e = probe("me/mine", get=fake(api, {"m.safetensors": header(["cond_stage_model.x"])}))
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            m = models.add_user_entry(e)
            self.assertTrue((Path(d) / "user_models.json").exists())
            self.assertEqual((m.repo, m.family, m.user), ("me/mine/m.safetensors", "sd15", True))
            self.assertIn(m.repo, [x.repo for x in models.pick(models.catalog_images(), "自分で足した")])
            self.assertEqual(models.image_model(m.repo).file, "m.safetensors")
            models.add_user_entry(e)                                          # 同じ物は 2 行にしない
            self.assertEqual(len(models.user_entries()), 1)
        models._USER.clear()


if __name__ == "__main__":
    unittest.main()
