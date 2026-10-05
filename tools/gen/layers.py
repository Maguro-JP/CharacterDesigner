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
BG_NEGATIVE = ("1girl, 1boy, person, people, human, character, figure, silhouette, text, watermark, signature, "
               "lowres, blurry, worst quality, low quality, jpeg artifacts, frame, border")
# 部位分け（segformer b3 clothes）の番号。水着は上下の服として出る
PART_IDS = {"髪": [2], "肌": [11, 12, 13, 14, 15], "水着・服": [4, 5, 6, 7, 8, 17], "帽子・小物": [1, 3, 9, 10, 16]}


# ---- 1. 人物 ----

def cut_character(src):
    """デザイン画から人物を切り抜く（背景は透明）。縁は 1px ぼかして、背景に重ねたときのギザギザを抑える。"""
    import design
    cut = design.cut_background(Image.open(src).convert("RGB"))
    # 縁を 1px 削ってからぼかす。削らないと、デザイン画の白い背景が縁に残り、腕や脚の周りが白く光った
    a = cut.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
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
    prompt = "no humans, scenery, detailed background, " + scene + ", " + people.QUALITY
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
    """背景の光の色（明るい上位 3% の平均）と、全体の色（平均）を返す。"""
    a = np.asarray(bg.convert("RGB")).reshape(-1, 3).astype(float)
    lum = a @ [0.299, 0.587, 0.114]
    top = a[lum >= np.percentile(lum, 97)].mean(axis=0)
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


def color_grade(char_layer, ambient, strength=0.18):
    """人物を背景の色に寄せる層（乗算）。人物の形で切り抜いた背景の平均の色を、薄く重ねる。"""
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


def build(design_png, outdir, scene, light_side="front", seed=7, height=0.8, x=0.5, blend_strength=0.0, prompt=""):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bg = background(scene, seed)
    bg.save(outdir / "background.png")
    char = place(cut_character(design_png), height, x)
    char.save(outdir / "character.png")
    light, ambient = light_of(bg)
    parts = part_layers(char)
    layers = [("背景", bg.convert("RGBA"), "normal", 1.0),
              ("接地の影", contact_shadow(char, ambient), "multiply", 1.0)]
    layers += [(f"人物: {n}", im, "normal", 1.0) for n, im in parts.items()]
    layers += [("色寄せ（背景の色）", color_grade(char, ambient), "multiply", 1.0),
               ("縁の光", rim_light(char, light, light_side), "screen", 0.85)]
    flat = flatten(layers)
    flat.save(outdir / "composite.png")
    save_psd(layers, outdir / "layers.psd")
    info = {"scene": scene, "seed": seed, "light": light, "ambient": ambient, "light_side": light_side,
            "layers": [n for n, *_ in layers]}
    if blend_strength > 0:
        blend(flat, prompt + ", " + scene, blend_strength, seed).save(outdir / "final.png")
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
    ap.add_argument("--height", type=float, default=0.8)
    ap.add_argument("--x", type=float, default=0.5)
    ap.add_argument("--blend", type=float, default=0.0)
    ap.add_argument("--prompt", default="")
    a = ap.parse_args()
    print(json.dumps(build(a.design, a.outdir, a.scene, a.light, a.seed, a.height, a.x, a.blend, a.prompt), ensure_ascii=False))


if __name__ == "__main__":
    main()
