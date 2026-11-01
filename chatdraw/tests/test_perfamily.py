"""模型ごとの頼み方を、模型の札（Hugging Face の README）に合わせた所の試験。照らした表は docs/knowledge/model-prompting.md。

- 札の質のタグ（Animagine 4.0 の high score など）を後ろに足し、頭の決まり文句と二重にしない
- 札の描かない物、工程の数、頼みの効き（CFG）、描き方（scheduler）、CLIP skip、渡す引数（Neta Lumina の system_prompt）
- CLIP の長さを超える頼みは、質のタグと頭の決まり文句を外して頼みそのものを残す
- 1 つのファイルの FLUX.1 を読むのに借りる設定を、同意の要らない置き場から取る
模型は読まない（描く部品は偽物に替える）。
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

GEN = types.SimpleNamespace(manual_seed=lambda s: s)
FAKE_TORCH = types.SimpleNamespace(Generator=lambda d: GEN)


class Words:
    """語で区切って数える偽の tokenizer（CLIP の語片の代わり）"""

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [w for w in text.replace(",", " ").split() if w]}


def pipe_with(tokenizer=None):
    def call(prompt=None, negative_prompt=None, num_inference_steps=1, guidance_scale=1.0, true_cfg_scale=1.0, generator=None,
             guidance_rescale=0.0, clip_skip=None, system_prompt=None, max_sequence_length=512, cfg_trunc_ratio=1.0,
             cfg_normalization=False):
        pass
    p = type("P", (), {"__call__": staticmethod(call), "device": "cpu"})()
    if tokenizer is not None:
        p.tokenizer, p.text_encoder = tokenizer, object()
    return p


def args_for(repo, prompt="1girl, waving", pipe=None, file=""):
    from chatdraw.engine import prompt_args
    from chatdraw.models import catalog_images, family
    info = next(m for m in catalog_images() if m.hub == repo and (not file or m.file == file))
    with mock.patch.dict(sys.modules, {"torch": FAKE_TORCH}):
        return info, prompt_args(info, family(info.family), prompt, "", info.steps, info.guidance, 1, pipe or pipe_with())


class CardPromptTest(unittest.TestCase):
    def test_animagine4_uses_card_quality_and_negative(self):
        for file in ("", "animagine-xl-4.0-opt.safetensors"):
            info, a = args_for("cagliostrolab/animagine-xl-4.0", file=file)
            self.assertTrue(a["prompt"].startswith("1girl, waving") and a["prompt"].endswith("masterpiece, high score, great score, absurdres"))
            self.assertTrue(a["negative_prompt"].startswith("lowres, bad anatomy, bad hands"))
            self.assertIn("low score", a["negative_prompt"])
            self.assertEqual((info.steps, info.guidance), (28, 5.0))

    def test_animagine3_prefix_without_double_quality(self):
        for repo, head in (("cagliostrolab/animagine-xl-3.1", "masterpiece, best quality, very aesthetic, absurdres, "),
                           ("cagliostrolab/animagine-xl-3.0", "masterpiece, best quality, ")):
            info, a = args_for(repo)
            self.assertTrue(a["prompt"].startswith(head), repo)
            self.assertEqual(a["prompt"].count("masterpiece"), 1, repo)
            self.assertEqual((info.steps, info.guidance), (28, 7.0), repo)
            self.assertNotIn("(", a["negative_prompt"])   # diffusers は A1111 の重み付けの括弧を読まない

    def test_noobai_eps_uses_card_prefix(self):
        info, a = args_for("Laxhar/noobai-XL-1.1")
        self.assertTrue(a["prompt"].startswith("masterpiece, best quality, newest, absurdres, highres, safe, 1girl"))
        self.assertTrue(a["negative_prompt"].startswith("nsfw, worst quality, old, early"))
        self.assertEqual(a["prompt"].count("masterpiece"), 1)

    def test_no_double_quality_anywhere(self):
        from chatdraw.models import catalog_images
        for m in catalog_images():
            if m.family not in ("sdxl", "sd15"):
                continue
            _info, a = args_for(m.hub, file=m.file)
            self.assertLessEqual(a["prompt"].count("masterpiece"), 1, m.repo)
            self.assertLessEqual(a["prompt"].count("best quality"), 1, m.repo)

    def test_photoreal_and_pony_get_no_anime_quality_tags(self):
        for repo in ("RunDiffusion/Juggernaut-XL-v9", "SG161222/RealVisXL_V5.0", "playgroundai/playground-v2.5-1024px-aesthetic",
                     "stabilityai/stable-diffusion-xl-base-1.0", "Runware/Pony_Diffusion_V6_XL", "Lykon/dreamshaper-xl-lightning"):
            _info, a = args_for(repo)
            self.assertNotIn("masterpiece", a["prompt"], repo)
        _info, a = args_for("Runware/Pony_Diffusion_V6_XL")
        self.assertTrue(a["prompt"].startswith("score_9, score_8_up, score_7_up, "))

    def test_steps_and_cfg_follow_cards(self):
        from chatdraw.models import image_model
        want = {"Lykon/dreamshaper-xl-lightning": (4, 2.0), "playgroundai/playground-v2.5-1024px-aesthetic": (50, 3.0),
                "RunDiffusion/Juggernaut-XL-v9": (35, 5.0), "gsdf/Counterfeit-V2.5": (20, 10.0),
                "VirtualAddressExtension/Neta-Lumina-v1.0-diffusers": (50, 4.0), "black-forest-labs/FLUX.2-klein-4B": (4, 1.0),
                "Tongyi-MAI/Z-Image-Turbo": (9, 0.0), "Qwen/Qwen-Image-2512": (50, 4.0), "lodestones/Chroma1-HD": (40, 3.0),
                "black-forest-labs/FLUX.1-schnell": (4, 0.0), "Laxhar/noobai-XL-Vpred-1.0": (28, 5.0)}
        for repo, sg in want.items():
            m = image_model(repo)
            self.assertEqual((m.steps, m.guidance), sg, repo)

    def test_clip_skip_is_converted_per_family(self):
        info, a = args_for("genai-archive/anything-v5")
        self.assertEqual(info.clip_skip, 2)
        self.assertEqual(a["clip_skip"], 1)   # SD1.5 の diffusers は 1 が A1111 の 2
        info, a = args_for("Runware/Pony_Diffusion_V6_XL")
        self.assertEqual(info.clip_skip, 2)
        self.assertNotIn("clip_skip", a)      # SDXL の diffusers は既定が A1111 の 2

    def test_neta_lumina_gets_card_system_prompt(self):
        _info, a = args_for("VirtualAddressExtension/Neta-Lumina-v1.0-diffusers")
        self.assertEqual(a["system_prompt"], "You are an assistant designed to generate anime images based on textual prompts.")
        self.assertEqual((a["cfg_trunc_ratio"], a["cfg_normalization"]), (0.25, True))

    def test_new_families_use_card_negative(self):
        _info, a = args_for("lodestones/Chroma1-HD", "a girl")
        self.assertTrue(a["negative_prompt"].startswith("low quality, ugly, unfinished"))
        _info, a = args_for("Qwen/Qwen-Image-2512", "a girl")
        self.assertIn("deformed fingers", a["negative_prompt"])
        self.assertIn("true_cfg_scale", a)

    def test_card_words_have_no_cjk(self):
        from chatdraw.engine import has_japanese
        from chatdraw.models import catalog_images
        for m in catalog_images():
            for text in (m.prefix, m.negative, m.quality or "", *(str(v) for _k, v in m.call)):
                self.assertFalse(has_japanese(text), m.repo)


class TokenFitTest(unittest.TestCase):
    def test_fit_tokens_keeps_request(self):
        from chatdraw.engine import fit_tokens
        t = Words()
        self.assertEqual(fit_tokens(t, "a b, ", "c d", "e f"), "a b, c d, e f")
        body = ", ".join(f"w{i}" for i in range(70))
        self.assertEqual(fit_tokens(t, "p1 p2 p3, ", body, "q1 q2 q3 q4 q5 q6"), "p1 p2 p3, " + body)   # 質のタグを先に外す
        body = ", ".join(f"w{i}" for i in range(74))
        self.assertEqual(fit_tokens(t, "p1 p2 p3, ", body, "q1"), body)   # 足りなければ頭の決まり文句も外す
        self.assertEqual(fit_tokens(None, "p, ", "c", "q"), "p, c, q")   # 数えられないときはそのまま

    def test_prompt_args_fits_clip_length(self):
        long = ", ".join(f"tag{i}" for i in range(72))
        _info, a = args_for("Laxhar/noobai-XL-Vpred-1.0", long, pipe_with(Words()))
        self.assertTrue(a["prompt"].endswith("tag71"))   # 頼みの最後の語が切られずに残る
        self.assertNotIn("masterpiece", a["prompt"])


class LoadTest(unittest.TestCase):
    def test_scheduler_follows_card(self):
        from chatdraw.engine import use_scheduler
        from chatdraw.models import image_model
        made = []

        class Sched:
            @classmethod
            def from_config(cls, config):
                made.append((cls.__name__, config))
                s = cls()
                s.config = config
                return s
        fake = types.SimpleNamespace(DPMSolverMultistepScheduler=type("DPMSolverMultistepScheduler", (Sched,), {}),
                                     EulerAncestralDiscreteScheduler=type("EulerAncestralDiscreteScheduler", (Sched,), {}))
        pipe = types.SimpleNamespace(scheduler=types.SimpleNamespace(config={"k": 1}))
        with mock.patch.dict(sys.modules, {"diffusers": fake}):
            self.assertTrue(use_scheduler(pipe, image_model("Lykon/dreamshaper-xl-lightning")))
            self.assertEqual(made[-1], ("DPMSolverMultistepScheduler", {"k": 1}))
            self.assertTrue(use_scheduler(pipe, image_model("genai-archive/anything-v5")))
            self.assertEqual(made[-1][0], "EulerAncestralDiscreteScheduler")
            self.assertFalse(use_scheduler(pipe, image_model("cagliostrolab/animagine-xl-4.0")))
        self.assertEqual(len(made), 2)

    def test_flux1_single_file_borrows_ungated_config(self):
        from chatdraw.models import SINGLE_BASE
        self.assertFalse(SINGLE_BASE["flux1"].startswith("black-forest-labs/"))   # 元の置き場は同意が要り、トークンが無いと読めなかった

    def test_qwen_image_native_size(self):
        from chatdraw.engine import native_size
        self.assertEqual(native_size((1328, 1328), "qwenimage"), (1328, 1328))


if __name__ == "__main__":
    unittest.main()
