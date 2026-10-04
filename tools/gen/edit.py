"""描いた人物の絵を、部位を指定して直す。指定した部位の外は1画素も変えない。

言葉だけで「角を足して」「肌を青く」と描き直すと、服・ポーズ・背景まで入れ替わった（docs/knowledge/traits.md）。
人体の部位分けのモデル（segformer b3 clothes、MIT）で顔・腕・脚・髪・服・靴を塗り分け、
直すのはその範囲だけにして、範囲の外は元の画素を貼り戻す。範囲の外で変わった画素の数を毎回出す（0 でなければ失敗）。

  parts   絵 → 部位の塗り分け（<絵>.parts.png、確かめ用の重ね絵 <絵>.parts-view.png）
  recolor 肌などの色を、陰影を保ったまま置き換える（画像生成を使わない）
  inpaint 範囲だけを描き直す（SDXL inpainting の本体。範囲の外は貼り戻す）

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/edit.py parts in.png
  PYTHONPATH=.cache/gen/lib python3 tools/gen/edit.py recolor in.png out.png --region skin --color "#4a7ad0"
  PYTHONPATH=.cache/gen/lib python3 tools/gen/edit.py inpaint in.png out.png --region skin_arms --prompt "black tribal tattoos"
部位の名前: skin, face, arms, legs, skin_arms, hair, head_top, upper, lower, shoes, clothes（+ でつなぐと合わせる。例 upper+arms。末尾の -feet で足先を外す。例 lower+legs-feet）
"""
import argparse
import colorsys
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
SEG_MODEL = "sayeed99/segformer_b3_clothes"
LABELS = {"background": 0, "hat": 1, "hair": 2, "sunglasses": 3, "upper": 4, "skirt": 5, "pants": 6, "dress": 7,
          "belt": 8, "left_shoe": 9, "right_shoe": 10, "face": 11, "left_leg": 12, "right_leg": 13,
          "left_arm": 14, "right_arm": 15, "bag": 16, "scarf": 17}
REGIONS = {
    "face": [11], "arms": [14, 15], "legs": [12, 13], "skin": [11, 12, 13, 14, 15], "skin_arms": [14, 15],
    "hair": [2], "upper": [4, 7], "lower": [5, 6, 7], "shoes": [9, 10], "clothes": [1, 4, 5, 6, 7, 8, 16, 17],
}


_SEG = None


def parts(src):
    """部位の塗り分け（1画素1部位の番号を明るさに入れた L の絵）を作り、絵の隣に置く。2回目からは読むだけ。"""
    out = Path(str(src) + ".parts.png")
    if out.exists():
        return Image.open(out)
    import numpy as np
    import torch
    from transformers import AutoModelForSemanticSegmentation
    im = Image.open(src).convert("RGB")
    global _SEG
    if _SEG is None:
        from transformers.utils import logging as tlog
        tlog.disable_progress_bar()
        _SEG = AutoModelForSemanticSegmentation.from_pretrained(SEG_MODEL)
    model = _SEG
    # 前処理は自前で書く（モデル付属の前処理は torchvision を要求し、この環境に無い）
    a = np.asarray(im.resize((512, 512), Image.BILINEAR), dtype=np.float32) / 255.0
    a = (a - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
    with torch.no_grad():
        logits = model(pixel_values=torch.tensor(a.transpose(2, 0, 1)[None], dtype=torch.float32)).logits
    seg = torch.nn.functional.interpolate(logits, size=(im.height, im.width), mode="bilinear").argmax(1)[0]
    lab = Image.fromarray(seg.numpy().astype("uint8"), "L")
    lab.save(out)
    return lab


def region_mask(src, region, grow=0):
    """部位の名前から範囲（白が範囲）を作る。head_top は髪の上を上へ広げた範囲（角や耳を足す場所）。"""
    lab = parts(src)
    if region == "head_top":
        hair = lab.point(lambda v: 255 if v in (1, 2) else 0)
        x0, y0, x1, y1 = hair.getbbox() or (0, 0, 1, 1)
        h = y1 - y0
        m = Image.new("L", lab.size, 0)
        m.paste(255, (max(0, x0 - h // 3), max(0, y0 - h), min(lab.width, x1 + h // 3), y0 + h // 2))
        return m
    # 「upper+arms」のように + でつなぐと範囲を合わせる。服の形は元の服の輪郭から出られないので、
    # 長袖なら腕、長い丈なら脚まで範囲に入れる（短パンのまま柄だけ変わったため）
    # 末尾に「-feet」を付けると足先を範囲から外す。部位分けは素足を脚に含めるので、脚まで描き直すと
    # 頼んでいない靴が出たり足先がかすれたりした。足先は人物の下端から身長の 6% と決める（素足の高さ）
    no_feet = region.endswith("-feet")
    region = region.removesuffix("-feet")
    ids = [i for r in region.split("+") for i in REGIONS[r]]
    m = lab.point(lambda v: 255 if v in ids else 0)
    if grow:
        m = m.filter(ImageFilter.MaxFilter(grow * 2 + 1))
    if no_feet:
        body = lab.point(lambda v: 255 if v else 0).getbbox()
        if body:
            cut = body[3] - int((body[3] - body[1]) * 0.06)
            m.paste(0, (0, cut, m.width, m.height))
    return m


def outside_changed(before, after, mask):
    """範囲の外で変わった画素の数。0 でなければ、ほかを変えてしまっている。"""
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB")).convert("L").point(lambda v: 255 if v else 0)
    outside = ImageChops.multiply(diff, ImageChops.invert(mask.point(lambda v: 255 if v else 0)))
    return sum(outside.histogram()[1:])


def is_skin_tone(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return (h < 0.12 or h > 0.95) and 0.08 < s < 0.75 and v > 0.3


def recolor(src, out, region, color, grow=0):
    """範囲の色を目標の色に置き換える。範囲の平均を目標の色に合わせ、元の濃淡の比（陰影）はそのまま残す。

    - 縁: 部位分けの境目に元の肌色が1〜2画素残ったので、範囲を2画素広げ、そのうち肌色の画素だけを足す
    - 目や口の線（暗い）と白目（彩度が低く明るい）は変えない
    """
    im = Image.open(src).convert("RGB")
    m = region_mask(src, region, grow)
    px0 = im.load()
    if region in ("skin", "face", "arms", "legs", "skin_arms"):
        wide = m.filter(ImageFilter.MaxFilter(5)).load()
        mp = m.load()
        for y in range(im.height):
            for x in range(im.width):
                if wide[x, y] and not mp[x, y] and is_skin_tone(*px0[x, y]):
                    mp[x, y] = 255
    keep = lambda s, v: v < 0.25 or (s < 0.08 and v > 0.85)  # noqa: E731
    pts = [(x, y) for y in range(im.height) for x in range(im.width) if m.getpixel((x, y))]
    hsv = {p: colorsys.rgb_to_hsv(*(c / 255 for c in px0[p])) for p in pts}
    use = [hsv[p] for p in pts if not keep(hsv[p][1], hsv[p][2])]
    ms = sum(s for _, s, _ in use) / max(1, len(use))
    mv = sum(v for _, _, v in use) / max(1, len(use))
    th, ts, tv = colorsys.rgb_to_hsv(*(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    res = im.copy()
    px = res.load()
    for p in pts:
        h, s, v = hsv[p]
        if keep(s, v):
            continue
        s2 = min(1.0, ts * s / max(0.01, ms))
        v2 = min(1.0, tv * v / max(0.01, mv))
        px[p] = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(th, s2, v2))
    res.save(out)
    n = outside_changed(im, res, m)
    print(f"{out}: 範囲 {len(pts)} 画素、範囲の外で変わった画素 {n}")
    return n


INPAINT_UNET = "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"


def inpaint(src, out, region, prompt, negative="", grow=4, steps=20, guidance=7.0, seed=7, strength=0.99):
    """範囲だけを SDXL inpainting で描き直し、範囲の外は元の画素を貼り戻す。"""
    import gc
    import torch
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionXLInpaintPipeline, UNet2DConditionModel
    im = Image.open(src).convert("RGB")
    # 描き直しは広げた範囲で行い（つながりのため）、貼り戻すのは元の部位の範囲だけにする。
    # 広げた範囲まで貼ると、腕の周りの背景が描き直されて明るい縁取りが出た
    m = region_mask(src, region, grow)
    keep_in = region_mask(src, region, 0)
    pipe = design._pipe("xl")
    comp = {k: v for k, v in pipe.components.items() if k != "unet"}
    # 本体を2つ持つとメモリ 15GB を超えて強制終了された。今の本体を捨ててから読む
    del pipe
    gc.collect()
    unet = UNet2DConditionModel.from_pretrained(INPAINT_UNET, subfolder="unet", variant="fp16", torch_dtype=torch.bfloat16)
    inp = StableDiffusionXLInpaintPipeline(**comp, unet=unet)
    inp.scheduler = EulerAncestralDiscreteScheduler.from_config(inp.scheduler.config)
    pe, ne, pp, np_ = design.encode_xl(inp, prompt + ", 2d anime style illustration, cel shading",
                                       ", ".join(x for x in ("text, watermark, nsfw", negative) if x))
    # SDXL 系は 1024 前後で描く。512x768 のまま描き直すと、細い腕や手がくすんだり半透明の影になったりした。
    # 長い辺が 1024 未満なら拡大して描き、元の大きさに戻す
    k = max(1.0, 1024 / max(im.size))
    w, h = (round(im.width * k) // 8) * 8, (round(im.height * k) // 8) * 8
    gen = inp(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
              image=im.resize((w, h)), mask_image=m.resize((w, h)), strength=strength, num_inference_steps=steps,
              guidance_scale=guidance, width=w, height=h, generator=torch.Generator().manual_seed(seed)).images[0]
    gen = gen.resize(im.size)
    # 範囲の外は元の画素を貼り戻す。境目は 2 画素ぼかして継ぎ目を目立たなくする（ぼかしは範囲の内側だけ）
    soft = ImageChops.multiply(keep_in.filter(ImageFilter.GaussianBlur(2)), keep_in)
    res = Image.composite(gen, im, soft)
    res.save(out)
    n = outside_changed(im, res, keep_in)
    m = keep_in
    print(f"{out}: 範囲 {sum(m.histogram()[1:])} 画素、範囲の外で変わった画素 {n}")
    return n


def foreground(src):
    """人物（翼・尾・角を含む）の範囲。画面の端から無地の背景を塗りつぶして抜く（design.cut_background）。

    部位分けのモデルは人の部位（顔・腕・脚・服）しか知らず、翼や尾や角を背景として消してしまう。
    背景を抜くのは端からのつながりで決め、体とつながった翼や尾は残す。
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    return design.keep_largest(design.cut_background(Image.open(src))).getchannel("A").point(lambda v: 255 if v else 0)


def clean_background(src, out=None):
    """背景を無地の白にする。人物（翼・尾・角を含む）は残す。

    背景に蛇・猫・狼・影などが描かれ、それを体の部品が出たと取り違えた。人を描いたら毎回これを通す。
    """
    im = Image.open(src).convert("RGB")
    fg = foreground(src)
    res = Image.composite(im, Image.new("RGB", im.size, (255, 255, 255)), fg)
    res.save(out or src)
    return res


def inspect(src, limbs=True):
    """生き物として破綻している絵を機械で見つける。当てはまった理由の一覧を返す（空なら通る）。

    - 背景に人物と離れた物がある（端から背景を抜いたあと、大きな塊が2つ以上）
    - 腕・脚の左右どちらかが無い（部位分けで数える）
    - 体が画面の端で切れている
    """
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    cut = design.cut_background(Image.open(src))
    alpha = np.asarray(cut.getchannel("A")) > 0
    if not alpha.any():
        return ["人物が写っていない"]
    reasons = []
    # 塊の数（全体の 3% 以上）。人物と離れた物（背後の動物、別の人物）が残ると 2 つ以上になる
    from collections import deque
    H, W = alpha.shape
    seen = np.zeros_like(alpha)
    sizes = []
    for y0 in range(0, H, 2):
        for x0 in range(0, W, 2):
            if alpha[y0, x0] and not seen[y0, x0]:
                n, q = 0, deque([(y0, x0)])
                seen[y0, x0] = True
                while q:
                    y, x = q.popleft()
                    n += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < H and 0 <= xx < W and alpha[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = True
                            q.append((yy, xx))
                sizes.append(n)
    big = [n for n in sizes if n > alpha.sum() * 0.03]
    if len(big) >= 2:
        reasons.append(f"人物と離れた物がある（塊が {len(big)} つ）")
    lab = np.asarray(parts(src))
    # 人と違う体（ラミア、人魚、ケンタウロス、ハーピー）は脚や腕の数が人と違うので数えない（limbs=False）
    for name, ids in ((("左腕", [14]), ("右腕", [15]), ("左脚", [12]), ("右脚", [13])) if limbs else ()):
        if not np.isin(lab, ids).any():
            reasons.append(f"{name}が無い")
    fg = np.asarray(foreground(src)) > 0
    ys, xs = np.nonzero(fg)
    if ys.min() <= 1 or ys.max() >= H - 2 or xs.min() <= 1 or xs.max() >= W - 2:
        reasons.append("体が画面の端で切れている")
    return reasons


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parts")
    p.add_argument("src")
    r = sub.add_parser("recolor")
    r.add_argument("src")
    r.add_argument("out")
    r.add_argument("--region", default="skin")
    r.add_argument("--color", required=True)
    r.add_argument("--grow", type=int, default=0)
    c = sub.add_parser("clean")
    c.add_argument("src")
    c.add_argument("--out", default=None)
    k = sub.add_parser("inspect")
    k.add_argument("src", nargs="+")
    i = sub.add_parser("inpaint")
    i.add_argument("src")
    i.add_argument("out")
    i.add_argument("--region", required=True)
    i.add_argument("--prompt", required=True)
    i.add_argument("--negative", default="")
    i.add_argument("--grow", type=int, default=4)
    i.add_argument("--seed", type=int, default=7)
    i.add_argument("--strength", type=float, default=0.99,
                   help="描き直しの強さ。模様を乗せるだけ（刺青、鱗）なら 0.6〜0.8 で形を保つ")
    a = ap.parse_args()
    if a.cmd == "parts":
        lab = parts(a.src)
        print(f"{a.src}.parts.png: " + ", ".join(k for k, v in LABELS.items() if lab.histogram()[v]))
    elif a.cmd == "clean":
        clean_background(a.src, a.out)
    elif a.cmd == "inspect":
        bad = 0
        for f in a.src:
            r = inspect(f)
            bad += bool(r)
            print(f"{f}: {'通る' if not r else '落とす: ' + '、'.join(r)}")
        sys.exit(1 if bad else 0)
    elif a.cmd == "recolor":
        sys.exit(1 if recolor(a.src, a.out, a.region, a.color, a.grow) else 0)
    else:
        sys.exit(1 if inpaint(a.src, a.out, a.region, a.prompt, a.negative, a.grow, seed=a.seed, strength=a.strength) else 0)


if __name__ == "__main__":
    main()
