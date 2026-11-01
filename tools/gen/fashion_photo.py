"""服装の図鑑の人物を、写実の模型で全身のファッション写真のように描く（図鑑の見本は資料なので、アニメ調より実写風が読み取りやすい）。

  CD_FETCH=1 python3 tools/gen/fashion_photo.py <出力> <id>... [--seed 0] [--steps 30] [--figures casts/fashion-trend/characters]

1 人につき、服の全体が分かる正面と背面の全身と、細部（頭、襟と胸元、腰、裾、足元）の拡大を残す。
細部は正面の全身から切り出して 2 倍にし、弱い描き直し（img2img、強さ 0.3）で布目と縫い目を描き足す。
別に描くと服の形や色が全身と食い違うので、全身の絵を土台にする。

人物の設定は casts/fashion-zukan/characters/<id>.json の look と outfit を使う。アニメ絵の言葉（1girl、solo）は外し、
写真の言葉（スタジオ、無地の背景、全身）を足す。重いので Actions で回す（.github/workflows/fashion-photo.yml）。
描いた絵の隣に、使った言葉と種を <id>-s<種>.json で残す（再現のため）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401  模型を勝手に取りに行かない設定を先に効かせる

ROOT = Path(__file__).resolve().parents[2]
FIGURES = ROOT / "casts" / "fashion-zukan" / "characters"
MODEL = "SG161222/RealVisXL_V5.0"   # openrail++（使い方の制限あり、絵の商用利用は可。docs/references.md）
# アニメ絵のタグで、写真の言葉にすると人数や画風を引っ張るもの
ANIME_WORDS = re.compile(r"\b(1girl|1boy|solo|male focus|anime style|cel shading|clean lineart)\b,?\s*", re.I)
# 写真の言葉は服の後ろに置く。前に置くと、SDXL の要約（pooled、最初の 75 トークンの区切りから取る）が写真の言葉だけになり、
# 14 人のうち 13 人で色や特徴のある品目（黒、袴、帽子、横ひだ）がありふれた品（灰色、ワンピース、縦ひだ）にすり替わった（2026-10-31）
PHOTO = ("(full body shot:1.2), entire figure from head to shoes in frame, (shoes visible:1.2), small figure with empty space above the head and below the feet, "
         "fashion editorial lookbook photograph, plain off-white studio background, soft even studio lighting, sharp focus, photorealistic, high detail fabric texture")
NEGATIVE = ("anime, illustration, drawing, cartoon, painting, 3d render, cgi, doll, cropped, out of frame, cut off feet, "
            "cropped legs, legs cut off, close-up, "
            "extra fingers, missing fingers, fused fingers, deformed hands, extra arms, extra legs, bad anatomy, "
            "two people, text, logo, brand logo, watermark, signature, nsfw, cleavage, see-through")


# 顔の言葉（目、化粧、前髪、肌、頬）。背面では外す。残すと、流行の 10 人の背面 30 枚すべてで振り返った顔や横顔が描かれた（2026-11-01）
FACE_WORDS = re.compile(r"\b(eyes?|eyeshadow|makeup|bangs|skin|cheeks?|lips?|glasses)\b", re.I)


def back_look(look: str) -> str:
    """look から顔の言葉を含む句を外す（後ろ姿では顔が見えないので、描かせる理由が無い）"""
    out = []
    for x in (x.strip() for x in look.split(",")):
        if "hair" in x:   # 髪は後ろからも見える。前髪などの飾りの句（with 以降）だけ外す
            x = x.split(" with ")[0]
        if x and not FACE_WORDS.search(x):
            out.append(x)
    return ", ".join(out)


def prompt_of(c: dict, view: str = "front") -> tuple[str, str]:
    look = ANIME_WORDS.sub("", c["look"]).strip(" ,")
    if view == "back":
        look = back_look(look)
    # 主役の品は重みを付けて先頭に置く。流行の 10 人で、模型が流行の形を定番に寄せた（ズボンが細身で裾を折り返す 6 人、小物が抜ける 7 人、2026-11-01）
    key = ", ".join(f"({k}:1.3)" for k in c.get("key", []))
    pos = ", ".join(x for x in (key, look, f"wearing {c['outfit']}", PHOTO) if x)
    extra = ""
    if any(w in c["outfit"] for w in ("full length", "wide", "flare", "covering the shoes")):
        extra = "(rolled-up hem:1.3), cuffed trousers, skinny pants, tapered pants"
    neg = ", ".join(x for x in (NEGATIVE, c.get("negative", ""), extra) if x)
    return pos, neg


# 向きの言葉と、その向きで打ち消す言葉。後ろ姿は言葉を後ろに足すだけでは正面を描いた（サークルスカート、2026-10-31）ので、
# 頭に置き、顔と正面を打ち消す
# IP-Adapter（正面の絵の手本）を 0.5 にしても、14 人のうち 12 人が振り返るか正面を向いた（2026-10-31）。手本は顔ごと引っ張るので 0.3 に下げ、
# 言葉を強め、描いたあとに顔が写っていないかを見て、写っていれば種を替えて描き直す（check_view）
VIEWS = {"front": ("front view, facing the camera", ""),
         "back": ("(view from behind:1.4), (back of the head:1.3), the person faces away from the camera, back of the outfit visible",
                  "(face:1.4), (looking back:1.3), looking over shoulder, profile, eyes, nose, front view, facing camera")}
BACK_IP_SCALE = 0.4   # 2 回目（0.3）は前後で靴・髪・裾が食い違った人が 10 人を超えた。顔は検査で落とせるようになったので手本を強める
TRIES = {"front": 2, "back": 4}   # 向きごとの描き直しの上限（1 枚 約 40 分。合わせて 6 枚でジョブの上限 6 時間に収まる）。正面は 2 回目までにほぼ通り、背面が落ちやすい
# 細部の範囲（人物の外接枠の高さに対する割合、上端と下端）と、描き足すときの言葉
DETAILS = [("head", 0.00, 0.16, "close-up of the hair and headwear"),
           ("collar", 0.12, 0.38, "close-up of the collar, neckline, buttons and fabric texture"),
           ("waist", 0.34, 0.58, "close-up of the waist, belt, pockets and seams"),
           ("hem", 0.55, 0.85, "close-up of the hem, pleats and fabric folds"),
           ("feet", 0.82, 1.00, "close-up of the shoes and socks")]


def figure_box(im):
    """無地の背景から人物の外接枠を取る（背景は四隅の色に近い画素とする）"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(int)
    bg = np.median(np.concatenate([a[:8, :8], a[:8, -8:], a[-8:, :8], a[-8:, -8:]]).reshape(-1, 3), axis=0)
    ys, xs = np.nonzero(np.abs(a - bg).sum(axis=2) > 40)
    if len(xs) == 0:
        return 0, 0, im.width, im.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


YUNET = "CD_YUNET"   # 顔の検出の模型 YuNet（OpenCV の模型集、MIT）の置き場を渡す環境変数。Actions が取る（fashion-photo.yml）


def faces(im) -> int:
    """頭のあたり（上から 30%）に写った顔の数。YuNet があればそれで、無ければ OpenCV の Haar 検出（正面と横顔）で数える。
    OpenCV が無ければ -1。2 回目の背面で、検品担当が顔ありとした 10 枚を、Haar は 5 枚（真横の横顔）見逃し、
    YuNet は 1・2 回目の 22 枚をすべて見つけた（顔の無い 5 枚のうち 2 枚を顔ありと取り違えた。取り違えは描き直しが 1 回増えるだけ）"""
    import os
    try:
        import cv2
        import numpy as np
    except ImportError:
        return -1
    rgb = np.asarray(im.convert("RGB"))[: int(im.height * 0.30)]
    model = os.environ.get(YUNET, "")
    if model and os.path.exists(model):
        det = cv2.FaceDetectorYN.create(model, "", (rgb.shape[1], rgb.shape[0]), 0.7, 0.3, 50)
        _, found = det.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        return 0 if found is None else len(found)
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    n = 0
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        det = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for img in (g, cv2.flip(g, 1)) if "profile" in name else (g,):   # 横顔の検出は片向きだけなので左右を返しても見る
            n += len(det.detectMultiScale(img, scaleFactor=1.05, minNeighbors=4, minSize=(30, 30)))
    return n


# 服の最初の品の色が、暗い色か明るい色かの言葉。黒のスーツを頼んで灰色や白が描かれた（slim-suit、le-smoking、2026-10-31）
DARK = {"black", "navy", "charcoal", "dark"}
LIGHT = {"white", "cream", "ivory", "off-white"}
TOPS = {"jacket", "coat", "shirt", "blouse", "knit", "sweater", "t", "polo", "dress", "cardigan", "hoodie", "fleece", "suit",
        "henley", "vest", "top", "sweatshirt", "blazer", "parka", "tuxedo"}
OTHER = {"red", "brown", "blue", "green", "beige", "khaki", "grey", "gray", "pink", "purple", "olive", "yellow", "orange",
         "burgundy", "maroon", "oatmeal", "camel", "tan", "lavender", "mint", "pastel", "indigo", "denim", "plaid", "striped", "check"}


def expected_tone(outfit: str) -> str:
    """outfit の最初の品（読点まで、with より前）に出る最初の色の言葉から、胴が暗いか明るいかを返す。分からなければ空"""
    head = outfit.split(",")[0].split(" with ")[0].split(" over ")[0].lower()
    words = head.replace("-", " ").split()
    first_two = " ".join(outfit.lower().split(",")[:2])
    if "open" in first_two or " over " in first_two:   # 前を開けた上着や重ね着は、胴の真ん中に中の服が見える
        return ""
    if any(w in outfit.lower().split(",")[0] for w in ("print", "pattern", "stripe", "check", "plaid")):
        return ""    # 柄の入った服は、地の色と明るさが合わない
    if not TOPS & set(words):   # 最初の品が上半身の服でなければ（ジーンズが先頭など）、胴の明るさでは見ない
        return ""
    for k, w in enumerate(words):
        if w in OTHER:   # 最初の色がほかの色や柄なら、明るさでは見ない
            return ""
        if (w in DARK or w in LIGHT or w == "off") and k + 1 < len(words) and words[k + 1] == "and":
            return ""    # 「紺と白の縞」のように 2 色なら、明るさでは見ない
        if w in DARK:
            return "dark"
        if w in LIGHT or w == "off":
            return "light"
    return ""


def torso_luma(im) -> float:
    """胴のあたり（高さ 25〜45%、幅の真ん中 30%）の明るさの中央値（0〜255）"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(float)
    h, w = a.shape[:2]
    band = a[int(h * 0.25):int(h * 0.45), int(w * 0.35):int(w * 0.65)].reshape(-1, 3)
    return float(np.median(band @ [0.299, 0.587, 0.114]))


def bottom_cut(im) -> float:
    """下の端の行で、背景（その行の左右 1 割の色）と違う画素の割合。人物が枠の下で切れると大きくなる。
    1 回目の 28 枚で、切れた 9 枚は 0.32〜0.80、切れていない 19 枚は 0.01 以下だった。
    四隅の色から人物の外接枠を取るやり方は、床の影と背景の濃淡を人物と取り違え、28 枚すべてを切れたとした"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(int)
    out = 0.0
    for row in (a[-1], a[-4]):
        w = len(row) // 10
        bg = np.median(np.concatenate([row[:w], row[-w:]]), axis=0)
        out = max(out, float((np.abs(row - bg).sum(axis=1) > 60).mean()))
    return out


def check_view(im, view: str, outfit: str = "") -> list[str]:
    """描いた全身を数字で見る。見つかった崩れを返す（空なら通す）。
    全身を頼んでも 14 人のうち 5 人が膝や腿で切れ、靴が無かった。背面は 12 人が振り返った（2026-10-31）。
    胴の明るさは、2 回目の 13 人で、頼んだ暗い服 4 人が 69〜76、頼んだ明るい服 2 人が 195〜211、黒を頼んで白が描かれた 2 人が 188〜203 だった"""
    bad = []
    tone = expected_tone(outfit)
    luma = torso_luma(im) if tone else 0.0
    if tone == "dark" and luma > 110:
        bad.append(f"暗い色を頼んだ服が明るい（胴の明るさ {luma:.0f}）")
    if tone == "light" and luma < 150:
        bad.append(f"明るい色を頼んだ服が暗い（胴の明るさ {luma:.0f}）")
    if bottom_cut(im) > 0.1:
        bad.append("足元が枠の下で切れている")
    if view == "back" and faces(im) > 0:
        bad.append("背面に顔が写っている")
    return bad


def without_head(im):
    """背面の手本にする正面の絵から、頭のあたり（上から 22%）を背景の色で塗りつぶす。
    手本の顔ごと引っ張られて、流行の 10 人の背面 30 枚すべてに顔か横顔が描かれた（2026-11-01）。服だけを手本にする"""
    import numpy as np
    from PIL import Image
    a = np.asarray(im.convert("RGB")).copy()
    bg = np.median(np.concatenate([a[:8, :8], a[:8, -8:]]).reshape(-1, 3), axis=0).astype(a.dtype)
    a[: int(a.shape[0] * 0.22)] = bg
    return Image.fromarray(a)


def details(img2img, im, pos, neg, seed, out: Path, name: str) -> list[dict]:
    import torch
    from PIL import Image
    x0, y0, x1, y1 = figure_box(im)
    h = y1 - y0
    rows = []
    for part, top, bottom, words in DETAILS:
        t, b = y0 + int(h * top), y0 + int(h * bottom)
        cx, w = (x0 + x1) // 2, max(x1 - x0, int((b - t) * 0.75))
        box = (max(0, cx - w // 2), max(0, t), min(im.width, cx + w // 2), min(im.height, b))
        crop = im.crop(box)
        side = 1024 / max(crop.size)
        crop = crop.resize((int(crop.width * side) // 8 * 8, int(crop.height * side) // 8 * 8), Image.LANCZOS)
        r = img2img(prompt=f"{words}, {pos}", negative_prompt=neg, image=crop, strength=0.3, guidance_scale=5.0,
                    num_inference_steps=30, generator=torch.Generator().manual_seed(seed)).images[0]
        f = f"{name}-detail-{part}.png"
        r.save(out / f)
        rows.append({"part": part, "file": f, "box": list(box), "words": words})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--figures", default=str(FIGURES), help="人物の設定の置き場（図鑑は casts/fashion-zukan/characters、今の流行は casts/fashion-trend/characters）")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    a = ap.parse_args()
    import torch
    from PIL import Image
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    pipe = StableDiffusionXLPipeline.from_pretrained(MODEL, torch_dtype=torch.float32)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
    torch.set_num_threads(torch.get_num_threads())
    print(f"模型を読んだ {time.time() - t:.0f} 秒", flush=True)
    from diffusers import StableDiffusionXLImg2ImgPipeline
    img2img = StableDiffusionXLImg2ImgPipeline(**pipe.components)   # 同じ部品を使い回す（模型は 1 回だけ読む）
    for ident in a.ids:
        c = json.loads((Path(a.figures) / f"{ident}.json").read_text(encoding="utf-8"))
        pos, neg = prompt_of(c)
        name = f"{ident}-s{a.seed}"
        rec = {"id": ident, "name": c.get("name", ""), "model": MODEL, "seed": a.seed, "steps": a.steps,
               "prompt": pos, "negative": neg, "views": {}, "details": []}
        # 背面は正面の絵を手本（IP-Adapter）にして描く。言葉だけで描くと、前と後ろで上着の色や丈が変わった（19 世紀の紳士）
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models", weight_name="ip-adapter_sdxl_vit-h.safetensors",
                             image_encoder_folder="models/image_encoder")
        front = None
        for view, (words, away) in VIEWS.items():
            vpos = prompt_of(c, view)[0]
            text = f"{words}, {vpos}" if view == "back" else f"{vpos}, {words}"
            pe, ne, pp, np_ = design.encode_xl(pipe, text, ", ".join(x for x in (neg, away) if x))
            pipe.set_ip_adapter_scale(0.0 if front is None else BACK_IP_SCALE)
            ref = without_head(front) if front is not None else Image.new("RGB", (224, 224), "white")
            tries = []
            for k in range(TRIES[view]):   # 検品に落ちたら種を替えて描き直す。落ちた絵も -try<k> で残す
                t = time.time()
                im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                          negative_pooled_prompt_embeds=np_, num_inference_steps=a.steps, guidance_scale=5.0,
                          width=a.width, height=a.height, ip_adapter_image=ref,
                          generator=torch.Generator().manual_seed(a.seed + k)).images[0]
                bad = check_view(im, view, c["outfit"])
                tries.append({"seed": a.seed + k, "sec": round(time.time() - t), "bad": bad})
                print(f"{name}-{view} 種 {a.seed + k} {time.time() - t:.0f} 秒 {bad or '通す'}", flush=True)
                if not bad:
                    break
                im.save(out / f"{name}-{view}-try{k}.png")
            if not bad or view == "front":   # 落ちた背面は最終にしない（前後が食い違ったまま残った）。-try<k> だけ残る
                im.save(out / f"{name}-{view}.png")
            rec["views"][view] = {"file": f"{name}-{view}.png", "prompt": text, "tries": tries, "passed": not tries[-1]["bad"]}
            if front is None:
                front = im
        pipe.unload_ip_adapter()   # 細部の描き直し（img2img）は手本なしで描く
        t = time.time()
        rec["details"] = details(img2img, front, pos, neg, a.seed, out, name)
        print(f"細部 {len(rec['details'])} 枚 {time.time() - t:.0f} 秒", flush=True)
        (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__":
    main()
