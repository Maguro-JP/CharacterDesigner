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


def prompt_of(c: dict) -> tuple[str, str]:
    look = ANIME_WORDS.sub("", c["look"]).strip(" ,")
    pos = f"{look}, wearing {c['outfit']}, {PHOTO}"
    neg = ", ".join(x for x in (NEGATIVE, c.get("negative", "")) if x)
    return pos, neg


# 向きの言葉と、その向きで打ち消す言葉。後ろ姿は言葉を後ろに足すだけでは正面を描いた（サークルスカート、2026-10-31）ので、
# 頭に置き、顔と正面を打ち消す
# IP-Adapter（正面の絵の手本）を 0.5 にしても、14 人のうち 12 人が振り返るか正面を向いた（2026-10-31）。手本は顔ごと引っ張るので 0.3 に下げ、
# 言葉を強め、描いたあとに顔が写っていないかを見て、写っていれば種を替えて描き直す（check_view）
VIEWS = {"front": ("front view, facing the camera", ""),
         "back": ("(view from behind:1.4), (back of the head:1.3), the person faces away from the camera, back of the outfit visible",
                  "(face:1.4), (looking back:1.3), looking over shoulder, profile, eyes, nose, front view, facing camera")}
BACK_IP_SCALE = 0.3
TRIES = 3   # 1 つの向きで描き直す回数の上限（1 枚 約 40 分。2 つの向きで 6 枚まで描いてもジョブの上限 6 時間に収まる）
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


def faces(im) -> int:
    """頭のあたり（上から 27%）に写った顔（正面と横顔）の数を、OpenCV の Haar 検出で数える。OpenCV が無ければ -1。
    1 回目の 14 人の背面で、検品担当が振り返ったとした 12 人のうち 10 人を見つけ、後ろ姿の 2 人は 0 だった。
    絵の全体で探すと、服の柄を顔と取り違えた"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return -1
    g = cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2GRAY)[: int(im.height * 0.27)]
    n = 0
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        det = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for img in (g, cv2.flip(g, 1)) if "profile" in name else (g,):   # 横顔の検出は片向きだけなので左右を返しても見る
            n += len(det.detectMultiScale(img, scaleFactor=1.05, minNeighbors=4, minSize=(30, 30)))
    return n


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


def check_view(im, view: str) -> list[str]:
    """描いた全身を数字で見る。見つかった崩れを返す（空なら通す）。
    全身を頼んでも 14 人のうち 5 人が膝や腿で切れ、靴が無かった。背面は 12 人が振り返った（2026-10-31）"""
    bad = []
    if bottom_cut(im) > 0.1:
        bad.append("足元が枠の下で切れている")
    if view == "back" and faces(im) > 0:
        bad.append("背面に顔が写っている")
    return bad


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
            text = f"{words}, {pos}" if view == "back" else f"{pos}, {words}"
            pe, ne, pp, np_ = design.encode_xl(pipe, text, ", ".join(x for x in (neg, away) if x))
            pipe.set_ip_adapter_scale(0.0 if front is None else BACK_IP_SCALE)
            ref = front if front is not None else Image.new("RGB", (224, 224), "white")
            tries = []
            for k in range(TRIES):   # 検品に落ちたら種を替えて描き直す。落ちた絵も -try<k> で残す
                t = time.time()
                im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
                          negative_pooled_prompt_embeds=np_, num_inference_steps=a.steps, guidance_scale=5.0,
                          width=a.width, height=a.height, ip_adapter_image=ref,
                          generator=torch.Generator().manual_seed(a.seed + k)).images[0]
                bad = check_view(im, view)
                tries.append({"seed": a.seed + k, "sec": round(time.time() - t), "bad": bad})
                print(f"{name}-{view} 種 {a.seed + k} {time.time() - t:.0f} 秒 {bad or '通す'}", flush=True)
                if not bad:
                    break
                im.save(out / f"{name}-{view}-try{k}.png")
            im.save(out / f"{name}-{view}.png")
            rec["views"][view] = {"file": f"{name}-{view}.png", "tries": tries, "passed": not tries[-1]["bad"]}
            if front is None:
                front = im
        pipe.unload_ip_adapter()   # 細部の描き直し（img2img）は手本なしで描く
        t = time.time()
        rec["details"] = details(img2img, front, pos, neg, a.seed, out, name)
        print(f"細部 {len(rec['details'])} 枚 {time.time() - t:.0f} 秒", flush=True)
        (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__":
    main()
