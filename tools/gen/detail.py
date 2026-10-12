"""顔と髪だけを大きく描き直す（顔の描き込み。ADetailer と同じ考え方）。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/detail.py in.png out.png "<描いた言葉>" [--strength 0.4]

全身の絵では顔が 100〜200 画素しか無く、模型は目と髪を細かく描けない（左右の目の大きさや高さがそろわない、
前髪の線が目に混ざる、髪が同じ太さのくさびの並びになる）。そこで顔と頭の周りを切り出し、1024 画素に広げて
目と髪を描く言葉を足して弱く描き直し、縁をぼかして元の絵に戻す。構図と全体の色は元の絵のまま。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FACE_WORDS = ("detailed face, beautiful detailed eyes, symmetrical eyes, same size eyes, detailed iris, "
              "beautiful detailed hair, flowing hair strands, hair clumps, thin hair tips, clean lineart")
FACE_NEGATIVE = "asymmetrical eyes, uneven eyes, mismatched eyes, extra eyelids, hair over eyes, messy lines, blurry, flat hair"
SIDE = 1024


def head_box(src, margin: float = 0.9):
    """顔の部位から頭の周り（髪を含む）の正方形の枠を返す。顔が読めなければ None"""
    import numpy as np
    import edit
    seg = np.asarray(edit.parts(src))
    ys, xs = np.nonzero(seg == edit.LABELS["face"])
    if len(xs) < 50:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 - (y1 - y0) * 0.15  # 髪は顔より上に多いので中心を少し上げる
    half = max(x1 - x0, y1 - y0) * (0.5 + margin)
    h, w = seg.shape
    half = min(half, w / 2, h / 2)
    cx, cy = min(max(cx, half), w - half), min(max(cy, half), h - half)
    return int(cx - half), int(cy - half), int(cx + half), int(cy + half)


def detail(src, out, prompt: str, negative: str = "", strength: float = 0.4, steps: int = 24, seed: int = 0) -> dict:
    import torch
    from PIL import Image, ImageDraw, ImageFilter
    import demi
    import design
    import free_text
    im = Image.open(src).convert("RGB")
    box = head_box(src)
    if box is None:
        if str(out) != str(src):
            im.save(out)
        return {"box": None, "reason": "顔が読めなかった（後ろ向き・小さすぎる）"}
    crop = im.crop(box)
    pos, neg = free_text.full_prompt(f"{prompt}, {FACE_WORDS}", ", ".join(x for x in (negative, FACE_NEGATIVE) if x))
    pipe = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    redone = pipe(image=crop.resize((SIDE, SIDE), Image.LANCZOS), strength=strength, prompt_embeds=pe,
                  negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  num_inference_steps=steps, guidance_scale=6.0, generator=torch.Generator().manual_seed(seed)).images[0]
    redone = redone.resize(crop.size, Image.LANCZOS)
    # 枠の縁で継ぎ目が出ないよう、内側の楕円だけを使い、縁を枠の 1/10 でぼかす
    s = crop.size[0]
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).ellipse((s * 0.06, s * 0.06, s * 0.94, s * 0.94), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(s / 10))
    im.paste(redone, box[:2], mask)
    im.save(out)
    return {"box": box, "side": s}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("prompt")
    ap.add_argument("--negative", default="")
    ap.add_argument("--strength", type=float, default=0.4)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    print(detail(a.src, a.out, a.prompt, a.negative, a.strength, seed=a.seed))


if __name__ == "__main__":
    main()
