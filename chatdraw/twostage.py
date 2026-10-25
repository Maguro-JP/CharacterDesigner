"""構図と仕上げを別の模型に任せて、絵全体を 1 枚として描く（切り貼りはしない）。

1. 構図: 文で頼める新しい世代（FLUX.2 klein など）に、同じ頼みを文で描かせる。手足の数や姿勢が崩れにくい
2. 形を取り出す: 1 の絵から、骨組み（openpose、体・手・顔）、奥行き（Depth Anything V2）、細い線を取る。色や塗りは捨てる
3. 仕上げ: SDXL のアニメの模型（Animagine など）に、2 の形を ControlNet（xinsir の Union）で渡し、白紙から絵全体を描かせる

設計の決まり（docs/knowledge/drawing-algorithm.md の「設計の見直し」）:
- 段ごとに絵をファイルに残し、次の段はファイルから始める。どの段から描き直しても、前の段をやり直さない
- 仕上げは、1 つの構図から縛りの組み合わせ（variants）を何通りも描く。模型は 1 回だけ読む。比べるのは縛りの違いだけにする
- 既定の縛りは骨組みと奥行き。細い線は構図の模型の指や塗りの癖までなぞるので、比べの 1 通りとしてだけ使う

どの段も絵全体を描く。直す所を切り出して貼ることも、1 の絵に上塗りすることもしない。
"""
from __future__ import annotations

import gc
import json
import time
from pathlib import Path

UNION = "xinsir/controlnet-union-sdxl-1.0"
DEPTH = "depth-anything/Depth-Anything-V2-Small-hf"
POSE = "lllyasviel/Annotators"
# xinsir の Union の種類の番号（README の表）: 0 骨組み、1 奥行き、2 太い線、3 細い線
MODES = {"pose": 0, "depth": 1, "lines": 3}
# 比べの既定。名前はファイル名に入る
VARIANTS = [
    {"name": "pose-depth", "pose": 0.7, "depth": 0.4, "end": 0.7},
    {"name": "depth-lines", "depth": 0.5, "lines": 0.4, "end": 0.6},
]


def structure(image, keep: Path):
    """絵から形だけを取り出して keep に置く。骨組み（黒地に色の棒）、奥行き（白いほど手前）、細い線（黒地に白）"""
    from PIL import ImageOps
    from chatdraw.paths import HUB
    out = {}
    t = time.time()
    from controlnet_aux import OpenposeDetector
    det = OpenposeDetector.from_pretrained(POSE, cache_dir=str(HUB))
    out["pose"] = det(image, detect_resolution=1024, image_resolution=max(image.size), include_body=True, include_hand=True,
                      include_face=True).resize(image.size)
    del det
    from transformers import pipeline
    est = pipeline("depth-estimation", model=DEPTH, model_kwargs={"cache_dir": str(HUB)})
    out["depth"] = est(image)["depth"].convert("RGB").resize(image.size)
    del est
    gc.collect()
    from chatdraw.postfx import lineart
    out["lines"] = ImageOps.invert(lineart(image).convert("L")).convert("RGB")
    for k, im in out.items():
        im.save(keep / f"2-{k}.png")
    print(f"形を取り出す: {time.time() - t:.0f} 秒", flush=True)
    return out


def load_render(model: str):
    """仕上げの模型と Union を 1 回だけ読む"""
    import os
    import shutil
    import tempfile
    import torch
    from diffusers import ControlNetUnionModel, StableDiffusionXLControlNetUnionPipeline
    from huggingface_hub import hf_hub_download
    from chatdraw.paths import HUB
    cfg = hf_hub_download(UNION, "config_promax.json", cache_dir=str(HUB))
    weights = hf_hub_download(UNION, "diffusion_pytorch_model_promax.safetensors", cache_dir=str(HUB))
    # promax の重みは別の名前で置かれているので、読める名前のフォルダーに並べ直す（重みはリンクで、写さない）
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
    return pipe


def render(pipe, prompt: str, negative: str, shapes: dict, variant: dict, seed: int, size, steps: int, guidance: float, on_step=None):
    """variant に名前のある縛りだけを渡して、白紙から描く。縛りは工程の前半（end の割合まで）だけに効かせる"""
    import torch
    kinds = [k for k in MODES if k in variant]
    w, h = size

    def step(p, i, _t, kw):
        if on_step:
            on_step(i + 1, steps)
        return kw
    return pipe(prompt=prompt, negative_prompt=negative, width=w, height=h, num_inference_steps=steps, guidance_scale=guidance,
                control_image=[shapes[k].resize(size) for k in kinds], control_mode=[MODES[k] for k in kinds],
                controlnet_conditioning_scale=[float(variant[k]) for k in kinds], control_guidance_end=float(variant.get("end", 0.6)),
                generator=torch.Generator("cpu").manual_seed(seed), callback_on_step_end=step).images[0]


def compose(sentence: str, seed: int, compose_model: str, size, path):
    """構図の模型（FLUX.2 klein など）で、文から絵全体を描く。
    頼みを読む部品（Qwen3、約 8GB）は最初に 1 回だけ使い、読み終えたら外してから描く。
    外さないと 16GB の機械でメモリが足りず、1 工程に約 23 分、絵にする所で 2 時間以上止まった"""
    import torch
    from chatdraw.engine import Painter, native_size
    from chatdraw.models import image_model
    cm = image_model(compose_model)
    painter = Painter(compose_model, steps=cm.steps, size=size, guidance=cm.guidance)
    pipe = painter.load()
    if not hasattr(pipe, "encode_prompt") or getattr(pipe, "text_encoder", None) is None:
        painter.paint(sentence, seed, on_step=lambda i, n: print(f"構図 {i}/{n}", flush=True)).save(path)
        return
    t = time.time()
    with torch.no_grad():
        embeds = pipe.encode_prompt(sentence, device="cpu")
    embeds = embeds[0] if isinstance(embeds, tuple) else embeds
    pipe.text_encoder = None
    gc.collect()
    print(f"頼みを読む: {time.time() - t:.0f} 秒", flush=True)
    w, h = native_size(size, cm.family)

    def step(p, i, _t, kw):
        print(f"構図 {i + 1}/{cm.steps} {time.time() - t:.0f} 秒", flush=True)
        return kw
    im = pipe(prompt_embeds=embeds, width=w, height=h, num_inference_steps=cm.steps, guidance_scale=cm.guidance,
              generator=torch.Generator("cpu").manual_seed(seed), callback_on_step_end=step).images[0]
    im.save(path)
    print(f"構図を保存: {time.time() - t:.0f} 秒", flush=True)


def finish(tags: str, seed: int, render_model: str, size, composition_path, keep: Path, variants=None):
    """1 つの構図から、縛りの組み合わせごとに 1 枚ずつ描く。描けた絵から順にファイルに残す（途中で打ち切られても残る）"""
    from PIL import Image
    from chatdraw.models import image_model
    keep = Path(keep)
    shapes = structure(Image.open(composition_path).convert("RGB"), keep)
    rm = image_model(render_model)
    t = time.time()
    pipe = load_render(render_model)
    print(f"仕上げの模型を読む: {time.time() - t:.0f} 秒", flush=True)
    for v in variants or VARIANTS:
        t = time.time()
        out = render(pipe, f"{tags}, masterpiece, best quality", "lowres, worst quality, low quality, bad anatomy, bad hands",
                     shapes, v, seed, tuple(size), rm.steps, rm.guidance,
                     on_step=lambda i, n, name=v["name"]: print(f"仕上げ {name} {i}/{n} {time.time() - t:.0f} 秒", flush=True))
        out.save(keep / f"3-{v['name']}-s{seed}.png")
        print(f"仕上げ {v['name']}: {time.time() - t:.0f} 秒", flush=True)


def draw(sentence: str, tags: str, seed: int, compose_model: str, render_model: str, size=(832, 1216), say=print, keep=None,
         composition=None, variants=None, stage="all"):
    """sentence は構図の模型に渡す文、tags は仕上げの模型に渡すタグ。
    composition に前に描いた構図の絵を渡すと、構図の段をとばす。stage は "compose"、"finish"、"all"。
    段ごとに別の処理（プロセス）で動かし、段の間でメモリを OS に返す（16GB の機械で、FLUX のあとに SDXL を読むと
    1 つの処理の中では解放しきれなかった）"""
    import shutil
    import subprocess
    import sys
    keep = Path(keep or ".")
    keep.mkdir(parents=True, exist_ok=True)
    comp = keep / "1-composition.png"
    w, h = size
    if composition:
        if Path(composition).resolve() != comp.resolve():
            shutil.copy(composition, comp)
    elif stage in ("all", "compose"):
        t = time.time()
        subprocess.run([sys.executable, "-u", "-m", "chatdraw.twostage", "compose", sentence, str(seed), compose_model, str(w), str(h),
                        str(comp)], check=True)
        say(f"構図: {time.time() - t:.0f} 秒")
    if stage == "compose":
        return None
    if not comp.exists():
        raise FileNotFoundError(f"構図の絵がありません: {comp}")
    t = time.time()
    subprocess.run([sys.executable, "-u", "-m", "chatdraw.twostage", "finish", tags, str(seed), render_model, str(w), str(h), str(comp),
                    str(keep), json.dumps(variants or VARIANTS)], check=True)
    say(f"形と仕上げ: {time.time() - t:.0f} 秒")
    return sorted(keep.glob(f"3-*-s{seed}.png"))


if __name__ == "__main__":
    import sys
    cmd, text, seed, model, w, h = sys.argv[1:7]
    if cmd == "compose":
        compose(text, int(seed), model, (int(w), int(h)), sys.argv[7])
    else:
        finish(text, int(seed), model, (int(w), int(h)), sys.argv[7], Path(sys.argv[8]), json.loads(sys.argv[9]))
