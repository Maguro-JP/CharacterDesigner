"""LoRA・学習セット・キャラクターシートを、アプリの窓から押して最後まで通す。
LoRA は試験用の小さな SDXL に peft で作った本物の LoRA を、diffusers の load_lora_weights と set_adapters で重ねて描く。
Civitai と Hugging Face は通信せず、取る関数を差し替えて同じ経路を通す（取ってくるだけで、何も上げない）"""
import json
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from chatdraw.tests.test_editing import app  # noqa: E402


def _tiny_sdxl():
    from chatdraw.tests.test_finish_quality import TINY, tiny_ready
    if not tiny_ready():
        return None
    import glob
    from diffusers import StableDiffusionXLPipeline
    local = sorted(glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--" + TINY.replace("/", "--") + "/snapshots/*/")))
    return lambda: StableDiffusionXLPipeline.from_pretrained(local[-1] if local else TINY)


def make_lora(load, out: Path) -> Path:
    """小さな SDXL の UNet に peft の LoRA を付け、diffusers の形で書く（重みは乱数。形が本物と同じなら足りる）"""
    import torch
    from peft import LoraConfig, get_peft_model_state_dict
    from diffusers import StableDiffusionXLPipeline
    pipe = load()
    pipe.unet.add_adapter(LoraConfig(r=4, lora_alpha=4, target_modules=["to_q", "to_k", "to_v", "to_out.0"],
                                     init_lora_weights="gaussian"))
    with torch.no_grad():
        for n, p in pipe.unet.named_parameters():
            if "lora_B" in n:
                p.normal_(0, 0.05)
    out.mkdir(parents=True, exist_ok=True)
    StableDiffusionXLPipeline.save_lora_weights(str(out), unet_lora_layers=get_peft_model_state_dict(pipe.unet),
                                                weight_name="tinystyle.safetensors")
    return out / "tinystyle.safetensors"


class Base(unittest.TestCase):
    def setUp(self):
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        from chatdraw import paths
        self.patches = [mock.patch.object(paths, "data_home", lambda: self.d / "data"),
                        mock.patch.object(paths, "LLM_HOME", self.d / "LLM"),
                        mock.patch.object(paths, "HOME", self.d / "home")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def wait(self, cond, secs=20):
        end = time.time() + secs
        while time.time() < end and not cond():
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertTrue(cond())


class LoraLibTest(Base):
    def test_family_from_keys(self):
        from chatdraw import lora
        self.assertEqual(lora.family_from_keys(["lora_unet_down_blocks_0_attentions_0_proj_in.lora_down.weight"]), "sd15")
        self.assertEqual(lora.family_from_keys(["lora_te2_text_model_encoder_layers_0.lora_up.weight"]), "sdxl")
        self.assertEqual(lora.family_from_keys(["lora_unet_double_blocks_0_img_attn_proj.lora_down.weight"]), "flux1")
        self.assertEqual(lora.family_from_keys(["transformer.single_transformer_blocks.0.attn.to_q.lora_A.weight"]), "flux1")
        self.assertEqual(lora.family_from_keys(["x"]), "")

    def test_parse_source(self):
        from chatdraw import lora
        self.assertEqual(lora.parse_source("https://civitai.com/models/123/name?modelVersionId=456"),
                         ("civitai", {"model": "123", "version": "456"}))
        self.assertEqual(lora.parse_source("123@9"), ("civitai", {"model": "123", "version": "9"}))
        self.assertEqual(lora.parse_source("https://civitai.com/api/download/models/77"), ("civitai", {"model": "", "version": "77"}))
        self.assertEqual(lora.parse_source("owner/repo"), ("hf", {"repo": "owner/repo", "file": ""}))
        self.assertEqual(lora.parse_source("https://huggingface.co/o/r/blob/main/a/b.safetensors"),
                         ("hf", {"repo": "o/r", "file": "a/b.safetensors"}))
        self.assertEqual(lora.parse_source("こんにちは"), ("", {}))

    def test_compatible_and_reason(self):
        from chatdraw import lora
        self.assertEqual(lora.compatible("sdxl", "sdxl"), (True, ""))
        ok, why = lora.compatible("sd15", "sdxl")
        self.assertFalse(ok)
        self.assertIn("SD1.5 用", why)
        self.assertTrue(lora.compatible("", "flux1")[0])

    def test_civitai_fetch_from_dialog(self):
        """管理画面の LoRA の窓に URL を入れて「取る」。系統・きっかけの言葉・見本の画像が .json に残り、一覧に出る"""
        from chatdraw import lora
        from chatdraw.loradialog import LoraDialog
        asked = []

        def get_json(url):
            asked.append(url)
            return {"name": "Ink", "type": "LORA", "modelVersions": [{
                "id": 456, "baseModel": "Illustrious", "trainedWords": ["inkstyle"],
                "images": [{"url": "https://image.civitai.com/a.jpeg"}],
                "files": [{"name": "ink_v1.safetensors", "primary": True, "downloadUrl": "https://civitai.com/api/download/models/456"}]}]}

        def download(url, dst, say):
            asked.append(url)
            dst.write_bytes(b"x")
        dlg = LoraDialog(None, "sd15")
        dlg.fetch("https://civitai.com/models/123", wait=True, get_json=get_json, download=download)
        self.wait(lambda: dlg.list.count() == 1)
        self.assertEqual(asked, ["https://civitai.com/api/v1/models/123", "https://civitai.com/api/download/models/456"])
        p = lora.loras()[0]
        self.assertEqual(p, self.d / "LLM" / "lora" / "ink_v1.safetensors")
        m = lora.meta(p)
        self.assertEqual((m["family"], m["trainedWords"], m["source"]), ("sdxl", ["inkstyle"], "civitai"))
        self.assertIn("SDXL 用", dlg.list.item(0).toolTip())   # 今の模型（SD1.5）に合わない理由
        self.assertEqual(lora.with_trigger("1girl", p), "inkstyle, 1girl")
        dlg.list.setCurrentRow(0)
        dlg.remove_selected()
        self.assertEqual(lora.loras(), [])

    def test_hf_fetch(self):
        from chatdraw import lora
        d = self.d

        class Hub:
            @staticmethod
            def list_repo_files(repo):
                return ["README.md", "pytorch_lora_weights.safetensors"]

            @staticmethod
            def hf_hub_download(repo, file, local_dir):
                p = Path(local_dir) / file
                p.write_bytes(b"x")
                return str(p)
        got = lora.add_from("someone/cute-lora", hub=Hub)
        self.assertTrue(got.is_relative_to(d / "LLM" / "lora"))
        self.assertEqual(lora.loras(), [got])
        self.assertEqual(lora.meta(got)["source"], "hf:someone/cute-lora")


@unittest.skipUnless(_tiny_sdxl(), "試験用の小さな SDXL が取れません")
class LoraDrawTest(Base):
    def test_real_lora_changes_drawing_and_wrong_family_is_skipped(self):
        """本物の LoRA を足して重ねると絵が変わる。系統の合わない模型には重ねず、理由を返す"""
        import numpy as np
        import torch
        from chatdraw import lora
        load = _tiny_sdxl()
        src = make_lora(load, self.d / "made")
        got = lora.add_file(src)
        self.assertEqual(lora.family_of(got), "sdxl")
        pipe = load()
        args = dict(prompt="a cat", num_inference_steps=2, width=64, height=64, output_type="np")
        plain = pipe(generator=torch.Generator().manual_seed(1), **args).images[0]
        state = {}
        self.assertIsNone(lora.apply(pipe, [(str(got), 1.5)], state=state, model_family="sdxl"))
        self.assertEqual(state["loaded"], [str(got)])
        self.assertEqual(pipe.get_active_adapters(), [lora.adapter_name(got)])
        styled = pipe(generator=torch.Generator().manual_seed(1), **args).images[0]
        self.assertGreater(float(np.abs(styled - plain).mean()), 1e-4)
        self.assertIsNone(lora.apply(pipe, [(str(got), 0.0)], state=state, model_family="sdxl"))   # 2 度目は読まず強さだけ
        self.assertIsNone(lora.apply(pipe, "", state=state))
        self.assertEqual(pipe.get_active_adapters(), [])
        note = lora.apply(pipe, str(got), 1.0, state={}, model_family="sd15")
        self.assertIn("重ねられません", note)


class AppLoraRowTest(Base):
    def test_window_lora_pick_disables_wrong_family(self):
        from PySide6.QtCore import Qt
        from chatdraw import lora
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        d = self.d / "LLM" / "lora"
        d.mkdir(parents=True)
        for n, fam in (("xl", "sdxl"), ("old", "sd15")):
            (d / f"{n}.safetensors").write_bytes(b"x")
            lora.write_meta(d / f"{n}.safetensors", {"family": fam, "trainedWords": ["w" + n]})
        w = Window(Studio(FakeWords(), FakePainter(), self.d / "out"))
        try:
            Window._lora_fill(w, "sdxl")
            box = w.lora_pick
            self.assertEqual(box.count(), 3)
            i_xl, i_old = box.findData(str(d / "xl.safetensors")), box.findData(str(d / "old.safetensors"))
            self.assertTrue(box.model().item(i_xl).isEnabled())
            self.assertFalse(box.model().item(i_old).isEnabled())
            self.assertIn("SD1.5 用", box.itemData(i_old, Qt.ToolTipRole))
            box.setCurrentIndex(i_xl)
            w.lora_strength.setValue(150)
            self.assertEqual((w.studio.painter.lora, w.studio.painter.lora_scale), (str(d / "xl.safetensors"), 1.5))
            self.assertTrue(w.lora_strength.isVisibleTo(w))
        finally:
            w.dirty = False
            w.close()


class FakeIPPipe:
    def __call__(self, prompt=None, ip_adapter_image=None):
        return None


class ReferenceFallbackTest(unittest.TestCase):
    def test_no_ip_adapter_draws_without_reference(self):
        from chatdraw.engine import Painter
        p = Painter.__new__(Painter)
        p._ref, p.family, notes = False, "flux1", []
        p._note = notes.append
        args = {}
        Painter._use_reference(p, FakeIPPipe(), Image.new("RGB", (8, 8)), 0.6, args)
        self.assertNotIn("ip_adapter_image", args)
        self.assertIn("参考画像なしで描きます", notes[0])

        class Broken(FakeIPPipe):
            def load_ip_adapter(self, *a, **k):
                raise OSError("no network")
        p.family = "sdxl"
        Painter._use_reference(p, Broken(), Image.new("RGB", (8, 8)), 0.6, args)
        self.assertNotIn("ip_adapter_image", args)
        self.assertIn("読めませんでした", notes[1])


class RefSetTest(Base):
    def test_refset_dialog_use_and_kohya_export(self):
        from chatdraw import refs
        pics = []
        for i, c in enumerate(("red", "blue", "green")):
            p = self.d / f"p{i}.png"
            Image.new("RGB", (40, 60), c).save(p)
            pics.append(str(p))
        (self.d / "p0.json").write_text(json.dumps({"prompt": "red hair"}), encoding="utf-8")
        used = []
        dlg = refs.RefSetDialog(refs.RefSets(), None, on_use=lambda path, d: used.append(path), target="hero", kind="character")
        dlg.name.setText("主人公")
        dlg.words.setText("herostyle")
        dlg.add_images(pics)
        s = refs.RefSets().for_target("character", "hero")
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["images"], pics)
        out = dlg.use()
        self.assertEqual(used, [out])
        self.assertEqual(Image.open(out).size, (512, 512))   # 3 枚を 2×2 に並べた 1 枚
        res = dlg.export()
        folder = Path(res["folder"])
        self.assertEqual(folder.name, "10_主人公")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["001.png", "001.txt", "002.png", "002.txt", "003.png", "003.txt"])
        self.assertEqual((folder / "001.txt").read_text(encoding="utf-8"), "herostyle, red hair")
        self.assertEqual((folder / "002.txt").read_text(encoding="utf-8"), "herostyle")


class SheetTest(Base):
    def test_sheet_from_window_opens_layers_and_writes_psd(self):
        """設定資料の人物から、窓のメニューの「キャラクターシートを作る」で PSD を書き、レイヤーのまま開く"""
        from chatdraw import charadesign, project
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        c = charadesign.save_character("hero", "1girl, red hair", Image.new("RGB", (64, 96), "red"))
        b = charadesign.bible()
        for role, color in (("turn-front", "red"), ("turn-side", "orange"), ("turn-back", "brown"), ("expr-smile", "pink")):
            charadesign._add(b, c["id"], role, Image.new("RGB", (64, 96), color))
        w = Window(Studio(FakeWords(), FakePainter(), self.d / "out"))
        try:
            w.chara_id = c["id"]
            w._fill_chara_menu()
            act = next(a for a in w.chara_menu.actions() if a.text() == "キャラクターシートを作る")
            self.assertTrue(act.isEnabled())
            self.assertTrue(act.toolTip())
            act.trigger()
            out = self.d / "home" / "bible" / "characters" / f"{c['id']}-sheet.psd"
            self.assertTrue(out.is_file())
            self.wait(lambda: [l.name for l in w.canvas.layers][-1:] == ["表情 笑顔"])
            names = [l.name for l in w.canvas.layers]
            self.assertEqual(names, ["背景", "三面図 正面", "三面図 横", "三面図 後ろ", "表情 笑顔"])
            _man, layers = project.read_psd(out)
            self.assertEqual(len(layers), 5)
            self.assertEqual(w.canvas.size_px(), (24 * 4 + 512 * 3, 24 * 3 + 768 + 384))
        finally:
            w.dirty = False
            w.close()


if __name__ == "__main__":
    unittest.main()
