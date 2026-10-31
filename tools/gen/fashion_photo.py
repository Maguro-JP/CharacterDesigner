"""服装の図鑑の人物を、写実の模型で全身のファッション写真のように描く（図鑑の見本は資料なので、アニメ調より実写風が読み取りやすい）。

  CD_FETCH=1 python3 tools/gen/fashion_photo.py <出力> <id>... [--seed 0] [--steps 30]

1 人につき、服の全体が分かる正面と背面の全身と、細部（頭、襟と胸元、腰、裾、足元）の拡大を残す。
細部は正面の全身から切り出して 2 倍にし、弱い描き直し（img2img、強さ 0.3）で布目と縫い目を描き足す。
別に描くと服の形や色が全身と食い違うので、全身の絵を土台にする。

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


VIEWS = {"front": "front view", "back": "back view, from behind, showing the back of the outfit"}
# 細部の範囲（人物の外接枠の高さに対する割合、上端と下端）と、描き足すときの言葉
DETAILS = [("head", 0.00, 0.16, "close-up of the hair and headwear"),
           ("collar", 0.12, 0.38, "close-up of the collar, neckline, buttons and fabric texture"),
           ("waist", 0.34, 0.58, "close-up of the waist, belt, pockets and seams"),
           ("hem", 0.55, 0.85, "close-up of the hem, pleats and fabric folds"),
           ("feet", 0.82, 1.00, "close-up of the shoes and socks")]


def figure_box(im):
    """無地の背景から人物の外接枠を取る（背景は四隅の色に近い画素とする）"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(int)
    bg = np.median(np.concatenate([a[:8, :8], a[:8, -8:], a[-8:, :8], a[-8:, -8:]]).reshape(-1, 3), axis=0)
    ys, xs = np.nonzero(np.abs(a - bg).sum(axis=2) > 40)
    if len(xs) == 0:
        return 0, 0, im.width, im.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def details(img2img, im, pos, neg, seed, out: Path, name: str) -> list[dict]:
    import torch
    from PIL import Image
    x0, y0, x1, y1 = figure_box(im)
    h = y1 - y0
    rows = []
    for part, top, bottom, words in DETAILS:
        t, b = y0 + int(h * top), y0 + int(h * bottom)
        cx, w = (x0 + x1) // 2, max(x1 - x0, int((b - t) * 0.75))
        box = (max(0, cx - w // 2), max(0, t), min(im.width, cx + w // 2), min(im.height, b))
        crop = im.crop(box)
        side = 1024 / max(crop.size)
        crop = crop.resize((int(crop.width * side) // 8 * 8, int(crop.height * side) // 8 * 8), Image.LANCZOS)
        r = img2img(prompt=f"{words}, {pos}", negative_prompt=neg, image=crop, strength=0.3, guidance_scale=5.0,
                    num_inference_steps=30, generator=torch.Generator().manual_seed(seed)).images[0]
        f = f"{name}-detail-{part}.png"
        r.save(out / f)
        rows.append({"part": part, "file": f, "box": list(box), "words": words})
    return rows


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
    from diffusers import StableDiffusionXLImg2ImgPipeline
    img2img = StableDiffusionXLImg2ImgPipeline(**pipe.components)   # 同じ部品を使い回す（模型は 1 回だけ読む）
    for ident in a.ids:
        c = json.loads((FIGURES / f"{ident}.json").read_text(encoding="utf-8"))
        pos, neg = prompt_of(c)
        name = f"{ident}-s{a.seed}"
        rec = {"id": ident, "name": c.get("name", ""), "model": MODEL, "seed": a.seed, "steps": a.steps,
               "prompt": pos, "negative": neg, "views": {}, "details": []}
        for view, words in VIEWS.items():
            pe, ne, pp, np_ = design.encode_xl(pipe, f"{pos}, {words}", neg)
            t = time.time()
            im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                      negative_pooled_prompt_embeds=np_, num_inference_steps=a.steps, guidance_scale=5.0,
                      width=a.width, height=a.height, generator=torch.Generator().manual_seed(a.seed)).images[0]
            im.save(out / f"{name}-{view}.png")
            rec["views"][view] = {"file": f"{name}-{view}.png", "sec": round(time.time() - t)}
            print(f"{name}-{view}.png {time.time() - t:.0f} 秒", flush=True)
            if view == "front":
                t = time.time()
                rec["details"] = details(img2img, im, pos, neg, a.seed, out, name)
                print(f"細部 {len(rec['details'])} 枚 {time.time() - t:.0f} 秒", flush=True)
        (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__":
    main()
