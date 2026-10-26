"""構図と仕上げを別の模型に任せて、絵全体を 1 枚として描く（切り貼りはしない）。

1. 構図: 文で頼める新しい世代（FLUX.2 klein など）に、同じ頼みを文で描かせる。手足の数や姿勢が崩れにくい
2. 形を取り出す: 1 の絵から、骨組み（VitPose の体の 17 点を openpose の形に描いた物）、奥行き（Depth Anything V2）、細い線を取る。色や塗りは捨てる
3. 仕上げ: SDXL のアニメの模型（Animagine など）に、2 の形を ControlNet（xinsir の Union）で渡し、白紙から絵全体を描かせる

設計の決まり（docs/knowledge/drawing-algorithm.md の「設計の見直し」）:
- 段ごとに絵をファイルに残し、次の段はファイルから始める。どの段から描き直しても、前の段をやり直さない
- 仕上げは、1 つの構図から縛りの組み合わせ（variants）を何通りも描く。模型は 1 回だけ読む。比べるのは縛りの違いだけにする
- 既定の縛りは骨組みと奥行き。細い線は構図の模型の指や塗りの癖までなぞるので、比べの 1 通りとしてだけ使う

どの段も絵全体を描く。直す所を切り出して貼ることも、1 の絵に上塗りすることもしない。
"""
from __future__ import annotations

import gc
import json
import time
from pathlib import Path

UNION = "xinsir/controlnet-union-sdxl-1.0"
DEPTH = "depth-anything/Depth-Anything-V2-Small-hf"
POSE = "usyd-community/vitpose-base-simple"   # Apache-2.0。transformers だけで読める（部品を増やさない）
# 2 段で描くのに要る部品（構図と仕上げの模型は別に取る）。(repo, 取るファイル)
PARTS = [(UNION, ["config_promax.json", "diffusion_pytorch_model_promax.safetensors"]),
         (DEPTH, ["*.json", "*.safetensors"]),
         (POSE, ["*.json", "*.safetensors"]),
         ("SmilingWolf/wd-vit-tagger-v3", ["model.onnx", "selected_tags.csv"])]   # 頼んだ物が描かれたかの検品
PARTS_GB = 3.3
# COCO の 17 点（VitPose の出力）から引く骨と、その色（ControlNet の openpose の絵と同じ並びの色）
_NECK = 17
BONES = [(_NECK, 0), (_NECK, 5), (5, 7), (7, 9), (_NECK, 6), (6, 8), (8, 10), (_NECK, 11), (11, 13), (13, 15), (_NECK, 12), (12, 14),
         (14, 16), (0, 1), (1, 3), (0, 2), (2, 4)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170),
          (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170)]


def parts_ready() -> bool:
    """2 段で描く部品が手元にあるか（取りに行かずに確かめる）"""
    from huggingface_hub import snapshot_download
    from chatdraw.paths import HUB
    try:
        for repo, files in PARTS:
            snapshot_download(repo, cache_dir=str(HUB), local_files_only=True, allow_patterns=files)
        return True
    except Exception:
        return False


def fetch_parts(say=print):
    from huggingface_hub import snapshot_download
    from chatdraw.paths import HUB
    for i, (repo, files) in enumerate(PARTS, 1):
        say(f"2 段で描く部品を取っています（{i}/{len(PARTS)}）")
        snapshot_download(repo, cache_dir=str(HUB), allow_patterns=files)


def keypoints(image, threshold: float = 0.3) -> dict:
    """VitPose で体の 17 点を読み、名前と (x, y) を返す（確からしさが threshold 未満の点は入れない）"""
    import torch
    from transformers import AutoProcessor, VitPoseForPoseEstimation
    from chatdraw.paths import HUB
    names = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
             "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]
    proc = AutoProcessor.from_pretrained(POSE, cache_dir=str(HUB), local_files_only=True)
    model = VitPoseForPoseEstimation.from_pretrained(POSE, cache_dir=str(HUB), local_files_only=True)
    w, h = image.size
    boxes = [[[0, 0, w, h]]]
    with torch.no_grad():
        res = proc.post_process_pose_estimation(model(**proc(image, boxes=boxes, return_tensors="pt")), boxes=boxes)[0][0]
    return {n: tuple(p) for n, p, sc in zip(names, res["keypoints"].tolist(), res["scores"].tolist()) if sc >= threshold}


def pose_map(image, threshold: float = 0.3):
    """VitPose で体の 17 点を取り、ControlNet の openpose と同じ形の絵（黒地に色の棒と点）にする。
    人は 1 人の絵として、絵全体を枠にする。手の指は取らない（指の形は仕上げの模型に任せる）"""
    import torch
    from PIL import Image, ImageDraw
    from transformers import AutoProcessor, VitPoseForPoseEstimation
    from chatdraw.paths import HUB
    proc = AutoProcessor.from_pretrained(POSE, cache_dir=str(HUB))
    model = VitPoseForPoseEstimation.from_pretrained(POSE, cache_dir=str(HUB))
    w, h = image.size
    boxes = [[[0, 0, w, h]]]
    with torch.no_grad():
        out = model(**proc(image, boxes=boxes, return_tensors="pt"))
    res = proc.post_process_pose_estimation(out, boxes=boxes)[0][0]
    pts, scores = res["keypoints"].tolist(), res["scores"].tolist()
    ok = [s >= threshold for s in scores]
    neck = [(pts[5][0] + pts[6][0]) / 2, (pts[5][1] + pts[6][1]) / 2]
    pts.append(neck)
    ok.append(ok[5] and ok[6])
    canvas = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(canvas)
    width = max(4, round(min(w, h) / 120))
    for (a, b), c in zip(BONES, COLORS):
        if ok[a] and ok[b]:
            d.line([tuple(pts[a]), tuple(pts[b])], fill=tuple(int(v * 0.6) for v in c), width=width)
    for p, good, c in zip(pts, ok, COLORS + [(255, 0, 0)]):
        if good:
            d.ellipse([p[0] - width, p[1] - width, p[0] + width, p[1] + width], fill=c)
    return canvas, sum(ok)
# xinsir の Union の種類の番号（README の表）: 0 骨組み、1 奥行き、2 太い線、3 細い線
MODES = {"pose": 0, "depth": 1, "lines": 3}
# 比べの既定。名前はファイル名に入る
VARIANTS = [
    {"name": "pose-depth", "pose": 0.7, "depth": 0.4, "end": 0.7},
    {"name": "depth-lines", "depth": 0.5, "lines": 0.4, "end": 0.6},
]


def structure(image, keep: Path):
    """絵から形だけを取り出して keep に置く。骨組み（黒地に色の棒）、奥行き（白いほど手前）、細い線（黒地に白）"""
    from PIL import ImageOps
    from chatdraw.paths import HUB
    out = {}
    t = time.time()
    out["pose"], found = pose_map(image)
    print(f"骨組みの点: {found}/18", flush=True)
    from transformers import pipeline
    est = pipeline("depth-estimation", model=DEPTH, model_kwargs={"cache_dir": str(HUB)})
    out["depth"] = est(image)["depth"].convert("RGB").resize(image.size)
    del est
    gc.collect()
    from chatdraw.postfx import lineart
    out["lines"] = ImageOps.invert(lineart(image).convert("L")).convert("RGB")
    for k, im in out.items():
        im.save(keep / f"2-{k}.png")
    print(f"形を取り出す: {time.time() - t:.0f} 秒", flush=True)
    return out


def load_render(model: str):
    """仕上げの模型と Union を 1 回だけ読む"""
    import os
    import shutil
    import tempfile
    import torch
    from diffusers import ControlNetUnionModel, StableDiffusionXLControlNetUnionPipeline
    from huggingface_hub import hf_hub_download
    from chatdraw.paths import HUB
    cfg = hf_hub_download(UNION, "config_promax.json", cache_dir=str(HUB))
    weights = hf_hub_download(UNION, "diffusion_pytorch_model_promax.safetensors", cache_dir=str(HUB))
    # promax の重みは別の名前で置かれているので、読める名前のフォルダーに並べ直す（重みはリンクで、写さない）
    d = tempfile.mkdtemp()
    shutil.copy(cfg, os.path.join(d, "config.json"))
    try:
        os.symlink(weights, os.path.join(d, "diffusion_pytorch_model.safetensors"))
    except OSError:
        shutil.copy(weights, os.path.join(d, "diffusion_pytorch_model.safetensors"))
    from chatdraw.engine import cpu_dtype, dtype_note
    from chatdraw.models import image_model
    dtype = torch.float16 if torch.cuda.is_available() else cpu_dtype((image_model(model).gb or 7) + 2.5)   # 2.5 は Union の分
    print(f"仕上げの型: {dtype} {dtype_note(dtype)}", flush=True)
    cn = ControlNetUnionModel.from_pretrained(d, torch_dtype=dtype)
    pipe = StableDiffusionXLControlNetUnionPipeline.from_pretrained(model, controlnet=cn, torch_dtype=dtype, cache_dir=str(HUB))
    if torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
    return pipe


def render(pipe, prompt: str, negative: str, shapes: dict, variant: dict, seed: int, size, steps: int, guidance: float, on_step=None):
    """variant に名前のある縛りだけを渡して、白紙から描く。縛りは工程の前半（end の割合まで）だけに効かせる"""
    import torch
    kinds = [k for k in MODES if k in variant]
    w, h = size

    def step(p, i, _t, kw):
        if on_step:
            on_step(i + 1, steps)
        return kw
    return pipe(prompt=prompt, negative_prompt=negative, width=w, height=h, num_inference_steps=steps, guidance_scale=guidance,
                control_image=[shapes[k].resize(size) for k in kinds], control_mode=[MODES[k] for k in kinds],
                controlnet_conditioning_scale=[float(variant[k]) for k in kinds], control_guidance_end=float(variant.get("end", 0.6)),
                generator=torch.Generator("cpu").manual_seed(seed), callback_on_step_end=step).images[0]


def compose(sentence: str, seed: int, compose_model: str, size, path, tags: str = ""):
    """構図の模型（FLUX.2 klein など）で、文から絵全体を描く。
    頼みを読む部品（Qwen3、約 8GB）は最初に 1 回だけ使い、読み終えたら外してから描く。
    外さないと 16GB の機械でメモリが足りず、1 工程に約 23 分、絵にする所で 2 時間以上止まった"""
    import torch
    from chatdraw.engine import Painter, native_size
    from chatdraw.models import image_model
    cm = image_model(compose_model)
    painter = Painter(compose_model, steps=cm.steps, size=size, guidance=cm.guidance)
    pipe = painter.load()
    from chatdraw.engine import dtype_note
    print(f"構図の型: {painter.dtype} {dtype_note(painter.dtype)}", flush=True)
    if not hasattr(pipe, "encode_prompt") or getattr(pipe, "text_encoder", None) is None:
        painter.paint(enrich(sentence, seed), seed, on_step=lambda i, n: print(f"構図 {i}/{n}", flush=True)).save(path)
        return
    t = time.time()
    sentence = enrich(sentence, seed)
    print(f"構図の文: {sentence}", flush=True)
    with torch.no_grad():
        embeds = pipe.encode_prompt(sentence, device="cpu")
    embeds = embeds[0] if isinstance(embeds, tuple) else embeds
    pipe.text_encoder = None
    gc.collect()
    print(f"頼みを読む: {time.time() - t:.0f} 秒", flush=True)
    w, h = native_size(size, cm.family)
    # 1 回描いて終わりにしない。描いて検品し、手に崩れがあれば種を変えて描き直す（頼みは 1 回読んだ物を使い回す）。
    # 崩れの無い構図が出たらそこで止め、出なければ崩れの一番少ない構図を使う。どの回も 1-composition-t<回>.png に残す
    from chatdraw import handcheck, requestcheck
    rounds, best = [], None
    for k in range(COMPOSE_TRIES):
        s_k = seed + 1000 * k

        def step(p, i, _t, kw, k=k):
            print(f"構図 {k + 1}回目 {i + 1}/{cm.steps} {time.time() - t:.0f} 秒", flush=True)
            return kw
        im = pipe(prompt_embeds=embeds, width=w, height=h, num_inference_steps=cm.steps, guidance_scale=cm.guidance,
                  generator=torch.Generator("cpu").manual_seed(s_k), callback_on_step_end=step).images[0]
        try_path = Path(path).with_name(f"1-composition-t{k + 1}.png")
        im.save(try_path)
        res = handcheck.check(im, asked=tags)
        asked = requestcheck.check(im, tags, fetch=True) if tags else {"readable": False, "missing": []}
        print(f"構図 {k + 1}回目（種 {s_k}）: {handcheck.summary(res)}　{requestcheck.summary(asked)}", flush=True)
        bad = res["bad"] + [f"描かれていない: {m}" for m in asked["missing"]] + [f"頼んでいない: {e}" for e in asked.get("extra", [])]
        rounds.append({"try": k + 1, "seed": s_k, "bad": bad, "readable": res["readable"]})
        if best is None or len(bad) < len(best[1]):
            best = (im, bad)
        if res["readable"] and not bad:
            break
    best[0].save(path)
    Path(path).with_name("compose-rounds.json").write_text(json.dumps(rounds, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"構図を保存: {time.time() - t:.0f} 秒（{len(rounds)} 回描いた）", flush=True)


COMPOSE_TRIES = 6   # 構図を描き直す回数の上限（速い機械で 1 回 約 4 分）
FIX_ROUNDS = 6      # 質が先。仕上げのあと、崩れた手を直して検品し直す回数の上限


REFINE_SCALE, REFINE_STRENGTH = 1.5, 0.35


def refine(pipe, image, prompt: str, negative: str, seed: int, steps: int, guidance: float):
    """清書。絵全体を 1.5 倍に広げ、弱い強さ（0.35）で描き直して、指先・目・髪の線の細かい所を描き込む。
    AI の絵は縮めた大きさで細部を決めるので、指や線が雑で汚れて見えた。形は元の絵に従う（強さを弱くする）。
    最後に元の大きさへ戻す"""
    import torch
    from PIL import Image
    from diffusers import StableDiffusionXLImg2ImgPipeline
    parts = {k: v for k, v in pipe.components.items() if k in ("vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2",
                                                                 "unet", "scheduler")}
    i2i = StableDiffusionXLImg2ImgPipeline(**parts)   # 読んだ模型の部品をそのまま使う
    w, h = image.size
    big = image.resize((int(w * REFINE_SCALE) // 8 * 8, int(h * REFINE_SCALE) // 8 * 8), Image.LANCZOS)
    t = time.time()

    def step(p, i, _t, kw):
        print(f"清書 {i + 1} {time.time() - t:.0f} 秒", flush=True)
        return kw
    out = i2i(prompt=prompt, negative_prompt=negative, image=big, strength=REFINE_STRENGTH, num_inference_steps=steps,
              guidance_scale=guidance, generator=torch.Generator("cpu").manual_seed(seed + 9),
              callback_on_step_end=step).images[0]
    print(f"清書: {time.time() - t:.0f} 秒", flush=True)
    return out.resize((w, h), Image.LANCZOS)


def fix_hands(pipe, image, prompt: str, negative: str, seed: int, steps: int, guidance: float, keep: Path, name: str):
    """仕上げた絵の手を検品し、崩れた手の所だけを直して、もう一度検品する。崩れが消えるか FIX_ROUNDS 回で止める。
    直すのは手の枠の中だけで、枠の外は 1 画素も変えない（直した絵の枠の外を、元の絵の画素に戻す）。どの回も残す"""
    import torch
    from PIL import Image, ImageDraw, ImageFilter
    from diffusers import StableDiffusionXLInpaintPipeline
    from chatdraw import handcheck
    inpaint = None
    rounds = []
    for r in range(FIX_ROUNDS + 1):
        res = handcheck.check(image, asked=prompt)
        rounds.append({"round": r, "bad": res["bad"], "readable": res["readable"]})
        print(f"仕上げの検品 {r}回目: {handcheck.summary(res)}", flush=True)
        regions = handcheck.bad_regions(res)   # 手・足・顔のうち、崩れの見つかった所
        if not regions or r == FIX_ROUNDS:
            break
        if inpaint is None:
            parts = {k: v for k, v in pipe.components.items() if k in ("vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2",
                                                                         "unet", "scheduler")}
            inpaint = StableDiffusionXLInpaintPipeline(**parts)   # 読んだ模型の部品をそのまま使う（模型を 2 度読まない）
        mask = Image.new("L", image.size, 0)
        d = ImageDraw.Draw(mask)
        for (x0, y0, x1, y1), _kind in regions:
            cx, cy, rr = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.6
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
        soft = mask.filter(ImageFilter.GaussianBlur(4))
        words = ", ".join(dict.fromkeys(handcheck.FIX_WORDS[k] for _b, k in regions))
        out = inpaint(prompt=f"{prompt}, {words}",
                      negative_prompt=negative + ", extra fingers, missing fingers, fused fingers, extra toes, faceless, empty eyes",
                      image=image, mask_image=soft, width=image.width, height=image.height, strength=(0.55, 0.65, 0.75, 0.85, 0.9, 0.95)[min(r, 5)],
                      num_inference_steps=steps, guidance_scale=guidance,
                      generator=torch.Generator("cpu").manual_seed(seed + 77 * (r + 1))).images[0].resize(image.size)
        image = Image.composite(out, image, soft)   # 枠の外は元の絵のまま
        image.save(keep / f"3-{name}-s{seed}-fix{r + 1}.png")
    (keep / f"fix-rounds-{name}.json").write_text(json.dumps(rounds, ensure_ascii=False, indent=1), encoding="utf-8")
    return image


def finish(tags: str, seed: int, render_model: str, size, composition_path, keep: Path, variants=None):
    """1 つの構図から、縛りの組み合わせごとに 1 枚ずつ描く。描けた絵から順にファイルに残す（途中で打ち切られても残る）"""
    from PIL import Image
    from chatdraw.models import image_model
    keep = Path(keep)
    shapes = structure(Image.open(composition_path).convert("RGB"), keep)
    rm = image_model(render_model)
    t = time.time()
    pipe = load_render(render_model)
    print(f"仕上げの模型を読む: {time.time() - t:.0f} 秒", flush=True)
    for v in variants or VARIANTS:
        t = time.time()
        out = render(pipe, f"{tags}, masterpiece, best quality", "lowres, worst quality, low quality, bad anatomy, bad hands",
                     shapes, v, seed, tuple(size), rm.steps, rm.guidance,
                     on_step=lambda i, n, name=v["name"]: print(f"仕上げ {name} {i}/{n} {time.time() - t:.0f} 秒", flush=True))
        out.save(keep / f"3-{v['name']}-s{seed}-fix0.png")
        print(f"仕上げ {v['name']}: {time.time() - t:.0f} 秒", flush=True)
        prompt = f"{tags}, masterpiece, best quality, highly detailed, clean lineart"
        negative = "lowres, worst quality, low quality, bad anatomy, bad hands, blurry, messy lines, jpeg artifacts"
        out = fix_hands(pipe, out, prompt, negative, seed, rm.steps, rm.guidance, keep, v["name"])
        out = refine(pipe, out, prompt, negative, seed, rm.steps, rm.guidance)
        out.save(keep / f"3-{v['name']}-s{seed}-refined.png")
        out = fix_hands(pipe, out, prompt, negative, seed + 500, rm.steps, rm.guidance, keep, v["name"] + "-refined")
        out.save(keep / f"3-{v['name']}-s{seed}.png")
        from chatdraw import handcheck, requestcheck
        res = handcheck.check(out, asked=tags)
        asked = requestcheck.check(out, tags, fetch=True)
        passed = res["readable"] and not res["bad"] and not asked["missing"] and not asked.get("extra")
        (keep / f"result-{v['name']}.json").write_text(json.dumps({"passed": passed, "seed": seed, "bad": res["bad"],
                                                                   "missing": asked["missing"], "readable": res["readable"]},
                                                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"仕上げの結果: {'検品を通りました' if passed else '検品を通りません'}（{handcheck.summary(res)}　"
              f"{requestcheck.summary(asked)}）", flush=True)


# 構図の文に足す、場面の変化（カメラ・光・背景）。同じ頼みでいつも同じ浜辺・同じ正面の立ち姿になり、
# 構図の段がポーズの確認にしか使えなかったので、種ごとに違う組み合わせを足して、場面の魅力を出す
SCENE = {
    "camera": ["low angle shot", "slightly high angle", "dynamic three-quarter view", "cinematic wide shot", "dutch angle",
               "eye-level shot with shallow depth of field"],
    "light": ["golden hour backlight with rim light", "soft overcast light", "dramatic side lighting", "sparkling midday sun",
              "warm sunset glow", "dappled light through leaves"],
    "detail": ["detailed background with depth", "foreground elements framing the subject", "atmospheric perspective",
               "scattered props that tell a story", "wind-blown details", "reflections and light particles"],
}


def enrich(sentence: str, seed: int) -> str:
    """構図の文に、種で選んだカメラ・光・背景の言葉を足す（頼みの言葉は先に置き、頼みの方を効かせる）"""
    import random
    r = random.Random(seed)
    extra = [r.choice(v) for v in SCENE.values()]
    return f"{sentence.rstrip('. ')}. {', '.join(extra)}."


COMPOSERS = ("flux2", "zimage", "qwenimage", "flux1", "chroma", "lumina2")   # 文で頼める世代（構図の段に使う）


def pick(installed, painter_model: str = ""):
    """手元の模型から、構図の模型（文で頼める世代の点の高い物）と仕上げの模型（今の SDXL か、点の高い SDXL）を選ぶ。
    どちらかが無ければ None"""
    comp = sorted((m for m in installed if m.family in COMPOSERS), key=lambda m: -m.score)
    sdxl = [m for m in installed if m.family == "sdxl"]
    render = next((m for m in sdxl if m.repo == painter_model), None) or (max(sdxl, key=lambda m: m.score) if sdxl else None)
    return (comp[0], render) if comp and render else None


def run_stages(sentence: str, tags: str, seed: int, compose_model: str, render_model: str, size, keep: Path, variant: dict,
               say=print, stopped=lambda: False):
    """アプリから 2 段で描く。段ごとに別の処理で動かし、その出力の行を進みとして say に渡す。
    stopped() が真になったら処理を止める。描いた絵の道を返す"""
    import os
    import subprocess
    import sys
    keep.mkdir(parents=True, exist_ok=True)
    comp = keep / "1-composition.png"
    w, h = size
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p), PYTHONIOENCODING="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):   # 出力を読むので、窓の無い pythonw ではなく python で動かす（窓は flags で出さない）
        py = py[:-len("pythonw.exe")] + "python.exe"
    steps = [("構図", ["compose", sentence, str(seed), compose_model, str(w), str(h), str(comp), tags]),
             ("仕上げ", ["finish", tags, str(seed), render_model, str(w), str(h), str(comp), str(keep), json.dumps([variant])])]
    for label, args in steps:
        if label == "構図" and comp.exists():
            continue   # 前に描いた構図がある（同じ置き場で続きから描く）
        say(f"{label}の段を始めています")
        proc = subprocess.Popen([py, "-s", "-u", "-m", "chatdraw.twostage", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=env, creationflags=flags, text=True, encoding="utf-8", errors="replace")
        import threading

        def watch():   # 出力の無い間（1 工程に数分かかる）も、止めるを押したらすぐ止める
            while proc.poll() is None:
                if stopped():
                    proc.kill()
                    return
                time.sleep(0.5)
        threading.Thread(target=watch, daemon=True).start()
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line:
                tail = (tail + [line])[-5:]
                if line.startswith(("構図", "仕上げ", "形を", "頼みを", "骨組み")):
                    say(line)
        if stopped():
            raise InterruptedError("止めました")
        if proc.wait() != 0:
            raise RuntimeError(f"{label}の段で止まりました: {' / '.join(tail)}")
    return keep / f"3-{variant['name']}-s{seed}.png"


def draw(sentence: str, tags: str, seed: int, compose_model: str, render_model: str, size=(832, 1216), say=print, keep=None,
         composition=None, variants=None, stage="all"):
    """sentence は構図の模型に渡す文、tags は仕上げの模型に渡すタグ。
    composition に前に描いた構図の絵を渡すと、構図の段をとばす。stage は "compose"、"finish"、"all"。
    段ごとに別の処理（プロセス）で動かし、段の間でメモリを OS に返す（16GB の機械で、FLUX のあとに SDXL を読むと
    1 つの処理の中では解放しきれなかった）"""
    import shutil
    import subprocess
    import sys
    keep = Path(keep or ".")
    keep.mkdir(parents=True, exist_ok=True)
    comp = keep / "1-composition.png"
    w, h = size
    if composition:
        if Path(composition).resolve() != comp.resolve():
            shutil.copy(composition, comp)
    elif stage in ("all", "compose"):
        t = time.time()
        subprocess.run([sys.executable, "-u", "-m", "chatdraw.twostage", "compose", sentence, str(seed), compose_model, str(w), str(h),
                        str(comp), tags], check=True)
        say(f"構図: {time.time() - t:.0f} 秒")
    if stage == "compose":
        return None
    if not comp.exists():
        raise FileNotFoundError(f"構図の絵がありません: {comp}")
    t = time.time()
    subprocess.run([sys.executable, "-u", "-m", "chatdraw.twostage", "finish", tags, str(seed), render_model, str(w), str(h), str(comp),
                    str(keep), json.dumps(variants or VARIANTS)], check=True)
    say(f"形と仕上げ: {time.time() - t:.0f} 秒")
    return sorted(keep.glob(f"3-*-s{seed}.png"))


if __name__ == "__main__":
    import sys
    cmd, text, seed, model, w, h = sys.argv[1:7]
    if cmd == "compose":
        compose(text, int(seed), model, (int(w), int(h)), sys.argv[7], sys.argv[8] if len(sys.argv) > 8 else "")
    else:
        finish(text, int(seed), model, (int(w), int(h)), sys.argv[7], Path(sys.argv[8]), json.loads(sys.argv[9]))
