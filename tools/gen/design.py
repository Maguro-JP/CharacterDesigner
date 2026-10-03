"""文章からキャラクターデザインを描き、そこから画風を変えた派生（リアル風、ドット絵）を作る。

ベースは画像生成（Stable Diffusion 系、CPU で動かす）。1枚の絵を土台にして、
  draw    文章 → キャラクターデザインの絵（アニメ風）
  restyle 絵 → 同じ構図のまま別の画風（別のモデルで img2img）
  pixel   絵 → ドット絵（背景を抜き、縮小・減色・外側の輪郭・孤立ドットの掃除）
と派生させる。同じ人物のまま画風だけを変えられるよう、派生はいつも絵から作る（文章から作り直さない）。

前準備: sh tools/gen/setup.sh
使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py draw out.png "young swordsman, blue tunic, red scarf" [--seed 7] [--n 4]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py restyle in.png out.png --style real [--strength 0.55]
  python3 tools/gen/design.py pixel in.png out.sprite.json [--height 34] [--colors 32]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))

# 画風ごとのモデル。どれも CreativeML OpenRAIL-M（出典と許諾は docs/references.md）
STYLES = {
    "anime": "Meina/MeinaMix_V11",
    "real": "Lykon/dreamshaper-8",
}
LCM_LORA = "latent-consistency/lcm-lora-sdv1-5"
# 立ち絵の設定資料として描かせる決まり文句。全身・1人・無地の背景にしておくと、派生（ドット絵）で背景を抜ける
PREFIX = "masterpiece, best quality, character design, full body, standing, solo, "
SUFFIX = ", white background, simple background"
NEGATIVE = ("lowres, bad anatomy, bad hands, extra fingers, missing fingers, extra limbs, cropped, "
            "multiple views, text, watermark, signature, blurry")


def _pipe(style, img2img=False):
    import torch
    from diffusers import LCMScheduler, StableDiffusionImg2ImgPipeline, StableDiffusionPipeline
    torch.set_num_threads(os.cpu_count() or 4)
    cls = StableDiffusionImg2ImgPipeline if img2img else StableDiffusionPipeline
    pipe = cls.from_pretrained(STYLES[style], torch_dtype=torch.float32, safety_checker=None)
    # LCM-LoRA: 25 段かかるところを 6 段で描く。CPU で1枚 約1分（512x768、4 コア）
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.load_lora_weights(LCM_LORA)
    pipe.fuse_lora()
    return pipe


def draw(out, prompt, seed, n, style, steps, width, height):
    import torch
    pipe = _pipe(style)
    paths = []
    for i in range(n):
        t = time.time()
        g = torch.Generator().manual_seed(seed + i)
        im = pipe(PREFIX + prompt + SUFFIX, negative_prompt=NEGATIVE, num_inference_steps=steps,
                  guidance_scale=1.5, width=width, height=height, generator=g).images[0]
        p = out if n == 1 else str(Path(out).with_suffix("")) + f"-{seed + i}.png"
        im.save(p)
        meta = {"prompt": prompt, "seed": seed + i, "style": style, "model": STYLES[style], "steps": steps}
        Path(p + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(p)
        print(f"{p}: {time.time() - t:.1f} 秒")
    return paths


def restyle(src, out, style, strength, steps, prompt):
    import torch
    from PIL import Image
    pipe = _pipe(style, img2img=True)
    meta_path = Path(src + ".json")
    if not prompt and meta_path.exists():
        prompt = json.loads(meta_path.read_text(encoding="utf-8"))["prompt"]
    im = Image.open(src).convert("RGB")
    t = time.time()
    # img2img は strength×段数 しか描かない。strength 0.55 で 6 段なら 3 段だけ描き直し、構図と人物を保つ
    res = pipe(PREFIX + (prompt or "") + SUFFIX, image=im, strength=strength,
               num_inference_steps=max(steps, int(round(2 / strength))), guidance_scale=1.5,
               negative_prompt=NEGATIVE, generator=torch.Generator().manual_seed(0)).images[0]
    res.save(out)
    print(f"{out}: {time.time() - t:.1f} 秒")


def cut_background(im, tol=24):
    """四隅から塗りつぶして、無地の背景を透明にする。人物の中の白（目、服）は四隅とつながらないので残る。"""
    from PIL import Image
    im = im.convert("RGBA")
    W, H = im.size
    px = im.load()
    seen = set()
    stack = [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]
    base = [px[x, y][:3] for x, y in stack]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < W and 0 <= y < H):
            continue
        c = px[x, y][:3]
        if min(sum(abs(a - b) for a, b in zip(c, bc)) for bc in base) > tol * 3:
            continue
        seen.add((x, y))
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    for x, y in seen:
        px[x, y] = (0, 0, 0, 0)
    return im


def keep_largest(im):
    """不透明な塊のうち、いちばん大きいもの（本人）だけを残す。設定資料風の絵には小さな別の姿が写り込む。"""
    W, H = im.size
    a = im.getchannel("A").load()
    label = {}
    sizes = []
    for y0 in range(H):
        for x0 in range(W):
            if a[x0, y0] < 128 or (x0, y0) in label:
                continue
            k = len(sizes)
            stack, n = [(x0, y0)], 0
            label[(x0, y0)] = k
            while stack:
                x, y = stack.pop()
                n += 1
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < W and 0 <= ny < H and a[nx, ny] >= 128 and (nx, ny) not in label:
                        label[(nx, ny)] = k
                        stack.append((nx, ny))
            sizes.append(n)
    if not sizes:
        return im
    best = max(range(len(sizes)), key=lambda k: sizes[k])
    px = im.load()
    for (x, y), k in label.items():
        if k != best:
            px[x, y] = (0, 0, 0, 0)
    return im


def pixel(src, out, height, colors):
    """絵からドット絵を作る。描画器の後半と同じ考え方（縮小 → 減色 → 外側に暗い輪郭 → 孤立ドットの掃除）。"""
    from PIL import Image
    sys.path.insert(0, str(ROOT / "tools"))
    import build
    im = keep_largest(cut_background(Image.open(src)))
    bb = im.getchannel("A").getbbox()
    im = im.crop(bb)
    w = max(1, round(im.width * height / im.height))
    # 縮小は箱で平均する。最近傍で拾うと1ドットの線が途切れる
    small = im.resize((w, height), Image.BOX)
    alpha = small.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    rgb = small.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT).convert("RGB")
    W, H = w + 2, height + 2
    grid = [[None] * W for _ in range(H)]
    for y in range(height):
        for x in range(w):
            if alpha.getpixel((x, y)):
                grid[y + 1][x + 1] = "#%02x%02x%02x" % rgb.getpixel((x, y))
    # 外側に1ドットの輪郭。色は隣の色をほぼ黒まで落としたもの（手本の輪郭は純黒でなく内側の暗い色）
    out_grid = [row[:] for row in grid]
    for y in range(H):
        for x in range(W):
            if grid[y][x]:
                continue
            nb = [grid[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                  if 0 <= x + dx < W and 0 <= y + dy < H and grid[y + dy][x + dx]]
            if nb:
                r, g, b = build.hex_to_rgb(nb[0])
                out_grid[y][x] = "#%02x%02x%02x" % (r // 5 + 12, g // 5 + 10, b // 5 + 10)
    build.clean_orphans(out_grid)
    build.reduce_colors(out_grid, colors)
    sp = build.to_sprite({"name": Path(out).stem, "style": "generated", "head_height": None,
                          "body_box": [0, 0, W, H]}, out_grid)
    sp["generated_from"] = f"{Path(src).name}（tools/gen/design.py pixel）"
    Path(out).write_text(json.dumps(sp, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out}: {W}x{H}, {len(sp['palette'])} 色")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("out")
    d.add_argument("prompt")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--n", type=int, default=1)
    d.add_argument("--style", default="anime", choices=list(STYLES))
    d.add_argument("--steps", type=int, default=6)
    d.add_argument("--width", type=int, default=512)
    d.add_argument("--height", type=int, default=768)
    r = sub.add_parser("restyle")
    r.add_argument("src")
    r.add_argument("out")
    r.add_argument("--style", default="real", choices=list(STYLES))
    r.add_argument("--strength", type=float, default=0.55)
    r.add_argument("--steps", type=int, default=6)
    r.add_argument("--prompt", default="")
    p = sub.add_parser("pixel")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--height", type=int, default=34)
    p.add_argument("--colors", type=int, default=32)
    a = ap.parse_args()
    if a.cmd == "draw":
        draw(a.out, a.prompt, a.seed, a.n, a.style, a.steps, a.width, a.height)
    elif a.cmd == "restyle":
        restyle(a.src, a.out, a.style, a.strength, a.steps, a.prompt)
    else:
        pixel(a.src, a.out, a.height, a.colors)


if __name__ == "__main__":
    main()
