"""描いた絵を高い解像度に描き直す（hires fix）。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/hires.py in.png out.png "<描いた言葉>" [--scale 1.5] [--strength 0.35]

SDXL は約 100 万画素（832x1216）で描くのが得意で、それより大きく描かせると人物が増えたり形が崩れたりする。
そこで、得意な大きさで構図を決めてから、絵を引き伸ばし、同じ言葉で弱く描き直して線と細部を足す。
強さ（strength）が低いほど元の絵を保ち、高いほど細部が増えるが形が変わる。0.3〜0.4 を既定にする。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def upscale(src, out, prompt: str, negative: str = "", scale: float = 1.5, strength: float = 0.35,
            steps: int = 24, seed: int = 0) -> tuple[int, int]:
    """src を scale 倍に引き伸ばして描き直し、out に置く。返すのは出来た大きさ"""
    import torch
    from PIL import Image
    import demi
    import design
    import free_text
    im = Image.open(src).convert("RGB")
    # SDXL の潜在は 8 画素単位。8 の倍数にそろえないと端が切れる
    w, h = (int(im.width * scale) // 8 * 8, int(im.height * scale) // 8 * 8)
    big = im.resize((w, h), Image.LANCZOS)
    pos, neg = free_text.full_prompt(prompt, negative)
    pipe = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    res = pipe(image=big, strength=strength, prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
               negative_pooled_prompt_embeds=np_, num_inference_steps=steps, guidance_scale=6.0,
               generator=torch.Generator().manual_seed(seed)).images[0]
    res.save(out)
    return res.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("prompt")
    ap.add_argument("--negative", default="")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--strength", type=float, default=0.35)
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    print(upscale(a.src, a.out, a.prompt, a.negative, a.scale, a.strength, a.steps, a.seed))


if __name__ == "__main__":
    main()
