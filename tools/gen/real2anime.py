"""写実で体を描き（光と人体の形を写真の知識から借りる）、その絵を Animagine でイラストに描き直す。

写実の段は検品（measure.stray_color・stray_blob・garment_saturation）を通るまで種を替えて最大 8 回描き直し、
通らなければイラストは描かない（写実の崩れはイラストで布や影として残るため）。身体の題目で回 32〜95 を描いた台本。

  PYTHONPATH=.cache/gen/lib WHITEBG=1 python3 tools/gen/real2anime.py 回 種 prompts.txt 強さ
  （prompts.txt は 1 行 1 姿勢。出力は out/body/<回>/real-N.png と try-N.png）
"""
import sys, time, gc, os
sys.path.insert(0, "tools/gen")
import design  # 取らない設定を diffusers より先に効かせる
import torch, device
import shutil
from pathlib import Path
from PIL import Image
r, s, pf, strength = sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
d = Path("out/body") / r; d.mkdir(parents=True, exist_ok=True)
lines = open(pf).read().splitlines()
W, H = 832, 1216
# 1 段目: 写実
from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler, StableDiffusionXLImg2ImgPipeline
todo = [i for i in range(1, len(lines) + 1) if not (d / f"real-{i}.png").exists()]
if todo:
    pipe = StableDiffusionXLPipeline.from_pretrained("Lykon/dreamshaper-xl-lightning", variant="fp16", torch_dtype=device.dtype(torch))
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="sde-dpmsolver++", use_karras_sigmas=True)
    pipe = device.place(pipe, torch)
    for i in todo:
        t = time.time()
        p = (f"full body photo of a beautiful young adult Japanese woman in her early twenties, 22 years old, East Asian features, black hair, {lines[i-1]}, plain white bikini, barefoot, standing on a plain white studio floor, "
             "pale fair skin, porcelain complexion, flawless smooth clear skin, even skin tone, soft beauty retouch, magazine beauty photo, healthy average build, soft overcast daylight from upper left, evenly exposed, plain seamless light grey backdrop with nothing else in the scene, "
             "plain light grey seamless backdrop, realistic anatomy, whole body in frame, head and feet visible, fashion catalog photo")
        neg = ("nsfw, nude, cropped, out of frame, extra limbs, bad anatomy, deformed, text, watermark, multiple people, "
               "tan, tanned skin, oily skin, shiny skin, airbrushed, plastic skin, blotchy skin, rash, freckles, pores, visible pores, moles, blemishes, acne, goosebumps, visible veins, skin spots, uneven skin tone, red knees, wrinkles, skinny, emaciated, ribs, visible ribs, underweight, bony, glow, light leak, lens flare, rainbow colors, color smear, multicolored, glowing shapes, light painting, neon, cyan glow, props, objects on the floor, kneeling, colored light, gel light, haze")
        pe, ne, pp, np_ = design.encode_xl(pipe, p, neg)
        import measure
        best = None
        for k in range(8):
            # 頼んでいない光の漏れ・色のにじみ・小物は鮮やかな色で出る。検品で落ちたら種を替えて描き直す
            im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                      num_inference_steps=8, guidance_scale=2.5, width=W, height=H, generator=torch.Generator().manual_seed(s + i + 100 * k)).images[0]
            sc, bl = measure.stray_color(im), measure.stray_blob(im)
            import edit
            cand = d / f"real-{i}-cand{k}.png"
            im.save(cand)
            gs = measure.garment_saturation(im, edit.parts(str(cand)))
            # 1 を超えたら落ちる。合計（散らばった色）、一番大きな塊（色の板・布）、水着の色違いのどれでも落とす
            score = max(sc / 2.0, bl / 0.7, gs / 0.15)
            print(f"real-{i} try{k} stray_color={sc:.2f}% stray_blob={bl:.2f}% garment_sat={gs:.3f} {time.time()-t:.0f}s", flush=True)
            if best is None or score < best[0]:
                best = (score, im, cand)
            if score < 1.0:
                break
        best[1].save(d / f"real-{i}.png")
        # 部位分けは検品で作ったものを使い回す（同じ絵を 2 度分けない）
        shutil.copy(str(best[2]) + ".parts.png", d / f"real-{i}.png.parts.png")
        for c in d.glob(f"real-{i}-cand*.png*"):
            c.unlink()
        if best[0] >= 1.0:
            # 写実に崩れが残ったままイラストに描き直すと、崩れが布や影として残る。写実が通るまでイラストは描かない
            (d / f"real-{i}.failed").write_text(f"stray_score={best[0]:.2f}\n")
    del pipe; gc.collect()
if os.environ.get("ONLYREAL"):
    print("ALLDONE", flush=True); sys.exit(0)
# 2 段目: イラストに描き直す
import people
base = people.pipe()
pipe = StableDiffusionXLImg2ImgPipeline(**base.components)
for i in range(1, len(lines) + 1):
    out = d / f"try-{i}.png"
    if (d / f"real-{i}.failed").exists():
        print(f"try-{i} skipped: real failed", flush=True); continue
    if out.exists(): continue
    t = time.time()
    p = (f"1girl, solo, beautiful young adult Japanese woman, 22 years old, black hair, full body, {lines[i-1]}, plain white bikini, barefoot, white background, "
         "anime coloring, two-tone cel shading with a soft halftone, form shadow, reflected light, soft even studio light from upper left, pale skin, light peach skin tone, fair skin, smooth natural skin with soft subtle shading, low contrast, light pinkish beige shadow color, bright skin, clean dark lineart, outline around the whole body, masterpiece, best quality")
    pe, ne, pp, np_ = design.encode_xl(pipe, p, people.NEGATIVE + ", photorealistic, realistic, 3d, photo, skin texture, flat color, no lineart, patchy shadows, striped shadows, shadow stripes, visible ribs, rib lines, dappled light, leaf shadows, sunlight through trees, mottled shadows, dramatic lighting, hard cast shadows, dark skin, tan, muscular, abs, harsh contrast, dirty, color blotches, color noise, colored stains, grunge, rainbow, iridescent, glossy skin, oily skin, shiny skin, specular spots, wet skin, text, signature, watermark, calligraphy, stamp, halftone, screentone dots")
    src = Image.open(d / f"real-{i}.png").convert("RGB")
    if os.environ.get("WHITEBG"):
        # 写真の灰色の壁を残すと、模型が壁に模様や光の筋を描き足した。人物の外を白にしてから渡す
        import edit, numpy as np
        a = np.asarray(src).copy()
        # 部位分けの背景には椅子などの台も入る。消すと座った人が宙に浮いた（回22）ので、壁の色に近い所だけを白にする
        bg = np.asarray(edit.parts(str(d / f"real-{i}.png"))) == 0
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]).astype(float)
        wall = np.median(edge, axis=0)
        # 壁の色に近い所に加えて、色の無い（灰色の）所も白にする。壁の影を残すと筆の跡のような模様を描き足した（回24）
        near = (np.abs(a.astype(float) - wall).max(-1) < 40) | ((a.max(-1).astype(int) - a.min(-1)) < 28)
        # 残す背景は人物に触れている塊（腰掛けなど）だけ。人物から離れた影や壁の染みを残すと、模型が影の人形や模様に描き直した（回28）
        from scipy import ndimage
        keep = bg & ~near
        lab, n = ndimage.label(keep)
        touch = ndimage.binary_dilation(~bg, iterations=3)
        ids = np.unique(lab[touch & keep])
        a[bg & ~np.isin(lab, ids[ids > 0])] = 255
        src = Image.fromarray(a)
    if os.environ.get("TONE"):
        # 写実の明暗の位置をそのまま段の影に置き換えてから描き直させる（影の位置を模型に決めさせない）
        import toneshade, edit, numpy as np
        a = np.asarray(src, dtype=np.float32) / 255
        seg = np.asarray(edit.parts(str(d / f"real-{i}.png")))
        L = edit.LABELS
        # 顔と髪は写実のまま残す（平らにすると目鼻が消えた）。背景は白にする（灰色の壁を残すと模様を描き足した）
        body = np.isin(seg, [L["left_arm"], L["right_arm"], L["left_leg"], L["right_leg"]])
        # 部位分けは水着の胴の肌を顔（face）と読む。人物の上から 13% より下の face は胴として扱う
        ys = np.nonzero(seg != 0)[0]
        cut = int(ys.min() + 0.13 * (ys.max() - ys.min()))
        lower_face = (seg == L["face"]) & (np.arange(seg.shape[0])[:, None] > cut)
        body |= lower_face
        tn = toneshade.shade(a, body, 3, float(os.environ.get("SOFT", "0")))
        tn[seg == 0] = 1.0
        src = Image.fromarray((tn * 255).astype(np.uint8))
        src.save(d / f"tone-{i}.png")
    im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
              image=src, strength=strength, num_inference_steps=int(32 / strength) + 1,
              guidance_scale=6.0, generator=torch.Generator().manual_seed(s + i)).images[0]
    im.save(out); open(d / f"try-{i}.txt", "w").write(f"{lines[i-1]}\nseed {s+i}\nreal->anime strength {strength}\n")
    print(f"try-{i} {time.time()-t:.0f}s", flush=True)
print("ALLDONE", flush=True)
