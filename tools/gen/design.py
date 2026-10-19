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
import functools
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 描く部品（torch、diffusers）は .cache/gen/lib にある。PYTHONPATH を付け忘れると torch が読めず止まったので、自分で通す
_LIB = ROOT / ".cache" / "gen" / "lib"
if _LIB.exists() and str(_LIB) not in sys.path:
    sys.path.append(str(_LIB))


def hub_defaults():
    """模型の置き場所（HF_HOME）と、取りに行かない既定（HF_HUB_OFFLINE）を決める。利用者が環境変数で決めた値は変えない。
    模型は既定で外から取りに行かない。呼んだ関数が手元に無い模型を指していると、数 GB を取りに行って
    ディスクを埋めた（2026-10-14 に 2 回）。初めて取るときだけ CD_FETCH=1 を付けて動かす。
    huggingface_hub は読み込んだ時の環境変数を定数に写すので、diffusers を先に読んだ呼び出し元（6周目の run.py）では
    環境変数を足しても効かず、模型を ~/.cache/huggingface へ取りに行った。読み込み済みなら定数も書き換え、読む順番に左右されなくする"""
    mine = {k: k not in os.environ for k in ("HF_HOME", "HF_HUB_OFFLINE")}
    home = os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
    offline = os.environ.setdefault("HF_HUB_OFFLINE", "0" if os.environ.get("CD_FETCH") == "1" else "1") == "1"
    c = sys.modules.get("huggingface_hub.constants")
    if c is None:
        return
    if mine["HF_HOME"] and not os.environ.get("HF_HUB_CACHE") and not os.environ.get("HUGGINGFACE_HUB_CACHE"):
        c.HF_HOME, c.HF_HUB_CACHE = home, os.path.join(home, "hub")
        c.HF_ASSETS_CACHE = os.path.join(home, "assets")
    if mine["HF_HUB_OFFLINE"]:
        # diffusers は定数を自分の名前に写して持つものがある（LoRA の読み込みなど）。読み込み済みのものも合わせる
        for name in ("huggingface_hub.constants", "diffusers.loaders.lora_base", "diffusers.utils.hub_utils",
                     "diffusers.models.attention_dispatch"):
            m = sys.modules.get(name)
            if m is not None and hasattr(m, "HF_HUB_OFFLINE"):
                m.HF_HUB_OFFLINE = offline


hub_defaults()

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
    # monster64: 等身を保つ解像度高めのモンスターのドット絵（携帯機以降の育成ゲームの戦闘画面の大きさ）。
    # 数字は手本で数えていない（未確認）
    "monster64": {"height": 64, "colors": 24, "mode": True},
    # monster96: モンスターのドット絵の標準（利用者の評価: 96 は良い感じ。64 は白い体の顔がつぶれた）
    "monster96": {"height": 96, "colors": 24, "mode": True},
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
# 生き物でない物（卵、道具）。モンスターの決まり文句（feral、creature design、作品の「鋭い目」）を付けると、
# 卵に目と脚が生えて生き物になった（DigiMon の卵、2026-10-03）。kind: "item" は SDXL 系で、物として描く
XL_ITEM_SUFFIX = (", single object, still life, centered, full view, 2d game item illustration, cel shading, "
                  "clean lineart, flat colors, white background")
XL_ITEM_NEGATIVE = ("eyes, face, mouth, creature, animal, character, person, legs, feet, arms, hands, wings, tail, "
                    "multiple objects, cropped, text, watermark")
# 手足の無い塊の生き物（幼年期のスライム形態など）。生き物の決まり文句（creature design、full body、feral）で
# 描くと、「腕なし、脚なし」と書いても腕・脚・翼・尾が付いた。物の決まり文句なら塊になったが、物の打ち消しに
# 目と顔があるので顔と胸の印が出なかった（DigiMon の幼年期、2026-10-06）。kind: "blob" は物の文で形を取り、
# 顔は打ち消さず、手足だけを打ち消す
XL_BLOB_SUFFIX = (", single round creature, full view, centered, 2d game monster illustration, cel shading, "
                  "clean lineart, flat colors, white background")
XL_BLOB_NEGATIVE = ("legs, feet, arms, hands, fingers, claws, wings, tail, neck, standing, sitting, "
                    "multiple creatures, cropped, text, watermark")
# 性別。指定が無いとアニメの人物向けのモデルは少女を描き、男性の職まで女性になった。
# 「1boy」だけでは中性的な美形に寄った（学んだ絵に多い）ので、男性は体と顔の骨格から書く
GENDER = {"male": ("1boy, male focus, adult man, broad shoulders, strong jawline, thick neck, short hair, masculine, ",
                   "1girl, female, breasts, skirt, androgynous, feminine face, long eyelashes, bishounen, makeup"),
          "female": ("1girl, adult woman, feminine, ", ""),
          # 中性的: 男女どちらとも読める顔と体。性別の印（胸、髭、化粧）を打ち消す
          "androgynous": ("1person, androgynous, gender-neutral face, flat chest, short layered hair, ",
                          "breasts, beard, makeup, very muscular")}
# 年齢。頭身と顔の骨格で描き分ける。adult（既定）は GENDER の書き方のまま
AGE = {"child": ("young child, about 7 years old, small body, big head, short legs, chubby cheeks, 4 heads tall, ",
                 "adult, teenager, tall, long legs, mature, beard, breasts, makeup"),
       "teen": ("teenager, about 16 years old, slim youthful body, ", "old, wrinkles, beard"),
       "adult": ("", ""),
       "middle": ("middle-aged, about 45 years old, mature face, slight wrinkles, ", "child, teenager, young face"),
       "elder": ("elderly, about 70 years old, wrinkled face, grey hair, slightly hunched, ",
                 "young, child, smooth skin")}
# 素体の肌着と打ち消し。服は後から着せ替えるので、素体は体の線が見える簡素な無地のものにそろえる
BODY_WEAR = {"male": "plain grey tank top, plain grey shorts, barefoot, plain grey background",
             "female": "plain grey sports top, plain grey shorts, barefoot, plain grey background",
             "androgynous": "plain grey tank top, plain grey shorts, barefoot, plain grey background"}
BODY_NEGATIVE = ("cape, coat, jacket, armor, scarf, belt, bag, weapon, props, jewelry, scenery, background objects, "
                 "creature in background, extra character, nude, nsfw")
# 中年と老人は SDXL 系で描く。アニメの人物向けのモデルは、言葉を強めても女性の老人を若い顔で描いた
OLD_AGES = {"middle", "elder"}
# 年齢の形容は性別の名詞に直接付ける（「elderly woman」）。離して書くと若い顔に戻った
XL_AGE = {"child": ("young", "child about 7 years old, "), "teen": ("teenage", ""), "adult": ("", ""),
          "middle": ("middle-aged", "about 45 years old, slight wrinkles, "),
          "elder": ("elderly", "about 70 years old, deep wrinkles, ")}
XL_HUMAN_SUFFIX = (", full body, standing, character design, 2d anime style illustration, cel shading, clean lineart, "
                   "white background")
XL_HUMAN_NEGATIVE = "nsfw, nude, cropped, multiple views, text, watermark, extra fingers, bad anatomy"
# 女性の老人は、アニメの人物向けのモデルが若い女性に寄せた（白髪の若い女性になった）。祖母の言葉で強める
ELDER_FEMALE = "old woman, grandmother, deep wrinkles, sagging cheeks, white hair in a bun, "


@functools.lru_cache(maxsize=2)
def _pipe(style, img2img=False):
    """模型は 1 回だけ読む。draw は 1 枚ごとに呼ばれ、読み直すと 1 枚に読み込みの時間が足された"""
    import torch
    from diffusers import LCMScheduler, StableDiffusionImg2ImgPipeline, StableDiffusionPipeline
    torch.set_num_threads(os.cpu_count() or 4)
    if style in XL:
        from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
        # bfloat16: float32 では 2 つの文章の読み手と合わせてメモリが 15GB に収まらない。この CPU は bf16 の命令を持つ
        import device
        pipe = StableDiffusionXLPipeline.from_pretrained(STYLES[style], variant="fp16", torch_dtype=device.dtype(torch))
        # 少ない段数で描く版のモデル。作者の推奨（DPM++ SDE Karras、4〜6 段、guidance 2）に合わせる
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="sde-dpmsolver++",
                                                                 use_karras_sigmas=True)
        return device.place(pipe, torch)
    cls = StableDiffusionImg2ImgPipeline if img2img else StableDiffusionPipeline
    pipe = cls.from_pretrained(STYLES[style], torch_dtype=torch.float32, safety_checker=None)
    # LCM-LoRA: 25 段かかるところを 6 段で描く。CPU で1枚 約1分（512x768、4 コア）
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    # 名前を明示する。省くと取得済みでもオフラインの既定（HF_HUB_OFFLINE=1）で読めずに落ちた
    pipe.load_lora_weights(LCM_LORA, weight_name="pytorch_lora_weights.safetensors")
    pipe.fuse_lora()
    import device
    return device.place(pipe, torch)


def split_tokens(tok, text, size=75):
    """指示文をトークンにし、size 個以下の区切りに分ける。区切りは size に届く手前の最後の読点で切る。
    ちょうど 75 個目で切ると、決まり文句の「clean lineart」が「clean」と「lineart」に割れ、別の区切りで読まれた（7周目、80 トークン）。
    読点が無いほど長い言葉だけは size で切る。verbose=False は、区切って読むので不要な「77 を超えた」警告を出さないため"""
    ids = tok(text, add_special_tokens=False, verbose=False).input_ids
    comma = tok(",", add_special_tokens=False, verbose=False).input_ids
    comma = comma[0] if len(comma) == 1 else None
    out = []
    while len(ids) > size:
        cut = max((i + 1 for i in range(size) if ids[i] == comma), default=size)
        out.append(ids[:cut])
        ids = ids[cut:]
    if ids or not out:
        out.append(ids)
    return out


def encode(pipe, prompt, negative):
    """77 トークンで切らずに、長い指示文を 75 トークン以下の区切り（読点で切る）に分けて読ませ、つなげて渡す。

    SD1.5 の文章の読み手（CLIP）は 77 トークンまでしか読まない。世界観の決まりと人物の細部を
    両方書くと後ろが切れて、角灯や白い背景が絵から落ちた。区切りごとに頭と終わりの印を付けて読み、
    横につなげる（区切りの数は指示文と打ち消しの文でそろえる）。
    """
    import torch
    tok, enc = pipe.tokenizer, pipe.text_encoder
    body = [split_tokens(tok, t) for t in (prompt, negative)]
    n = max(1, *[len(b) for b in body])
    out = []
    for parts in body:
        chunks = []
        for i in range(n):
            c = parts[i] if i < len(parts) else []
            c = [tok.bos_token_id] + c + [tok.eos_token_id] * (76 - len(c))
            with torch.no_grad():
                chunks.append(enc(torch.tensor([c]))[0])
        out.append(torch.cat(chunks, dim=1))
    return out


WEIGHTED = re.compile(r"\(([^():]+):([0-9]*\.?[0-9]+)\)")


def split_weighted(tok, text, size=75):
    """「(short skirt:1.5)」の形で重みを付けた指示文を、split_tokens と同じ区切りに分け、トークンごとの重みも返す。
    重みの無い所は 1.0。打ち消しに「short skirt」を入れても指示文と同じ重みでしか効かず、
    丈の長い服を頼んだ 11 枚すべてが短いスカートになったので、言葉ごとに強められるようにした"""
    ids, ws, pos = [], [], 0
    for m in list(WEIGHTED.finditer(text)) + [None]:
        plain = text[pos:m.start()] if m else text[pos:]
        for seg, w in ((plain, 1.0),) + (((m.group(1), float(m.group(2))),) if m else ()):
            t = tok(seg, add_special_tokens=False, verbose=False).input_ids if seg.strip() else []
            ids += t
            ws += [w] * len(t)
        if m:
            pos = m.end()
    comma = tok(",", add_special_tokens=False, verbose=False).input_ids
    comma = comma[0] if len(comma) == 1 else None
    out = []
    while len(ids) > size:
        cut = max((i + 1 for i in range(size) if ids[i] == comma), default=size)
        out.append((ids[:cut], ws[:cut]))
        ids, ws = ids[cut:], ws[cut:]
    if ids or not out:
        out.append((ids, ws))
    return out


def encode_xl(pipe, prompt, negative):
    """SDXL 系の2つの文章の読み手それぞれで、長い指示文を 75 トークン以下の区切り（読点で切る）に分けて読み、つなげて渡す。

    SDXL 系も 77 トークンまでしか読まない。DigiMon の作風（鋭い目、角張った輪郭）を共通に足したら
    41 枚すべてで後ろの「2D アニメの塗り、白い背景」が切れ、背景の入った絵になった。
    返すのは (指示文, 打ち消し, 指示文の要約, 打ち消しの要約)。要約（pooled）は最初の区切りから取る。
    """
    import torch
    pairs = [(pipe.tokenizer, pipe.text_encoder), (pipe.tokenizer_2, pipe.text_encoder_2)]
    ids = [[split_weighted(tok, t) for t in (prompt, negative)] for tok, _ in pairs]
    n = max(1, *[len(b) for per in ids for b in per])
    embeds, pooled = [[], []], [None, None]
    for (tok, enc), per in zip(pairs, ids):
        for k, body in enumerate(per):
            chunks = []
            for i in range(n):
                c, w = body[i] if i < len(body) else ([], [])
                pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
                c = [tok.bos_token_id] + c + [tok.eos_token_id] + [pad] * (75 - len(c))
                w = [1.0] + w + [1.0] * (76 - len(w))
                with torch.no_grad():
                    out = enc(torch.tensor([c]), output_hidden_states=True)
                h = out.hidden_states[-2]
                if any(x != 1.0 for x in w):
                    # 重みを掛けたあと、区切り全体の平均を元に戻す。平均ごと動くと絵全体の調子が変わるため
                    mean = h.mean()
                    h = h * torch.tensor(w, dtype=h.dtype).view(1, -1, 1)
                    h = h * (mean / h.mean())
                chunks.append(h)
                if enc is pipe.text_encoder_2 and i == 0:
                    pooled[k] = out[0]
            embeds[k].append(torch.cat(chunks, dim=1))
    dt = pipe.unet.dtype
    pe, ne = (torch.cat(e, dim=-1).to(dt) for e in embeds)
    return pe, ne, pooled[0].to(dt), pooled[1].to(dt)


# draw の構図。upper は手や持ち物を確かめる絵のため。全身では手が 60〜100 画素しかなく、手の形が描けたかを読めなかった。
# portrait（close-up）にすると手が枠の外に出るので付けない
FRAMING = {"full": PREFIX, "upper": PREFIX.replace("full body, standing, ", "upper body, ")}


def draw(out, prompt, seed, n, style, steps, width, height, kind="human", negative="", framing="full", scene=False):
    import torch
    pipe = _pipe(style)
    # 人用の決まり文句（character design, standing）のまま動物を頼むと、獣の耳の少女になる
    if kind == "creature" and style in XL:
        # SDXL は言葉で書く。アニメのタグ（no humans, feral）は効かない
        head, tail, neg = "", XL_CREATURE_SUFFIX, XL_CREATURE_NEGATIVE
        if " style" in prompt:
            # 画風を頼まれたら、決まり文句のアニメ塗りで上書きしない
            tail = ", full body, creature design, white background"
    elif kind == "creature":
        head, tail, neg = CREATURE_PREFIX, CREATURE_SUFFIX, NEGATIVE + ", " + CREATURE_NEGATIVE
    elif scene:
        # 既定の「全身・白地」は、構図や場所や持ち物を頼んだ言葉とぶつかり、持ち物ごと落ちる。scene では外す
        head, tail, neg = PREFIX.replace("full body, standing, ", ""), "", NEGATIVE
    else:
        # 人は構図（全身か上半身）で決まり文句を変える
        head, tail, neg = FRAMING[framing], SUFFIX, NEGATIVE
    # 既定の打ち消しに足す。年齢の見え方（child, round face など）を絵ごとに抑えるため
    neg = ", ".join(x for x in (neg, negative) if x)
    paths = []
    for i in range(n):
        t = time.time()
        g = torch.Generator().manual_seed(seed + i)
        if style in XL:
            # SDXL は要約（pooled）も渡さないと止まる。guidance は batch の XL と同じ 2.0
            pe, ne, pp, np_ = encode_xl(pipe, head + prompt + tail, neg)
            im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                      negative_pooled_prompt_embeds=np_, num_inference_steps=steps,
                      guidance_scale=2.0, width=width, height=height, generator=g).images[0]
        else:
            pe, ne = encode(pipe, head + prompt + tail, neg)
            im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, num_inference_steps=steps,
                      guidance_scale=1.5, width=width, height=height, generator=g).images[0]
        p = out if n == 1 else str(Path(out).with_suffix("")) + f"-{seed + i}.png"
        im.save(p)
        meta = {"prompt": prompt, "negative": negative, "seed": seed + i, "style": style, "model": STYLES[style], "steps": steps, "framing": framing}
        Path(p + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(p)
        print(f"{p}: {time.time() - t:.1f} 秒")
    return paths


def hires(path, prompt, seed, style, scale=1.5, strength=0.35, steps=6, negative=""):
    """描いた全身の絵を scale 倍に引き伸ばし、同じ模型・同じ言葉で弱く描き直す（hires fix）。
    初めから大きく描かせると人物が増えたり形が崩れたりするので、得意な大きさで構図を決めてから細部を足す。
    SD1.5 系は描いた模型の部品をそのまま使い、模型を 2 度読まない"""
    import torch
    from diffusers import StableDiffusionImg2ImgPipeline
    from PIL import Image
    if style in XL:
        import hires as hr
        return hr.upscale(path, path, prompt, negative, scale, strength, seed=seed)
    import hires as hr
    import tile
    pipe = StableDiffusionImg2ImgPipeline(**_pipe(style).components)
    im = Image.open(path).convert("RGB")
    w, h = int(im.width * scale) // 8 * 8, int(im.height * scale) // 8 * 8
    big = im.resize((w, h), Image.LANCZOS)
    pe, ne = encode(pipe, FRAMING["full"] + prompt + SUFFIX, ", ".join(x for x in (NEGATIVE, negative) if x))
    out = big
    # 姿勢が変わった描き直しは弱めて描き直し、それでも変わるなら引き伸ばしただけの絵を使う（hires.upscale と同じ決まり）
    for st in (strength, strength * tile.RETRY):
        # LCM は strength × 段数 しか回らない。段数を strength で割り、描き直す段数を元の段数にそろえる
        n = max(steps, round(steps / max(st, 0.1)))
        cand = pipe(image=big, strength=st, prompt_embeds=pe, negative_prompt_embeds=ne,
                    num_inference_steps=n, guidance_scale=1.5, generator=torch.Generator().manual_seed(seed)).images[0]
        if tile.drift(big, cand, scale=hr.POSE_SCALE) <= tile.DRIFT:
            out = cand
            break
    out.save(path)
    return out.size


def load_cast(path):
    """設定集を読む。common は全員の指示文の後ろに付ける（作品の世界観と画風を全員でそろえるため）。

    人物の指示文を先に置く。先頭の言葉ほど強く効き、共通の配色が人物の服の色を上書きしたため。
    """
    cast = json.loads(Path(path).read_text(encoding="utf-8"))
    for c in cast["characters"]:
        # モンスターには人向けの世界観（服や頭身の決まり）を付けない。creature_common が別にある
        if c.get("kind") == "creature":
            common = cast.get("creature_common", cast.get("common", ""))
        elif c.get("kind") == "item":
            # 物には生き物の決まり（目、顔つき）も人の決まりも付けない。item_common だけ
            common = cast.get("item_common", "")
        elif c.get("kind") == "blob":
            # 塊の生き物に creature_common を付けると手足を呼ぶ言葉が混ざるので、作風だけの blob_common を使う
            common = cast.get("blob_common", "")
        else:
            common = cast.get("common", "")
        c["full_prompt"] = c["prompt"] + (", " + common if common else "")
    return cast


TRAITS = json.loads((Path(__file__).parent / "traits.json").read_text(encoding="utf-8"))


PATTERNS = json.loads((ROOT / "casts" / "patterns.json").read_text(encoding="utf-8"))["patterns"]


def trait_texts(c):
    """設定集の traits（"分類:種類" の並び）と patterns（casts/patterns.json の名前）を、指示文と打ち消しの言葉にする。
    知らない種類や名前は止める（黙って無視すると、効かなかったのか書き間違いなのか分からない）。"""
    ps, ns = [], []
    traits = list(c.get("traits", []))
    for name in c.get("patterns", []):
        if name not in PATTERNS:
            raise SystemExit(f"{c.get('id')}: patterns の {name} が casts/patterns.json に無い")
        traits += PATTERNS[name].get("traits", [])
        if PATTERNS[name].get("prompt"):
            ps.append(PATTERNS[name]["prompt"])
        if PATTERNS[name].get("negative"):
            ns.append(PATTERNS[name]["negative"])
    for t in traits:
        cat, _, key = t.partition(":")
        if cat not in TRAITS or key not in TRAITS[cat]:
            raise SystemExit(f"{c.get('id')}: traits の {t} が tools/gen/traits.json に無い")
        ps.append(TRAITS[cat][key]["p"])
        if TRAITS[cat][key].get("neg"):
            ns.append(TRAITS[cat][key]["neg"])
    return ", ".join(ps), ", ".join(ns)


def full_texts(c, style="anime"):
    """1人ぶんの指示文と打ち消しの文。人でない者と性別で、決まり文句を切り替える。"""
    tp, tn = trait_texts(c)
    if tp:
        # 描き分けの部品は人物の説明の前に置く（先頭の言葉ほど強く効く）
        c = {**c, "full_prompt": tp + ", " + c["full_prompt"],
             "negative": ", ".join(x for x in (c.get("negative", ""), tn) if x)}
    if c.get("kind") == "item":
        neg = ", ".join(x for x in (XL_ITEM_NEGATIVE, c.get("negative", "")) if x)
        return c["full_prompt"] + XL_ITEM_SUFFIX, neg
    if c.get("kind") == "blob":
        neg = ", ".join(x for x in (XL_BLOB_NEGATIVE, c.get("negative", "")) if x)
        return c["full_prompt"] + XL_BLOB_SUFFIX, neg
    if c.get("kind") == "creature" and style in XL:
        neg = ", ".join(x for x in (XL_CREATURE_NEGATIVE, c.get("negative", "")) if x)
        return c["full_prompt"] + XL_CREATURE_SUFFIX, neg
    if style in XL:
        # SDXL 系の人。タグではなく言葉で書く（SDXL 系は 1boy などのタグで学んでいない）
        who = {"male": "man", "female": "woman", "androgynous": "androgynous person"}.get(c.get("gender"), "person")
        if c.get("framing") == "body":
            c = {**c, "full_prompt": c["full_prompt"] + ", " + BODY_WEAR.get(c.get("gender"), BODY_WEAR["male"]),
                 "negative": ", ".join(x for x in (c.get("negative", ""), BODY_NEGATIVE) if x)}
        adj, detail = XL_AGE.get(c.get("age", "adult"), ("", ""))
        if c.get("age") == "elder" and c.get("gender") == "female":
            detail += "grandmother, sagging cheeks, white hair in a bun, "
        neg = ", ".join(x for x in (XL_HUMAN_NEGATIVE, AGE.get(c.get("age", "adult"), ("", ""))[1], c.get("negative", "")) if x)
        return f"{adj} {who} ".lstrip() + c["full_prompt"] + ", " + detail + XL_HUMAN_SUFFIX.lstrip(", "), neg
    if c.get("kind") == "creature":
        head, tail, neg = CREATURE_PREFIX, CREATURE_SUFFIX, CREATURE_NEGATIVE
    else:
        g = GENDER.get(c.get("gender"), ("", ""))
        a = AGE.get(c.get("age", "adult"), ("", ""))
        gp, gn = g
        if c.get("age") in ("child", "teen"):
            # 子どもと十代に「adult man / adult woman」と骨格の言葉を付けない（年齢の指定と食い違う）
            gp = {"male": "1boy, male, ", "female": "1girl, female, "}.get(c.get("gender"), gp)
        if c.get("age") == "elder" and c.get("gender") == "female":
            gp = "1girl, " + ELDER_FEMALE
        prefix = PREFIX
        if c.get("framing") == "body":
            # 素体: 体の部品（肌、鱗、刺青、体型）を服に引っ張られずに見るため、簡素な無地の肌着で描く。
            # 服を着た姿で試すと、肌の色や質感の言葉が服や背景に移った（青い肌 → 青い服、鱗 → 背後の蛇）
            prefix = PREFIX.replace("full body, standing, ", "full body, standing straight, arms slightly away from body, body reference, ")
            wear = BODY_WEAR.get(c.get("gender"), BODY_WEAR["male"])
            c = {**c, "full_prompt": c["full_prompt"] + ", " + wear,
                 "negative": ", ".join(x for x in (c.get("negative", ""), BODY_NEGATIVE) if x)}
        if c.get("framing") == "portrait":
            # 顔の部品（輪郭、鼻、耳、目）は全身の絵では小さすぎて描かれない。胸から上で描く
            prefix = PREFIX.replace("full body, standing, ", "upper body, portrait, close-up, ")
        head, tail, neg = prefix + gp + a[0], "", ", ".join(x for x in (gn, a[1]) if x)
    return head + c["full_prompt"] + tail + SUFFIX, ", ".join(x for x in (NEGATIVE, neg, c.get("negative", "")) if x)


def cast_paths(cast, outdir, style=None):
    """設定集の1人ごとに、描く絵（パス, seed, 画風）を返す。

    画像生成のモデルは描いた絵を見直さない（くちばしが2つ、途切れた脚）。機械の検品は絵を捨てず、
    直す所の印（<絵>.json の marks）を付けて残す。機械が落とした絵を一覧から外すと、人が魅力を感じた絵まで消えた。
    設定集の rejected（{"画像の名前": "理由"}）は、利用者が要らないと決めた絵だけを書く所で、その絵は数に入れずに描き足す。

    人は style（設定集の style、無ければ anime）だけで、モンスターは CREATURE_STYLES の全部で描く。
    anime 以外の画風の絵は名前に画風を入れる（id-real-7.png）。
    """
    base = style or cast.get("style", "anime")
    for c in cast["characters"]:
        seed, n = c.get("seed", 7), c.get("n", cast.get("n", 2))
        styles = c.get("styles") or (CREATURE_STYLES if c.get("kind") in ("creature", "item", "blob")
                                     else ["xl"] if c.get("age") in OLD_AGES else [base])
        rejected = c.get("rejected", {})
        shots = []
        for st in styles:
            tag = "" if st == "anime" else f"{st}-"
            # 利用者が要らないと決めた絵（rejected のキーは画像の名前）は数に入れず、次の seed で描き足す
            s, got = seed, 0
            while got < n:
                name = f"{c['id']}-{tag}{s}.png"
                if name not in rejected:
                    shots.append((Path(outdir) / name, s, st))
                    got += 1
                s += 1
        yield c, shots


def base_image(cast, c, outdir):
    """系統のベース（from に書いた人物）の決定稿の絵。決定稿（chosen）が無ければ None。"""
    if not c.get("from"):
        return None
    from PIL import Image
    b = next((x for x in cast["characters"] if x["id"] == c["from"]), None)
    if not b or "chosen" not in b:
        return None
    tag = "xl-" if b.get("kind") == "creature" else ""
    p = Path(outdir) / f"{b['id']}-{tag}{b['chosen']}.png"
    return Image.open(p).convert("RGB") if p.exists() else None


def batch(cast_path, outdir, style, steps, width, height, kind=None):
    import torch
    cast = load_cast(cast_path)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    todo = [(c, p, seed, st) for c, shots in cast_paths(cast, outdir, style) for p, seed, st in shots
            if not p.exists() and (kind is None or (c.get("kind") in ("creature", "blob")) == (kind == "creature"))]
    print(f"{len(todo)} 枚を描く")
    # 下絵（init_dir/<id>.png）がある人物は、その形の上に描く（img2img）。文章だけでは手足の数や
    # 「手足の無い塊」を守らせきれなかった。strength が小さいほど下絵の形が残る
    init_dir = cast.get("init_dir")
    strength = cast.get("init_strength", 0.75)
    # モデルの読み込みは画風ごとに1回にする
    for st in dict.fromkeys(t[3] for t in todo):
        pipe = _pipe(st)
        # 系統の派生: "from" に書いたベースの決定稿（chosen）を手本として読ませる（IP-Adapter）。
        # 系統ごとに別々に描くと、同じ系統で違う生き物が生まれたため。手本の強さは from_scale（既定 0.6）
        if st in XL and any(t[0].get("from") for t in todo if t[3] == st):
            pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                 weight_name="ip-adapter_sdxl_vit-h.safetensors",
                                 image_encoder_folder="models/image_encoder")
        i2i = None
        if init_dir and st in XL:
            from diffusers import StableDiffusionXLImg2ImgPipeline
            i2i = StableDiffusionXLImg2ImgPipeline(**pipe.components)
        for c, p, seed, _ in [t for t in todo if t[3] == st]:
            t = time.time()
            text, neg = full_texts(c, st)
            g = torch.Generator().manual_seed(seed)
            if st in XL:
                pe, ne, pp, np_ = encode_xl(pipe, text, neg)
                kw = dict(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                          negative_pooled_prompt_embeds=np_, guidance_scale=2.0, generator=g)
                ref = base_image(cast, c, outdir)
                if ref is not None:
                    pipe.set_ip_adapter_scale(c.get("from_scale", cast.get("from_scale", 0.6)))
                    kw["ip_adapter_image"] = ref
                elif c.get("from"):
                    print(f"  注意: {c['id']} の手本（{c['from']} の決定稿）が無いので、手本なしで描く", flush=True)
                init = Path(init_dir) / f"{c['id']}.png" if i2i else None
                if init and init.exists():
                    from PIL import Image
                    # 下絵の縦横比を保つ（正方形に引き伸ばすと人物が横に太った）。SDXL 系は 8 の倍数の大きさで描く
                    base = Image.open(init).convert("RGB")
                    k = 1024 / max(base.size)
                    base = base.resize((round(base.width * k / 8) * 8, round(base.height * k / 8) * 8))
                    # img2img は strength×段数しか描かないので、段数を増やして描く段を保つ
                    im = i2i(image=base, strength=c.get("init_strength", strength),
                             num_inference_steps=max(steps, int(round(steps / c.get("init_strength", strength)))),
                             **kw).images[0]
                else:
                    im = pipe(num_inference_steps=steps, width=768, height=1024, **kw).images[0]
            else:
                pe, ne = encode(pipe, text, neg)
                im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, num_inference_steps=steps, guidance_scale=1.5,
                          width=width, height=height, generator=g).images[0]
            im.save(p)
            meta = {"name": c.get("name", c["id"]), "prompt": text, "negative": neg, "seed": seed, "style": st,
                    "model": STYLES[st], "steps": steps}
            note = ""
            if c.get("kind") not in ("creature", "item", "blob"):
                meta["inspect"], meta["marks"] = check_person(p)
                # ここは形の検品（edit.inspect）だけ。作画監督の検品は描き終えたあとなので、結果は最後の行に出す
                note = "  形: " + "、".join(meta["inspect"]) if meta["inspect"] else "  形の外れなし"
            Path(str(p) + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{p}: {time.time() - t:.1f} 秒{note}", flush=True)
        del pipe
    # 顔の崩れ（目の左右、正面に戻すと歪む顔）は、描く模型を手放してから顔の描き直しを自動でかける。
    # 描く模型と描き直す模型を同時に持たないため、描き終えたあとにまとめて行う
    people = [t[1] for t in todo if t[0].get("kind") not in ("creature", "item") and t[1].exists()]
    if people:
        auto_face_fix(people)
    # 結果の行は <絵>.json の marks から作る。描いた直後の行は作画監督の検品より前なので、7周目で marks に印がある
    # 2枚を「外れなし」と出した
    for p in people:
        print(result_line(p), flush=True)


def result_line(p):
    """<絵>.json の marks と顔の描き直しの結果から、1枚の結果の行を作る"""
    f = Path(str(p) + ".json")
    meta = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    whats = list(dict.fromkeys(m.get("what", "?") for m in meta.get("marks", [])))
    line = f"結果 {p}: " + (f"直す所 {len(whats)}（" + "、".join(whats) + "）" if whats else "外れなし")
    ff = meta.get("facefix")
    if ff:
        line += "  顔の描き直し: " + ("採るかの判定なし" if "adopted" not in ff else "採った" if ff["adopted"]
                                     else "採らない（" + ff.get("why", "") + "）")
    return line


# edit.inspect の理由のうち、構図そのものの崩れ（人がいない、2人目や離れた物、体が画面の端で切れた）。部分の描き直しでは直らない
LAYOUT_WORDS = ("人物が写っていない", "離れた物", "端で切れている")


def person_marks(reasons):
    """edit.inspect の理由を、直す所の印（qc.marks と同じ形）にする。"""
    return [{"what": r, "kind": "layout" if any(w in r for w in LAYOUT_WORDS) else "fix",
             "repair": "none" if any(w in r for w in LAYOUT_WORDS) else "inpaint", "where": r} for r in reasons]


def check_person(p):
    """人の絵を機械で検品し、(理由, 直す所の印) を返す。絵は捨てず、外れがあっても背景を白に消して並べる。

    背景の物（蛇、猫、狼、影）と、欠けた手足・二重の人物・画面で切れた体を数える。構図の崩れには kind layout の印を付ける。
    元の絵は <名前>.raw.png に残す。
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import shutil
    import edit
    reasons = edit.inspect(str(p))
    shutil.copy(p, str(p).replace(".png", ".raw.png"))
    # 2人目や離れた物がある絵は、背景を消すと片方が消えて崩れが見えなくなる。元のまま残す
    if not any("離れた物" in r or "写っていない" in r for r in reasons):
        edit.clean_background(str(p))
    return reasons, person_marks(reasons)


def _excess(m):
    """印の数字が決まりの範囲からどれだけ外れているか（範囲内は 0）。数字の無い印は 1（読めない）"""
    w = m.get("where")
    v = w.get("value") if isinstance(w, dict) else None
    if not isinstance(v, (int, float)):
        return 1.0
    lo, hi = w.get("min"), w.get("max")
    return max((lo - v) if lo is not None else 0, (v - hi) if hi is not None else 0, 0)


def face_worse(before, after):
    """顔を描き直す前後の印を比べ、悪くなった所を返す（空なら悪くなっていない）。
    顔の印（repair が face_fix）が新しく出た、または範囲からの外れが大きくなったものを数える。
    ok（外れが1つも無い）だけで比べると、外れが減っても残る限り直しが効いたか分からなかった"""
    was = {m.get("what"): _excess(m) for m in before if m.get("repair") == "face_fix"}
    out = []
    for m in after:
        if m.get("repair") != "face_fix":
            continue
        k, e = m.get("what"), _excess(m)
        if k not in was:
            out.append(f"{k} が新しく出た")
        elif e > was[k] + 1e-9:
            w = m.get("where")
            v = w.get("value") if isinstance(w, dict) else None
            out.append(f"{k} {v}" if v is not None else f"{k} が悪くなった")
    return out


def auto_face_fix(paths, fix=None, check=None):
    """描いた絵を作画監督（qc.auto_check）にかけ、直せる顔の崩れ（repair が face_fix の印）があれば顔を描き直す。
    直した絵は <名前>.facefix.png に置き、元の絵は残す。直した絵も同じ検品にかけ、結果を <絵>.json の facefix に書く。
    fix と check は試験で差し替える（既定は imgproc.face_fix と qc.auto_check）"""
    sys.path.insert(0, str(Path(__file__).parent))
    if check is None:
        import qc
        check = qc.auto_check
    if fix is None:
        import imgproc
        fix = imgproc.face_fix
    done = {}
    for p in paths:
        meta_path = Path(str(p) + ".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        res = check(str(p), meta.get("prompt", ""))
        if res.get("held"):  # 固定の制限に当たった絵は qc.hold が held/ へ移した。ここでは触らない
            continue
        meta["marks"] = meta.get("marks", []) + res.get("marks", [])
        if res.get("differences"):
            meta["differences"] = res["differences"]
        if any(m.get("repair") == "face_fix" for m in res.get("marks", [])):
            out = str(p).replace(".png", ".facefix.png")
            r = fix(str(p), out)
            if r.get("fixed"):
                after = check(out, meta.get("prompt", ""))
                r = {**r, "file": Path(out).name, "ok": after.get("ok"), "marks": after.get("marks", [])}
                worse = face_worse(res.get("marks", []), after.get("marks", []))
                r["adopted"] = not worse
                if worse:
                    # 直したあとの方が悪い絵は採らない。7周目は 4 枚とも外れが残り、1 枚は face.rms が 0.091 → 0.181 に悪くなった。
                    # 悪い方を置いておくと、一覧や次の手順が誤って拾うので、名前を変えて元の絵を正とする
                    rej = Path(out).with_suffix(".rejected.png")
                    Path(out).replace(rej)
                    r.update(file=rej.name, why="直したあとの方が悪い: " + "、".join(worse))
                    meta["marks"].append({"what": "face_fix_rejected", "kind": "fix", "repair": "none",
                                          "where": {"worse": worse, "file": rej.name}, "unreadable": False})
            else:
                r["adopted"] = False
            meta["facefix"] = r
            done[str(p)] = r
            print(f"{p}: 顔を描き直した → {r.get('file', '')} {'採った' if r.get('adopted') else '採らない ' + r.get('why', '')}",
                  flush=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return done


FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"


def mark_label(p):
    """一覧図に書く印。構図の崩れがあれば「構図」、直す所があれば「直す N」、無ければ空"""
    f = Path(str(p) + ".json")
    marks = json.loads(f.read_text(encoding="utf-8")).get("marks", []) if f.exists() else []
    layout = sum(m.get("kind") == "layout" for m in marks)
    fix = len(marks) - layout
    return "、".join(x for x in (f"構図 {layout}" if layout else "", f"直す {fix}" if fix else "") if x)


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
            # 機械の検品で外れた絵も並べ、直す所の印を左上に書く（構図の崩れは別の印）
            text = mark_label(p)
            if text:
                d.rectangle((label + i * thumb, y, label + i * thumb + d.textlength(text, font=small) + 8, y + 22), fill="white")
                d.text((label + i * thumb + 4, y + 2), text, fill=(200, 0, 0), font=small)
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


def cut_background(im, tol=24, step=4):
    """背景を透明にする。四辺から塗り広げ、となりの画素との差が step 以下なら背景として続ける。

    四隅の色と比べるだけでは、灰色のグラデーションと床の影が抜けなかった（SDXL 系の絵）。
    背景はなだらかに色が変わり、人物は輪郭で急に色が変わるので、となりとの差で止める。
    彩度の高い画素（tol*2 を超える）には入らない。輪郭の無い白い部分は抜ける恐れがあるので、絵で確かめる。
    """
    from PIL import Image
    im = im.convert("RGBA")
    W, H = im.size
    px = im.load()
    seen = set()
    stack = [(x, y, None) for x in range(W) for y in (0, H - 1)] + [(x, y, None) for y in range(H) for x in (0, W - 1)]
    while stack:
        x, y, prev = stack.pop()
        if (x, y) in seen or not (0 <= x < W and 0 <= y < H):
            continue
        c = px[x, y][:3]
        if prev is not None and sum(abs(a - b) for a, b in zip(c, prev)) > step * 3:
            continue
        # 背景は彩度が低い（灰色・白）。色の付いた画素に入ったら止める。明るさの変化（後光、影）は許す
        if max(c) - min(c) > tol * 2:
            continue
        seen.add((x, y))
        stack += [(x + 1, y, c), (x - 1, y, c), (x, y + 1, c), (x, y - 1, c)]
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


def pixel(src, out, height, colors, heads=None, smooth=0, mode=False):
    """絵からドット絵を作る。描画器の後半と同じ考え方（縮小 → 減色 → 外側に暗い輪郭 → 孤立ドットの掃除）。

    smooth: 縮める前に色の面をならす強さ（最頻値フィルタの大きさ、0 でならさない）。SDXL 系の絵は質感の
    描き込みが多く、そのまま縮めると細かい色の粒になって濁った。
    """
    from PIL import Image, ImageFilter
    sys.path.insert(0, str(ROOT / "tools"))
    import build
    im = keep_largest(cut_background(Image.open(src)))
    bb = im.getchannel("A").getbbox()
    im = im.crop(bb)
    if heads:
        im = deform(im, heads)
    if smooth:
        a = im.getchannel("A")
        im = im.convert("RGB").filter(ImageFilter.ModeFilter(smooth)).convert("RGBA")
        im.putalpha(a)
    w = max(1, round(im.width * height / im.height))
    W, H = w + 2, height + 2
    grid = [[None] * W for _ in range(H)]
    if mode:
        # 先に大きいまま減色し、区画の中でいちばん多い色を取る。平均して縮めると境目に中間色が生まれ、
        # 細かい色の粒になった（孤立ドット率 0.067 → 0.013、DigiMon の5体、高さ 64）
        from collections import Counter
        a = im.getchannel("A").load()
        q = im.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT).convert("RGB").load()
        bx, by = im.width / w, im.height / height
        for y in range(height):
            for x in range(w):
                cnt, tot = Counter(), 0
                for yy in range(int(y * by), max(int(y * by) + 1, int((y + 1) * by))):
                    for xx in range(int(x * bx), max(int(x * bx) + 1, int((x + 1) * bx))):
                        tot += 1
                        if a[xx, yy] >= 128:
                            cnt[q[xx, yy]] += 1
                if cnt and sum(cnt.values()) * 2 >= tot:
                    grid[y + 1][x + 1] = "#%02x%02x%02x" % cnt.most_common(1)[0][0]
    else:
        # 縮小は箱で平均する。最近傍で拾うと1ドットの線が途切れる
        small = im.resize((w, height), Image.BOX)
        alpha = small.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        rgb = small.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT).convert("RGB")
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
    d.add_argument("--width", type=int)
    d.add_argument("--height", type=int)
    d.add_argument("--kind", default="human", choices=["human", "creature"])
    d.add_argument("--negative", default="", help="既定の打ち消しに足す言葉")
    d.add_argument("--framing", choices=list(FRAMING), default="full", help="upper は上半身（手を確かめる絵）")
    d.add_argument("--scene", action="store_true", help="全身・白地の決まり文句を外す（構図・場所・持ち物を言葉で決めるとき）")
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
    p.add_argument("--smooth", type=int, default=None, help="縮める前に色の面をならす強さ（例 9）")
    p.add_argument("--mode", action="store_true", help="区画の中でいちばん多い色で縮める（色の粒が減る）")
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
        # 四足は縦長の画面だと立ち上がって脚が欠ける。動物は横長を既定にする
        w, h = (768, 512) if a.kind == "creature" else (512, 768)
        draw(a.out, a.prompt, a.seed, a.n, a.style, a.steps, a.width or w, a.height or h, a.kind, a.negative, a.framing, a.scene)
    elif a.cmd == "restyle":
        restyle(a.src, a.out, a.style, a.strength, a.steps, a.prompt)
    else:
        # 作風を指定しないときは変形しない。既定を箱庭ドットにしていた頃は、高さだけ指定しても
        # 2.8 頭身への変形が黙ってかかり、モンスターの角や耳が横に寝た
        pre = PRESETS[a.preset] if a.preset else {"height": 34, "colors": 32}
        pixel(a.src, a.out, a.height or pre["height"], a.colors or pre["colors"], a.heads or pre.get("heads"),
              a.smooth if a.smooth is not None else pre.get("smooth", 0), a.mode or pre.get("mode", False))


if __name__ == "__main__":
    main()
