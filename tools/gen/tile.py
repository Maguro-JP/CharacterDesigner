"""拡大した絵を区切りごとに描き直し、描き込みを大きさに見合う所まで足す（タイルの描き直し）。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/tile.py in.png out.png "<描いた言葉>" [--long 4096] [--strength 0.3]

AI の拡大（upscale.py）だけでは線はくっきりするが描き込みは増えず、拡大前と同じ絵に見えた。
SDXL は約 100 万画素で描くのが得意で、4096 画素の絵を丸ごと描き直すと人物が増えたり形が崩れたりする。
そこで、拡大した絵を 1024 画素の区切りに分け、区切りごとに同じ模型・同じ言葉で弱く描き直して細部（髪の毛束、布のしわ、
線の強弱）を足し、重なりをぼかして戻す。区切りの中に別の顔や手を描き足すのを防ぐため、描き直した区切りの形の変わり方（drift）を測り、変わりすぎた区切りは弱めて描き直すか元のまま使う。
最後に清書（cleanup.py）で線のごみと塗りのまだらを整える。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401  模型を勝手に取りに行かない設定を先に効かせる

LONG = 4096      # 仕上がりの長辺の既定（イラストの入稿でよく使う 4K 相当）
SIDE = 1024      # 区切りの一辺（SDXL の得意な大きさ）
OVERLAP = 192    # 区切りの重なり。狭いと継ぎ目が出る
DRIFT = 0.045    # 区切りの描き直しで許す形の変わり方（縮めた明るさの差の平均）。超えたら弱めて描き直し、それでも超えたら元のまま
RETRY = 0.6      # 超えたときに強さへ掛ける割合
TILE_NEGATIVE = "face, eyes, extra face, extra hands, extra fingers, text, watermark, blurry, lowres"


def spans(length: int, side: int = SIDE, overlap: int = OVERLAP) -> list[int]:
    """長さ length を side の区切りで、重なり overlap 以上を保って覆う始点の並び（最後の区切りは端にそろえる）"""
    if length <= side:
        return [0]
    n = -(-(length - overlap) // (side - overlap))
    step = (length - side) / (n - 1)
    return [round(i * step) for i in range(n)]


def feather(side: int, overlap: int, left: bool, top: bool, right: bool, bottom: bool):
    """重なる側だけ縁をなだらかにした重み（重なりの中で 0 から 1 へ）"""
    import numpy as np
    ramp = np.linspace(0, 1, overlap)
    w = np.ones(side)
    wx, wy = w.copy(), w.copy()
    if left:
        wx[:overlap] = ramp
    if right:
        wx[-overlap:] = ramp[::-1]
    if top:
        wy[:overlap] = ramp
    if bottom:
        wy[-overlap:] = ramp[::-1]
    return np.outer(wy, wx)[..., None]


def drift(a, b, scale: int = 16) -> float:
    """形の変わり方: 2 枚を 1/scale に縮めた明るさの差の平均（0〜1）。細部（毛束・しわ）は縮めると消え、
    形（輪郭・顔や手の位置・増えた物）の違いだけが残る"""
    import numpy as np
    from PIL import Image
    size = (max(1, a.width // scale), max(1, a.height // scale))
    x = np.asarray(a.convert("L").resize(size, Image.BOX), dtype=float) / 255.0
    y = np.asarray(b.convert("L").resize(size, Image.BOX), dtype=float) / 255.0
    return float(np.abs(x - y).mean())


def tile(src, out, prompt: str, long: int = LONG, strength: float = 0.4, steps: int = 20, seed: int = 0) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    import demi
    import free_text
    import upscale
    t0 = time.time()
    upscale.upscale(src, out, long=long)
    big = Image.open(out).convert("RGB")
    t1 = time.time()
    pipe = demi.img2img()
    pos, neg = free_text.full_prompt(prompt, TILE_NEGATIVE)
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    log = []
    acc = np.zeros((big.height, big.width, 3))
    wsum = np.zeros((big.height, big.width, 1))
    xs, ys = spans(big.width), spans(big.height)
    for yi, y in enumerate(ys):
        for xi, x in enumerate(xs):
            crop = big.crop((x, y, x + SIDE, y + SIDE))
            # 描き込みを足すほど形も変わりやすい。形が変わった区切り（顔や手が増えた、輪郭がずれた）は弱めて描き直し、
            # それでも変わるなら元の区切りを使う。描き込みより形が崩れないことを先にする
            redone, kept = crop, "original"
            for st in (strength, strength * RETRY):
                cand = pipe(image=crop, strength=st, prompt_embeds=pe, negative_prompt_embeds=ne,
                            pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_, num_inference_steps=steps,
                            guidance_scale=5.0, generator=torch.Generator().manual_seed(seed + yi * 100 + xi)).images[0]
                d = drift(crop, cand)
                if d <= DRIFT:
                    redone, kept = cand, round(st, 2)
                    break
            log.append({"x": x, "y": y, "used": kept, "drift": round(d, 3)})
            w = feather(SIDE, OVERLAP, xi > 0, yi > 0, xi < len(xs) - 1, yi < len(ys) - 1)
            acc[y:y + SIDE, x:x + SIDE] += np.asarray(redone, dtype=float) * w
            wsum[y:y + SIDE, x:x + SIDE] += w
            print(f"区切り {yi * len(xs) + xi + 1}/{len(xs) * len(ys)}: {time.time() - t1:.0f} 秒", flush=True)
    Image.fromarray(np.clip(acc / np.maximum(wsum, 1e-6), 0, 255).astype("uint8")).save(out)
    return {"size": big.size, "tiles": len(xs) * len(ys), "upscale": round(t1 - t0), "tile": round(time.time() - t1),
            "kept_original": sum(1 for t in log if t["used"] == "original"), "log": log}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("prompt")
    ap.add_argument("--long", type=int, default=LONG)
    ap.add_argument("--strength", type=float, default=0.4)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    print(tile(a.src, a.out, a.prompt, a.long, a.strength, a.steps, a.seed))


if __name__ == "__main__":
    main()
