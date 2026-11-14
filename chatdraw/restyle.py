"""画風の加工: 今の絵を、形と構図を保ったまま別の画風（アニメの塗り、厚塗り、水彩、線画、セル画、鉛筆画、色鉛筆画、
墨絵、ガッシュ画、アルコールマーカー画、モノクロ漫画風、フィギュア風、ドット絵）に描き替える。

作り: 元の絵を土台にした img2img（低い強さ）に、元の線を ControlNet（xinsir の Union の線の型）で渡す。
- 白紙から描かせると構図と顔が変わる。元の絵を土台にし、強さを低くして形を元の絵に寄せる
- 強さだけを低くすると画風が変わらず、上げると形が崩れた。線を ControlNet で縛り、強さを上げても線の位置は動かないようにする
- 描いたあとに元の絵と線の重なりと形の変わりを測り、崩れていれば強さを下げて描き直す（STRENGTH_STEPS）。
  下げきっても崩れるなら、崩れたまま渡さず Unavailable で止めて理由を出す
- 画風の言葉は加工の指示なので加工のときだけ足す。利用者の描く言葉は変えない
- 白黒の画風（鉛筆画・墨絵・漫画）は模型が色を残すことがあるので、描いたあとに灰色にそろえる（EXTRA の post）
- ドット絵は模型に「pixel art」で塗りを平らにさせてから、縮小・減色・最近傍の拡大で格子にそろえる
  （模型だけでは格子がそろわない。Pixel Art XL の札も 8 分の 1 の最近傍の縮小を勧めている）
- 言葉と強さの根拠は docs/knowledge/restyle-styles.md
- 絵の模型と Union は 1 回だけ読み、続けて掛けるときは読み直さない（_CACHE）
"""
from __future__ import annotations

# (名前, メニューの名前, ツールチップ, 模型に渡す言葉, 強さ)
# 強さは私の推測で決めた初めの値。形を壊さないよう上限を 0.45 にそろえた
STYLES = (
    ("anime", "アニメの塗り", "影を 2 段ではっきり分けた、アニメの塗りに描き替えます",
     "anime coloring, anime screencap, clean lineart, two-tone shading, vivid colors", 0.45),
    ("thick", "厚塗り", "線を目立たせず、色を重ねた厚塗りに描き替えます",
     "thick painting, impasto, painterly, visible brush strokes, rich colors, soft lighting", 0.45),
    ("watercolor", "水彩", "にじみと紙の白を残した水彩に描き替えます",
     "watercolor (medium), traditional media, soft colors, color bleeding, paper texture", 0.45),
    ("lineart", "線画", "色を除いた、白い地の線画に描き替えます",
     "lineart, monochrome, greyscale, white background, clean lines, no color", 0.45),
    ("cel", "セル画", "平らな塗りと硬い影の、昔のセル画に描き替えます",
     "cel animation, retro anime, 1990s anime style, flat colors, hard shadows, film grain", 0.45),
    # ここから下は見本の画風に合わせて足した物。0.4〜0.5 では Actions の本物の模型で画風がほとんど変わらなかった（形の変わり 0.011）。
    # 調べた幅（0.4〜0.7）の上の側へ上げ、線の縛りも緩める。形が崩れれば検品が強さを下げて描き直す
    ("pencil", "鉛筆画", "紙に鉛筆で描いた、白黒の陰影の絵に描き替えます",
     "traditional media, graphite (medium), pencil sketch, monochrome, greyscale, hatching, paper texture", 0.65),
    ("colored_pencil", "色鉛筆画", "線の重なりが見える、色鉛筆の絵に描き替えます",
     "traditional media, colored pencil (medium), visible pencil strokes, hatching, paper texture, soft colors", 0.65),
    ("sumie", "墨絵", "墨のにじみと濃淡だけで描いた墨絵に描き替えます",
     "sumi-e, ink wash painting, traditional media, ink (medium), monochrome, greyscale, brush strokes, washi paper", 0.7),
    ("gouache", "ガッシュ画", "不透明の絵の具で平らに塗った、つやの無いガッシュ画に描き替えます",
     "traditional media, gouache (medium), painting (medium), opaque paint, matte colors, flat brush strokes", 0.65),
    ("marker", "アルコールマーカー画", "色の重ね塗りと白い光を残した、アルコールマーカーの絵に描き替えます",
     "traditional media, marker (medium), alcohol marker, copic, marker strokes, bold colors, white highlights", 0.65),
    ("manga", "モノクロ漫画風", "スクリーントーンと黒のベタで描いた、白黒の漫画のコマに描き替えます",
     "manga, monochrome, greyscale, screentone, halftone, ink (medium), high contrast, black and white", 0.6),
    ("figure", "フィギュア風", "つやのある樹脂で作った、立体のフィギュアの写真に描き替えます",
     "pvc figure, figure, 3d, blender (medium), glossy plastic, smooth shading, studio lighting, product photo", 0.65),
    ("pixel", "ドット絵", "少ない色の、格子のそろったドット絵に描き替えます",
     "pixel art, limited palette, flat colors, retro game sprite, dithering", 0.4),
)
# 画風ごとの足し: 打ち消しに足す言葉（neg）、線の縛り（control）、描いたあとの処理（post）
EXTRA = {
    "pencil": dict(neg="color, colorful, painting, anime coloring", post="grey", control=0.6),
    "colored_pencil": dict(neg="digital painting, smooth shading", control=0.6),
    "sumie": dict(neg="color, colorful, screentone, anime coloring", post="grey", control=0.6),
    "gouache": dict(neg="glossy, shiny, 3d", control=0.6),
    "marker": dict(neg="oil painting, impasto", control=0.6),
    "manga": dict(neg="color, colorful, painting, watercolor", post="grey", control=0.7),
    # 立体の質感は塗りを大きく変えるので、線の縛りを少し緩める（強いと平らな塗りのまま残る）
    "figure": dict(neg="2d, flat color, sketch, lineart, traditional media", control=0.6),
    "pixel": dict(neg="blurry, smooth gradient, anti-aliasing", post="pixel"),
}
PIXEL_LONG = 128          # ドット絵の長い辺のドット数（tools/gen/design.py pixel の既定と同じ幅）
PIXEL_COLORS = 32
NEGATIVE = "lowres, bad anatomy, bad hands, extra fingers, missing fingers, deformed, blurry, jpeg artifacts, watermark, text"
LINES = 3                 # Union の線の型（canny・lineart・anime lineart）
CONTROL = 0.8             # 線の縛りの強さ
CONTROL_END = 0.9         # 工程のこの割合まで線で縛る（終わりだけ自由にして塗りをなじませる）
STRENGTH_STEPS = (1.0, 0.75, 0.55)   # 崩れたときに強さに掛ける倍率（順に試す）
LINE_KEEP = 0.35          # 元の線の画素のうち、描いたあとも線の近く（2 画素）に残る割合の下限
SHAPE_DRIFT = 0.08        # 縮めた明るさの形の変わり（retouch.drift）の上限。画風は色を変えるので綺麗化（0.02）より緩い
WORK_SIDE = 1024          # 描く大きさの長い辺。大きな絵は縮めて描き、元の大きさに戻す

_CACHE: dict = {}
LAST: dict = {}           # 直前の加工の強さと検品（画面の知らせと試験が読む）


def control_lines(image):
    """ControlNet に渡す線の絵（黒地に白い線）。元の絵から模型を使わずに取る"""
    from PIL import ImageOps
    from chatdraw.postfx import lineart
    return ImageOps.invert(lineart(image).convert("L")).convert("RGB")


def _controlnet(dtype):
    """Union を読む（twostage と同じ重み）。試験は _CACHE["controlnet"] に小さな物を置いて差し替える"""
    if "controlnet" in _CACHE:
        return _CACHE["controlnet"]
    import os
    import shutil
    import tempfile
    from diffusers import ControlNetUnionModel
    from huggingface_hub import hf_hub_download
    from chatdraw.paths import HUB
    from chatdraw.twostage import UNION
    cfg = hf_hub_download(UNION, "config_promax.json", cache_dir=str(HUB))
    weights = hf_hub_download(UNION, "diffusion_pytorch_model_promax.safetensors", cache_dir=str(HUB))
    d = tempfile.mkdtemp()
    shutil.copy(cfg, os.path.join(d, "config.json"))
    try:
        os.symlink(weights, os.path.join(d, "diffusion_pytorch_model.safetensors"))
    except OSError:
        shutil.copy(weights, os.path.join(d, "diffusion_pytorch_model.safetensors"))
    _CACHE["controlnet"] = ControlNetUnionModel.from_pretrained(d, torch_dtype=dtype)
    return _CACHE["controlnet"]


def pipeline(painter):
    """painter の読んだ模型の部品をそのまま使う img2img と ControlNet の道。同じ模型なら作り直さない"""
    key = (getattr(painter, "model", None), id(painter.load()))
    if _CACHE.get("key") == key:
        return _CACHE["pipe"]
    from diffusers import (ControlNetUnionModel, StableDiffusionXLControlNetImg2ImgPipeline,
                           StableDiffusionXLControlNetUnionImg2ImgPipeline)
    base = painter.load()
    cn = _controlnet(base.unet.dtype)
    # Union は線の型を control_mode で選ぶ。線だけの ControlNet（試験の小さな物など）は型を選ばずにそのまま渡す
    kind = StableDiffusionXLControlNetUnionImg2ImgPipeline if isinstance(cn, ControlNetUnionModel) else StableDiffusionXLControlNetImg2ImgPipeline
    pipe = kind.from_pipe(base, controlnet=cn)
    _CACHE.update(key=key, pipe=pipe)
    return pipe


def _params(pipe) -> set:
    import inspect
    return set(inspect.signature(pipe.__call__).parameters)


def line_kept(a, b) -> float:
    """元 a の線の画素のうち、b でも線の近く（2 画素）に線がある割合。線が残っていれば 1 に近い"""
    import numpy as np
    from scipy.ndimage import binary_dilation
    w = np.float32([0.299, 0.587, 0.114])

    def lines(x):
        g = np.asarray(x.convert("RGB"), np.float32) @ w
        from scipy.ndimage import uniform_filter
        return (uniform_filter(g, 7) - g) > 18     # 周りより暗い細い所（塗りの濃さによらない）
    la, lb = lines(a), lines(b)
    if la.sum() < 50:
        return 1.0
    return float((la & binary_dilation(lb, iterations=2)).sum() / la.sum())


def check(src, out) -> dict:
    """形と線が元の絵から崩れていないか。崩れていれば why に理由"""
    import numpy as np
    from chatdraw.finishers import _gen
    rt = _gen("retouch")
    a = np.asarray(src.convert("RGB")).astype(float)
    b = np.asarray(out.convert("RGB").resize(src.size)).astype(float)
    d = rt.drift(a, b)
    k = line_kept(src, out.resize(src.size))
    why = (f"形が変わりすぎる（{d:.3f}）" if d > SHAPE_DRIFT else f"元の線が消える（残り {k:.0%}）" if k < LINE_KEEP else "")
    return dict(drift=round(d, 4), line_kept=round(k, 3), why=why)


def post(kind: str, img):
    """描いたあとの処理。白黒の画風は灰色に、ドット絵は縮小・減色して元の大きさへ最近傍で戻す"""
    from PIL import Image
    how = EXTRA.get(kind, {}).get("post")
    if how == "grey":
        return img.convert("L").convert("RGB")
    if how == "pixel":
        from chatdraw.postfx import pixel_art
        dots = pixel_art(img, long=PIXEL_LONG, colors=PIXEL_COLORS, outline=False, transparent=False).convert("RGB")
        return dots.resize(img.size, Image.NEAREST)
    return img


def restyle(painter, image, kind: str, seed: int = 0, say=None):
    """image を画風 kind に描き替えた絵（元と同じ大きさ）。崩れたら強さを下げて描き直す"""
    import torch
    from PIL import Image
    from chatdraw.engine import Stopped, check_stop, english_only, negative_for
    from chatdraw.models import image_model
    style = {s[0]: s for s in STYLES}[kind]
    src = image.convert("RGB")
    W, H = src.size
    k = min(1.0, WORK_SIDE / max(W, H))
    w, h = max(8, round(W * k / 8) * 8), max(8, round(H * k / 8) * 8)
    small = src.resize((w, h), Image.LANCZOS)
    ctrl = control_lines(small)
    pipe = pipeline(painter)
    try:
        neg = negative_for(image_model(painter.model), getattr(painter, "avoid", ""))
    except Exception:   # 目録に無い模型（試験の小さな模型）でも描けるように
        neg = NEGATIVE
    extra = EXTRA.get(kind, {})
    if extra.get("neg"):
        neg = f"{neg}, {extra['neg']}" if neg else extra["neg"]
    tries = []
    for f in STRENGTH_STEPS:
        check_stop()
        s = round(style[4] * f, 3)
        steps = max(int(getattr(painter, "steps", 20) or 20), int(2 / s) + 1)
        if say is not None:
            say(f"{style[1]}に描き替えています（強さ {s}）")

        def step(p, i, _t, kw):
            if getattr(painter, "stop", False):
                p._interrupt = True
            return kw
        union = {"control_image": [ctrl], "control_mode": [LINES]} if "control_mode" in _params(pipe) else {"control_image": ctrl}
        out = pipe(prompt=english_only(style[3]), negative_prompt=neg, image=small, **union,
                   strength=s, num_inference_steps=steps, guidance_scale=float(getattr(painter, "guidance", 6.0) or 6.0),
                   controlnet_conditioning_scale=extra.get("control", CONTROL), control_guidance_end=CONTROL_END, width=w, height=h,
                   generator=torch.Generator("cpu").manual_seed(seed), callback_on_step_end=step).images[0]
        if getattr(painter, "stop", False):
            raise Stopped("止めました")
        q = check(small, out)
        tries.append(dict(strength=s, **q))
        if not q["why"]:
            LAST.clear()
            LAST.update(kind=kind, label=style[1], strength=s, tries=tries)
            out = out.resize((W, H), Image.LANCZOS) if out.size != (W, H) else out
            return post(kind, out)   # 検品は描いた絵で見る（ドット絵の格子は線の残りの測りを下げるため、後に掛ける）
    LAST.clear()
    LAST.update(kind=kind, label=style[1], tries=tries, rejected=True)
    from chatdraw.finishers import Unavailable
    raise Unavailable(f"{style[1]}に描き替えると形が崩れたので、掛けませんでした（{tries[-1]['why']}）。元の絵のままです")


def note() -> str:
    """画面に出す 1 文: 使った強さと、強さを下げて描き直した回数"""
    if not LAST or LAST.get("rejected"):
        return ""
    n = len(LAST["tries"]) - 1
    return f"強さ {LAST['strength']} で描き替えました" + (f"（崩れたので {n} 回、強さを下げて描き直しました）" if n else "") + "。"
