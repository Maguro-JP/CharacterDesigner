"""キャラクターデザインの絵を、背景つきの完成絵にする。人物と背景を別々に作り、レイヤーで重ねて PSD に書き出す。

人物と背景を1回で描くと、モデルの力が人物に寄り、背景が白っぽく薄くなった。手本（デザイン画）の白い背景にも引っ張られ、
水着の縁の色まで変わった（2026-10-06、docs/knowledge/traits.md）。そこで分けて作る。

  1. 人物: デザイン画をそのまま切り抜く。水着の形と色がデザインのまま残る
  2. 背景: 人を描かない指定（no humans）で、場面だけを描く。モデルの力を全部背景に使える
  3. 影と光: 背景の色から光の色を取り、接地の影・全体の色寄せ・縁の光（リムライト）を別のレイヤーで作る
  4. 部位: 髪・肌・水着を部位分け（segformer）で別のレイヤーにする（人物レイヤーは1枚でも残す）
  5. 書き出し: PSD（Photoshop・CLIP STUDIO で開ける）と、重ねた1枚の PNG。
     --blend を付けると、重ねた絵を軽く描き直して境目をなじませた1枚も出す（レイヤーは描き直さない）

線画と塗りは分けられない（画像を作るモデルは線と色を一緒に描く）。部位の境目は部位分けの精度に左右される。

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/layers.py <デザイン画.png> <出力フォルダ> --scene "<背景の言葉（英語）>" \
      [--light front|left|right|back] [--seed 7] [--height 0.8] [--x 0.5] [--blend 0.3 --prompt "<人物の言葉>"]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
sys.path.insert(0, str(Path(__file__).parent))

SIZE = (832, 1216)   # 縦長。全身の人物が大きく入る
BG_NEGATIVE = ("1girl, 1boy, person, people, human, character, figure, silhouette, aerial view, from above, high angle, "
               "text, watermark, signature, "
               "lowres, blurry, worst quality, low quality, jpeg artifacts, frame, border")
# 部位分け（segformer b3 clothes）の番号。水着は上下の服として出る
PART_IDS = {"髪": [2], "肌": [11, 12, 13, 14, 15], "水着・服": [4, 5, 6, 7, 8, 17], "帽子・小物": [1, 3, 9, 10, 16]}


# ---- 1. 人物 ----

def cut_character(src):
    """デザイン画から人物を切り抜く（背景は透明）。縁は 1px ぼかして、背景に重ねたときのギザギザを抑える。"""
    import design
    im = Image.open(src)
    # 透明の部分がある絵（別の方法で切り抜いた人物）は、その切り抜きをそのまま使う
    cut = im.convert("RGBA") if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255 else design.cut_background(im.convert("RGB"))
    # 縁の色を、内側の色で置き換える。デザイン画の白い背景が縁（特に髪の細い房）に混ざっていて、背景に重ねると白く光った。
    # 縁を削るだけでは髪の房が残り、削りすぎると房が消える
    alpha = cut.getchannel("A")
    inner = alpha.filter(ImageFilter.MinFilter(9))
    rgb = np.asarray(cut.convert("RGB")).astype(float)
    w = np.asarray(inner).astype(float)[..., None] / 255
    num = np.stack([np.asarray(Image.fromarray((rgb[..., c] * w[..., 0]).astype("uint8")).filter(ImageFilter.GaussianBlur(5))).astype(float)
                    for c in range(3)], axis=-1)
    den = np.asarray(Image.fromarray((w[..., 0] * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(5))).astype(float)[..., None] / 255
    bleed = np.where(den > 0.02, num / np.maximum(den, 1e-3), rgb)
    band = (np.asarray(alpha) > 0) & (np.asarray(inner) == 0)
    rgb[band] = bleed[band]
    a = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    cut = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).convert("RGBA")
    cut.putalpha(a)
    return cut.crop(a.point(lambda v: 255 if v > 8 else 0).getbbox())


def place(char, height=0.8, x=0.5, foot=0.93):
    """人物を画面の大きさに合わせて置く。高さは画面の割合、x は中心の横位置、foot は足元の高さ。"""
    h = int(SIZE[1] * height)
    w = int(char.width * h / char.height)
    c = char.resize((w, h), Image.LANCZOS)
    layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    layer.paste(c, (int(SIZE[0] * x - w / 2), int(SIZE[1] * foot - h)), c)
    return layer


# ---- 2. 背景 ----

def background(scene, seed, steps=28):
    """人を描かない場面の絵を描く。人物が混ざったら seed を変えて描き直す（最大 3 回）。"""
    import torch
    import design
    import people
    pipe = people.pipe()
    # 目の高さで描かせる。指定しないと見下ろしの構図になり、目の高さで描いた人物が巨人のように浮いた
    prompt = "no humans, scenery, detailed background, eye level, horizon in the middle, " + scene + ", " + people.QUALITY
    for k in range(3):
        t = time.time()
        pe, ne, pp, np_ = design.encode_xl(pipe, prompt, BG_NEGATIVE)
        kw = {}
        if people._IP:
            pipe.set_ip_adapter_scale(0.0)
            kw["ip_adapter_image"] = Image.new("RGB", (224, 224), "white")
        im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  num_inference_steps=steps, guidance_scale=6.0, width=SIZE[0], height=SIZE[1],
                  generator=torch.Generator().manual_seed(seed + k * 100), **kw).images[0]
        people_found = has_person(im)
        print(f"背景: {time.time() - t:.0f} 秒 seed {seed + k * 100} " + ("人が混ざった" if people_found else "通った"), flush=True)
        if not people_found:
            return im
    return im


def has_person(im):
    """背景に人が混ざっていないか。部位分けで顔か腕か脚が一定以上あれば「混ざった」とする。"""
    import edit
    tmp = Path("/tmp/_layers_bg_check.png")
    im.save(tmp)
    lab = np.asarray(edit.parts(tmp))
    return np.isin(lab, [11, 12, 13, 14, 15]).mean() > 0.004


# ---- 3. 影と光 ----

def light_of(bg):
    """背景の光の色と、全体の色（平均）を返す。

    光の色は明るさの 85〜96% の帯の平均。最も明るい所（太陽の芯）は白に飛んでいて、夕日でも縁の光が白くなった。
    """
    a = np.asarray(bg.convert("RGB")).reshape(-1, 3).astype(float)
    lum = a @ [0.299, 0.587, 0.114]
    top = a[(lum >= np.percentile(lum, 85)) & (lum <= np.percentile(lum, 96))].mean(axis=0)
    return tuple(int(v) for v in top), tuple(int(v) for v in a.mean(axis=0))


def contact_shadow(char_layer, ambient):
    """足元の接地の影。人物の足元の幅に合わせた楕円をぼかす。色は背景の平均を暗くしたもの（黒にしない）。"""
    a = np.asarray(char_layer.getchannel("A")) > 128
    ys, xs = np.nonzero(a)
    foot_y = ys.max()
    feet = xs[ys > foot_y - (ys.max() - ys.min()) * 0.06]
    cx, rw = (feet.min() + feet.max()) / 2, (feet.max() - feet.min()) * 0.9 + 30
    m = Image.new("L", SIZE, 0)
    from PIL import ImageDraw
    ImageDraw.Draw(m).ellipse((cx - rw, foot_y - 14, cx + rw, foot_y + 18), fill=150)
    m = m.filter(ImageFilter.GaussianBlur(14))
    col = tuple(int(v * 0.35) for v in ambient)
    layer = Image.new("RGBA", SIZE, col + (0,))
    layer.putalpha(m)
    return layer


def grade_strength(ambient):
    """色寄せの強さ。背景が暗いほど強くする（夕暮れで人物だけ昼のように明るく浮いた）。明るい昼は 0.12、暗い夕暮れで 0.45 まで"""
    lum = 0.299 * ambient[0] + 0.587 * ambient[1] + 0.114 * ambient[2]
    return float(np.clip(0.12 + (175 - lum) / 255 * 0.9, 0.12, 0.45))


def color_grade(char_layer, ambient, strength=None):
    """人物を背景の色に寄せる層（乗算）。背景の平均の色を、人物の形で重ねる。"""
    strength = grade_strength(ambient) if strength is None else strength
    a = char_layer.getchannel("A").point(lambda v: int(v * strength))
    tint = tuple(int(255 - (255 - c) * 0.9) for c in ambient)
    layer = Image.new("RGBA", SIZE, tint + (0,))
    layer.putalpha(a)
    return layer


def rim_light(char_layer, light, side="back", width=6):
    """縁の光（スクリーン）。光の来る側の輪郭に沿って、光の色の細い帯を置く。back は両側と上。"""
    a = char_layer.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    inner = a.filter(ImageFilter.MinFilter(width * 2 + 1))
    band = np.asarray(ImageChops.subtract(a, inner)).astype(float)
    H, W = band.shape
    xs = np.linspace(0, 1, W)[None, :].repeat(H, 0)
    ys = np.linspace(0, 1, H)[:, None].repeat(W, 1)
    weight = {"left": 1 - xs, "right": xs, "front": np.full((H, W), 0.35), "back": np.clip(1.2 - ys, 0.3, 1.0)}[side]
    m = Image.fromarray(np.clip(band * weight, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2))
    layer = Image.new("RGBA", SIZE, light + (0,))
    layer.putalpha(m)
    return layer


_DEPTH = None


_DEPTH_CACHE = {}


def depth_map(bg):
    """背景の奥行き（大きいほど手前）。Depth Anything V2 Small（Apache-2.0、約 100MB、1枚 約6秒）。"""
    global _DEPTH
    key = hash(bg.tobytes())
    if key in _DEPTH_CACHE:
        return _DEPTH_CACHE[key]
    if _DEPTH is None:
        from transformers import pipeline
        _DEPTH = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device="cpu")
    d = _DEPTH(bg)["predicted_depth"]
    d = d.squeeze().numpy() if hasattr(d, "numpy") else np.asarray(d)
    _DEPTH_CACHE[key] = np.asarray(Image.fromarray(d.astype("float32")).resize(SIZE, Image.BILINEAR))
    return _DEPTH_CACHE[key]


def horizon(bg):
    """地平線の高さ（画面の上からの割合）。空は奥行きがほぼ 0 なので、最も遠い所（最大の 0.3% 未満）が行の半分を超える一番下の行。
    見えている水平線と、3枚の背景で画面の 3% 以内で合った。空が見えない背景は None（大きさは --height で決める）"""
    d = depth_map(bg)
    rows = np.where((d < d.max() * 0.003).mean(axis=1) > 0.5)[0]
    return float(rows.max()) / SIZE[1] if len(rows) else None


def perspective_height(horizon_y, foot, eye=0.93):
    """遠近に合う人物の高さ（画面の割合）。目の高さのカメラでは、立っている人の目はどの距離でも地平線に来る。
    目は足元から身長の eye の高さにあるので、身長 =（足元 − 地平線）/ eye"""
    return (foot - horizon_y) / eye


def foreground(bg, char_layer, margin=1.12):
    """人物の足元より手前にある背景の物（ひまわり、岩、しぶき）を切り出し、人物の前に重ねる層。

    足元の奥行きを基準に、それより margin 倍以上手前の所を前景とする。平らな地面は足元より下にしか無いので人物に掛からない。
    人物に掛かる所だけを残す（掛からない所は背景と同じなので要らない）。
    """
    d = depth_map(bg)
    a = np.asarray(char_layer.getchannel("A")) > 128
    ys, xs = np.nonzero(a)
    fy, fx = ys.max(), int(np.median(xs[ys > ys.max() - 10]))
    fd = float(np.median(d[max(0, fy - 8):fy + 8, max(0, fx - 30):fx + 30]))
    near = d > fd * margin
    grown = np.asarray(Image.fromarray(a.astype("uint8") * 255).filter(ImageFilter.MaxFilter(9))) > 0
    m = Image.fromarray((near & grown).astype("uint8") * 255)
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))   # 小さな点を消し、縁をなめらかに
    layer = bg.convert("RGBA")
    layer.putalpha(m)
    return layer, float(np.asarray(m).mean() / 255)


def submerge(char_layer, depth_frac=0.035):
    """浅い水の中に立つ人物の足を、水面から下だけ消す（足首まで沈める）。水面の線は少し揺らす。戻り値は人物と水面の高さ。"""
    a = np.asarray(char_layer.getchannel("A")).astype(float)
    ys, xs = np.nonzero(a > 128)
    top, foot = ys.min(), ys.max()
    wl = foot - (foot - top) * depth_frac
    H, W = a.shape
    yy = np.arange(H)[:, None] + 3 * np.sin(np.arange(W)[None, :] / 9.0)
    fade = np.clip((wl + 6 - yy) / 12, 0, 1)        # 水面の上はそのまま、下は 12px で消える
    out = char_layer.copy()
    out.putalpha(Image.fromarray((a * fade).astype("uint8")))
    return out, int(wl)


def ripples(char_layer, waterline):
    """水面で足のまわりに広がる波紋。脚が水面を横切る所を中心に、白い楕円の輪を重ねる（スクリーン）。"""
    from PIL import ImageDraw
    a = np.asarray(char_layer.getchannel("A")) > 128
    row = a[max(0, waterline - 4):waterline + 1].any(axis=0)
    xs = np.nonzero(row)[0]
    m = Image.new("L", SIZE, 0)
    d = ImageDraw.Draw(m)
    if len(xs):
        # 脚ごとの塊に分ける（間が 6px 以上空いたら別の脚）
        legs, start = [], xs[0]
        for p, q in zip(xs, xs[1:]):
            if q - p > 6:
                legs.append((start, p)); start = q
        legs.append((start, xs[-1]))
        for x0, x1 in legs:
            cx, r = (x0 + x1) / 2, (x1 - x0) / 2 + 6
            for k, (w, al) in enumerate(((1.6, 150), (2.6, 100), (3.6, 55))):
                d.ellipse((cx - r * w, waterline - r * w * 0.12, cx + r * w, waterline + r * w * 0.12), outline=al, width=2)
    # 脚の上には描かない。脚に重なると足首の輪（アンクレット）に見えた
    m = ImageChops.subtract(m, Image.fromarray((a * 255).astype("uint8")).filter(ImageFilter.MaxFilter(3)))
    m = m.filter(ImageFilter.GaussianBlur(1.2))
    layer = Image.new("RGBA", SIZE, (255, 255, 255, 0))
    layer.putalpha(m)
    return layer


def reflection(char_layer, line, ambient, strength=0.35, length=0.45):
    """水面や濡れた砂への映り込み。人物を line（足元か水面）で上下に返し、下へ行くほど薄く、横に少し揺らす（通常の重ね）。"""
    a = np.asarray(char_layer.getchannel("A")).astype(float)
    ys = np.nonzero(a.max(axis=1) > 128)[0]
    h = ys.max() - ys.min()
    flipped = char_layer.transpose(Image.FLIP_TOP_BOTTOM)
    shift = 2 * line - SIZE[1]                        # 返した絵を line で接するように動かす
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    canvas.paste(flipped, (0, shift), flipped)
    rgb = np.asarray(canvas.convert("RGB")).astype(float)
    al = np.asarray(canvas.getchannel("A")).astype(float)
    tint = np.array(ambient, float)
    rgb = rgb * 0.6 + tint * 0.4                      # 水の色に寄せる
    yy = np.arange(SIZE[1])[:, None]
    fall = np.clip(1 - (yy - line) / (h * length), 0, 1) * (yy > line)
    out = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).convert("RGBA")
    out.putalpha(Image.fromarray((al * fall * strength).astype("uint8")))
    # 横に揺らす（水面の細かい波）
    arr = np.asarray(out).copy()
    for y in range(line, SIZE[1]):
        arr[y] = np.roll(arr[y], int(2 * np.sin(y / 3.0)), axis=0)
    return Image.fromarray(arr).filter(ImageFilter.GaussianBlur(1.5))


def cast_shadow(char_layer, ambient, side, opacity=0.42):
    """光と反対の向きに地面へ落ちる影（乗算）。人物の形を足元で返して縦に潰し、光の向きに合わせて斜めにずらす。
    left の光 → 右へ、right → 左へ、back（逆光）→ 手前へ長く、front → 後ろへ短く（ほとんど人物に隠れる）"""
    a = char_layer.getchannel("A")
    arr = np.asarray(a) > 128
    ys, xs = np.nonzero(arr)
    foot = ys.max()
    squash, shear = {"left": (0.28, 0.9), "right": (0.28, -0.9), "back": (0.45, 0.15), "front": (0.18, 0.3)}[side]
    flip = a.transpose(Image.FLIP_TOP_BOTTOM)
    h = SIZE[1]
    # 足元を軸に、下へ返して縦に潰し、横にずらす（アフィン変換）。front は後ろ（上）へ伸ばす
    up = side == "front"
    sy = squash
    c = 1 / sy
    if up:
        m = a.transform(SIZE, Image.AFFINE, (1, shear, -shear * foot, 0, c, foot - c * foot), Image.BILINEAR)
    else:
        m = flip.transform(SIZE, Image.AFFINE, (1, -shear, shear * foot, 0, c, (h - foot) - c * foot), Image.BILINEAR)
    m = m.point(lambda v: int(v * opacity)).filter(ImageFilter.GaussianBlur(5))
    col = tuple(int(v * 0.3) for v in ambient)
    layer = Image.new("RGBA", SIZE, col + (0,))
    layer.putalpha(m)
    return layer


def local_blend(flat, char_layer, effects, prompt, strength, seed, band=29):
    """人物の輪郭の周り・足元・影・映り込みだけを描き直してなじませる。人物の中身と背景の残りは元のまま。
    全体を描き直すと人物の顔や水着まで変わる（一律 0.3 で試した）"""
    a = char_layer.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    # band: 輪郭の外へ描き直す幅（奇数、px）。切り抜きの縁の汚れ（髪の白いもや）が遠くまであるときは広げる
    m = ImageChops.subtract(a.filter(ImageFilter.MaxFilter(band)), a.filter(ImageFilter.MinFilter(9)))
    for e in effects:
        m = ImageChops.lighter(m, e.getchannel("A").point(lambda v: 255 if v > 10 else 0).filter(ImageFilter.MaxFilter(15)))
    ys = np.nonzero(np.asarray(a).max(axis=1))[0]
    feet = Image.new("L", SIZE, 0)
    feet.paste(255, (0, int(ys.max() - (ys.max() - ys.min()) * 0.08), SIZE[0], min(SIZE[1], int(ys.max() + 40))))
    m = ImageChops.lighter(m, ImageChops.multiply(feet, a.filter(ImageFilter.MaxFilter(61))))
    m = m.filter(ImageFilter.GaussianBlur(8))
    redrawn = blend(flat, prompt, strength, seed)
    k = np.asarray(m).astype(float)[..., None] / 255
    out = np.asarray(flat).astype(float) * (1 - k) + np.asarray(redrawn).astype(float) * k
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8")), m


# ---- 4. 部位 ----

def part_layers(char_layer):
    """人物を部位ごとのレイヤーに分ける。部位分けに入らなかった所（輪郭の線など）は「その他」に残し、足すと元に戻るようにする。"""
    import edit
    rgb = Image.new("RGB", SIZE, "white")
    rgb.paste(char_layer, (0, 0), char_layer)
    tmp = Path("/tmp/_layers_char.png")
    rgb.save(tmp)
    lab = np.asarray(edit.parts(tmp))
    alpha = np.asarray(char_layer.getchannel("A")).copy()
    out, used = {}, np.zeros(lab.shape, bool)
    for name, ids in PART_IDS.items():
        m = np.isin(lab, ids) & ~used
        used |= m
        a = np.where(m, alpha, 0).astype("uint8")
        if a.max() > 0:
            layer = char_layer.copy()
            layer.putalpha(Image.fromarray(a))
            out[name] = layer
    rest = np.where(~used, alpha, 0).astype("uint8")
    layer = char_layer.copy()
    layer.putalpha(Image.fromarray(rest))
    out["その他（輪郭など）"] = layer
    return out


# ---- 5. 書き出し ----

def flatten(layers):
    """レイヤーを下から重ねて1枚にする（PSD の重ね方と同じ: 通常・乗算・スクリーン）。"""
    base = layers[0][1].convert("RGB")
    for _, im, mode, opacity in layers[1:]:
        a = (np.asarray(im.getchannel("A")).astype(float) / 255 * opacity)[..., None]
        top = np.asarray(im.convert("RGB")).astype(float)
        b = np.asarray(base).astype(float)
        mixed = {"normal": top, "multiply": b * top / 255, "screen": 255 - (255 - b) * (255 - top) / 255}[mode]
        base = Image.fromarray(np.clip(b * (1 - a) + mixed * a, 0, 255).astype("uint8"))
    return base


def save_psd(layers, path):
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import BlendMode
    modes = {"normal": BlendMode.NORMAL, "multiply": BlendMode.MULTIPLY, "screen": BlendMode.SCREEN}
    psd = PSDImage.new("RGBA", SIZE)
    for i, (name, im, mode, opacity) in enumerate(layers):
        # 古い形式の名前（Pascal 文字列）は ASCII しか書けず、日本語の名前で落ちた。仮の名前で作り、Unicode の名前に日本語を入れる
        layer = PixelLayer.frompil(im.convert("RGBA"), psd, f"layer{i}")
        layer.name = name
        layer.blend_mode = modes[mode]
        layer.opacity = int(255 * opacity)
        psd.append(layer)
    psd.save(path)


def blend(flat, prompt, strength, seed):
    """重ねた絵を軽く描き直して、人物と背景の境目と光をなじませる（レイヤーとは別の1枚）。"""
    import torch
    import design
    import demi
    pipe = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(pipe, prompt, BG_NEGATIVE.replace("1girl, ", "").replace("person, people, human, character, figure, silhouette, ", "")
                                       + ", multiple girls, extra people")
    return pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                image=flat, strength=strength, num_inference_steps=30, guidance_scale=6.0,
                generator=torch.Generator().manual_seed(seed)).images[0]


def cut_person(src):
    """背景のある絵から人物だけを切り抜く（部位分けで、背景以外の所）。一番大きい塊だけ残し、縁をなめらかにする。"""
    import edit
    import design
    lab = np.asarray(edit.parts(src))
    m = Image.fromarray(((lab != 0) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    im = Image.open(src).convert("RGBA")
    im.putalpha(m)
    return design.keep_largest(im)


def build(design_png, outdir, scene, light_side="front", seed=7, height=None, x=0.5, blend_strength=0.0, prompt="", foot=0.93,
          bg_path=None, ground="ground", band=29):
    """完成絵を組む。height を渡さなければ、背景の地平線と足元の位置から遠近に合う大きさにする。
    ground: water（浅い水に立つ: 足首を沈め、波紋と映り込み）、wet（濡れた砂: 映り込みと影）、ground（地面: 影）"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bg = Image.open(bg_path).convert("RGB").resize(SIZE) if bg_path else background(scene, seed)   # 気に入った背景を使い回せる
    bg.save(outdir / "background.png")
    hz = horizon(bg)
    if height is None:
        height = min(0.9, perspective_height(hz, foot)) if hz is not None else 0.8
    char = place(cut_character(design_png), height, x, foot)
    light, ambient = light_of(bg)
    effects = []
    under = []   # 人物より下に重ねる層（影、映り込み）
    if ground == "water":
        char, wl = submerge(char)
        under.append(("水面の映り込み", reflection(char, wl, ambient, 0.3, 0.35), "normal", 1.0))
        over_fx = [("波紋", ripples(char, wl), "screen", 0.9)]
    else:
        over_fx = []
        if ground == "wet":
            ys = np.nonzero(np.asarray(char.getchannel("A")).max(axis=1) > 128)[0]
            under.append(("濡れた砂の映り込み", reflection(char, int(ys.max()), ambient, 0.28, 0.3), "normal", 1.0))
        under.append(("影（光と反対へ）", cast_shadow(char, ambient, light_side), "multiply", 1.0))
    under.append(("接地の影", contact_shadow(char, ambient), "multiply", 1.0))
    char.save(outdir / "character.png")
    parts = part_layers(char)
    layers = [("背景", bg.convert("RGBA"), "normal", 1.0)] + under
    layers += [(f"人物: {n}", im, "normal", 1.0) for n, im in parts.items()]
    fg, fg_cover = foreground(bg, char)
    grade = grade_strength(ambient) + (0.15 if light_side == "back" else 0.0)   # 逆光は人物の前が暗い
    layers += [("色寄せ（背景の色）", color_grade(char, ambient, grade), "multiply", 1.0),
               ("縁の光", rim_light(char, light, light_side), "screen", 1.0 if light_side == "back" else 0.85)]
    layers += over_fx
    layers += [("前景（人物より手前の背景）", fg, "normal", 1.0)]
    flat = flatten(layers)
    flat.save(outdir / "composite.png")
    save_psd(layers, outdir / "layers.psd")
    info = {"scene": scene, "seed": seed, "horizon": hz, "height": round(height, 3), "foot": foot, "ground": ground,
            "light": light, "ambient": ambient, "light_side": light_side,
            "grade": round(grade, 3), "foreground_cover": round(fg_cover, 4), "layers": [n for n, *_ in layers]}
    if blend_strength > 0:
        effects = [im for _, im, *_ in under + over_fx]
        final, mask = local_blend(flat, char, effects, prompt + ", " + scene, blend_strength, seed, band)
        final.save(outdir / "final.png")
        mask.save(outdir / "blend-mask.png")
        info["blend"] = blend_strength
    (outdir / "layers.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("design")
    ap.add_argument("outdir")
    ap.add_argument("--scene", required=True)
    ap.add_argument("--light", default="front", choices=["front", "left", "right", "back"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--height", type=float, default=None, help="人物の高さ（画面の割合）。省くと地平線と足元から遠近に合わせる")
    ap.add_argument("--ground", default="ground", choices=["ground", "wet", "water"])
    ap.add_argument("--bg", default=None, help="使い回す背景の絵")
    ap.add_argument("--x", type=float, default=0.5)
    ap.add_argument("--foot", type=float, default=0.93, help="足元の高さ（画面の割合）。小さくすると奥に立ち、手前の物が脚に掛かる")
    ap.add_argument("--blend", type=float, default=0.0)
    ap.add_argument("--prompt", default="")
    a = ap.parse_args()
    print(json.dumps(build(a.design, a.outdir, a.scene, a.light, a.seed, a.height, a.x, a.blend, a.prompt, a.foot, a.bg, a.ground), ensure_ascii=False))


if __name__ == "__main__":
    main()
