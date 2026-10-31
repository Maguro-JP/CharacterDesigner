"""服装の図鑑の人物を、写実の模型で全身のファッション写真のように描く（図鑑の見本は資料なので、アニメ調より実写風が読み取りやすい）。

  CD_FETCH=1 python3 tools/gen/fashion_photo.py <出力> <id>... [--seed 0] [--steps 30]

人物の設定は casts/fashion-zukan/characters/<id>.json の look と outfit を使う。アニメ絵の言葉（1girl、solo）は外し、
写真の言葉（スタジオ、無地の背景、全身）を足す。重いので Actions で回す（.github/workflows/fashion-photo.yml）。
描いた絵の隣に、使った言葉と種を <id>-s<種>.json で残す（再現のため）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401  模型を勝手に取りに行かない設定を先に効かせる

ROOT = Path(__file__).resolve().parents[2]
FIGURES = ROOT / "casts" / "fashion-zukan" / "characters"
MODEL = "SG161222/RealVisXL_V5.0"   # openrail++（使い方の制限あり、絵の商用利用は可。docs/references.md）
# アニメ絵のタグで、写真の言葉にすると人数や画風を引っ張るもの
ANIME_WORDS = re.compile(r"\b(1girl|1boy|solo|male focus|anime style|cel shading|clean lineart)\b,?\s*", re.I)
PHOTO = ("full body fashion photograph, standing, whole body from head to shoes in frame, facing the camera, "
         "plain light grey studio background, soft even studio lighting, 85mm lens, sharp focus, "
         "natural skin texture, photorealistic, high detail fabric texture")
NEGATIVE = ("anime, illustration, drawing, cartoon, painting, 3d render, cgi, doll, cropped, out of frame, cut off feet, "
            "extra fingers, missing fingers, fused fingers, deformed hands, extra arms, extra legs, bad anatomy, "
            "two people, text, logo, brand logo, watermark, signature, nsfw, cleavage, see-through")


def prompt_of(c: dict) -> tuple[str, str]:
    look = ANIME_WORDS.sub("", c["look"]).strip(" ,")
    pos = f"{PHOTO}, {look}, wearing {c['outfit']}"
    neg = ", ".join(x for x in (NEGATIVE, c.get("negative", "")) if x)
    return pos, neg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    a = ap.parse_args()
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    pipe = StableDiffusionXLPipeline.from_pretrained(MODEL, torch_dtype=torch.float32)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
    torch.set_num_threads(torch.get_num_threads())
    print(f"模型を読んだ {time.time() - t:.0f} 秒", flush=True)
    for ident in a.ids:
        c = json.loads((FIGURES / f"{ident}.json").read_text(encoding="utf-8"))
        pos, neg = prompt_of(c)
        pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
        t = time.time()
        im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  num_inference_steps=a.steps, guidance_scale=5.0, width=a.width, height=a.height,
                  generator=torch.Generator().manual_seed(a.seed)).images[0]
        name = f"{ident}-s{a.seed}"
        im.save(out / f"{name}.png")
        (out / f"{name}.json").write_text(json.dumps({"id": ident, "model": MODEL, "seed": a.seed, "steps": a.steps,
                                                      "prompt": pos, "negative": neg, "sec": round(time.time() - t)},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}.png {time.time() - t:.0f} 秒", flush=True)


if __name__ == "__main__":
    main()
