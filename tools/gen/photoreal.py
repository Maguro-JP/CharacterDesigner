"""アニメ調の絵を写真級に描き直す（後の加工の 1 つ、リアル風）。

  CD_FETCH=1 PYTHONPATH=.cache/gen/lib python3 tools/gen/photoreal.py in.png out/ [--strength 0.7] [--dry-run]

重いので Actions で回す（.github/workflows/photoreal.yml、頼みは config/photoreal-request.json）。

経路: 帯を消す → Realistic Vision V6 B1 に ControlNet の tile と lineart を 2 つ掛けて img2img →
1.5 倍に拡大して tile だけで弱く（strength 0.3）重ねたタイルごとに描き直す。

- 帯: 元の絵に服（部位 7）の暗い大きな塊があると、模型はそれを黒い帯として描き写した。描く前に背景（部位 0）だけから
  拡散で埋める。埋める元に肌を入れると脚の肌色がにじんだ。部位は絵の隣の .parts.png を使い回す（2 度計算しない）
- lineart: tile だけでは髪型と模様が崩れた（縮れた茶髪になった）。輪郭を lineart で押さえると髪型が残った
- 2 段目をタイルにするのは、1152x1728 を一度に描くと注意の計算が CPU のメモリに乗らないため
- 模型は 1 回だけ読み、2 段目は 1 段目の部品を使い回す。CPU 4 コアで 1 段目 約 21 分、2 段目 約 24 分、最大 RSS 約 10.7GB
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401  模型を勝手に取りに行かない設定を先に効かせる

CHECKPOINT = ("SG161222/Realistic_Vision_V6.0_B1_noVAE", "Realistic_Vision_V6.0_NV_B1_fp16.safetensors")
CONFIG = "stable-diffusion-v1-5/stable-diffusion-v1-5"   # 単体ファイルの形の設定だけを読む（SD1.5 と同じ形）
VAE = "stabilityai/sd-vae-ft-mse"
TILE = "lllyasviel/control_v11f1e_sd15_tile"
LINEART = "lllyasviel/control_v11p_sd15_lineart"
PROMPT = ("RAW photo, a 27 year old woman, plain white bikini, standing, hand on hip, grey studio backdrop, "
          "natural skin texture, soft studio lighting, 85mm, sharp focus, high detail")
NEGATIVE = ("anime, cartoon, illustration, painting, 3d, cgi, plastic skin, airbrushed, lowres, bad anatomy, "
            "bad hands, extra fingers, child, teen")
BACKGROUND, CLOTH = 0, 7


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


class Log:
    def __init__(self, path: Path):
        self.path, self.d = path, {}

    def __call__(self, k, v):
        self.d[k] = v
        self.path.write_text(json.dumps(self.d, indent=1, ensure_ascii=False))
        print(k, v, flush=True)


def load_source(src: Path, width: int, height: int):
    """絵と部位を同じ大きさにそろえる（部位は番号なので最近傍で）"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    parts = Image.open(str(src) + ".parts.png")
    if im.size != (width, height):
        im = im.resize((width, height), Image.LANCZOS)
    if parts.size != (width, height):
        parts = parts.resize((width, height), Image.NEAREST)
    return im, parts


def clean_band(im, parts, dark: int = 80, grow: int = 6):
    """服の暗い最大の塊（帯）を背景から埋める。返すのは (絵, 埋めた画素数)"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(im).astype(np.float32)
    p = np.asarray(parts)
    m = ndimage.binary_opening((p == CLOTH) & (a.max(2) < dark), iterations=2)
    lab, n = ndimage.label(m)
    if n == 0:
        return im, 0
    sz = ndimage.sum(m, lab, range(1, n + 1))
    m = lab == (1 + int(np.argmax(sz)))          # 一番大きい塊だけ（髪や水着の影を巻き込まない）
    ys, xs = np.nonzero(m)
    box = np.zeros_like(m)
    box[max(ys.min() - 15, 0):ys.max() + 25, max(xs.min() - 15, 0):xs.max() + 15] = True
    m |= box & np.isin(p, (BACKGROUND, CLOTH)) & (a.max(2) < dark + 10)   # 帯の端（手の下、裾の先）
    m = ndimage.binary_dilation(m, iterations=grow) & np.isin(p, (BACKGROUND, CLOTH))
    known = ~m & (p == BACKGROUND)
    fill = np.where(known[..., None], a, 0)
    w = known.astype(np.float32)
    k = np.ones((5, 5), np.float32)
    rem = m.copy()
    while rem.any():
        s = np.stack([ndimage.convolve(fill[..., c] * w, k, mode="nearest") for c in range(3)], -1)
        ws = ndimage.convolve(w, k, mode="nearest")
        new = rem & (ws > 0)
        if not new.any():
            m &= ~rem                             # 背景に届かない所は触らない
            break
        fill[new] = s[new] / ws[new][:, None]
        w[new] = 1
        rem &= ~new
    out = a.copy()
    out[m] = fill[m]
    bl = np.stack([ndimage.gaussian_filter(out[..., c], 3) for c in range(3)], -1)
    out[m] = bl[m]                                # 埋めた所の縞を消す
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), int(m.sum())


def lineart(im):
    """暗い線と縁の強さから lineart の条件の絵を作る（模型を読まずに済ませる）"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    g = np.asarray(im.convert("L")).astype(np.float32)
    d = np.clip(ndimage.gaussian_filter(g, 2.0) - g, 0, None) * 6
    g1 = ndimage.gaussian_filter(g, 1)
    s = np.hypot(ndimage.sobel(g1, 0), ndimage.sobel(g1, 1)) / 4
    return Image.fromarray(np.clip(np.maximum(d, s), 0, 255).astype(np.uint8)).convert("RGB")


def tiles(length: int, side: int, overlap: int) -> list[int]:
    if length <= side:
        return [0]
    return list(range(0, length - side, side - overlap)) + [length - side]


def load(log):
    """tile の pipe と、tile＋lineart の pipe（部品は共有）を 1 回だけ読む"""
    import torch
    from diffusers import (AutoencoderKL, ControlNetModel, DPMSolverMultistepScheduler,
                           StableDiffusionControlNetImg2ImgPipeline)
    from huggingface_hub import hf_hub_download
    t = time.time()
    vae = AutoencoderKL.from_pretrained(VAE)
    tile = ControlNetModel.from_pretrained(TILE)
    la = ControlNetModel.from_pretrained(LINEART, variant="fp16", use_safetensors=True, torch_dtype=torch.float32)
    ck = hf_hub_download(*CHECKPOINT)
    pipe = StableDiffusionControlNetImg2ImgPipeline.from_single_file(
        ck, controlnet=tile, vae=vae, config=CONFIG, torch_dtype=torch.float32,
        safety_checker=None, feature_extractor=None, requires_safety_checker=False)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
    pipe.set_progress_bar_config(disable=True)
    c = dict(pipe.components)
    c.pop("controlnet")
    multi = StableDiffusionControlNetImg2ImgPipeline(**c, controlnet=[tile, la])
    multi.set_progress_bar_config(disable=True)
    log("load_s", round(time.time() - t, 1))
    return pipe, multi


def stage1(multi, clean, li, a, log):
    import torch
    t = time.time()
    r = multi(a.prompt, negative_prompt=a.negative, image=clean, control_image=[clean, li], strength=a.strength,
              controlnet_conditioning_scale=[a.tile_scale, a.lineart_scale], num_inference_steps=a.steps,
              guidance_scale=a.guidance, generator=torch.Generator().manual_seed(a.seed),
              width=clean.width, height=clean.height).images[0]
    log("stage1_s", round(time.time() - t, 1))
    log("stage1_rss_gb", round(rss_gb(), 2))
    return r


def stage2(pipe, src, a, log):
    """拡大してから tile をもう一度。重ねたタイルで描いて縁をなだらかに混ぜる"""
    import numpy as np
    import torch
    from PIL import Image
    t = time.time()
    T, ov = a.tile, a.overlap
    W, H = int(src.width * a.scale) // 8 * 8, int(src.height * a.scale) // 8 * 8
    big = src.resize((W, H), Image.LANCZOS)
    acc = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    xs, ys = tiles(W, T, ov), tiles(H, T, ov)
    ramp = np.minimum(np.minimum(np.arange(T), np.arange(T)[::-1]) / ov, 1) + 1e-3
    wt = (ramp[None, :] * ramp[:, None])[..., None]
    n = 0
    for y in ys:
        for x in xs:
            c = big.crop((x, y, x + T, y + T))
            r = pipe(a.prompt, negative_prompt=a.negative, image=c, control_image=c, strength=a.strength2,
                     controlnet_conditioning_scale=a.tile2_scale, num_inference_steps=a.steps,
                     guidance_scale=a.guidance, generator=torch.Generator().manual_seed(a.seed + n),
                     width=T, height=T).images[0]
            acc[y:y + T, x:x + T] += np.asarray(r).astype(np.float32) * wt
            wsum[y:y + T, x:x + T] += wt
            n += 1
            print("tile", n, len(xs) * len(ys), round(time.time() - t), flush=True)
    log("stage2_tiles", n)
    log("stage2_s", round(time.time() - t, 1))
    log("stage2_rss_gb", round(rss_gb(), 2))
    return Image.fromarray(np.clip(acc / wsum, 0, 255).astype(np.uint8))


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path, help="入力の絵（隣に <絵>.parts.png が要る）")
    ap.add_argument("out", type=Path, help="書き出す場所")
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--height", type=int, default=1152)
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--negative", default=NEGATIVE)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--guidance", type=float, default=6.0)
    ap.add_argument("--strength", type=float, default=0.7, help="1 段目の強さ")
    ap.add_argument("--tile-scale", type=float, default=0.6)
    ap.add_argument("--lineart-scale", type=float, default=0.8)
    ap.add_argument("--scale", type=float, default=1.5, help="2 段目の拡大率（0 なら 2 段目をしない）")
    ap.add_argument("--strength2", type=float, default=0.3)
    ap.add_argument("--tile2-scale", type=float, default=0.8)
    ap.add_argument("--tile", type=int, default=768)
    ap.add_argument("--overlap", type=int, default=128)
    ap.add_argument("--dry-run", action="store_true", help="模型を読まず、帯消しと lineart だけ書き出す")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse(argv if argv is not None else sys.argv[1:])
    if not Path(str(a.src) + ".parts.png").exists():
        print(f"部位の絵がありません: {a.src}.parts.png", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    log = Log(a.out / "times.json")
    log("args", {k: str(v) for k, v in vars(a).items()})
    stem = a.src.name.split(".")[0]
    t = time.time()
    im, parts = load_source(a.src, a.width, a.height)
    clean, px = clean_band(im, parts)
    li = lineart(clean)
    clean.save(a.out / f"{stem}-0-clean.png")
    li.save(a.out / f"{stem}-0-lineart.png")
    log("band_px", px)
    log("clean_s", round(time.time() - t, 2))
    if a.dry_run:
        return 0
    pipe, multi = load(log)
    r1 = stage1(multi, clean, li, a, log)
    r1.save(a.out / f"{stem}-1-photoreal-st{a.strength}-s{a.seed}.png")
    del multi
    if a.scale > 0:
        r2 = stage2(pipe, r1, a, log)
        r2.save(a.out / f"{stem}-2-tile-x{a.scale}-s{a.seed}.png")
    log("total_s", round(time.time() - t, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
