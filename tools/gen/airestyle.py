"""元絵の形を保ったまま、画像生成で画風だけを描き直す（SDXL の img2img）。

stylize.py の加工は模型を使わないので速いが、写実・アニメ塗り・漫画のように描き方そのものが違う画風は
色と線を変えるだけでは出なかった。ここでは元絵を下敷きにして、描き直す強さ（strength）を半分ほどに抑え、
構図と体の形は元絵から、塗りと線は画風の言葉から取らせる。

  python3 tools/gen/airestyle.py 元.png 出力ディレクトリ [画風 ...]   画風を省くと全部
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402  模型の置き場所と取りに行かない既定を、diffusers より先に決める

STYLES = {
    "real": "wildlife photograph, natural fur and skin texture, soft daylight, shallow depth of field",
    "anime": "2d anime illustration, cel shading, clean lineart, flat colors",
    "manga": "black and white manga illustration, ink lineart, screentone shading, monochrome",
    "watercolor": "watercolor painting, soft washes, paper texture",
    "storybook": "children's picture book illustration, gouache, soft shapes",
}
NEGATIVE = "extra legs, extra heads, deformed anatomy, text, watermark, frame, human"

# 0.5 では 5 段のうち 2 段しか描き直さず、元絵とほぼ同じだった。0.72 で形（足、向き）を保ったまま塗りが変わった
STRENGTH = 0.72
STEPS = 10


def _pipe():
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLImg2ImgPipeline
    import device
    torch.set_num_threads(__import__("os").cpu_count() or 4)
    pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(design.STYLES["xl"], variant="fp16", torch_dtype=device.dtype(torch))
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="sde-dpmsolver++",
                                                             use_karras_sigmas=True)
    return device.place(pipe, torch)


def apply(src: str, outdir: str, names: list[str] | None = None, subject: str = "", strength: float = STRENGTH) -> list[str]:
    import torch
    from PIL import Image
    im = Image.open(src).convert("RGB")
    # SDXL は 8 の倍数の大きさを要る
    w, h = (im.width // 8) * 8, (im.height // 8) * 8
    im = im.resize((w, h))
    pipe = _pipe()  # 模型は 1 回だけ読み、全部の画風で使い回す
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in names or list(STYLES):
        t = time.time()
        prompt = f"{STYLES[n]}, {subject}, same pose, full body" if subject else f"{STYLES[n]}, same pose, full body"
        res = pipe(prompt=prompt, negative_prompt=NEGATIVE, image=im, strength=strength, num_inference_steps=STEPS,
                   guidance_scale=2.0, generator=torch.Generator().manual_seed(0)).images[0]
        p = out / f"{Path(src).stem}-ai-{n}.png"
        res.save(p)
        print(f"{p}: {time.time() - t:.0f} 秒", flush=True)
        paths.append(str(p))
    return paths


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    args = sys.argv[3:]
    subject = ""
    if args and args[0].startswith("--subject="):
        subject = args.pop(0).split("=", 1)[1]
    apply(sys.argv[1], sys.argv[2], args or None, subject)


if __name__ == "__main__":
    main()
