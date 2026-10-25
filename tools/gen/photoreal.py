"""アニメ調の絵を写真級に描き直す（後の加工の 1 つ、リアル風）。

  CD_FETCH=1 PYTHONPATH=.cache/gen/lib python3 tools/gen/photoreal.py in.png out/ [--strength 0.7] [--dry-run]

重いので Actions で回す（.github/workflows/photoreal.yml、頼みは config/photoreal-request.json）。

経路: 帯と浮いた暗い塊を消す → Realistic Vision V6 B1 に ControlNet の tile と lineart を 2 つ掛けて img2img →
1.5 倍に拡大して tile だけで弱く（strength 0.25）重ねたタイルごとに描き直す →
1 段目の高い周波数（σ2.5、量 1.0）を混ぜ戻す。

- 帯: 元の絵に服（部位 7）の暗い大きな塊があると、模型はそれを黒い帯として描き写した。描く前に背景（部位 0）だけから
  拡散で埋める。埋める元に肌を入れると脚の肌色がにじんだ。部位は絵の隣の .parts.png を使い回す（2 度計算しない）
- lineart: tile だけでは髪型と模様が崩れた（縮れた茶髪になった）。輪郭を lineart で押さえると髪型が残った
- 2 段目をタイルにするのは、1152x1728 を一度に描くと注意の計算が CPU のメモリに乗らないため
- 模型は 1 回だけ読み、2 段目は 1 段目の部品を使い回す。CPU 4 コアで 1 段目 約 21 分、2 段目 約 24 分、最大 RSS 約 10.7GB
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401  模型を勝手に取りに行かない設定を先に効かせる

CHECKPOINT = ("SG161222/Realistic_Vision_V6.0_B1_noVAE", "Realistic_Vision_V6.0_NV_B1_fp16.safetensors")
CONFIG = "stable-diffusion-v1-5/stable-diffusion-v1-5"   # 単体ファイルの形の設定だけを読む（SD1.5 と同じ形）
VAE = "stabilityai/sd-vae-ft-mse"
TILE = "lllyasviel/control_v11f1e_sd15_tile"
LINEART = "lllyasviel/control_v11p_sd15_lineart"
DEPTH = "lllyasviel/control_v11f1p_sd15_depth"
DEPTH_EST = "depth-anything/Depth-Anything-V2-Small-hf"
PROMPT = ("RAW photo, a 27 year old woman, plain white bikini, standing, hand on hip, grey studio backdrop, "
          "natural skin texture, soft studio lighting, 85mm, sharp focus, high detail")
NEGATIVE = ("anime, cartoon, illustration, painting, 3d, cgi, plastic skin, airbrushed, lowres, bad anatomy, "
            "bad hands, extra fingers, child, teen")
BACKGROUND, CLOTH = 0, 7
SKIN = (11, 12, 13, 14, 15)   # 顔・脚・腕（edit.LABELS）


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


class Log:
    def __init__(self, path: Path):
        self.path, self.d = path, {}

    def __call__(self, k, v):
        self.d[k] = v
        self.path.write_text(json.dumps(self.d, indent=1, ensure_ascii=False))
        print(k, v, flush=True)


def load_source(src: Path, width: int, height: int):
    """絵と部位を同じ大きさにそろえる（部位は番号なので最近傍で）"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    parts = Image.open(str(src) + ".parts.png")
    if im.size != (width, height):
        im = im.resize((width, height), Image.LANCZOS)
    if parts.size != (width, height):
        parts = parts.resize((width, height), Image.NEAREST)
    return im, parts


def clean_band(im, parts, dark: int = 80, grow: int = 6):
    """服の暗い最大の塊（帯）を背景から埋める。返すのは (絵, 埋めた画素数)"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(im).astype(np.float32)
    p = np.asarray(parts)
    m = ndimage.binary_opening((p == CLOTH) & (a.max(2) < dark), iterations=2)
    lab, n = ndimage.label(m)
    if n == 0:
        return im, 0
    sz = ndimage.sum(m, lab, range(1, n + 1))
    m = lab == (1 + int(np.argmax(sz)))          # 一番大きい塊だけ（髪や水着の影を巻き込まない）
    ys, xs = np.nonzero(m)
    box = np.zeros_like(m)
    box[max(ys.min() - 15, 0):ys.max() + 25, max(xs.min() - 15, 0):xs.max() + 15] = True
    m |= box & np.isin(p, (BACKGROUND, CLOTH)) & (a.max(2) < dark + 10)   # 帯の端（手の下、裾の先）
    m = ndimage.binary_dilation(m, iterations=grow) & np.isin(p, (BACKGROUND, CLOTH))
    known = ~m & (p == BACKGROUND)
    fill = np.where(known[..., None], a, 0)
    w = known.astype(np.float32)
    k = np.ones((5, 5), np.float32)
    rem = m.copy()
    while rem.any():
        s = np.stack([ndimage.convolve(fill[..., c] * w, k, mode="nearest") for c in range(3)], -1)
        ws = ndimage.convolve(w, k, mode="nearest")
        new = rem & (ws > 0)
        if not new.any():
            m &= ~rem                             # 背景に届かない所は触らない
            break
        fill[new] = s[new] / ws[new][:, None]
        w[new] = 1
        rem &= ~new
    out = a.copy()
    out[m] = fill[m]
    bl = np.stack([ndimage.gaussian_filter(out[..., c], 3) for c in range(3)], -1)
    out[m] = bl[m]                                # 埋めた所の縞を消す
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), int(m.sum())


def find_blobs(a, dark=60, near=6, smin=150, smax=5000, contrast=100, base_width=768):
    """周りから浮いた暗い塊を、部位の番号に頼らず大きさと明るさの差で見つける。部位分けが手の下の塊を腕に数えて
    帯消しから外し、描くと黒い飾りになったため。数字は 768 幅で決めたので、面積は幅の 2 乗、距離は幅に比例させる"""
    import numpy as np
    from scipy import ndimage
    f = a.shape[1] / base_width
    near, r_in, r_out = max(1, round(near * f)), max(1, round(2 * f)), max(2, round(8 * f))
    smin, smax = smin * f * f, smax * f * f
    L = a.max(2)
    d = L < dark
    grp, n = ndimage.label(ndimage.binary_dilation(d, iterations=near))   # 近い欠片は 1 つの塊に寄せる
    lab = np.where(d, grp, 0)
    out = np.zeros(d.shape, bool)
    for i in range(1, n + 1):
        m = lab == i
        sz = int(m.sum())
        if not (smin <= sz <= smax):
            continue                                                       # 髪（約 1.6 万画素）や目の点は外れる
        ring = ndimage.binary_dilation(m, iterations=r_out) & ~ndimage.binary_dilation(m, iterations=r_in) & ~d
        if ring.sum() and float(np.median(L[ring]) - L[m].mean()) >= contrast:
            out |= m
    return out


def fill_blobs(im, grow=3):
    """暗い塊を明るい周り（max>=90）から拡散で埋める。返すのは (絵, 埋めた画素数)"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(im).astype(np.float32)
    m = find_blobs(a)
    if not m.any():
        return im, 0
    m = ndimage.binary_dilation(m, iterations=max(1, round(grow * a.shape[1] / 768)))   # にじんだ縁も一緒に
    known = ~m & (a.max(2) >= 90)
    f = np.where(known[..., None], a, 0)
    w = known.astype(np.float32)
    k = np.ones((5, 5), np.float32)
    rem = m.copy()
    while rem.any():
        s = np.stack([ndimage.convolve(f[..., c] * w, k, mode="nearest") for c in range(3)], -1)
        ws = ndimage.convolve(w, k, mode="nearest")
        new = rem & (ws > 0)
        if not new.any():
            break
        f[new] = s[new] / ws[new][:, None]
        w[new] = 1
        rem &= ~new
    o = a.copy()
    o[m] = f[m]
    bl = np.stack([ndimage.gaussian_filter(o[..., c], 2) for c in range(3)], -1)
    o[m] = bl[m]
    return Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)), int(m.sum())


def hfmix(s1, s2, sigma=2.5, k=1.0):
    """2 段目の低い周波数に 1 段目（拡大）の高い周波数を戻す。2 段目は肌が滑らかに塗り直された（平らな面 0.0036 → 0.0234）"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    def g(x):
        return np.stack([ndimage.gaussian_filter(x[..., c], sigma) for c in range(3)], -1)
    a = np.asarray(s1.resize(s2.size, Image.LANCZOS)).astype(np.float32)
    b = np.asarray(s2).astype(np.float32)
    o = g(b) + k * (a - g(a)) + (1 - k) * (b - g(b))
    return Image.fromarray(np.clip(o, 0, 255).astype(np.uint8))


def lineart(im):
    """暗い線と縁の強さから lineart の条件の絵を作る（模型を読まずに済ませる）"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    g = np.asarray(im.convert("L")).astype(np.float32)
    d = np.clip(ndimage.gaussian_filter(g, 2.0) - g, 0, None) * 6
    g1 = ndimage.gaussian_filter(g, 1)
    s = np.hypot(ndimage.sobel(g1, 0), ndimage.sobel(g1, 1)) / 4
    return Image.fromarray(np.clip(np.maximum(d, s), 0, 255).astype(np.uint8)).convert("RGB")


def deshade(im, parts, sigma=12.0, keep=1.5):
    """セルの影の段差をぼかして消す（1 段目の前）。部位ごとに明るさを大きくならし（部位の外を混ぜない）、
    細かい明るさ（線、目、σ keep より細かい所）はそのまま戻す。色は明るさの比で掛けるので色相は変えない。
    元の段のある影を tile で写すと、写真の肌の上にアニメの影の境が残った"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    f = im.width / 768
    a = np.asarray(im).astype(np.float32)
    p = np.asarray(parts)
    L = a.mean(2) + 1e-3
    out = L.copy()
    small = ndimage.gaussian_filter(L, keep * f)
    for i in np.unique(p):
        if i == BACKGROUND:
            continue
        m = (p == i).astype(np.float32)
        if m.sum() < 200:
            continue
        num = ndimage.gaussian_filter(L * m, sigma * f)
        den = ndimage.gaussian_filter(m, sigma * f)
        big = num / np.maximum(den, 1e-3)
        sm = ndimage.gaussian_filter(L * m, keep * f) / np.maximum(ndimage.gaussian_filter(m, keep * f), 1e-3)
        out[m > 0] = (big + (L - sm))[m > 0]
    # 線・目の縁は元のまま。暗い画素で比を掛けると色が赤や白に跳ねて縁取りになった
    line = ndimage.binary_dilation(np.asarray(lineart(im).convert("L")) > 60, iterations=max(1, round(f)))
    ratio = np.clip(np.clip(out, 0, 255) / L, 0.7, 1.4)
    ratio = np.where(line | (p == BACKGROUND), 1.0, ratio)
    ratio = ndimage.gaussian_filter(ratio, 1.0 * f)
    o = a * ratio[..., None]
    return Image.fromarray(np.clip(o, 0, 255).astype(np.uint8))


def depth_map(im):
    """奥行きを読む（Depth Anything V2 Small、約 100MB）。depth の ControlNet と光の付け直しで共有する"""
    from transformers import pipeline
    d = pipeline("depth-estimation", model=DEPTH_EST)(im)["depth"]
    return d.convert("RGB").resize(im.size)


def normals(depth, width, body=None):
    """奥行き（手前ほど明るい）から面の向き（単位の法線、x 右・y 上・z 手前）を出す。
    人物の外を一番近い人物の奥行きで埋めてから傾きを取る。埋めないと輪郭の段差で縁が真横向きになり、縁が暗い帯になった"""
    import numpy as np
    from scipy import ndimage
    f = width / 768
    z = np.asarray(depth.convert("L")).astype(np.float32) / 255
    if body is not None and body.any():
        idx = ndimage.distance_transform_edt(~body, return_distances=False, return_indices=True)
        z = z[tuple(idx)]
    z = ndimage.gaussian_filter(z, 3 * f)
    gy, gx = np.gradient(z)
    k = 40.0 * f                                    # 奥行きの傾きを面の傾きにする強さ
    n = np.stack([-gx * k, gy * k, np.ones_like(z)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def lambert(n, deg, elev=40.0):
    import numpy as np
    t, e = np.radians(deg), np.radians(elev)
    return np.clip(n @ np.array([np.cos(t) * np.cos(e), np.sin(t) * np.cos(e), np.sin(e)]), 0, 1)


def normal_corr(im, depth, parts):
    """推定した面の向きから作った陰影と、絵の明るさの相関（光の向きは 30° 刻みで一番合うもの）。返すのは (相関, 向き)。
    顔と胴の大きな面だけで、大きくならした明るさで測る。部位ごと・細かい明るさで測ると、実写でも髪の筋・服の模様・
    手足の細い面で相関が 0.01〜0.29 に散り、アニメの残る絵と見分けられなかった"""
    import numpy as np
    from scipy import ndimage
    f = im.width / 768
    seg = np.asarray(parts)
    small = (2, 12, 13, 14, 15)                     # 髪・手足は大きな面に入れない
    big = (seg != BACKGROUND) & ~np.isin(seg, small)
    big = ndimage.binary_erosion(big, iterations=max(3, round(8 * f)))
    if big.sum() < 500:
        return None, 0
    L = ndimage.gaussian_filter(np.asarray(im.convert("L")).astype(np.float32), 6 * f)[big]
    n = normals(depth, im.width, seg != BACKGROUND)[big]
    best = (-1.0, 0)
    for deg in range(0, 360, 30):
        c = float(np.corrcoef(lambert(n, deg), L)[0, 1])
        if c > best[0]:
            best = (c, deg)
    return round(best[0], 3), best[1]


def relight(im, parts, depth, deg=135.0, elev=40.0, amount=0.35):
    """奥行きから面の向きを出し、1 つの光（deg: 0° が右、90° が上）で陰と色を付け直す。人物だけに掛ける。
    部位ごとに陰の側が食い違った（顔が下から、腕が左上から照らされた）ので、元の絵の陰を 1 つの光の陰に寄せる。
    色も面の向きに沿わせる: 陰の側は赤を残し青を落とす（肌の中で光が散る分）、光の側はわずかに温かく。
    平らな塗りの上でも、面の向きでなだらかに明るさと色が変わる"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    f = im.width / 768
    body = np.asarray(parts) != BACKGROUND
    sh = lambert(normals(depth, im.width, body), deg, elev)
    sh = sh / max(float(np.median(sh[body])), 1e-3)
    g = np.where(body, 1 - amount + amount * sh, 1.0)
    g = ndimage.gaussian_filter(g, 2 * f)           # 人物の縁で段を作らない
    skin = np.isin(np.asarray(parts), SKIN)
    warm = ndimage.gaussian_filter(skin.astype(np.float32), 2 * f)   # 色の寄せは肌だけ（服と髪の色は変えない）
    gain = np.stack([g ** (1 - 0.1 * warm), g, g ** (1 + 0.08 * warm)], -1)   # 赤・緑・青
    a = np.asarray(im).astype(np.float32) * gain
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def keep_metrics(src, out, src_parts=None):
    """肌の平らな面の割合と、髪・線の形が保てているかを測る（影の検品と並べて毎回出す）。
    flat_skin: 肌の 3x3 の中で RGB の幅が 2 以下の画素の割合（アニメの塗りの残り。0.005 以下を目安）
    hair_iou: 元と描いた絵の髪の部位の重なり。line_f: 元の線と描いた絵の線の一致（2 画素までのずれを許す F 値）"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    import edit
    o = out.resize(src.size, Image.LANCZOS)
    a = np.asarray(o).astype(np.int16)
    rng = ndimage.maximum_filter(a, (3, 3, 1)) - ndimage.minimum_filter(a, (3, 3, 1))
    flat = rng.max(2) <= 2
    po = np.asarray(_parts_of(o))
    ps = np.asarray(src_parts) if src_parts is not None else np.asarray(_parts_of(src))
    skin = ndimage.binary_erosion(np.isin(po, [edit.LABELS[k] for k in ("face", "left_arm", "right_arm", "left_leg", "right_leg")]), iterations=3)
    hs, ho = ps == edit.LABELS["hair"], po == edit.LABELS["hair"]
    ls = np.asarray(lineart(src).convert("L")) > 60
    lo = np.asarray(lineart(o).convert("L")) > 60
    prec = (lo & ndimage.binary_dilation(ls, iterations=2)).sum() / max(lo.sum(), 1)
    rec = (ls & ndimage.binary_dilation(lo, iterations=2)).sum() / max(ls.sum(), 1)
    return {"flat_skin": round(float(flat[skin].mean()), 4) if skin.any() else None,
            "hair_iou": round(float((hs & ho).sum() / max((hs | ho).sum(), 1)), 3),
            "line_f": round(float(2 * prec * rec / max(prec + rec, 1e-6)), 3)}


def _parts_of(im):
    """部位分け（edit.parts）は絵のファイルを受けるので、一時のファイルを通す"""
    import tempfile
    import edit
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.png"
        im.save(f)
        return edit.parts(f).copy()


def check(src, out_img, src_parts, log, tag, ref=None):
    """影の検品（measure.shadow と styles/photoreal-norms.json）と、肌・髪・線・色の保ち方を並べて記録する。
    色は ref（1 段目の絵。無ければ元の絵）と比べる"""
    import numpy as np
    import edit
    import measure
    t = time.time()
    rgb = np.asarray(out_img).astype(np.float32) / 255
    seg = np.asarray(_parts_of(out_img))
    sh = measure.shadow(rgb, seg, edit.LABELS)
    sh["normal_corr"], sh["normal_light_deg"] = normal_corr(out_img, depth_map(out_img), seg)
    km = keep_metrics(src, out_img, src_parts)
    r = ref or src
    rs = np.asarray(src_parts) if ref is None else np.asarray(_parts_of(ref))
    km.update(measure.color_keep(np.asarray(r).astype(np.float32) / 255, rgb, rs, seg, edit.LABELS))
    log(f"{tag}_shadow", sh)
    log(f"{tag}_keep", km)
    log(f"{tag}_fails", measure.judge_shadow({**sh, **km}))
    log(f"{tag}_check_s", round(time.time() - t, 1))


def tiles(length: int, side: int, overlap: int) -> list[int]:
    if length <= side:
        return [0]
    return list(range(0, length - side, side - overlap)) + [length - side]


def load(log, depth=False):
    """tile の pipe と、tile＋lineart の pipe（部品は共有）を 1 回だけ読む"""
    import torch
    from diffusers import (AutoencoderKL, ControlNetModel, DPMSolverMultistepScheduler,
                           StableDiffusionControlNetImg2ImgPipeline)
    from huggingface_hub import hf_hub_download
    t = time.time()
    vae = AutoencoderKL.from_pretrained(VAE)
    tile = ControlNetModel.from_pretrained(TILE)
    la = ControlNetModel.from_pretrained(LINEART, variant="fp16", use_safetensors=True, torch_dtype=torch.float32)
    ck = hf_hub_download(*CHECKPOINT)
    pipe = StableDiffusionControlNetImg2ImgPipeline.from_single_file(
        ck, controlnet=tile, vae=vae, config=CONFIG, torch_dtype=torch.float32,
        safety_checker=None, feature_extractor=None, requires_safety_checker=False)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
    pipe.set_progress_bar_config(disable=True)
    c = dict(pipe.components)
    c.pop("controlnet")
    nets = [tile, la]
    if depth:
        nets.append(ControlNetModel.from_pretrained(DEPTH, variant="fp16", use_safetensors=True, torch_dtype=torch.float32))
    multi = StableDiffusionControlNetImg2ImgPipeline(**c, controlnet=nets)
    multi.set_progress_bar_config(disable=True)
    log("load_s", round(time.time() - t, 1))
    return pipe, multi


def stage1(multi, clean, li, a, log, depth=None, hair=None):
    """1 段目。hair（髪の部位の真偽の配列）があれば、髪の範囲だけ strength を a.hair_strength に下げる:
    各段の後で、髪の範囲の潜在を元の絵に同じ雑音を足したものに戻し、最後の a.hair_strength の分だけ描かせる。
    strength 0.7 で、ボブの髪が長い髪に描き変わった（髪の重なり 0.94 → 0.76）"""
    import numpy as np
    import torch
    t = time.time()
    ctl, sc = [clean, li], [a.tile_scale, a.lineart_scale]
    if depth is not None and a.depth_scale > 0:
        ctl.append(depth)
        sc.append(a.depth_scale)
    kw = {}
    if hair is not None and hair.any() and 0 <= a.hair_strength < a.strength:
        from scipy import ndimage
        x = multi.image_processor.preprocess(clean).to(torch.float32)
        with torch.no_grad():
            init = multi.vae.encode(x).latent_dist.mean * multi.vae.config.scaling_factor
        noise = torch.randn(init.shape, generator=torch.Generator().manual_seed(a.seed + 1000))
        h, w = init.shape[-2:]
        m = ndimage.zoom(ndimage.binary_dilation(hair, iterations=8).astype(np.float32), (h / hair.shape[0], w / hair.shape[1]), order=1)
        m = torch.from_numpy(np.clip(ndimage.gaussian_filter(m, 1), 0, 1))[None, None]
        free = int(round(a.steps * a.hair_strength))     # 髪を描かせる最後の段の数

        def keep_hair(pipe, i, ts, kws):
            sch = pipe.scheduler
            k = sch.step_index
            if k is not None and k < len(sch.timesteps) - free:
                ref = sch.add_noise(init, noise, sch.timesteps[k:k + 1])
                kws["latents"] = kws["latents"] * (1 - m) + ref * m
            return kws
        kw = {"callback_on_step_end": keep_hair, "callback_on_step_end_tensor_inputs": ["latents"]}
    r = multi(a.prompt, negative_prompt=a.negative, image=clean, control_image=ctl, strength=a.strength,
              controlnet_conditioning_scale=sc, num_inference_steps=a.steps,
              guidance_scale=a.guidance, generator=torch.Generator().manual_seed(a.seed),
              width=clean.width, height=clean.height, **kw).images[0]
    log("stage1_s", round(time.time() - t, 1))
    log("stage1_rss_gb", round(rss_gb(), 2))
    return r


ICLIGHT = ("lllyasviel/ic-light", "iclight_sd15_fc.safetensors")


def light_gradient(size, deg):
    """光の向き（0° が右、90° が上）に明るくなる灰色の勾配。IC-Light の fc 版に光の向きを渡す背景"""
    import numpy as np
    from PIL import Image
    W, H = size
    yy, xx = np.mgrid[:H, :W].astype(np.float32)
    v = np.cos(np.radians(deg)) * (xx / W - 0.5) + np.sin(np.radians(deg)) * (0.5 - yy / H)
    v = (v - v.min()) / max(v.max() - v.min(), 1e-6)
    return Image.fromarray((v * 255).astype(np.uint8)).convert("RGB")


def iclight_merge(img, r, parts):
    """IC-Light の絵 r から明るさだけを取り、1 段目の絵 img に合わせる"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    r = r.resize(img.size, Image.LANCZOS)
    # 明るさだけを使う。IC-Light の色をそのまま使うと、灰色の勾配に引かれて絵が灰色に抜け、黒髪が白くなった。
    # 低い周波数の明るさ（Lab の L）だけを IC-Light から取り、色（a,b）と細かい明るさは 1 段目のまま
    mix = np.asarray(hfmix(img, r, sigma=4.0 * img.width / 768)).astype(np.float32) / 255
    lab0, labm = rgb2lab(np.asarray(img).astype(np.float32) / 255), rgb2lab(mix)
    hair = np.asarray(parts) == 2
    w = ndimage.gaussian_filter(((np.asarray(parts) != BACKGROUND) & ~hair).astype(np.float32), 2)   # 髪の明るさも替えない
    m = w > 0.5
    if m.any():   # 明るさの平均は 1 段目にそろえ、陰の付き方（明るさの変わり方）だけを取る。そのままでは体が全体に暗く沈んだ
        labm[..., 0] += float(lab0[..., 0][m].mean() - labm[..., 0][m].mean())
    lab0[..., 0] = labm[..., 0] * w + lab0[..., 0] * (1 - w)
    o = lab2rgb(lab0) * 255
    return Image.fromarray(np.clip(o, 0, 255).astype(np.uint8))


def iclight(pipe, img, parts, a, log):
    """IC-Light（SD1.5、fc 版）で人物に 1 方向の光を付け直す。Realistic Vision の UNet に IC-Light の差分を足して入力を 8 ch にし、
    人物（背景を灰色にした絵）の潜在を毎段つなげて描く。終わったら差分を引いて元の UNet に戻す（2 段目で使い回すため。
    UNet を写すとメモリが 3.4GB 増えて 16GB の機械に乗らない）。返す絵は、人物の中だけ IC-Light の低い周波数と
    1 段目の高い周波数（肌の肌理と線）を合わせる"""
    import numpy as np
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionImg2ImgPipeline
    from huggingface_hub import hf_hub_download
    from PIL import Image
    from safetensors.torch import load_file
    from scipy import ndimage
    t = time.time()
    unet = pipe.unet
    off = load_file(hf_hub_download(*ICLIGHT))
    old_conv, old_fwd = unet.conv_in, unet.forward
    with torch.no_grad():
        conv = torch.nn.Conv2d(8, old_conv.out_channels, old_conv.kernel_size, old_conv.stride, old_conv.padding)
        conv.weight.zero_()
        conv.weight[:, :4].copy_(old_conv.weight)
        conv.bias.copy_(old_conv.bias)
        unet.conv_in = conv
        sd = unet.state_dict()
        for k, v in off.items():
            sd[k].add_(v.to(sd[k].dtype))

    def fwd(sample, timestep, encoder_hidden_states, **kw):
        c = kw["cross_attention_kwargs"]["concat_conds"].to(sample)
        c = torch.cat([c] * (sample.shape[0] // c.shape[0]), 0)
        kw["cross_attention_kwargs"] = {}
        return old_fwd(torch.cat([sample, c], 1), timestep, encoder_hidden_states, **kw)
    unet.forward = fwd
    try:
        body = ndimage.binary_dilation(np.asarray(parts) != BACKGROUND, iterations=3)
        fg = np.where(body[..., None], np.asarray(img), 127).astype(np.uint8)
        proc = pipe.image_processor
        with torch.no_grad():
            cc = pipe.vae.encode(proc.preprocess(Image.fromarray(fg)).float()).latent_dist.mode() * pipe.vae.config.scaling_factor
        i2i = StableDiffusionImg2ImgPipeline(vae=pipe.vae, text_encoder=pipe.text_encoder, tokenizer=pipe.tokenizer, unet=unet,
                                             scheduler=DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True),
                                             safety_checker=None, feature_extractor=None, requires_safety_checker=False)
        i2i.set_progress_bar_config(disable=True)
        r = i2i(a.prompt + ", soft directional light", negative_prompt=a.negative, image=light_gradient(img.size, a.light_deg),
                strength=a.iclight, num_inference_steps=a.steps, guidance_scale=2.0,
                generator=torch.Generator().manual_seed(a.seed), cross_attention_kwargs={"concat_conds": cc}).images[0]
    finally:
        unet.forward = old_fwd
        with torch.no_grad():
            sd = unet.state_dict()
            for k, v in off.items():
                if k in sd and sd[k].shape == v.shape:
                    sd[k].sub_(v.to(sd[k].dtype))
        unet.conv_in = old_conv
    o = iclight_merge(img, r, parts)
    log("iclight_s", round(time.time() - t, 1))
    log("iclight_rss_gb", round(rss_gb(), 2))
    return r, o


def rgb2lab(rgb):
    import measure
    return measure.lab(rgb)


def lab2rgb(L):
    """Lab（D65）を sRGB（0〜1）に戻す（measure.lab の逆）"""
    import numpy as np
    fy = (L[..., 0] + 16) / 116
    fx, fz = fy + L[..., 1] / 500, fy - L[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787) * np.array([0.95047, 1.0, 1.08883])
    c = xyz @ np.linalg.inv(np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]]))
    c = np.clip(c, 0, 1)
    return np.clip(np.where(c > 0.0031308, 1.055 * c ** (1 / 2.4) - 0.055, 12.92 * c), 0, 1)


def face_fix(pipe, img, parts, a, log):
    """顔だけを正方形に切り出して 768 に広げ、tile で弱く描き直し、縁をぼかした楕円で戻す（imgproc.face_redraw と同じ形。
    あちらは SDXL の言葉の組み立てを使うので、SD1.5 の pipe ではここで描く）。全身の絵で顔は 100 画素前後しかなく、
    描き直しの後に唇のにじみ、目にかかる髪の崩れが残った"""
    import numpy as np
    import torch
    from PIL import Image, ImageDraw, ImageFilter
    import closeup
    t = time.time()
    seg = np.asarray(parts)
    if seg.shape != (img.height, img.width):
        seg = np.asarray(parts.resize(img.size, Image.NEAREST))
    b = closeup._bbox(seg == 11)
    if b is None:
        return img
    box = closeup.square(b, img.width, img.height, margin=0.25)
    crop = img.crop(box)
    big = crop.resize((768, 768), Image.LANCZOS)
    r = pipe(a.prompt + ", detailed face, detailed eyes, natural lips", negative_prompt=a.negative + ", deformed face, asymmetric eyes",
             image=big, control_image=big, strength=a.face, controlnet_conditioning_scale=0.8, num_inference_steps=a.steps,
             guidance_scale=a.guidance, generator=torch.Generator().manual_seed(a.seed + 7), width=768, height=768).images[0]
    small = r.resize(crop.size, Image.LANCZOS)
    w, h = crop.size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse([w * 0.08, h * 0.08, w * 0.92, h * 0.92], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(w // 16, 2)))
    out = img.copy()
    out.paste(small, box[:2], m)
    log("face_box", list(box))
    log("face_s", round(time.time() - t, 1))
    return out


def face_qc(img):
    try:
        return _face_qc(img)
    except Exception as e:   # 検品の部品が読めないときは通さない（読めない検品を通ったことにしない）
        return False, {"eyes": {"readable": False, "reason": f"{type(e).__name__}: {e}"}, "extra_eyes": None}


def _face_qc(img):
    """既存の顔の検品で顔を見る: 目が 2 つ読めて左右の大きさが釣り合う（qc.eye_mismatch）、タグが余分な目を読まない（qc.EXTRA_EYES）。
    返すのは (通ったか, 数字)"""
    import tempfile
    import numpy as np
    import edit
    import faceform
    import measure
    import qc
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "face.png"
        img.save(f)
        rgb = np.asarray(img, dtype=np.float32) / 255.0
        seg = np.asarray(edit.parts(f))
        view = {}
        hrgb, hseg = faceform.head_view(f, rgb, seg, view)
        eyes = measure.eyes(hrgb, hseg, edit.LABELS)
        mis = qc.eye_mismatch(eyes)
        extra = 0.0
        try:
            import tagger
            extra = float(tagger.read(f, 0.0).get("extra eyes", 0.0))
        except Exception as e:   # タグの模型が無ければ目の数字だけで見る
            print("tagger", e, flush=True)
    ok = bool(mis.get("readable")) and not mis.get("mismatch") and extra < qc.EXTRA_EYES
    return ok, {"eyes": mis, "extra_eyes": round(extra, 3)}


def face_inpaint(pipe, nets, img, a, log, tries=5):
    """顔の部位だけを inpaint で描き直す。顔の枠は骨格の点から取り（qc._face_from_joints）、2.5 倍に広げて 768 に拡大して描く。
    髪は描き直す範囲から外し、lineart の ControlNet で髪の線を押さえる（目に髪がかかったまま描かれたため）。
    既存の顔の検品（face_qc）を通るまで種を変えて描き直す（上限 tries 回）。通らなければ一番目の数字の良い絵を返す。
    tile で枠を丸ごと弱く描き直す方法（0.35）では、目にかかる髪と顔のにじみが直らなかった"""
    import tempfile
    import numpy as np
    import torch
    from diffusers import StableDiffusionControlNetInpaintPipeline
    from PIL import Image, ImageFilter
    from scipy import ndimage
    import closeup
    import qc
    t = time.time()
    ok0, q0 = face_qc(img)
    log("face_before", {"ok": ok0, **q0})
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.png"
        img.save(f)
        box = qc._face_from_joints(str(f), img.size)
    seg = np.asarray(_parts_of(img))
    if box is None:
        b = closeup._bbox(seg == 11)
        if b is None:
            return img
        box = b
    x0, y0, x1, y1 = box
    side = int(max(x1 - x0, y1 - y0) * 2.5)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = min(side, img.width, img.height)
    left = int(min(max(cx - side / 2, 0), img.width - side))
    top = int(min(max(cy - side / 2, 0), img.height - side))
    box = (left, top, left + side, top + side)
    crop = img.crop(box).resize((768, 768), Image.LANCZOS)
    cs = np.asarray(Image.fromarray(seg).crop(box).resize((768, 768), Image.NEAREST))
    m = ndimage.binary_dilation(cs == 11, iterations=6) & (cs != 2)          # 髪は描き直さない
    mask = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(4))
    li = lineart(crop)
    inp = StableDiffusionControlNetInpaintPipeline(**{k: v for k, v in pipe.components.items() if k != "controlnet"}, controlnet=nets)
    inp.set_progress_bar_config(disable=True)
    best = None
    for k in range(tries):
        r = inp(a.prompt + ", detailed face, symmetric eyes, natural lips, eyes visible", negative_prompt=a.negative + ", hair over eyes, deformed face, asymmetric eyes, extra eyes",
                image=crop, mask_image=mask, control_image=[crop, li], strength=a.face, controlnet_conditioning_scale=[0.5, 1.0],
                num_inference_steps=a.steps, guidance_scale=a.guidance, generator=torch.Generator().manual_seed(a.seed + 100 + k),
                width=768, height=768).images[0]
        small = r.resize((side, side), Image.LANCZOS)
        pm = mask.resize((side, side), Image.LANCZOS)
        out = img.copy()
        out.paste(small, box[:2], pm)
        ok, q = face_qc(out)
        log(f"face_try{k}", {"ok": ok, **q, "s": round(time.time() - t, 1)})
        score = q["eyes"].get("area_ratio", 99) if q["eyes"].get("readable") else 99
        if best is None or ok or score < best[0]:
            best = (score if not ok else -1, out)
        if ok:
            break
    log("face_box", list(box))
    log("face_s", round(time.time() - t, 1))
    return best[1]


def cast_shadow(img, parts, depth, deg=135.0, opacity=0.45):
    """床に落ち影を合成する。人物の形を、足元を支点に光と逆の向きへ倒して床に写す（光が左上なら右の奥へ）。
    奥行きで手前ほど高い所（体の厚み）として倒れ方を強め、足から離れるほどぼかして薄くする。背景だけを暗くする。
    元の絵の床は足元が周りより明るく（cast −0.5）、人物が浮いて見えた"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    p = np.asarray(parts)
    body = p != BACKGROUND
    if not body.any():
        return img
    H, W = body.shape
    f = W / 768
    ys, xs = np.nonzero(body)
    foot = ys.max()
    z = np.asarray(depth.convert("L")).astype(np.float32)[ys, xs] / 255
    h = (foot - ys).astype(np.float32)
    dx = -np.cos(np.radians(deg))                    # 光と逆の左右
    sx = xs + dx * h * 0.8 * (0.8 + 0.4 * z)
    sy = foot - h * 0.18                             # 奥へ倒れるので上に縮んで写る
    ok = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
    acc = np.zeros((H, W), np.float32)
    far = np.zeros((H, W), np.float32)
    np.add.at(acc, (sy[ok].astype(int), sx[ok].astype(int)), 1)
    np.add.at(far, (sy[ok].astype(int), sx[ok].astype(int)), h[ok])
    m = ndimage.binary_closing(acc > 0, iterations=max(2, round(4 * f)))
    dist = np.where(acc > 0, far / np.maximum(acc, 1), 0)
    dist = ndimage.grey_dilation(dist, size=max(3, round(6 * f))) / max(foot - ys.min(), 1)
    near = ndimage.gaussian_filter(m.astype(np.float32), 3 * f)
    farb = ndimage.gaussian_filter(m.astype(np.float32), 14 * f)
    k = np.clip(ndimage.gaussian_filter(dist, 8 * f), 0, 1)
    s = (near * (1 - k) + farb * k) * (1 - 0.5 * k)  # 足から離れるほどぼけて薄い
    cy, cx = foot, int(xs[ys > foot - 0.03 * H].mean())
    yy, xx = np.mgrid[:H, :W]
    contact = np.exp(-(((xx - cx) / (40 * f)) ** 2 + ((yy - cy) / (8 * f)) ** 2))   # 足元の接地の影
    s = np.clip(np.maximum(s, contact), 0, 1) * ~body
    a = np.asarray(img).astype(np.float32) * (1 - opacity * s)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def stage2(pipe, src, a, log):
    """拡大してから tile をもう一度。重ねたタイルで描いて縁をなだらかに混ぜる"""
    import numpy as np
    import torch
    from PIL import Image
    t = time.time()
    T, ov = a.tile, a.overlap
    W, H = int(src.width * a.scale) // 8 * 8, int(src.height * a.scale) // 8 * 8
    big = src.resize((W, H), Image.LANCZOS)
    acc = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    xs, ys = tiles(W, T, ov), tiles(H, T, ov)
    ramp = np.minimum(np.minimum(np.arange(T), np.arange(T)[::-1]) / ov, 1) + 1e-3
    wt = (ramp[None, :] * ramp[:, None])[..., None]
    n = 0
    for y in ys:
        for x in xs:
            c = big.crop((x, y, x + T, y + T))
            r = pipe(a.prompt, negative_prompt=a.negative, image=c, control_image=c, strength=a.strength2,
                     controlnet_conditioning_scale=a.tile2_scale, num_inference_steps=a.steps,
                     guidance_scale=a.guidance, generator=torch.Generator().manual_seed(a.seed + n),
                     width=T, height=T).images[0]
            acc[y:y + T, x:x + T] += np.asarray(r).astype(np.float32) * wt
            wsum[y:y + T, x:x + T] += wt
            n += 1
            print("tile", n, len(xs) * len(ys), round(time.time() - t), flush=True)
    log("stage2_tiles", n)
    log("stage2_s", round(time.time() - t, 1))
    log("stage2_rss_gb", round(rss_gb(), 2))
    return Image.fromarray(np.clip(acc / wsum, 0, 255).astype(np.uint8))


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path, help="入力の絵（隣に <絵>.parts.png が要る）")
    ap.add_argument("out", type=Path, help="書き出す場所")
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--height", type=int, default=1152)
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--negative", default=NEGATIVE)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--guidance", type=float, default=6.0)
    ap.add_argument("--strength", type=float, default=0.7, help="1 段目の強さ")
    ap.add_argument("--tile-scale", type=float, default=0.6)
    ap.add_argument("--lineart-scale", type=float, default=0.8)
    ap.add_argument("--scale", type=float, default=1.5, help="2 段目の拡大率（0 なら 2 段目をしない）")
    ap.add_argument("--strength2", type=float, default=0.25)
    ap.add_argument("--hf-sigma", type=float, default=2.5, help="1 段目の高い周波数を戻す幅（0 なら戻さない）")
    ap.add_argument("--hf-amount", type=float, default=1.0)
    ap.add_argument("--tile2-scale", type=float, default=0.8)
    ap.add_argument("--tile", type=int, default=768)
    ap.add_argument("--overlap", type=int, default=128)
    ap.add_argument("--deshade", type=float, default=0, help="1 段目の前にセルの影の段差をならす幅（768 幅の画素、0 ならしない）")
    ap.add_argument("--depth-scale", type=float, default=0, help="depth の ControlNet の強さ（0 なら使わない）")
    ap.add_argument("--relight", type=float, default=0, help="奥行きから付け直す陰の量（0 ならしない）")
    ap.add_argument("--light-deg", type=float, default=135, help="付け直す光の向き（0° が右、90° が上）")
    ap.add_argument("--hair-strength", type=float, default=-1, help="髪の範囲の 1 段目の強さ（負なら全体と同じ）")
    ap.add_argument("--iclight", type=float, default=0, help="1 段目の後に IC-Light を掛ける強さ（0 ならしない）")
    ap.add_argument("--post-relight", type=float, default=0, help="描き直しの後に奥行きから陰と色を付け直す量（0 ならしない）")
    ap.add_argument("--cast", type=float, default=0, help="床の落ち影の濃さ（0 なら付けない）")
    ap.add_argument("--face", type=float, default=0, help="最後に顔を inpaint で描き直す強さ（0 ならしない）")
    ap.add_argument("--final-hf", type=float, default=0, help="工程の最後に高い周波数を戻す幅（0 ならしない）")
    ap.add_argument("--check", action="store_true", help="段ごとに影の検品と肌・髪・線の保ち方を測る（部位分けの模型を読む）")
    ap.add_argument("--dry-run", action="store_true", help="模型を読まず、帯消しと lineart だけ書き出す")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse(argv if argv is not None else sys.argv[1:])
    if not Path(str(a.src) + ".parts.png").exists():
        # library の .parts.png は git に入れない（検品の副産物）ので、Actions では無い。無ければ部位分けの模型で作って隣に置く
        if a.dry_run:
            print(f"部位の絵がありません: {a.src}.parts.png（--dry-run は模型を読まないので作らない）", file=sys.stderr)
            return 2
        import edit
        t = time.time()
        edit.parts(a.src)
        print("parts_s", round(time.time() - t, 1), flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    log = Log(a.out / "times.json")
    log("args", {k: str(v) for k, v in vars(a).items()})
    stem = a.src.name.split(".")[0]
    t = time.time()
    im, parts = load_source(a.src, a.width, a.height)
    clean, px = clean_band(im, parts)
    clean, bpx = fill_blobs(clean)
    li = lineart(clean)                           # 線は段差をならす前の絵から取る（線の形を保つ）
    if a.deshade > 0:
        t1 = time.time()
        clean = deshade(clean, parts, a.deshade)
        log("deshade_s", round(time.time() - t1, 2))
    clean.save(a.out / f"{stem}-0-clean.png")
    li.save(a.out / f"{stem}-0-lineart.png")
    log("band_px", px)
    log("blob_px", bpx)
    log("clean_s", round(time.time() - t, 2))
    if a.dry_run:
        return 0
    dep = None
    if a.depth_scale > 0 or a.relight > 0:
        t1 = time.time()
        dep = depth_map(clean)
        dep.save(a.out / f"{stem}-0-depth.png")
        log("depth_s", round(time.time() - t1, 1))
    if a.relight > 0:
        clean = relight(clean, parts, dep, a.light_deg, amount=a.relight)
        clean.save(a.out / f"{stem}-0-relit.png")
    if a.check:
        check(im, clean, parts, log, "input")
    pipe, multi = load(log, depth=a.depth_scale > 0)
    import numpy as np
    from PIL import Image
    hair = np.asarray(parts) == 2 if a.hair_strength >= 0 else None   # 2 は髪（edit.LABELS）
    r1 = stage1(multi, clean, li, a, log, dep, hair)
    r1.save(a.out / f"{stem}-1-photoreal-st{a.strength}-s{a.seed}.png")
    r1_color = r1                                  # 色の検品の基準（描き直しの後の工程は 1 段目の色を保つ）
    if a.check:
        check(im, r1, parts, log, "stage1")
    nets = multi.controlnet.nets[:2] if hasattr(multi.controlnet, "nets") else multi.controlnet   # tile と lineart（顔の描き直しで使い回す）
    del multi
    if a.iclight > 0:
        raw, r1 = iclight(pipe, r1, parts, a, log)
        raw.save(a.out / f"{stem}-1b-iclight-raw.png")
        r1.save(a.out / f"{stem}-1b-iclight.png")
        if a.check:
            check(im, r1, parts, log, "iclight", ref=r1_color)
    if a.scale > 0:
        r2 = stage2(pipe, r1, a, log)
        r2.save(a.out / f"{stem}-2-tile-x{a.scale}-s{a.seed}.png")
        if a.check:
            check(im, r2, parts, log, "stage2", ref=r1_color)
        if a.hf_sigma > 0:
            r3 = hfmix(r1, r2, a.hf_sigma, a.hf_amount)
            r3.save(a.out / f"{stem}-3-hf-g{a.hf_sigma}-s{a.seed}.png")
            r2 = r3
            if a.check:
                check(im, r2, parts, log, "hf", ref=r1_color)
    else:
        r2 = r1
    if a.post_relight > 0 or a.cast > 0:
        t1 = time.time()
        p2 = _parts_of(r2)
        d2 = depth_map(r2)
        if a.post_relight > 0:
            r2 = relight(r2, p2, d2, a.light_deg, amount=a.post_relight)
        if a.cast > 0:
            r2 = cast_shadow(r2, p2, d2, a.light_deg, a.cast)
        r2.save(a.out / f"{stem}-4-light-r{a.post_relight}-c{a.cast}-s{a.seed}.png")
        log("post_light_s", round(time.time() - t1, 1))
        if a.check:
            check(im, r2, parts, log, "light", ref=r1_color)
    textured = r2
    if a.face > 0:
        r2 = face_inpaint(pipe, nets, r2, a, log)
        r2.save(a.out / f"{stem}-5-face-f{a.face}-s{a.seed}.png")
        if a.check:
            check(im, r2, parts, log, "face", ref=r1_color)
    if a.final_hf > 0:
        # 工程の最後にも高い周波数を戻す。光の付け直し・顔の描き直しは低い周波数を変えるが、肌理は 2 段目の後の絵から取る
        keep = np.asarray(_parts_of(r2)) == 11
        mixed = hfmix(textured, r2, a.final_hf, 1.0)
        mm = np.asarray(mixed).copy()
        mm[keep] = np.asarray(r2)[keep]          # 顔は描き直した絵の肌理を使う
        r2 = Image.fromarray(mm)
        r2.save(a.out / f"{stem}-6-finalhf-g{a.final_hf}-s{a.seed}.png")
    if a.check:
        check(im, r2, parts, log, "final", ref=r1_color)
    log("total_s", round(time.time() - t, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
