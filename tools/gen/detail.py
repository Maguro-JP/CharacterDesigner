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


def head_box(src, margin: float = 0.4):
    """顔と髪の部位から頭の周りの正方形の枠を返す。顔が読めなければ None。
    描き直しには、下絵と同じ言葉を渡す（言葉が違うと光の色が変わり、枠の縁で食い違う）"""
    import numpy as np
    import edit
    from scipy import ndimage
    seg = np.asarray(edit.parts(src))
    face = seg == edit.LABELS["face"]
    ys, xs = np.nonzero(face)
    if len(xs) < 50:
        return None
    # 枠は顔と、顔につながった髪の塊を合わせた範囲から決める。顔だけで決めると髪の途中で枠が切れ、
    # 枠の内と外で髪の描き方と色が食い違った
    lab, _ = ndimage.label(face | (seg == edit.LABELS["hair"]))
    ids = np.unique(lab[face])
    ys, xs = np.nonzero(np.isin(lab, ids[ids > 0]))
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # 部位分けは光で白く飛んだ髪を拾わないので、合わせた範囲より広く取る
    half = max(x1 - x0, y1 - y0) / 2 * (1 + margin)
    h, w = seg.shape
    half = min(half, w / 2, h / 2)
    cx, cy = min(max(cx, half), w - half), min(max(cy, half), h - half)
    return int(cx - half), int(cy - half), int(cx + half), int(cy + half)


# open hand を入れると、閉じかけた手や顎に添えた手まで指を扇に広げ、6 本以上に増やした（2026-10-17、try-301）
HAND_WORDS = ("detailed hand, five fingers, separated fingers, correct hand anatomy, clean lineart")
HAND_NEGATIVE = "fused fingers, extra fingers, missing fingers, six fingers, four fingers, deformed hand, claws, blurry"


def detail(src, out, prompt: str, negative: str = "", strength: float = 0.4, steps: int = 24, seed: int = 0,
           box=None, words: str = FACE_WORDS, extra_negative: str = FACE_NEGATIVE, control: str | None = None,
           control_scale: float = 0.8, control_mode: int | None = None) -> dict:
    import torch
    from PIL import Image, ImageDraw, ImageFilter
    import demi
    import design
    import free_text
    im = Image.open(src).convert("RGB")
    if box is None:
        box = head_box(src)
    if box is None:
        if str(out) != str(src):
            im.save(out)
        return {"box": None, "reason": "顔が読めなかった（後ろ向き・小さすぎる）"}
    crop = im.crop(box)
    pos, neg = free_text.full_prompt(f"{prompt}, {words}", ", ".join(x for x in (negative, extra_negative) if x))
    extra = {}
    if control and control_mode is not None:
        # union の型で縛る（3 は線: canny・lineart）。control は絵と同じ大きさの、黒地に白い線の絵
        import people
        pipe = people.union_img2img()
        ctrl = Image.open(control).convert("RGB").resize(im.size).crop(box).resize((SIDE, SIDE), Image.LANCZOS)
        extra = dict(control_image=[ctrl], control_mode=[control_mode], controlnet_conditioning_scale=control_scale)
    elif control:
        # 人形の奥行きの同じ枠を切り出して渡し、形（指の本数と向き）を人形で縛る。
        # 言葉と強さだけで手を描き直すと、元の崩れた手の形に引っ張られ、指が 2〜3 本の爪の形のまま残った
        import people
        pipe = people.depth_img2img()
        ctrl = Image.open(control).convert("RGB").resize(im.size).crop(box).resize((SIDE, SIDE), Image.LANCZOS)
        extra = dict(control_image=ctrl, controlnet_conditioning_scale=control_scale)
    else:
        pipe = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    redone = pipe(image=crop.resize((SIDE, SIDE), Image.LANCZOS), strength=strength, prompt_embeds=pe,
                  negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  num_inference_steps=steps, guidance_scale=6.0, generator=torch.Generator().manual_seed(seed),
                  **extra).images[0]
    redone = redone.resize(crop.size, Image.LANCZOS)
    # 枠の縁で継ぎ目が出ないよう、内側の楕円だけを使い、縁を枠の 1/10 でぼかす
    s = crop.size[0]
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).ellipse((s * 0.06, s * 0.06, s * 0.94, s * 0.94), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(s / 10))
    im.paste(redone, box[:2], mask)
    im.save(out)
    return {"box": box, "side": s}


def detail_masked(src, out, prompt: str, box, keep_labels, words: str, extra_negative: str = "", strength: float = 0.5,
                  seed: int = 0, grow: int = 1, protect=(), protect_circles=()) -> int:
    """枠を描き直し、その結果を部位（keep_labels）の範囲にだけ使う。顔・角・手など protect の部位と、
    protect_circles（(x, y, 半径) の円、鈴など部位分けに出ない物）は元の絵のまま残す。
    枠の楕円で混ぜるだけでは、髪の枠に顔や角が入って一緒に描き変わった。返すのは差し替えた画素の数"""
    import numpy as np
    from PIL import Image, ImageFilter
    import edit
    tmp = str(out) + ".tmp.png"
    detail(src, tmp, prompt, "", strength, seed=seed, box=box, words=words, extra_negative=extra_negative)
    seg = np.asarray(edit.parts(src))
    m = Image.fromarray((np.isin(seg, keep_labels) * 255).astype(np.uint8))
    if grow > 1:
        m = m.filter(ImageFilter.MaxFilter(grow))
    k = Image.fromarray((np.isin(seg, protect) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))
    k = np.asarray(k).copy()
    yy, xx = np.mgrid[0:k.shape[0], 0:k.shape[1]]
    for x, y, r in protect_circles:
        k[(xx - x) ** 2 + (yy - y) ** 2 < r * r] = 255
    mm = np.asarray(m).astype(int) - k
    inside = np.zeros_like(mm)
    inside[box[1]:box[3], box[0]:box[2]] = 1
    mm = Image.fromarray((np.clip(mm, 0, 255) * inside).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
    im = Image.open(src).convert("RGB")
    im.paste(Image.open(tmp).convert("RGB"), (0, 0), mm)
    im.save(out)
    Path(tmp).unlink()
    return int((np.asarray(mm) > 127).sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("prompt")
    ap.add_argument("--negative", default="")
    ap.add_argument("--strength", type=float, default=0.4)
    ap.add_argument("--seed", type=int, default=0)
    # 手は部位分けで枠が取れないので、正方形の枠を x0,y0,x1,y1 で渡す（全身の絵では手が 30〜50 画素しか無く、
    # 指が潰れて数えられなかった。顔と同じく切り出して大きく描き直す）
    ap.add_argument("--hand", action="append", default=[], metavar="x0,y0,x1,y1")
    ap.add_argument("--auto-hands", action="store_true", help="手の枠を手のひらの模型で探す（hands.py --auto と同じ）")
    a = ap.parse_args()
    if a.auto_hands:
        import hands
        from PIL import Image
        w, h = Image.open(a.src).size
        for b in hands.detect_palms(Image.open(a.src).convert("RGB")) or hands.auto_boxes(a.src):
            x0, y0, x1, y1 = (int(v) for v in b.split(":")[0].split(","))
            # 見当の枠は手首寄りに外れることがあるので 1.3 倍に広げ、絵の内に収める（正方形のまま）
            r = min(int((x1 - x0) * 0.65), w // 2, h // 2)
            cx, cy = min(max((x0 + x1) // 2, r), w - r), min(max((y0 + y1) // 2, r), h - r)
            a.hand.append(f"{cx - r},{cy - r},{cx + r},{cy + r}")
        if not a.hand:
            sys.exit("手の枠が出なかった（肘と手首が読めない）")
    if not a.hand:
        print(detail(a.src, a.out, a.prompt, a.negative, a.strength, seed=a.seed))
        return
    src = a.src
    for i, b in enumerate(a.hand):
        box = tuple(int(v) for v in b.split(","))
        if box[2] - box[0] != box[3] - box[1]:
            sys.exit(f"--hand の枠は正方形にする: {b}")
        print(detail(src, a.out, a.prompt, a.negative, a.strength, seed=a.seed + i, box=box,
                     words=HAND_WORDS, extra_negative=HAND_NEGATIVE))
        src = a.out


if __name__ == "__main__":
    main()
