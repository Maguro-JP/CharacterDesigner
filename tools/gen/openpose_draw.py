"""関節の骨組み（OpenPose の 18 点）で姿勢を縛り、手本の絵（IP-Adapter）で服と顔を寄せて描く。

奥行きの下絵で縛ると、裸の人形の起伏を服の形として描き、服が体に貼り付いた（羊娘で 0/6）。
骨組みは関節の位置しか渡さないので、服の膨らみは描く模型と手本の絵に任せられる。

ControlNet union（xinsir/controlnet-union-sdxl-1.0）は control_mode=0 が openpose。
この環境には promax 版が無く、標準版（diffusion_pytorch_model.safetensors）を読む。

  python3 tools/gen/openpose_draw.py skeleton POSE OUT.png
  python3 tools/gen/openpose_draw.py draw ID POSE OUTDIR --ref IMG --seed 0 --count 2
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import design  # noqa: E402  模型の置き場所と取りに行かない既定を先に効かせる

W, H = 832, 1216
# OpenPose の 18 点: 0 鼻 1 首 2 右肩 3 右肘 4 右手首 5 左肩 6 左肘 7 左手首 8 右腰 9 右膝 10 右足首
# 11 左腰 12 左膝 13 左足首 14 右目 15 左目 16 右耳 17 左耳。右は人物の右（絵の左）
LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
         (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
          (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
          (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85)]
# 四面図の正面（out/sheep-girl/turnaround/front/sheep-girl-7.png、832x1216）から目で読んだ関節の位置。
# 腰を 520 に置くと、描いた絵のベルトが背丈の 34% の高さに上がり脚が長くなった（正面図は 39%、股は 43%）。
# 骨組みの腰の点は股の高さとして読まれるので、正面図の股（544）より少し下の 560 に置く
STAND = {0: (415, 200), 1: (415, 262), 2: (352, 288), 3: (325, 420), 4: (305, 560), 5: (478, 288), 6: (505, 420),
         7: (525, 560), 8: (378, 560), 9: (338, 850), 10: (308, 1060), 11: (452, 560), 12: (488, 850),
         13: (522, 1060), 14: (398, 185), 15: (434, 185), 16: (378, 192), 17: (455, 192)}
POSES = {
    # 左の前腕を腰の高さで前へ曲げる（籠を掛ける腕）。右腕は下ろしたまま
    # 左手は腰の横（ベルトの脇）。前腕を腹の前へ渡すと、手が股の上に差し込まれた
    "basket": ({6: (515, 410), 7: (478, 505)}, "left hand resting on side of waist by belt, right arm down"),
    # 右手を腰に当て、肘を外へ張る
    "hip": ({3: (285, 400), 4: (362, 505)}, "right hand on hip, right elbow out, left arm down"),
    # 右手を肩の横で小さく振る
    "wave": ({3: (285, 390), 4: (272, 250)}, "waving, right hand raised beside head, open palm, left arm down"),
}


# 開いた手の 21 点（OpenPose の手: 0 手首、1-4 親指、5-8 人差し指、9-12 中指、13-16 薬指、17-20 小指）。
# 手首を原点に、前腕の向きを +y にした手の座標。x は親指の側が +。体の骨組みだけでは、下ろした手の指が 2〜3 本に溶けた
OPEN_HAND = [(0, 0), (8, 8), (14, 16), (18, 24), (21, 31),
             (6, 28), (8, 39), (9, 48), (10, 56),
             (1, 30), (1, 42), (1, 52), (1, 61),
             (-5, 29), (-6, 40), (-7, 49), (-8, 57),
             (-10, 26), (-13, 35), (-15, 42), (-17, 48)]
HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (0, 9), (9, 10), (10, 11), (11, 12),
              (0, 13), (13, 14), (14, 15), (15, 16), (0, 17), (17, 18), (18, 19), (19, 20)]
# 姿勢ごとに、開いた手で縛る手（肘と手首の番号、親指が向く側 +1 は絵の右）。腰に当てた手は隠れるので縛らない
HANDS = {"basket": [(3, 4, 1)], "hip": [(6, 7, -1)], "wave": [(3, 4, 1), (6, 7, -1)]}


def hand_points(elbow, wrist, thumb):
    """前腕の向き（肘→手首）に沿って開いた手の 21 点を置く。thumb は親指が絵の右（+1）か左（-1）か"""
    import math
    dx, dy = wrist[0] - elbow[0], wrist[1] - elbow[1]
    n = math.hypot(dx, dy) or 1
    uy = (dx / n, dy / n)            # 指先の向き
    ux = (-uy[1], uy[0])             # それに直交する向き
    if ux[0] * thumb < 0 or (ux[0] == 0 and ux[1] * thumb < 0):
        ux = (-ux[0], -ux[1])
    return [(wrist[0] + x * ux[0] + y * uy[0], wrist[1] + x * ux[1] + y * uy[1]) for x, y in OPEN_HAND]


def skeleton(pose: str, out: str):
    pts = {**STAND, **POSES[pose][0]}
    im = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(im)
    for i, (a, b) in enumerate(LIMBS):
        c = tuple(int(v * 0.6) for v in COLORS[i])
        d.line([pts[a], pts[b]], fill=c, width=10)
    for i, p in pts.items():
        d.ellipse([p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6], fill=COLORS[i])
    import colorsys
    for e, w, thumb in HANDS.get(pose, []):
        hp = hand_points(pts[e], pts[w], thumb)
        for i, (a, b) in enumerate(HAND_EDGES):
            c = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(i / len(HAND_EDGES), 1.0, 1.0))
            d.line([hp[a], hp[b]], fill=c, width=2)
        for q in hp:
            d.ellipse([q[0] - 2, q[1] - 2, q[0] + 2, q[1] + 2], fill=(0, 0, 255))
    im.save(out)


def draw(ident, pose, outdir, ref, seed, count, scale, ref_scale, end, words=None, extra_negative=""):
    import torch
    import bible
    import free_text
    import people
    from diffusers import ControlNetUnionModel, StableDiffusionXLControlNetUnionPipeline
    import device
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    skel = out / f"{pose}-skeleton.png"
    skeleton(pose, skel)
    pos, neg = bible.prompt(ident, pose=POSES[pose][1], items=[])
    if words:
        # 設定の言葉をそのまま組むと 227 語になり、姿勢の言葉が 3 つ目の区切りに落ちた。固定部分を 77 語以内に削って渡す
        pos = f"{words}, {POSES[pose][1]}"
    if extra_negative:
        neg = f"{extra_negative}, {neg}"
    pos, neg = free_text.full_prompt(pos, neg)
    base = people.pipe()
    people.use_reference()
    cn = ControlNetUnionModel.from_pretrained(people.CONTROL_MODEL, torch_dtype=device.dtype(torch))
    device.module(cn, torch)
    p = StableDiffusionXLControlNetUnionPipeline(**{k: v for k, v in base.components.items() if k in (
        "vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "unet", "scheduler",
        "feature_extractor", "image_encoder")}, controlnet=cn)
    p.vae.enable_tiling()
    p.set_ip_adapter_scale(ref_scale)
    pe, ne, pp, np_ = design.encode_xl(p, pos, neg)
    refimg = Image.open(ref).convert("RGB")
    ctrl = Image.open(skel).convert("RGB")
    for k in range(count):
        im = p(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
               control_image=[ctrl], control_mode=[0], controlnet_conditioning_scale=scale, control_guidance_end=end,
               ip_adapter_image=refimg, width=W, height=H, num_inference_steps=24, guidance_scale=6.0,
               generator=torch.Generator().manual_seed(seed + k)).images[0]
        im.save(out / f"{ident}-{pose}-{seed + k}.png")
        print(f"{pose} seed {seed + k} 描けた", flush=True)
    (out / f"{ident}-{pose}-prompt.txt").write_text(json.dumps(dict(prompt=pos, negative=neg, seed=seed, count=count,
        control_scale=scale, control_end=end, ref=ref, ref_scale=ref_scale), ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("skeleton"); s.add_argument("pose", choices=list(POSES)); s.add_argument("out")
    s = sub.add_parser("draw"); s.add_argument("id"); s.add_argument("pose", choices=list(POSES)); s.add_argument("outdir")
    s.add_argument("--ref", required=True); s.add_argument("--seed", type=int, default=0); s.add_argument("--count", type=int, default=2)
    s.add_argument("--scale", type=float, default=0.8); s.add_argument("--ref-scale", type=float, default=0.5)
    s.add_argument("--end", type=float, default=0.8)
    s.add_argument("--words", help="設定の言葉の代わりに使う固定部分（姿勢の言葉は後ろに足す）")
    s.add_argument("--extra-negative", default="")
    a = ap.parse_args()
    if a.cmd == "skeleton":
        skeleton(a.pose, a.out)
    else:
        draw(a.id, a.pose, a.outdir, a.ref, a.seed, a.count, a.scale, a.ref_scale, a.end, a.words, a.extra_negative)


if __name__ == "__main__":
    main()
