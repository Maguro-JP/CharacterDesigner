"""人の設定資料（正面・背面・横と、特徴の部位の拡大）を、アニメ絵のタグを学んだ SDXL のモデルで描く。

これまでのアニメ風（SD1.5 系）は、耳・角・翼・尾・肌を言葉どおりに描けず、背景や服に移した。
老人だけ別のモデルで描いて画風もそろわなかった（docs/knowledge/traits.md）。
Animagine XL 3.1（CreativeML OpenRAIL++-M）はアニメ絵のタグ（pointy ears、dragon tail、old woman）を学んでおり、
1つのモデルで年齢も種族もそろった画風で描けた。少ない段数で描く仕組みは無く、CPU で1枚 約3分。

描いた絵は毎回 edit.inspect で検品し、落ちたら seed を変えて描き直す（最大 3 回）。通った絵は背景を白に消す。

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/people.py card <出力フォルダ> <名前> --gender male --age adult \
      [--tags "elf, pointy ears"] [--zoom head] [--views front,back]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/people.py sheet <出力フォルダ> <一覧図.png>
--zoom は拡大する部位: head（耳・角・顔）、arms（腕の肌・刺青）、back（背中・翼）、tail（腰から下の後ろ）、none
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
sys.path.insert(0, str(Path(__file__).parent))

MODEL = "cagliostrolab/animagine-xl-3.1"
QUALITY = "masterpiece, best quality, very aesthetic, absurdres"
NEGATIVE = ("nsfw, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, "
            "worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, "
            "artist name, multiple views, background objects, scenery, animal, extra character")
# 素体: 体の線が見える無地の肌着、素足、無地の背景。服は後から着せ替える
BODY = "full body, standing, arms at sides, white background, simple background, barefoot, grey tank top, grey shorts"
# 向き。「from front」は効かず真横を向いたので、正面は見る人の方を向く言葉で書く
VIEWS = {"front": "facing viewer, looking at viewer, straight-on, front view",
         "back": "from behind, back view, facing away",
         "side": "from side, profile"}
GENDER = {"male": "1boy, male focus", "female": "1girl"}
AGE = {"child": "child, young", "teen": "teenage", "adult": "adult", "middle": "mature, middle-aged",
       "elder": "old, wrinkled skin, grey hair"}
AGE_GENDER = {("elder", "male"): "old man", ("elder", "female"): "old woman",
              ("child", "male"): "boy, shota", ("child", "female"): "girl, loli"}
FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
_PIPE = None


def pipe():
    global _PIPE
    if _PIPE is None:
        import torch
        from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionXLPipeline
        torch.set_num_threads(os.cpu_count() or 4)
        _PIPE = StableDiffusionXLPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16)
        _PIPE.scheduler = EulerAncestralDiscreteScheduler.from_config(_PIPE.scheduler.config)
    return _PIPE


def prompt_of(gender, age, tags, hair, view, body=BODY):
    who = AGE_GENDER.get((age, gender), "")
    parts = [GENDER[gender], "solo", who, AGE[age], tags, hair, body, VIEWS[view], QUALITY]
    return ", ".join(p for p in parts if p)


def draw(out, prompt, seed, steps=24, limbs=True, body=None):
    """1枚描いて検品する。落ちたら seed を変えて描き直す（最大 3 回）。通った絵は背景を白に消す。"""
    import torch
    import edit
    for k in range(3):
        t = time.time()
        # 指示文は 77 トークンで切れる（ラミアなどは向きの指定まで切れた）。分けて読ませる
        import design
        pe, ne, pp, np_ = design.encode_xl(pipe(), prompt, NEGATIVE)
        im = pipe()(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                    negative_pooled_prompt_embeds=np_, num_inference_steps=steps, guidance_scale=6.0,
                    width=832, height=1216, generator=torch.Generator().manual_seed(seed + k * 100)).images[0]
        im.save(out)
        reasons = edit.inspect(out, limbs)
        print(f"{out}: {time.time() - t:.0f} 秒 seed {seed + k * 100} " + ("通った" if not reasons else "落とした: " + "、".join(reasons)),
              flush=True)
        if not reasons:
            im.save(str(out).replace(".png", ".raw.png"))
            edit.clean_background(out)
            return seed + k * 100, []
    return seed + 200, reasons


def zoom_box(src, where):
    """拡大する範囲。部位分けで頭・腕を探す。背中と尾は人物の範囲の上半分・下半分。"""
    import edit
    lab = edit.parts(src)
    fg = edit.foreground(src)
    x0, y0, x1, y1 = fg.getbbox()
    if where == "head":
        # 顔を中心に、顔の高さの 2.2 倍を半径にする。髪まで含めると長い髪が腰まであり、全身ほどの範囲になった。
        # 耳や角は顔より上と横に出るので、中心を少し上にずらす
        b = lab.point(lambda v: 255 if v == 11 else 0).getbbox()
        if b:
            fh = max(b[3] - b[1], b[2] - b[0])
            cx, cy, r = (b[0] + b[2]) // 2, b[1] + fh // 4, fh * 2.2
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


def card(outdir, name, gender, age, tags, hair, views, zoom, seed, label, limbs=True, body=BODY):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    shots, meta = [], {"name": name, "label": label, "gender": gender, "age": age, "tags": tags, "views": {}}
    for v in views:
        p = outdir / f"{name}-{v}.png"
        text = prompt_of(gender, age, tags, hair, v, body)
        if not p.exists():
            used, reasons = draw(p, text, seed, limbs=limbs)
        else:
            used, reasons = seed, []
        meta["views"][v] = {"prompt": text, "seed": used, "inspect": reasons, "file": p.name}
        shots.append((v, p, reasons))
    # 設定資料の1枚: 向きごとの全身と、特徴の部位の拡大
    H = 640
    tiles = []
    for v, p, reasons in shots:
        im = Image.open(p).convert("RGB")
        tiles.append(({"front": "正面", "back": "背面", "side": "横"}[v] + ("（落とした）" if reasons else ""),
                      im.resize((int(im.width * H / im.height), H))))
    if zoom != "none":
        src = shots[0][1] if zoom in ("head", "arms") else next((p for v, p, _ in shots if v == "back"), shots[0][1])
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
    a = ap.parse_args()
    hair = a.hair or ("short black hair" if a.gender == "male" else "black hair, bob cut")
    card(a.outdir, a.name, a.gender, a.age, a.tags, hair, a.views.split(","), a.zoom, a.seed, a.label or a.name)


if __name__ == "__main__":
    main()
