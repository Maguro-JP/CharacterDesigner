"""構図と仕上げを別の模型に任せて、絵全体を 1 枚として描く（切り貼りはしない）。

1. 構図: 文で頼める新しい世代（FLUX.2 klein など）に、同じ頼みを文で描かせる。手足の数や姿勢が崩れにくい
2. 形を取り出す: 1 の絵から奥行き（Depth Anything V2）と細い線（chatdraw.postfx.lineart）を取る。色や塗りは捨てる
3. 仕上げ: SDXL のアニメの模型（Animagine など）に、2 の形を ControlNet（xinsir の Union、奥行きと細い線）で渡し、
   白紙から絵全体を描かせる。形の縛りは工程の前半（control_end まで）だけに効かせ、後半は模型に細部と塗りを任せる

どの段も絵全体を描く。直す所を切り出して貼ることも、1 の絵に上塗りすることもしない。
仕上げの模型は 1 の絵の色を見ないので、塗りと線は SDXL のアニメの模型の質になる。
"""
from __future__ import annotations

import gc
import time

UNION = "xinsir/controlnet-union-sdxl-1.0"
UNION_FILES = dict(allow_patterns=["config_promax.json", "diffusion_pytorch_model_promax.safetensors"])
DEPTH = "depth-anything/Depth-Anything-V2-Small-hf"
DEPTH_MODE, LINE_MODE = 1, 3   # xinsir の Union の種類の番号（1 は奥行き、3 は細い線）


def structure(image):
    """絵から形だけを取り出す。奥行き（白いほど手前）と、黒地に白の細い線"""
    from PIL import ImageOps
    from transformers import pipeline
    from chatdraw.paths import HUB
    est = pipeline("depth-estimation", model=DEPTH, model_kwargs={"cache_dir": str(HUB)})
    depth = est(image.convert("RGB"))["depth"].convert("RGB").resize(image.size)
    del est
    gc.collect()
    from chatdraw.postfx import lineart
    lines = ImageOps.invert(lineart(image).convert("L")).convert("RGB")   # ControlNet の線は黒地に白
    return depth, lines


def render(prompt: str, negative: str, depth, lines, seed: int, model: str, size=(832, 1216), steps: int = 28,
           guidance: float = 5.0, depth_scale: float = 0.5, line_scale: float = 0.4, control_end: float = 0.6,
           on_step=None):
    import torch
    from diffusers import ControlNetUnionModel, StableDiffusionXLControlNetUnionPipeline
    from huggingface_hub import hf_hub_download
    from chatdraw.paths import HUB
    cfg = hf_hub_download(UNION, "config_promax.json", cache_dir=str(HUB))
    weights = hf_hub_download(UNION, "diffusion_pytorch_model_promax.safetensors", cache_dir=str(HUB))
    import os
    import shutil
    import tempfile
    # promax の重みは別の名前で置かれているので、読める形のフォルダーに並べ直す（ファイルは写さず、リンクか複写）
    d = tempfile.mkdtemp()
    shutil.copy(cfg, os.path.join(d, "config.json"))
    try:
        os.symlink(weights, os.path.join(d, "diffusion_pytorch_model.safetensors"))
    except OSError:
        shutil.copy(weights, os.path.join(d, "diffusion_pytorch_model.safetensors"))
    dtype = torch.float16 if torch.cuda.is_available() else torch.bfloat16
    cn = ControlNetUnionModel.from_pretrained(d, torch_dtype=dtype)
    pipe = StableDiffusionXLControlNetUnionPipeline.from_pretrained(model, controlnet=cn, torch_dtype=dtype, cache_dir=str(HUB))
    if torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
    w, h = size

    def step(p, i, _t, kw):
        if on_step:
            on_step(i + 1, steps)
        return kw
    out = pipe(prompt=prompt, negative_prompt=negative, width=w, height=h, num_inference_steps=steps, guidance_scale=guidance,
               control_image=[depth.resize(size), lines.resize(size)], control_mode=[DEPTH_MODE, LINE_MODE],
               controlnet_conditioning_scale=[depth_scale, line_scale], control_guidance_end=control_end,
               generator=torch.Generator("cpu").manual_seed(seed), callback_on_step_end=step).images[0]
    return out


def draw(sentence: str, tags: str, seed: int, compose_model: str, render_model: str, size=(832, 1216), say=print, keep=None):
    """sentence は構図の模型に渡す文、tags は仕上げの模型に渡すタグ。keep に置き場を渡すと途中の絵も残す"""
    from chatdraw.engine import Painter
    from chatdraw.models import image_model
    t = time.time()
    cm = image_model(compose_model)
    composer = Painter(compose_model, steps=cm.steps, size=size, guidance=cm.guidance)
    composition = composer.paint(sentence, seed, on_step=lambda i, n: say(f"構図 {i}/{n}"))
    del composer
    gc.collect()
    say(f"構図: {time.time() - t:.0f} 秒")
    t = time.time()
    depth, lines = structure(composition)
    say(f"形を取り出す: {time.time() - t:.0f} 秒")
    t = time.time()
    rm = image_model(render_model)
    out = render(f"{tags}, masterpiece, best quality", "lowres, worst quality, low quality, bad anatomy, bad hands",
                 depth, lines, seed, render_model, size=size, steps=rm.steps, guidance=rm.guidance,
                 on_step=lambda i, n: say(f"仕上げ {i}/{n}"))
    say(f"仕上げ: {time.time() - t:.0f} 秒")
    if keep is not None:
        composition.save(keep / "1-composition.png")
        depth.save(keep / "2-depth.png")
        lines.save(keep / "2-lines.png")
    return out
