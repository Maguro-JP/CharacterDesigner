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
  python3 tools/gen/design.py pixel in.png out.sprite.json [--preset diorama|survivor|retro16|chibi16] [--height N] [--colors N]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py batch casts/<作品>.json <出力フォルダ>
  python3 tools/gen/design.py sheet casts/<作品>.json <出力フォルダ> <一覧図.png>

batch は設定集（casts/*.json）の全員を、モデルを1回だけ読み込んで描く。描き終えた絵は飛ばすので、
途中で止まっても同じコマンドで続きから描ける。sheet は描いた絵を名前付きで1枚に並べる。
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
    # SDXL 系（CreativeML OpenRAIL++-M）。モンスターの体の組み立てが SD1.5 系よりはるかに崩れにくい。
    # CPU で1枚 2〜3 分（768x1024、6 段）
    "xl": "Lykon/dreamshaper-xl-lightning",
}
XL = {"xl"}
LCM_LORA = "latent-consistency/lcm-lora-sdv1-5"
# ドット絵の作風ごとの大きさと色数。等身は元の絵のまま縮める（頭を大きくする変換はまだ無い）
# diorama: 箱庭ドットの人物の高さと色数（styles/diorama.json）
# survivor: 少ない色で等身を保つ見下ろしのアクションの作風。数字は手本で数えていない（未確認）
# retro16 / chibi16: styles/retro16.json と styles/chibi16.json の大きさと色数（どちらも未確認の数字）
PRESETS = {
    "diorama": {"height": 34, "colors": 32, "heads": 2.8},
    "survivor": {"height": 40, "colors": 16},
    "retro16": {"height": 24, "colors": 15},
    "chibi16": {"height": 16, "colors": 12},
}
# 立ち絵の設定資料として描かせる決まり文句。全身・1人・無地の背景にしておくと、派生（ドット絵）で背景を抜ける
PREFIX = "masterpiece, best quality, character design, full body, standing, solo, "
SUFFIX = ", white background, simple background"
NEGATIVE = ("lowres, bad anatomy, bad hands, extra fingers, missing fingers, extra limbs, cropped, "
            "multiple views, text, watermark, signature, blurry, nsfw, nude, naked, nipples, cleavage")
# 人でない者（魔物、妖怪、モンスター）の決まり文句。アニメの人物向けのモデルは、人の立ち姿の決まり文句と
# 合わさると動物や玉の形の者まで少女の姿で描いた。人を描かない指定と、人の特徴の打ち消しを足す
# 「creature design, monster concept art」は人型の怪物を呼んだ。人のいない動物の絵を指す言葉（feral、animal focus）に替え、
# 指示文は動物の名詞から始める（四つ足なら quadruped と書く）
CREATURE_PREFIX = "masterpiece, best quality, full body, solo, no humans, animal focus, feral, "
CREATURE_SUFFIX = ", 2d anime style illustration, cel shading, clean lineart"
CREATURE_NEGATIVE = "1girl, 1boy, human, woman, man, breasts, human face, animal ears, kemonomimi, anthro"
# モンスターは2つのモデルで描いて並べる。アニメのモデルは塗りが設定画らしいが形が崩れやすく、
# リアル寄りのモデルは形が正確だが立体の置物のような塗りになった（亀・子犬・ゴーレムで比べた）
# SDXL 系に替えてからは xl だけで描く（亀・羽毛玉で比べ、SD1.5 系の2つより形も塗りも良かった）
CREATURE_STYLES = ["xl"]
# SDXL 系に渡すモンスターの決まり文句（長い指示文は encode_xl で分けて読む）
XL_CREATURE_SUFFIX = (", full body, creature design, 2d anime style illustration, cel shading, clean lineart, "
                      "flat colors, white background")
XL_CREATURE_NEGATIVE = ("human, humanoid, anthro, 1girl, extra heads, extra legs, extra wings, extra tails, "
                        "fused animals, two animals, cropped, text, watermark, nsfw")
# 性別。指定が無いとアニメの人物向けのモデルは少女を描き、男性の職まで女性になった
GENDER = {"male": ("1boy, male focus, ", "1girl, female, breasts, skirt"),
          "female": ("1girl, ", "")}


def _pipe(style, img2img=False):
    import torch
    from diffusers import LCMScheduler, StableDiffusionImg2ImgPipeline, StableDiffusionPipeline
    torch.set_num_threads(os.cpu_count() or 4)
    if style in XL:
        from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
        # bfloat16: float32 では 2 つの文章の読み手と合わせてメモリが 15GB に収まらない。この CPU は bf16 の命令を持つ
        pipe = StableDiffusionXLPipeline.from_pretrained(STYLES[style], variant="fp16", torch_dtype=torch.bfloat16)
        # 少ない段数で描く版のモデル。作者の推奨（DPM++ SDE Karras、4〜6 段、guidance 2）に合わせる
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="sde-dpmsolver++",
                                                                 use_karras_sigmas=True)
        return pipe
    cls = StableDiffusionImg2ImgPipeline if img2img else StableDiffusionPipeline
    pipe = cls.from_pretrained(STYLES[style], torch_dtype=torch.float32, safety_checker=None)
    # LCM-LoRA: 25 段かかるところを 6 段で描く。CPU で1枚 約1分（512x768、4 コア）
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.load_lora_weights(LCM_LORA)
    pipe.fuse_lora()
    return pipe


def encode(pipe, prompt, negative):
    """77 トークンで切らずに、長い指示文を 75 トークンずつに分けて読ませ、つなげて渡す。

    SD1.5 の文章の読み手（CLIP）は 77 トークンまでしか読まない。世界観の決まりと人物の細部を
    両方書くと後ろが切れて、角灯や白い背景が絵から落ちた。区切りごとに頭と終わりの印を付けて読み、
    横につなげる（区切りの数は指示文と打ち消しの文でそろえる）。
    """
    import torch
    tok, enc = pipe.tokenizer, pipe.text_encoder
    body = [tok(t, add_special_tokens=False).input_ids for t in (prompt, negative)]
    n = max(1, *[(len(b) + 74) // 75 for b in body])
    out = []
    for ids in body:
        chunks = []
        for i in range(n):
            c = ids[i * 75:(i + 1) * 75]
            c = [tok.bos_token_id] + c + [tok.eos_token_id] * (76 - len(c))
            with torch.no_grad():
                chunks.append(enc(torch.tensor([c]))[0])
        out.append(torch.cat(chunks, dim=1))
    return out


def encode_xl(pipe, prompt, negative):
    """SDXL 系の2つの文章の読み手それぞれで、長い指示文を 75 トークンずつ分けて読み、つなげて渡す。

    SDXL 系も 77 トークンまでしか読まない。DigiMon の作風（鋭い目、角張った輪郭）を共通に足したら
    41 枚すべてで後ろの「2D アニメの塗り、白い背景」が切れ、背景の入った絵になった。
    返すのは (指示文, 打ち消し, 指示文の要約, 打ち消しの要約)。要約（pooled）は最初の区切りから取る。
    """
    import torch
    pairs = [(pipe.tokenizer, pipe.text_encoder), (pipe.tokenizer_2, pipe.text_encoder_2)]
    ids = [[tok(t, add_special_tokens=False).input_ids for t in (prompt, negative)] for tok, _ in pairs]
    n = max(1, *[(len(b) + 74) // 75 for per in ids for b in per])
    embeds, pooled = [[], []], [None, None]
    for (tok, enc), per in zip(pairs, ids):
        for k, body in enumerate(per):
            chunks = []
            for i in range(n):
                c = body[i * 75:(i + 1) * 75]
                pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
                c = [tok.bos_token_id] + c + [tok.eos_token_id] + [pad] * (75 - len(c))
                with torch.no_grad():
                    out = enc(torch.tensor([c]), output_hidden_states=True)
                chunks.append(out.hidden_states[-2])
                if enc is pipe.text_encoder_2 and i == 0:
                    pooled[k] = out[0]
            embeds[k].append(torch.cat(chunks, dim=1))
    dt = pipe.unet.dtype
    pe, ne = (torch.cat(e, dim=-1).to(dt) for e in embeds)
    return pe, ne, pooled[0].to(dt), pooled[1].to(dt)


def draw(out, prompt, seed, n, style, steps, width, height):
    import torch
    pipe = _pipe(style)
    paths = []
    for i in range(n):
        t = time.time()
        g = torch.Generator().manual_seed(seed + i)
        pe, ne = encode(pipe, PREFIX + prompt + SUFFIX, NEGATIVE)
        im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, num_inference_steps=steps,
                  guidance_scale=1.5, width=width, height=height, generator=g).images[0]
        p = out if n == 1 else str(Path(out).with_suffix("")) + f"-{seed + i}.png"
        im.save(p)
        meta = {"prompt": prompt, "seed": seed + i, "style": style, "model": STYLES[style], "steps": steps}
        Path(p + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(p)
        print(f"{p}: {time.time() - t:.1f} 秒")
    return paths


def load_cast(path):
    """設定集を読む。common は全員の指示文の後ろに付ける（作品の世界観と画風を全員でそろえるため）。

    人物の指示文を先に置く。先頭の言葉ほど強く効き、共通の配色が人物の服の色を上書きしたため。
    """
    cast = json.loads(Path(path).read_text(encoding="utf-8"))
    for c in cast["characters"]:
        # モンスターには人向けの世界観（服や頭身の決まり）を付けない。creature_common が別にある
        if c.get("kind") == "creature":
            common = cast.get("creature_common", cast.get("common", ""))
        else:
            common = cast.get("common", "")
        c["full_prompt"] = c["prompt"] + (", " + common if common else "")
    return cast


def full_texts(c, style="anime"):
    """1人ぶんの指示文と打ち消しの文。人でない者と性別で、決まり文句を切り替える。"""
    if c.get("kind") == "creature" and style in XL:
        neg = ", ".join(x for x in (XL_CREATURE_NEGATIVE, c.get("negative", "")) if x)
        return c["full_prompt"] + XL_CREATURE_SUFFIX, neg
    if c.get("kind") == "creature":
        head, tail, neg = CREATURE_PREFIX, CREATURE_SUFFIX, CREATURE_NEGATIVE
    else:
        g = GENDER.get(c.get("gender"), ("", ""))
        head, tail, neg = PREFIX + g[0], "", g[1]
    return head + c["full_prompt"] + tail + SUFFIX, ", ".join(x for x in (NEGATIVE, neg, c.get("negative", "")) if x)


def cast_paths(cast, outdir, style=None):
    """設定集の1人ごとに、描く絵（パス, seed, 画風）を返す。

    画像生成のモデルは描いた絵を見直さない（くちばしが2つ、途切れた脚）。描いた絵は目で検品し、
    落とした絵は設定集の rejected に {"画像の名前": "理由"} で書く。理由は docs/knowledge/monster-design.md
    の検品表の言葉で書き、同じ破綻が続けば指示文を直す。

    人は style（設定集の style、無ければ anime）だけで、モンスターは CREATURE_STYLES の全部で描く。
    anime 以外の画風の絵は名前に画風を入れる（id-real-7.png）。
    """
    base = style or cast.get("style", "anime")
    for c in cast["characters"]:
        seed, n = c.get("seed", 7), c.get("n", cast.get("n", 2))
        styles = c.get("styles") or (CREATURE_STYLES if c.get("kind") == "creature" else [base])
        rejected = c.get("rejected", {})
        shots = []
        for st in styles:
            tag = "" if st == "anime" else f"{st}-"
            # 検品で落とした絵（rejected のキーは画像の名前）は数に入れず、次の seed で描き足す
            s, got = seed, 0
            while got < n:
                name = f"{c['id']}-{tag}{s}.png"
                if name not in rejected:
                    shots.append((Path(outdir) / name, s, st))
                    got += 1
                s += 1
        yield c, shots


def batch(cast_path, outdir, style, steps, width, height, kind=None):
    import torch
    cast = load_cast(cast_path)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    todo = [(c, p, seed, st) for c, shots in cast_paths(cast, outdir, style) for p, seed, st in shots
            if not p.exists() and (kind is None or (c.get("kind") == "creature") == (kind == "creature"))]
    print(f"{len(todo)} 枚を描く")
    # モデルの読み込みは画風ごとに1回にする
    for st in dict.fromkeys(t[3] for t in todo):
        pipe = _pipe(st)
        for c, p, seed, _ in [t for t in todo if t[3] == st]:
            t = time.time()
            text, neg = full_texts(c, st)
            g = torch.Generator().manual_seed(seed)
            if st in XL:
                pe, ne, pp, np_ = encode_xl(pipe, text, neg)
                im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                          negative_pooled_prompt_embeds=np_, num_inference_steps=steps, guidance_scale=2.0,
                          width=768, height=1024, generator=g).images[0]
            else:
                pe, ne = encode(pipe, text, neg)
                im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, num_inference_steps=steps, guidance_scale=1.5,
                          width=width, height=height, generator=g).images[0]
            im.save(p)
            meta = {"name": c.get("name", c["id"]), "prompt": text, "negative": neg, "seed": seed, "style": st,
                    "model": STYLES[st], "steps": steps}
            Path(str(p) + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{p}: {time.time() - t:.1f} 秒", flush=True)
        del pipe


FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"


def sheet(cast_path, outdir, out, thumb=256):
    """描いた絵を、1人1行（名前と役割＋seed ごとの絵）で並べた一覧図にする。"""
    from PIL import Image, ImageDraw, ImageFont
    cast = load_cast(cast_path)
    rows = [(c, [p for p, _, _ in shots if p.exists()]) for c, shots in cast_paths(cast, outdir)]
    rows = [(c, ps) for c, ps in rows if ps]
    cols = max(len(ps) for _, ps in rows)
    th = thumb * 3 // 2
    label = 220
    try:
        font, small = ImageFont.truetype(FONT, 22), ImageFont.truetype(FONT, 16)
    except OSError:
        font = small = ImageFont.load_default()
    im = Image.new("RGB", (label + cols * thumb, len(rows) * th), "white")
    d = ImageDraw.Draw(im)
    for r, (c, ps) in enumerate(rows):
        y = r * th
        d.text((10, y + 12), c.get("name", c["id"]), fill="black", font=font)
        line, yy = "", y + 46
        # 役割の説明は枠の幅で折り返す
        for ch in c.get("role", ""):
            if d.textlength(line + ch, font=small) > label - 20:
                d.text((10, yy), line, fill=(80, 80, 80), font=small)
                line, yy = "", yy + 20
            line += ch
        d.text((10, yy), line, fill=(80, 80, 80), font=small)
        for i, p in enumerate(ps):
            im.paste(Image.open(p).convert("RGB").resize((thumb, th), Image.LANCZOS), (label + i * thumb, y))
        d.line((0, y + th - 1, im.width, y + th - 1), fill=(200, 200, 200))
    im.save(out)
    print(f"{out}: {len(rows)} 人, {im.width}x{im.height}")


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
    pe, ne = encode(pipe, PREFIX + (prompt or "") + SUFFIX, NEGATIVE)
    res = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, image=im, strength=strength,
               num_inference_steps=max(steps, int(round(2 / strength))), guidance_scale=1.5,
               generator=torch.Generator().manual_seed(0)).images[0]
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


def deform(im, heads, neck=0.155):
    """頭を大きく、首から下を縦に縮めて、頭身を下げる（7 頭身の絵 → 箱庭ドットの約 2.8 頭身）。

    画像生成のモデルは「デフォルメ」「大きな頭」と書いても約 7 頭身で描いた（指示の効きが弱い）。
    絵の上から neck（頭の高さの割合）で切り、頭を拡大して体を縮める。部品の transforms と同じ考え方。
    """
    from PIL import Image
    W, H = im.size
    n = int(H * neck)
    # heads = 全体 / 頭。頭を k 倍、体を b 倍にして、(n*k + (H-n)*b) / (n*k) = heads にする
    k = 1.7
    b = (heads - 1) * n * k / (H - n)
    hd = im.crop((0, 0, W, n)).resize((int(W * k), int(n * k)), Image.LANCZOS)
    bd = im.crop((0, n, W, H)).resize((W, max(1, int((H - n) * b))), Image.LANCZOS)
    OW = max(hd.width, W)
    o = Image.new("RGBA", (OW, hd.height + bd.height), (0, 0, 0, 0))
    # 首の継ぎ目に隙間が出ないよう、体を頭に2ドット重ねる
    o.alpha_composite(bd, ((OW - W) // 2, hd.height - 2))
    o.alpha_composite(hd, ((OW - hd.width) // 2, 0))
    return o


def pixel(src, out, height, colors, heads=None):
    """絵からドット絵を作る。描画器の後半と同じ考え方（縮小 → 減色 → 外側に暗い輪郭 → 孤立ドットの掃除）。"""
    from PIL import Image
    sys.path.insert(0, str(ROOT / "tools"))
    import build
    im = keep_largest(cut_background(Image.open(src)))
    bb = im.getchannel("A").getbbox()
    im = im.crop(bb)
    if heads:
        im = deform(im, heads)
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
    p.add_argument("--preset", choices=list(PRESETS), default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--colors", type=int, default=None)
    p.add_argument("--heads", type=float, default=None, help="頭身を下げる（箱庭ドットは 2.8）。省くと元の絵のまま")
    b = sub.add_parser("batch")
    b.add_argument("cast")
    b.add_argument("outdir")
    b.add_argument("--style", default=None, choices=list(STYLES), help="省くと設定集の style（無ければ anime）")
    b.add_argument("--steps", type=int, default=6)
    b.add_argument("--width", type=int, default=512)
    b.add_argument("--height", type=int, default=768)
    b.add_argument("--kind", choices=["human", "creature"], default=None, help="人だけ、モンスターだけを描く")
    s = sub.add_parser("sheet")
    s.add_argument("cast")
    s.add_argument("outdir")
    s.add_argument("out")
    s.add_argument("--thumb", type=int, default=256)
    a = ap.parse_args()
    if a.cmd == "batch":
        batch(a.cast, a.outdir, a.style, a.steps, a.width, a.height, a.kind)
    elif a.cmd == "sheet":
        sheet(a.cast, a.outdir, a.out, a.thumb)
    elif a.cmd == "draw":
        draw(a.out, a.prompt, a.seed, a.n, a.style, a.steps, a.width, a.height)
    elif a.cmd == "restyle":
        restyle(a.src, a.out, a.style, a.strength, a.steps, a.prompt)
    else:
        pre = PRESETS[a.preset or "diorama"]
        pixel(a.src, a.out, a.height or pre["height"], a.colors or pre["colors"], a.heads or pre.get("heads"))


if __name__ == "__main__":
    main()
