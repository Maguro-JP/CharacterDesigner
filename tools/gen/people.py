"""人の設定資料（正面・背面・横と、特徴の部位の拡大）を、アニメ絵のタグを学んだ SDXL のモデルで描く。

これまでのアニメ風（SD1.5 系）は、耳・角・翼・尾・肌を言葉どおりに描けず、背景や服に移した。
老人だけ別のモデルで描いて画風もそろわなかった（docs/knowledge/traits.md）。
Animagine XL 3.1（CreativeML OpenRAIL++-M、2026-10-04 に公開元で確認）はアニメ絵のタグ（pointy ears、dragon tail、old woman）を学んでおり、
1つのモデルで年齢も種族もそろった画風で描けた。少ない段数で描く仕組みは無く、CPU で1枚 約3分。

描いた絵は毎回 edit.inspect で検品し、落ちたら seed を変えて描き直す（最大 3 回）。通った絵は背景を白に消す。

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/people.py card <出力フォルダ> <名前> --gender male --age adult \
      [--tags "elf, pointy ears"] [--zoom head] [--views front,back] [--base ideal]
--base は casts/body-types.json の anime にある体のベース。女性は ideal（利用者が決めた基準の体）を使う
  PYTHONPATH=.cache/gen/lib python3 tools/gen/people.py sheet <出力フォルダ> <一覧図.png>
--zoom は拡大する部位: head（耳・角・顔）、arms（腕の肌・刺青）、back（背中・翼）、tail（腰から下の後ろ）、none
"""
import cdhome
import argparse
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(cdhome.HOME / "gen" / "hf"))
# 模型は既定で外から取りに行かない。呼んだ関数が手元に無い模型を指していると、数 GB を取りに行って
# ディスクを埋めた（2026-10-14 に 2 回）。初めて取るときだけ CD_FETCH=1 を付けて動かす
os.environ.setdefault("HF_HUB_OFFLINE", "0" if os.environ.get("CD_FETCH") == "1" else "1")
sys.path.insert(0, str(Path(__file__).parent))
# 模型の置き場所（.cache/gen/hf）と取りに行かない既定を、diffusers・transformers を読む前に効かせる。
# 関数の中で design を読んでいたため、先に transformers を読んだ呼び出しでは ~/.cache/huggingface へ取りに行った
import design  # noqa: E402,F401

# 描く模型は tools/gen/models.py の一覧で作風ごとに決める（config/models.json、無ければ animagine-xl-4.0）。
# CD_DRAW_MODEL を付けると、その場だけ入れ替えられる。CD_STYLE で作風を選ぶ（既定 anime）
import models as _models
MODEL = _models.for_style(os.environ.get("CD_STYLE", "anime"))
QUALITY = "masterpiece, best quality, very aesthetic, absurdres"
NEGATIVE = ("nsfw, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, "
            "worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, "
            "artist name, multiple views, background objects, scenery, animal, extra character")
# 素体: 体の線が見える無地の肌着、素足、無地の背景。服は後から着せ替える
BODY = "full body, standing, arms at sides, white background, simple background, barefoot, grey tank top, grey shorts"
# 向き。「from front」は効かず真横を向いたので、正面は見る人の方を向く言葉で書く
VIEWS = {"front": "facing viewer, looking at viewer, straight-on, front view",
         # 「from behind」だけでは横向きや正面向きになることが多かった（羊・鼠・牛）。背中がこちらを向くことを重ねて書く
         "back": "from behind, back view, facing away, back facing viewer, view from directly behind",
         "side": "from side, profile",
         # 斜めの2方向。多角的な設定資料に使う（正面・斜め前・横・斜め後ろ・背面）
         "front34": "three-quarter view, body turned slightly to the side, looking at viewer",
         "back34": "from behind, back view, body turned slightly to the side, back facing viewer, facing away"}
VIEW_JA = {"front": "正面", "front34": "斜め前", "side": "横", "back34": "斜め後ろ", "back": "背面"}
GENDER = {"male": "1boy, male focus", "female": "1girl"}
AGE = {"child": "child, young", "teen": "teenage", "adult": "adult", "middle": "mature, middle-aged",
       "elder": "old, wrinkled skin, grey hair"}
AGE_GENDER = {("elder", "male"): "old man", ("elder", "female"): "old woman",
              ("child", "male"): "boy, shota", ("child", "female"): "girl, loli"}
FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
_PIPE = None
_IP = False  # 手本（IP-Adapter）を読み込んだか


def pipe():
    global _PIPE
    if _PIPE is None:
        import torch
        from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionXLPipeline
        import device
        # GPU があれば使う（tools/gen/device.py）。CPU のときは今までどおり bfloat16 で全部のコアを使う
        _PIPE = _models.load(os.environ.get("CD_STYLE", "anime"))
        _PIPE.scheduler = EulerAncestralDiscreteScheduler.from_config(_PIPE.scheduler.config)
        device.place(_PIPE, torch)
    return _PIPE


_CONTROL = None
DEPTH_MODEL = "diffusers/controlnet-depth-sdxl-1.0-small"   # openrail++。奥行きだけの小さい型（fp16 で約 320MB）
CONTROL_MODEL = "xinsir/controlnet-union-sdxl-1.0"   # Apache-2.0。奥行き・線・関節を1つの模型で扱う（promax 版、約 2.5GB）


def control_pipe():
    """姿勢の下絵（奥行き）で形を縛って描く部品。描く本体と文章の読み手は pipe() と同じものを共有する"""
    global _CONTROL
    if _CONTROL is None:
        import torch
        from diffusers import ControlNetUnionModel, StableDiffusionXLControlNetUnionPipeline
        import device
        base = pipe()
        shared = {k: v for k, v in base.components.items() if k in (
            "vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "unet", "scheduler",
            "feature_extractor", "image_encoder")}
        try:
            cn = ControlNetUnionModel.from_pretrained(CONTROL_MODEL, filename="diffusion_pytorch_model_promax.safetensors",
                                                      config_file_name="config_promax.json", torch_dtype=device.dtype(torch))
            device.module(cn, torch)
            _CONTROL = StableDiffusionXLControlNetUnionPipeline(**shared, controlnet=cn)
            _CONTROL.cd_union = True
        except OSError:
            # まとめの模型（約 2.5GB）を取っていない手元では、奥行きだけの小さい模型（約 320MB、取る台本が取る）で縛る。
            # 取っていないと、画面で下絵を選んだ仕事が config.json が無いと止まった（2026-10-20）
            from diffusers import ControlNetModel, StableDiffusionXLControlNetPipeline
            cn = ControlNetModel.from_pretrained(DEPTH_MODEL, variant="fp16", torch_dtype=device.dtype(torch))
            device.module(cn, torch)
            _CONTROL = StableDiffusionXLControlNetPipeline(**shared, controlnet=cn)
            _CONTROL.cd_union = False
        _CONTROL.vae.enable_tiling()
    return _CONTROL


def clothed(clothes):
    """素体の体の言葉の、肌着と素足だけを服の言葉に差し替える（立ち方と無地の背景はそのまま）。空なら素体のまま。"""
    if not clothes:
        return BODY
    return BODY.replace("barefoot, grey tank top, grey shorts", clothes)


_DEPTH = None


def depth_img2img():
    """下絵の色から描き直しつつ、奥行きの絵で体の形を縛る部品。描く本体と文章の読み手は pipe() と同じものを共有する。
    描き直しの強さだけでは、描く模型が腕の長さを自分の癖で決めた（下絵の 1.2〜1.4 倍）"""
    global _DEPTH
    if _DEPTH is None:
        import torch
        from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
        import device
        cn = ControlNetModel.from_pretrained(DEPTH_MODEL, variant="fp16", torch_dtype=device.dtype(torch))
        device.module(cn, torch)
        base = pipe()
        _DEPTH = StableDiffusionXLControlNetImg2ImgPipeline(**{k: v for k, v in base.components.items() if k in (
            "vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "unet", "scheduler",
            "feature_extractor", "image_encoder")}, controlnet=cn)
        _DEPTH.vae.enable_tiling()
    return _DEPTH


def prompt_of(gender, age, tags, hair, view, body=BODY):
    who = AGE_GENDER.get((age, gender), "")
    parts = [GENDER[gender], "solo", who, AGE[age], tags, hair, body, VIEWS[view], QUALITY]
    return ", ".join(p for p in parts if p)


def use_reference():
    """手本の絵を読ませる部品（IP-Adapter）を1回だけ読み込む。"""
    global _IP
    if not _IP:
        pipe().load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                               weight_name="ip-adapter_sdxl_vit-h.safetensors",
                               image_encoder_folder="models/image_encoder")
        _IP = True


# 手本から色と画風だけを受け取る強さ（InstantStyle の層の指定）。全体に 0.4 を掛けると、背面に描くはずの絵が
# 手本と同じ正面向きになった。形と向きを決める層には効かせず、画風の層（up の block_0 の2番目）にだけ効かせる
STYLE_ONLY = {"up": {"block_0": [0.0, 1.0, 0.0]}}


def draw(out, prompt, seed, steps=24, limbs=True, body=None, negative="", ref=None, ref_scale=STYLE_ONLY):
    """1枚描いて検品する。落ちたら seed を変えて描き直す（最大 3 回）。通った絵は背景を白に消す。"""
    import torch
    import edit
    for k in range(3):
        t = time.time()
        # 指示文は 77 トークンで切れる（ラミアなどは向きの指定まで切れた）。分けて読ませる
        import design
        pe, ne, pp, np_ = design.encode_xl(pipe(), prompt, NEGATIVE + (", " + negative if negative else ""))
        kw = {}
        if _IP:
            # 手本を読み込んだ後は毎回絵を渡す必要がある。手本の無い絵は強さ 0 にして白い絵を渡す
            from PIL import Image as _I
            pipe().set_ip_adapter_scale(ref_scale if ref is not None else 0.0)
            kw["ip_adapter_image"] = ref if ref is not None else _I.new("RGB", (224, 224), "white")
        im = pipe()(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                    negative_pooled_prompt_embeds=np_, num_inference_steps=steps, guidance_scale=6.0,
                    width=832, height=1216, generator=torch.Generator().manual_seed(seed + k * 100), **kw).images[0]
        im.save(out)
        reasons = edit.inspect(out, limbs)
        print(f"{out}: {time.time() - t:.0f} 秒 seed {seed + k * 100} " + ("通った" if not reasons else "落とした: " + "、".join(reasons)),
              flush=True)
        if not reasons:
            im.save(str(out).replace(".png", ".raw.png"))
            edit.clean_background(out)
            return seed + k * 100, []
    return seed + 200, reasons


# 完成の1枚絵で使う打ち消し。設定資料の打ち消しから、背景を消す言葉（背景の物、景色、動物）と多面図を外す
SCENE_NEGATIVE = NEGATIVE.replace("multiple views, background objects, scenery, animal, ", "")


def scene(out, prompt, seed, negative="", ref=None, ref_scale=STYLE_ONLY, steps=28, tries=3):
    """背景つきの完成の1枚絵を描く。設定資料の絵（ref）を手本にして、同じ人物の画風と色を保つ。

    設定資料の検品（背景の塊、画面の端）は背景があると必ず落ちるので使わない。
    手足が揃っているか（部位分け）だけを機械で見て、残りは目で見る。背景は消さない。
    """
    import torch
    import edit
    import design
    from PIL import Image as _I
    if ref is not None:
        use_reference()
    for k in range(tries):
        t = time.time()
        pe, ne, pp, np_ = design.encode_xl(pipe(), prompt, SCENE_NEGATIVE + (", " + negative if negative else ""))
        kw = {}
        if _IP:
            pipe().set_ip_adapter_scale(ref_scale if ref is not None else 0.0)
            kw["ip_adapter_image"] = ref if ref is not None else _I.new("RGB", (224, 224), "white")
        im = pipe()(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                    negative_pooled_prompt_embeds=np_, num_inference_steps=steps, guidance_scale=6.0,
                    width=832, height=1216, generator=torch.Generator().manual_seed(seed + k * 100), **kw).images[0]
        path = str(out).replace(".png", f"-try{k}.png")
        im.save(path)
        import numpy as np
        lab = np.asarray(edit.parts(path))
        reasons = [n for n, ids in (("左腕", [14]), ("右腕", [15]), ("左脚", [12]), ("右脚", [13])) if not np.isin(lab, ids).any()]
        print(f"{path}: {time.time() - t:.0f} 秒 seed {seed + k * 100} " + ("通った" if not reasons else "落とした: " + "、".join(reasons)),
              flush=True)
        if not reasons:
            im.save(out)
            return seed + k * 100, []
    return None, reasons


def zoom_box(src, where):
    """拡大する範囲。部位分けで頭・腕を探す。背中と尾は人物の範囲の上半分・下半分。"""
    import edit
    lab = edit.parts(src)
    fg = edit.foreground(src)
    x0, y0, x1, y1 = fg.getbbox()
    if where == "head":
        # 顔を中心に、顔の高さの 2.2 倍を半径にする。髪まで含めると長い髪が腰まであり、全身ほどの範囲になった。
        # 耳や角は顔より上と横に出るので、中心を少し上にずらす
        # 顔は人物の上 1/6（頭1つ分）の中でだけ探す。肌の多い服（水着）では、体の肌まで顔として拾われ、拡大が上半身全体になった
        top = y0 + (y1 - y0) // 6
        face = lab.point(lambda v: 255 if v == 11 else 0)
        face.paste(0, (0, top, face.width, face.height))
        b = face.getbbox()
        if b:
            fh = max(b[3] - b[1], b[2] - b[0])
            cx, cy, r = (b[0] + b[2]) // 2, b[1] + fh // 4, fh * 1.4
        else:
            cx, cy, r = (x0 + x1) // 2, y0 + (y1 - y0) // 10, (y1 - y0) // 7
    elif where == "arms":
        b = lab.point(lambda v: 255 if v in (14, 15) else 0).getbbox() or (x0, y0, x1, y1)
        cx, cy, r = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2, max(b[2] - b[0], b[3] - b[1]) * 0.6
    elif where == "back":
        cx, cy, r = (x0 + x1) // 2, y0 + (y1 - y0) // 3, max(x1 - x0, (y1 - y0) // 2) * 0.6
    elif where == "tail":
        cx, cy, r = (x0 + x1) // 2, y0 + (y1 - y0) * 2 // 3, max(x1 - x0, (y1 - y0) // 2) * 0.6
    else:
        return None
    return (int(cx - r), int(cy - r), int(cx + r), int(cy + r))


def base(name):
    """casts/body-types.json の anime にある体のベース（tags、body、negative、seed）を返す。"""
    return json.loads((ROOT / "casts" / "body-types.json").read_text(encoding="utf-8"))["anime"][name]


def base_body(b, outfit=""):
    """ベースの体の言葉。outfit を渡すと、ベースの白いビキニの部分だけを差し替える（体型の言葉は変えない）。"""
    if not outfit:
        return b["body"]
    keep = [t.strip() for t in b["body"].split(",") if "bikini" not in t and t.strip() != "no logo"]
    return ", ".join(keep + [outfit, "no logo"])


def card(outdir, name, gender, age, tags, hair, views, zoom, seed, label, limbs=True, body=BODY, negative="",
         same_as_front=True):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    shots, meta = [], {"name": name, "label": label, "gender": gender, "age": age, "tags": tags, "views": {}}
    for v in views:
        p = outdir / f"{name}-{v}.png"
        text = prompt_of(gender, age, tags, hair, v, body)
        # 検品を通った絵だけが .raw.png を持つ。3回とも落ちた向きは .failed.json に理由を残し、
        # 再開したときに同じ seed で同じ失敗を繰り返さない（九尾は尾が画面からはみ出して6回落ちた）
        failed = p.with_suffix(".failed.json")
        if failed.exists():
            used, reasons = json.loads(failed.read_text(encoding="utf-8"))
        elif not p.with_suffix(".raw.png").exists():
            # 正面以外は、正面の絵を手本にして描く（色と画風だけ）。向きごとに一から描くと、服の色や耳の形が正面と食い違った
            ref = None
            front = outdir / f"{name}-front.raw.png"
            if same_as_front and v != "front" and front.exists():
                use_reference()
                ref = Image.open(front).convert("RGB")
            used, reasons = draw(p, text, seed, limbs=limbs, negative=negative, ref=ref)
            if reasons:
                failed.write_text(json.dumps([used, reasons], ensure_ascii=False), encoding="utf-8")
        else:
            used, reasons = seed, []
        meta["views"][v] = {"prompt": text, "seed": used, "inspect": reasons, "file": p.name}
        shots.append((v, p, reasons))
    # 設定資料の1枚: 向きごとの全身と、特徴の部位の拡大
    H = 640
    tiles = []
    for v, p, reasons in shots:
        im = Image.open(p).convert("RGB")
        tiles.append((VIEW_JA[v] + ("（落とした）" if reasons else ""),
                      im.resize((int(im.width * H / im.height), H))))
    if zoom != "none":
        # 尾の拡大も正面から取る。背面から取ると、水着の体ではお尻への寄りになり、尾の付け根より体が主役になった
        src = shots[0][1] if zoom in ("head", "arms", "tail") else next((p for v, p, _ in shots if v == "back"), shots[0][1])
        box = zoom_box(str(src), zoom)
        if box:
            # 画面の外まで切り取ると黒く埋まるので、白い台紙に貼ってから切り取る
            base = Image.open(src).convert("RGB")
            pad = Image.new("RGB", (base.width + 2 * H, base.height + 2 * H), "white")
            pad.paste(base, (H, H))
            z = pad.crop((box[0] + H, box[1] + H, box[2] + H, box[3] + H)).resize((H, H))
            tiles.append(({"head": "頭の拡大", "arms": "腕の拡大", "back": "背中の拡大", "tail": "腰の拡大"}[zoom], z))
    W = sum(t.width for _, t in tiles) + 10 * (len(tiles) - 1)
    sheet = Image.new("RGB", (W, H + 70), "white")
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype(FONT, 26)
    d.text((10, 6), label, fill="black", font=f)
    x = 0
    for cap, t in tiles:
        sheet.paste(t, (x, 70))
        d.text((x + 8, 40), cap, fill=(90, 90, 90), font=ImageFont.truetype(FONT, 20))
        x += t.width + 10
    sheet.save(outdir / f"{name}-card.png")
    (outdir / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{outdir / (name + '-card.png')}")
    return meta


# 多面図: 1枚の絵に同じ人物を正面・横・背面で並べて描かせる。向きごとに別々に描くと耳の形・翼の有無・服の色が
# 食い違った（犬・竜・悪魔・狸）。アニメ絵のモデルは設定資料の多面図を学んでおり、1枚の中なら揃いやすい
SHEET = ("character reference sheet, multiple views, front view and back view, same character shown several times, "
         "full body, standing, arms at sides")
SHEET_SIZE = (1216, 832)


def figures(src):
    """多面図に並んだ人物の左右の範囲を、背景を抜いた絵の列の途切れから求める。"""
    import numpy as np
    import design
    alpha = np.asarray(design.cut_background(Image.open(src)).getchannel("A")) > 0
    cols = alpha.sum(axis=0) > alpha.shape[0] * 0.02
    spans, start = [], None
    for x, on in enumerate(list(cols) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start > alpha.shape[1] * 0.04:
                spans.append((start, x))
            start = None
    return spans


def draw_sheet(out, prompt, seed, steps=24, negative=""):
    """多面図を1枚描いて検品する。人物が3人以上並び、画面の端で切れていなければ通す（最大 3 回）。"""
    import torch
    import edit
    import design
    neg = NEGATIVE.replace("multiple views, ", "") + ", different characters, mismatched outfits" + (", " + negative if negative else "")
    for k in range(3):
        t = time.time()
        pe, ne, pp, np_ = design.encode_xl(pipe(), prompt, neg)
        kw = {}
        if _IP:
            pipe().set_ip_adapter_scale(0.0)
            kw["ip_adapter_image"] = Image.new("RGB", (224, 224), "white")
        im = pipe()(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                    negative_pooled_prompt_embeds=np_, num_inference_steps=steps, guidance_scale=6.0,
                    width=SHEET_SIZE[0], height=SHEET_SIZE[1], generator=torch.Generator().manual_seed(seed + k * 100),
                    **kw).images[0]
        im.save(out)
        n = len(figures(out))
        reasons = [r for r in edit.inspect(out, limbs=False) if r.startswith("体が画面の端")]
        if n < 3:
            reasons.append(f"並んだ人物が {n} 人")
        print(f"{out}: {time.time() - t:.0f} 秒 seed {seed + k * 100} " + ("通った" if not reasons else "落とした: " + "、".join(reasons)),
              flush=True)
        if not reasons:
            im.save(str(out).replace(".png", ".raw.png"))
            edit.clean_background(out)
            return seed + k * 100, []
    return seed + 200, reasons


def sheet_card(outdir, name, gender, age, tags, hair, seed, label, body=BODY, negative="", zoom="head"):
    """多面図1枚と、いちばん左の人物の頭の拡大を並べた設定資料を作る。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir / f"{name}-sheet.png"
    body = ", ".join(t.strip() for t in body.split(",") if t.strip() not in ("full body", "standing", "arms at sides"))
    who = AGE_GENDER.get((age, gender), "")
    text = ", ".join(x for x in [GENDER[gender], "solo", who, AGE[age], SHEET, tags, hair, body, QUALITY] if x)
    failed = p.with_suffix(".failed.json")
    if failed.exists():
        used, reasons = json.loads(failed.read_text(encoding="utf-8"))
    elif not p.with_suffix(".raw.png").exists():
        used, reasons = draw_sheet(p, text, seed, negative=negative)
        if reasons:
            failed.write_text(json.dumps([used, reasons], ensure_ascii=False), encoding="utf-8")
    else:
        used, reasons = seed, []
    H = 640
    sheet = Image.open(p).convert("RGB")
    tiles = [("多面図" + ("（落とした）" if reasons else ""), sheet.resize((int(sheet.width * H / sheet.height), H)))]
    spans = figures(p)
    if zoom == "head" and spans:
        # いちばん左の人物だけを切り出して、頭の範囲を探す
        x0, x1 = spans[0]
        one = outdir / f"{name}-first.png"
        sheet.crop((x0, 0, x1, sheet.height)).save(one)
        box = zoom_box(str(one), "head")
        if box:
            pad = Image.new("RGB", (sheet.width + 2 * H, sheet.height + 2 * H), "white")
            pad.paste(sheet, (H, H))
            tiles.append(("頭の拡大", pad.crop((box[0] + x0 + H, box[1] + H, box[2] + x0 + H, box[3] + H)).resize((H, H))))
    W = sum(t.width for _, t in tiles) + 10 * (len(tiles) - 1)
    im = Image.new("RGB", (W, H + 70), "white")
    d = ImageDraw.Draw(im)
    d.text((10, 6), label, fill="black", font=ImageFont.truetype(FONT, 26))
    x = 0
    for cap, t in tiles:
        im.paste(t, (x, 70))
        d.text((x + 8, 40), cap, fill=(90, 90, 90), font=ImageFont.truetype(FONT, 20))
        x += t.width + 10
    im.save(outdir / f"{name}-card.png")
    meta = {"name": name, "label": label, "prompt": text, "seed": used, "inspect": reasons, "figures": len(spans)}
    (outdir / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(outdir / f"{name}-card.png")
    return meta


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("card")
    c.add_argument("outdir")
    c.add_argument("name")
    c.add_argument("--gender", choices=list(GENDER), required=True)
    c.add_argument("--age", choices=list(AGE), default="adult")
    c.add_argument("--tags", default="")
    c.add_argument("--hair", default="")
    c.add_argument("--views", default="front,back")
    c.add_argument("--zoom", default="head", choices=["head", "arms", "back", "tail", "none"])
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--label", default="")
    c.add_argument("--base", default="", help="casts/body-types.json の anime にある体のベース（例: ideal）")
    c.add_argument("--outfit", default="", help="ベースの水着を差し替える服の言葉（例: \"pink frilled bikini\"）。体の言葉はそのまま")
    c.add_argument("--clothes", default="", help="素体の肌着と素足を差し替える服と靴の言葉（--base を使わないとき。casts/fashion.json の見本）")
    a = ap.parse_args()
    hair = a.hair or ("short black hair" if a.gender == "male" else "black hair, bob cut")
    if a.base:
        b = base(a.base)
        tags = ", ".join(t for t in (b["tags"], a.tags) if t)
        card(a.outdir, a.name, a.gender, a.age, tags, hair, a.views.split(","), a.zoom, a.seed if a.seed != 7 else b["seed"],
             a.label or a.name, body=base_body(b, a.outfit), negative=b["negative"])
        return
    card(a.outdir, a.name, a.gender, a.age, a.tags, hair, a.views.split(","), a.zoom, a.seed, a.label or a.name,
         body=clothed(a.clothes))


if __name__ == "__main__":
    main()
