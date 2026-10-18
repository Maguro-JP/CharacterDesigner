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
# 模型は既定で外から取りに行かない。呼んだ関数が手元に無い模型を指していると、数 GB を取りに行って
# ディスクを埋めた（2026-10-14 に 2 回）。初めて取るときだけ CD_FETCH=1 を付けて動かす
os.environ.setdefault("HF_HUB_OFFLINE", "0" if os.environ.get("CD_FETCH") == "1" else "1")
sys.path.insert(0, str(Path(__file__).parent))
# 模型の置き場所（.cache/gen/hf）と取りに行かない既定を、diffusers・transformers を読む前に効かせる。
# 関数の中で design を読んでいたため、先に transformers を読んだ呼び出しでは ~/.cache/huggingface へ取りに行った
import design  # noqa: E402,F401

SIZE = (832, 1216)   # 縦長。全身の人物が大きく入る
BG_NEGATIVE = ("1girl, 1boy, person, people, human, character, figure, silhouette, aerial view, from above, high angle, "
               "text, watermark, signature, "
               "lowres, blurry, worst quality, low quality, jpeg artifacts, frame, border")
# 部位分け（segformer b3 clothes）の番号。水着は上下の服として出る
PART_IDS = {"髪": [2], "肌": [11, 12, 13, 14, 15], "水着・服": [4, 5, 6, 7, 8, 17], "帽子・小物": [1, 3, 9, 10, 16]}


# ---- 1. 人物 ----

_REMBG = None


USE_ANIME_CUT = True   # False で、端から抜く・部位分けで補う古い切り抜きに戻す


def anime_cut(src):
    """アニメの人物を切り抜く（isnet-anime。anime-segmentation の切り抜きモデル、Apache-2.0、約 176MB。rembg 経由、MIT）。
    髪の房まで滑らかな透明度で抜ける。背景のある絵からも直接抜ける。人物と離れた物（手前の花など）は一番大きい塊だけ残して落とす。
    部位分け（服のモデル）と色のしきい値で抜くと、髪の縁の白いにじみ、片脚の消失、髪の灰のかけらが次々に出た"""
    global _REMBG
    import design
    from rembg import new_session, remove
    os.environ.setdefault("U2NET_HOME", str(ROOT / ".cache" / "gen" / "u2net"))
    if _REMBG is None:
        _REMBG = new_session("isnet-anime")
    out = remove(Image.open(src).convert("RGB"), session=_REMBG)
    out = drop_props(src, out)
    # 薄い透明度だけの霞（落とした物の名残）は、濃い所から 5 画素より離れていれば消す。髪の縁のやわらかさは残る。
    # 霞を消してから一番大きい塊を残す（先に残すと、霞でつながった茎のかけらが人物の塊に入った）
    a = out.getchannel("A")
    core = a.point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MaxFilter(11))
    out.putalpha(ImageChops.multiply(a, core))
    return design.keep_largest(out)


def drop_props(src, cut, reach=15, tol=8.0):
    """切り抜きに付いてきた、人物に触れている物（髪に重なった花や茎など）を落とす。
    部位分けの人物の範囲（reach 画素広げる）の外にあり、色みが髪と違う所を物とみなす。
    部位分けは髪の毛先を取りこぼすので、範囲の外を一律には落とさない（色みが髪に近い所は髪として残す）。
    色みは明るさを除いて比べる（髪は光と影で明るさが大きく変わる）。範囲の外に出た毛先は髪の色みから 3 以内（90%）、ひまわりの中央値は 10.5。5 まで締めると、花の色が映った髪が角ばって切れた"""
    import edit
    im = Image.open(src).convert("RGB")
    lab = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
    if not (lab == 2).any():
        return cut
    near = np.asarray(Image.fromarray(((lab != 0) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(reach))) > 0
    rgb = np.asarray(im).astype(float)
    ch = rgb / np.maximum(rgb.sum(2, keepdims=True), 1)
    dist = np.abs(ch - np.median(ch[lab == 2], axis=0)).sum(2) * 100
    prop = ~near & (dist > tol)
    # 1画素ずつの判定は斑になるので、塊にならして落とす
    prop = np.asarray(Image.fromarray((prop * 255).astype("uint8")).filter(ImageFilter.MedianFilter(7))) > 0
    a = np.asarray(cut.getchannel("A")).copy()
    a[prop] = 0
    out = cut.copy()
    out.putalpha(Image.fromarray(a))
    solid = np.asarray(cut.getchannel("A")) > 128
    out.info["props_dropped"] = float((prop & solid).sum() / max(solid.sum(), 1))
    return out


def cut_character(src):
    """デザイン画から人物を切り抜く（背景は透明）。縁は 1px ぼかして、背景に重ねたときのギザギザを抑える。"""
    import design
    im = Image.open(src)
    lost = 0.0   # 端から抜いたときに、部位分けの人物の範囲から落ちた割合（合わせて戻す前）
    # 透明の部分がある絵（別の方法で切り抜いた人物）は、その切り抜きをそのまま使う
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255:
        cut = im.convert("RGBA")
    elif USE_ANIME_CUT:
        cut = anime_cut(src)
        # 切り抜きモデルの透明度をそのまま使う（縁の名残の取り除きや穴埋めはしない）
        c = cut.crop(cut.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())
        c.info["remnant_removed"] = 0.0
        c.info["cut_lost"] = 0.0
        return c
    else:
        cut = design.cut_background(im.convert("RGB"))
        # 端から背景を抜くだけだと、背景の色に近い肌（薄い灰の背景と白い肌）まで抜け、片脚が消えた。
        # 部位分けの人物の範囲と合わせて（どちらかに入っていれば人物）、手足を落とさない
        import edit
        seg = Image.fromarray(((np.asarray(edit.parts(src)) != 0) * 255).astype("uint8")).resize(cut.size)
        alpha0 = cut.getchannel("A")
        lost = float(((np.asarray(seg) > 0) & (np.asarray(alpha0) == 0)).sum() / max((np.asarray(seg) > 0).sum(), 1))
        # 色は元の絵から取る（端から抜いた所は色が黒に消されていて、合わせた脚が黒く塗られた）
        # 合わせるのは、無地の背景の色から 12 より離れた点だけ（背景そのものの灰は 10 未満、白い肌は 23 ほど離れていた）。
        # 部位分けの範囲は人物の外へ少しはみ出し、そのまま合わせると頭の上や髪の横に灰のかけらが残った
        src_rgb = np.asarray(im.convert("RGB")).astype(float)
        edge = np.concatenate([src_rgb[:4].reshape(-1, 3), src_rgb[-4:].reshape(-1, 3), src_rgb[:, :4].reshape(-1, 3), src_rgb[:, -4:].reshape(-1, 3)])
        far = np.abs(src_rgb - np.median(edge, axis=0)).sum(axis=2) > 12
        add = Image.fromarray(((np.asarray(seg) > 0) & far).astype("uint8") * 255)
        # 無地への描き直しで、人物の周りに白い光のにじみが描かれた。背景より明るいので端から抜けずに残る（頭の上や髪の横の灰のかけら）。
        # 部位分けの人物の外にあり、背景より明るく色みの無い点だけを消す（人物の近くに限ると、脚や髪の縁まで削れた）
        bgc = np.median(edge, axis=0)
        lum = src_rgb @ [0.299, 0.587, 0.114]
        sat = src_rgb.max(axis=2) - src_rgb.min(axis=2)
        glow = ~(np.asarray(seg.filter(ImageFilter.MaxFilter(3))) > 0) & (lum > bgc @ [0.299, 0.587, 0.114] + 4) & (sat < 25)
        a0 = np.where(glow, 0, np.asarray(alpha0)).astype("uint8")
        cut = im.convert("RGB").convert("RGBA")
        cut.putalpha(ImageChops.lighter(Image.fromarray(a0), add))
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
    # 縁の名残を取り除く。どちらの場合も、髪の中の小さな穴は埋める
    border = np.asarray(im.convert("RGB")).astype(float)
    border = np.concatenate([border[:4].reshape(-1, 3), border[-4:].reshape(-1, 3)])
    white_bg = np.median(border, axis=0).min() > 240
    # 白い背景から抜いた人物は取り除かない（白いフリルと見分けられない）。灰の背景（plainify）や背景つきの絵は取り除く。
    # 灰の背景は白いフリルと 60 ほど離れていて見分けられる
    if im.mode == "RGBA" or not white_bg:
        clean, ratio = clean_remnant(rgb, np.asarray(alpha) > 128)
    else:
        clean, ratio = np.asarray(alpha) > 128, 0.0
    holes = ~clean & (np.asarray(Image.fromarray(clean.astype("uint8") * 255).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))) > 0)
    alpha = Image.fromarray(((clean | holes) * 255).astype("uint8"))
    a = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    cut = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).convert("RGBA")
    cut.putalpha(a)
    cut.info["remnant_removed"] = ratio
    c = cut.crop(a.point(lambda v: 255 if v > 8 else 0).getbbox())
    c.info["remnant_removed"] = ratio
    c.info["cut_lost"] = lost
    return c


def place(char, height=0.8, x=0.5, foot=0.93):
    """人物を画面の大きさに合わせて置く。高さは画面の割合、x は中心の横位置、foot は足元の高さ。"""
    h = int(SIZE[1] * height)
    w = int(char.width * h / char.height)
    c = char.resize((w, h), Image.LANCZOS)
    layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    layer.paste(c, (int(SIZE[0] * x - w / 2), int(SIZE[1] * foot - h)), c)
    return layer


# ---- 2. 背景 ----

def background(scene, seed, steps=28, size=SIZE, negative=BG_NEGATIVE, check=None):
    """人を描かない場面の絵を描く。人物が混ざったら seed を変えて描き直す（最大 3 回）。
    size・negative・check は背景だけを作るモード（background.py）が横長や別の検品で使う。省くと合成用の縦長と部位分けの検品"""
    check = check or has_person
    import torch
    import design
    import people
    pipe = people.pipe()
    # 目の高さで描かせる。指定しないと見下ろしの構図になり、目の高さで描いた人物が巨人のように浮いた
    prompt = "no humans, scenery, detailed background, eye level, horizon in the middle, " + scene + ", " + people.QUALITY
    for k in range(3):
        t = time.time()
        pe, ne, pp, np_ = design.encode_xl(pipe, prompt, negative)
        kw = {}
        if people._IP:
            pipe.set_ip_adapter_scale(0.0)
            kw["ip_adapter_image"] = Image.new("RGB", (224, 224), "white")
        im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  num_inference_steps=steps, guidance_scale=6.0, width=size[0], height=size[1],
                  generator=torch.Generator().manual_seed(seed + k * 100), **kw).images[0]
        people_found = check(im)
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


def rim_light(char_layer, light, side="back", width=2, bg=None):
    """縁の光（スクリーン）。光の来る側の輪郭に沿って、光の色の細い帯を置く。back は両側と上。
    bg を渡すと、輪郭のすぐ後ろの背景が明るいところだけ光らせる（逆光で縁が光るのは、後ろの明るさが回り込むため）。
    前は幅 6 の帯を一律に置いていて、細い髪の房が丸ごと白く光り、白い縁取りに見えた"""
    a = char_layer.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    inner = a.filter(ImageFilter.MinFilter(width * 2 + 1))
    band = np.asarray(ImageChops.subtract(a, inner)).astype(float)
    H, W = band.shape
    xs = np.linspace(0, 1, W)[None, :].repeat(H, 0)
    ys = np.linspace(0, 1, H)[:, None].repeat(W, 1)
    weight = {"left": 1 - xs, "right": xs, "front": np.full((H, W), 0.35), "back": np.clip(1.2 - ys, 0.3, 1.0)}[side]
    if bg is not None:
        lum = np.asarray(bg.convert("L").filter(ImageFilter.GaussianBlur(8))).astype(float)
        hi = max(np.percentile(lum, 95), 1.0)
        weight = weight * np.clip((lum / hi - 0.4) / 0.6, 0, 1)
    m = Image.fromarray(np.clip(band * weight, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.7))
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
        import device
        _DEPTH = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=device.name())
    d = _DEPTH(bg)["predicted_depth"]
    d = d.squeeze().numpy() if hasattr(d, "numpy") else np.asarray(d)
    _DEPTH_CACHE[key] = np.asarray(Image.fromarray(d.astype("float32")).resize(bg.size, Image.BILINEAR))
    return _DEPTH_CACHE[key]


def horizon(bg):
    """地平線の高さ（画面の上からの割合）。奥行きの模型の値（近いほど大きい）は、平らな地面では画面の行に対しておよそ
    一直線に変わり、地平線で 0 になる。画面の下 4 分の 1 の中ほどの列から直線を引き、0 になる行を地平線とする。
    前は「空が行の半分を超える一番下の行」で測っていたが、城のように建物が空を隠す背景では建物の上の空の端（0.10〜0.13）を
    地平線と読み、目の高さ（0.65〜0.80）から大きく外れた（2026-10-17、城門・大広間の 4 枚。新しい測り方は検品担当が
    絵で見た目の高さと 0.07 以内で合った）。地面が読めない（直線が下へ向かって近づかない）ときだけ前の測り方を使う。
    どちらでも読めなければ None（大きさは --height で決める）"""
    d = depth_map(bg)
    h, w = d.shape
    med = np.median(d[:, w // 4:3 * w // 4], axis=1)
    ys = np.arange(int(h * 0.75), h)
    k, b = np.polyfit(ys, med[ys], 1)
    if k > 0:
        hz = float(-b / k) / h
        if 0.05 < hz < 0.98:
            return hz
    rows = np.where((d < d.max() * 0.003).mean(axis=1) > 0.5)[0]
    return float(rows.max()) / h if len(rows) else None


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


def local_blend(flat, char_layer, effects, prompt, strength, seed, band=29, keep=None):
    """（使っていない）輪郭の周り・足元を描き直す。境目をぼかすだけで、光の向きや色は合わなかったので relight に替えた"""
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
    if keep is not None:
        # 前景（人物より手前の物）は描き直さない。描き直すと、葉の後ろに隠した足が葉の上に描き戻された
        m = ImageChops.subtract(m, keep.getchannel("A").filter(ImageFilter.MaxFilter(5)))
    redrawn = blend(flat, prompt, strength, seed)
    k = np.asarray(m).astype(float)[..., None] / 255
    out = np.asarray(flat).astype(float) * (1 - k) + np.asarray(redrawn).astype(float) * k
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8")), m


def _largest_blob(on):
    """つながった点の塊のうち、いちばん大きいものの点の数"""
    from collections import deque
    seen = np.zeros_like(on, dtype=bool)
    best = 0
    H, W = on.shape
    for y0, x0 in zip(*np.nonzero(on)):
        if seen[y0, x0]:
            continue
        q, n = deque([(y0, x0)]), 0
        seen[y0, x0] = True
        while q:
            y, x = q.popleft(); n += 1
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and on[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True; q.append((yy, xx))
        best = max(best, n)
    return best


def sky_color_map(bg, hz):
    """列ごとの空の色（地平線より上の、下側 30% の行の平均）。濡れた面と水面は空を映すので、この色に近い所が映り込める面"""
    a = np.asarray(bg.convert("RGB")).astype(float)
    h = int(hz * SIZE[1]) if hz else int(SIZE[1] * 0.3)
    band = a[max(0, int(h * 0.7)):max(1, h)]
    return band.mean(axis=0)   # (W, 3)


def reflective_mask(bg, hz):
    """映り込みが起きる面（水面・濡れた砂）の範囲。地平線より下で、空の色に近いか、水の色（青や青緑が強い）で、
    きめが細かい（ざらざらした砂や草ではない）所。水が無い所に映り込みを描かないために使う"""
    a = np.asarray(bg.convert("RGB")).astype(float)
    sky = sky_color_map(bg, hz)[None, :, :]
    near_sky = np.abs(a - sky).sum(axis=2) < 110
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    watery = (b > r + 25) & (b + g > 2 * r + 40)
    lum = a @ [0.299, 0.587, 0.114]
    blur = np.asarray(Image.fromarray(lum.astype("uint8")).filter(ImageFilter.GaussianBlur(4))).astype(float)
    smooth = np.abs(lum - blur) < 14
    below = np.zeros(a.shape[:2], bool)
    below[int((hz or 0.3) * SIZE[1]) + 2:] = True
    m = (near_sky | watery) & smooth & below
    return np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(5))) > 0


def feet_region(char_layer, below=40):
    """足元の範囲（足の下端の少し上から、少し下まで）"""
    a = np.asarray(char_layer.getchannel("A")) > 128
    ys, xs = np.nonzero(a)
    h = ys.max() - ys.min()
    top, bottom = int(ys.max() - h * 0.04), min(SIZE[1], int(ys.max() + below))
    fx = xs[ys > ys.max() - h * 0.04]
    return top, bottom, int(fx.min()) - 20, int(fx.max()) + 20


def ground_kind(bg, char_layer, hz):
    """足元が何か: water（水の色）、wet（空を映す濡れた面）、plants（花や草: 立てない）、ground（地面）"""
    top, bottom, x0, x1 = feet_region(char_layer)
    a = np.asarray(bg.convert("RGB")).astype(float)[top:bottom, max(0, x0):x1]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if ((b > r + 25) & (b + g > 2 * r + 40)).mean() > 0.4:
        return "water"
    # 花や草: 色相が黄緑〜緑で、ある程度鮮やか（ひまわりの葉の足元は平均 (103,113,85) の暗い緑だった）
    hsv = np.asarray(Image.fromarray(a.astype("uint8")).convert("HSV")).astype(float)
    hue, sat = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255
    if (((hue > 55) & (hue < 170) & (sat > 0.2)) | ((hue > 40) & (hue <= 55) & (sat > 0.6))).mean() > 0.35:
        return "plants"
    refl = reflective_mask(bg, hz)[top:bottom, max(0, x0):x1]
    if refl.mean() > 0.4:
        return "wet"
    return "ground"


# ---- 完成絵の検品（AI が描きがちな、あり得ない所を数える） ----

def inspect_composite(final, bg, char_layer, reflect=None, hz=None, ground=None):
    """完成絵の矛盾を数える。理由（日本語）と数字の辞書を返す。理由が空なら通る。

    - 水が無い所の映り込み: 映り込みのうち、水・濡れた面の外にある割合
    - 立てない所に立つ: 足元が花や草なのに、足が見えている割合
    """
    f = np.asarray(final.convert("RGB")).astype(float)
    g = np.asarray(bg.convert("RGB")).astype(float)
    a = char_layer.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    am = np.asarray(a) > 0
    # 白い残りと境界線は、色だけでは白い水着と見分けられなかった（綺麗な絵と汚い絵で差が出ない）。
    # 元の絵と比べて切り抜きの段階で取り除き（clean_remnant）、取り除いた割合を info に残す
    out, reasons = {}, []
    # 手足: 人物を白の上に置いて部位分けし、両脚があるか数える（切り抜きや塗り直しで脚が消えた）
    import edit
    tmp = Path("/tmp/_layers_inspect_char.png")
    w = Image.new("RGB", SIZE, "white")
    w.paste(char_layer, (0, 0), char_layer)
    w.save(tmp)
    lab = np.asarray(edit.parts(tmp))
    legs = [n for n, i in (("左脚", 12), ("右脚", 13)) if (lab == i).sum() < 200]
    out["legs_missing"] = legs
    if legs:
        reasons.append("脚が無い: " + "、".join(legs))
    if reflect is not None:
        ra = np.asarray(reflect.getchannel("A")) > 12
        if ra.any():
            off = float((ra & ~reflective_mask(bg, hz)).sum() / ra.sum())
            out["reflection_off_water"] = round(off, 4)
            if off > 0.15:
                reasons.append(f"水が無い所に映り込み（映り込みの {off:.1%} が水・濡れた面の外）")
    if ground == "plants":
        top, bottom, x0, x1 = feet_region(char_layer, below=0)
        shown = float(np.mean(np.abs(f[top:bottom, max(0, x0):x1] - g[top:bottom, max(0, x0):x1]).sum(axis=2) > 40)) if bottom > top else 0
        feet = am[top:bottom, max(0, x0):x1]
        vis = float((np.abs(f - g).sum(axis=2) > 40)[top:bottom, max(0, x0):x1][feet].mean()) if feet.any() else 0.0
        out["feet_visible_on_plants"] = round(vis, 4)
        if vis > 0.5:
            reasons.append(f"花や草の上に立っている（足の {vis:.0%} が手前の物に隠れていない）")
    return reasons, out


# ---- 合わせる（ぼかさない）: 人物を背景の光と色に合わせる ----

LIGHT_WORDS = {
    "front": "bright sunlight from the front, soft shadows",
    "left": "sunlight from the left, shadows on the right side of the body, cast shading",
    "right": "sunlight from the right, shadows on the left side of the body, cast shading",
    "back": "backlighting, light from behind, rim light on hair and shoulders, face and front of body in soft shadow",
}


def match_colors(char_layer, bg, light=None, amount=0.35, tint=0.15):
    """人物の明るさ（平均と幅）を周りの背景へ amount だけ寄せ、色みは光の色へ tint だけ寄せる。
    背景の平均の色へ寄せると、浜辺で肌が海の青緑になり、片脚が水に溶けて一本脚に見えた。
    光は肌に当たるが、肌は背景の色にはならない。色みは光の色（昼は白、夕日は橙）にだけ寄せる"""
    a = np.asarray(char_layer.getchannel("A")) > 128
    if not a.any():
        return char_layer
    # 人物の周り 75 画素の帯。PIL の MaxFilter(151) は 1 人 約 30 秒かかった。scipy の最大値フィルターは縦横に分けて
    # 計算するので 0.006 秒で、結果は画素単位で同じ（1216x832 の絵で確かめた）
    from scipy import ndimage
    near = ndimage.maximum_filter(a, size=151, mode="nearest") & ~a
    ycc = np.asarray(char_layer.convert("RGB").convert("YCbCr")).astype(float)
    gy = np.asarray(bg.convert("RGB").convert("YCbCr")).astype(float)[..., 0]
    y = ycc[..., 0]
    mc, sc = y[a].mean(), y[a].std() + 1e-3
    mb, sb = gy[near].mean(), gy[near].std() + 1e-3
    tm, ts = mc + (mb - mc) * amount, sc + (sb - sc) * amount * 0.5
    ycc[..., 0] = (y - mc) / sc * ts + tm
    if light is not None:
        lc = np.asarray(Image.new("RGB", (1, 1), tuple(light)).convert("YCbCr")).astype(float)[0, 0]
        for k in (1, 2):
            ycc[..., k] = ycc[..., k] + (lc[k] - 128) * tint
    rgb = Image.fromarray(np.clip(ycc, 0, 255).astype("uint8"), "YCbCr").convert("RGB")
    res = rgb.convert("RGBA")
    res.putalpha(char_layer.getchannel("A"))
    return res


def relight(flat, char_layer, prompt, light_side, light, strength=0.4, seed=7, keep=None, negative=""):
    """人物の中だけを、背景の光（向きと色）で塗り直す。輪郭の外は描き直さない（ぼかさない）。
    塗り直した人物の内側を、元の絵の人物の所に戻す。輪郭の 2px は元の切り抜きのまま残し、線を崩さない"""
    import torch
    import design
    import demi
    warm = "warm golden light" if light[0] > light[2] + 30 else ("cool light" if light[2] > light[0] + 20 else "natural light")
    words = f"{prompt}, {LIGHT_WORDS[light_side]}, {warm}, consistent lighting, detailed shading"
    pipe = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(pipe, words, BG_NEGATIVE.replace("1girl, ", "").replace("person, people, human, character, figure, silhouette, ", "")
                                       + ", multiple girls, extra people, extra limbs, bad hands" + (", " + negative if negative else ""))
    redrawn = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                   image=flat, strength=strength, num_inference_steps=30, guidance_scale=6.0,
                   generator=torch.Generator().manual_seed(seed)).images[0]
    m = char_layer.getchannel("A").point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.5))
    if keep is not None:
        m = ImageChops.subtract(m, keep.getchannel("A"))
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


def _local_mean(rgb, weight, sigma):
    """weight の掛かった所だけの、近所の平均の色（重み付きのぼかし）"""
    num = np.stack([np.asarray(Image.fromarray(np.clip(rgb[..., c] * weight, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(sigma))).astype(float)
                    for c in range(3)], axis=-1)
    den = np.asarray(Image.fromarray((weight * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(sigma))).astype(float)[..., None] / 255
    return num / np.maximum(den, 1e-3), den[..., 0]


def clean_remnant(rgb, mask, sigma=18):
    """切り抜きの縁に残った元の背景（白い縁、塊、もや）を取り除く。取り除いた後の mask と、取り除いた割合を返す。

    縁の点を、近所の「人物の内側の色」と「外の背景の色」と比べ、背景の色に近い点を背景の名残とみなす。
    白いフリルのように人物の内側も白い所は、内側の色に近いので残る。白さだけで数えると、白い水着と名残を見分けられなかった
    """
    m = mask.astype(bool)
    mi = Image.fromarray(m.astype("uint8") * 255)
    deep = np.asarray(mi.filter(ImageFilter.MinFilter(25))) > 0
    outside = ~(np.asarray(mi.filter(ImageFilter.MaxFilter(9))) > 0)
    edge = m & ~deep
    bgc, bgw = _local_mean(rgb, outside.astype(float), sigma)
    chc, chw = _local_mean(rgb, deep.astype(float), sigma * 1.5)
    dbg = np.abs(rgb - bgc).sum(axis=2)
    dch = np.abs(rgb - chc).sum(axis=2)
    remnant = edge & (bgw > 0.02) & (dbg < 45) & (dbg < dch * 0.6)
    # 名残は縁から外へつながっている。縁から離れた島（服の模様など）は外さない
    lab = remnant.copy()
    keep = np.zeros_like(lab)
    border = remnant & ~(np.asarray(mi.filter(ImageFilter.MinFilter(5))) > 0)
    from collections import deque
    q = deque(zip(*np.nonzero(border)))
    for y, x in q:
        keep[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < lab.shape[0] and 0 <= xx < lab.shape[1] and lab[yy, xx] and not keep[yy, xx]:
                keep[yy, xx] = True
                q.append((yy, xx))
    ratio = float(keep.sum() / max(edge.sum(), 1))
    return m & ~keep, ratio


def has_plain_background(src, tol=18):
    """絵の外周が無地（ほぼ一色）か。無地ならそのまま端から抜ける"""
    a = np.asarray(Image.open(src).convert("RGB")).astype(float)
    border = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    return float(np.abs(border - np.median(border, axis=0)).sum(axis=1).mean()) < tol


def plainify(src, out, prompt, strength=0.35, seed=7):
    """背景のある絵の人物を、無地の背景の上に描き直す（人物はそのまま、縁だけ描き直す）。
    背景のある絵から髪を切り抜くと、背景の名残（白い塊、もや）が残り、取り除くと髪がぎざぎざになった。
    人物の周りを無地で塗ってから軽く描き直すと、縁が無地に対して描かれ、端からきれいに抜ける"""
    import torch
    import design
    import demi
    import edit
    lab = np.asarray(edit.parts(src))
    person = Image.fromarray(((lab != 0) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(21)).filter(ImageFilter.GaussianBlur(6))
    im = Image.open(src).convert("RGB")
    flat = Image.new("RGB", im.size, (226, 228, 232))
    mixed = Image.composite(im, flat, person)
    pipe = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(pipe, prompt + ", simple background, grey background, full body",
                                       "background objects, scenery, outdoors, text, watermark, lowres, bad anatomy, extra limbs")
    r = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
             image=mixed, strength=strength, num_inference_steps=30, guidance_scale=6.0,
             generator=torch.Generator().manual_seed(seed)).images[0]
    r.save(out)
    return out


def cut_person(src):
    """背景のある絵から人物だけを切り抜く（部位分けで、背景以外の所）。一番大きい塊だけ残し、縁をなめらかにする。"""
    import edit
    import design
    lab = np.asarray(edit.parts(src))
    m = Image.fromarray(((lab != 0) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    im = Image.open(src).convert("RGBA")
    clean, ratio = clean_remnant(np.asarray(im.convert("RGB")).astype(float), np.asarray(m) > 0)
    im.putalpha(Image.fromarray(clean.astype("uint8") * 255))
    out = design.keep_largest(im)
    out.info["remnant_removed"] = ratio
    return out


def build(design_png, outdir, scene, light_side="front", seed=7, height=None, x=0.5, blend_strength=0.0, prompt="", foot=0.93,
          bg_path=None, ground="auto", band=29, retries=2, negative=""):
    """完成絵を組む。

    - 人物の大きさ: height を渡さなければ、背景の地平線と足元の位置から遠近に合わせる
    - 人物の元の絵に背景があれば、無地の上に描き直してから切り抜く（plainify）
    - 足元: auto は背景から判定する。water（足首を沈め、波紋と映り込み）、wet（濡れた面: 映り込みと影）、
      plants（花や草: 足が手前の物に隠れるまで奥へ下げる）、ground（地面: 影）
    - 映り込みは、映り込める面（水面、空を映す濡れた面）だけに切り抜く
    - 人物の色と明るさの幅を周りの背景に寄せ（match_colors）、blend_strength > 0 なら人物の中だけを背景の光で塗り直す（relight）。
      輪郭の外はぼかさない。影・映り込み・波紋・前景は塗り直しの後に重ねる
    - 最後に検品し、結果を layers.json に残す
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bg = Image.open(bg_path).convert("RGB").resize(SIZE) if bg_path else background(scene, seed)   # 気に入った背景を使い回せる
    bg.save(outdir / "background.png")
    hz = horizon(bg)
    src = design_png
    if not USE_ANIME_CUT and not has_plain_background(src) and Image.open(src).mode != "RGBA":
        src = plainify(src, str(outdir / "plain.png"), prompt or "1girl, solo", seed=seed)   # 古い切り抜きのときだけ
    cut = cut_character(src)
    remnant = cut.info.get("remnant_removed", 0.0)

    def place_at(f):
        h = height if height is not None else (min(0.9, perspective_height(hz, f)) if hz is not None else 0.8)
        return place(cut, h, x, f), h

    char, h_used = place_at(foot)
    kind = ground_kind(bg, char, hz) if ground == "auto" else ground
    if kind == "plants":
        # 花や草の上に立たせない。足が手前の物に半分以上隠れる所まで、足元を奥（上）へ動かす
        for f in np.arange(foot, 0.6, -0.02):
            c2, h2 = place_at(float(f))
            fg2, _ = foreground(bg, c2)
            top, bottom, x0, x1 = feet_region(c2, below=0)
            feet = np.asarray(c2.getchannel("A"))[top:bottom, max(0, x0):x1] > 128
            hidden = float((np.asarray(fg2.getchannel("A"))[top:bottom, max(0, x0):x1] > 128)[feet].mean()) if feet.any() else 0
            if hidden >= 0.6:
                char, h_used, foot = c2, h2, float(f)
                break
    light, ambient = light_of(bg)
    refl_mask = reflective_mask(bg, hz)
    under, over_fx, reflect = [], [], None
    if kind == "water":
        char, wl = submerge(char)
        reflect = reflection(char, wl, ambient, 0.3, 0.35)
        over_fx = [("波紋", ripples(char, wl), "screen", 0.9)]
    elif kind == "wet":
        ys = np.nonzero(np.asarray(char.getchannel("A")).max(axis=1) > 128)[0]
        reflect = reflection(char, int(ys.max()), ambient, 0.28, 0.3)
    if reflect is not None:
        ra = np.asarray(reflect.getchannel("A")).astype(float) * refl_mask   # 映り込める面の外は消す
        reflect.putalpha(Image.fromarray(ra.astype("uint8")))
        if (ra > 12).sum() > 200:
            under.append(("映り込み（水面・濡れた面だけ）", reflect, "normal", 1.0))
        else:
            reflect = None
    if kind != "water":
        under.append(("影（光と反対へ）", cast_shadow(char, ambient, light_side), "multiply", 1.0))
    under.append(("接地の影", contact_shadow(char, ambient), "multiply", 1.0))
    char = match_colors(char, bg, light)   # 人物の明るさを周りの背景に、色みを光の色に寄せる
    char.save(outdir / "character.png")
    parts = part_layers(char)
    layers = [("背景", bg.convert("RGBA"), "normal", 1.0)] + under
    layers += [(f"人物: {n}", im, "normal", 1.0) for n, im in parts.items()]
    fg, fg_cover = foreground(bg, char)
    grade = grade_strength(ambient) + (0.15 if light_side == "back" else 0.0)   # 逆光は人物の前が暗い
    layers += [("色寄せ（背景の色）", color_grade(char, ambient, grade), "multiply", 1.0),
               ("縁の光", rim_light(char, light, light_side, bg=bg), "screen", 0.8 if light_side == "back" else 0.6)]
    layers += over_fx
    layers += [("前景（人物より手前の背景）", fg, "normal", 1.0)]
    flat = flatten(layers)
    flat.save(outdir / "composite.png")
    save_psd(layers, outdir / "layers.psd")
    info = {"scene": scene, "seed": seed, "horizon": hz, "height": round(h_used, 3), "foot": round(foot, 3), "ground": kind,
            "light": light, "ambient": ambient, "light_side": light_side, "remnant_removed": round(remnant, 4),
            "grade": round(grade, 3), "foreground_cover": round(fg_cover, 4), "layers": [n for n, *_ in layers]}
    final = flat
    if blend_strength > 0:
        # 合わせる: 人物の中だけを背景の光で塗り直す。輪郭の外はぼかさない。
        # 前は輪郭の周りを描き直していたが、境目をぼかすだけで、光の向きや色は合わなかった（利用者: ぼかすじゃない、合わせる）
        final, mask = relight(flat, char, prompt, light_side, light, blend_strength, seed, keep=fg, negative=negative)
        # 波紋と前景は塗り直しの後に重ね直す（塗り直しが手前の物や波紋を描き替えないように）
        for (name, im, mode, op) in over_fx + [("前景", fg, "normal", 1.0)]:
            final = flatten([("下", final.convert("RGBA"), "normal", 1.0), (name, im, mode, op)])
        final.save(outdir / "final.png")
        mask.save(outdir / "relight-mask.png")
        info["relight"] = blend_strength
    reasons, nums = inspect_composite(final, bg, char, reflect, hz, kind)
    info["inspect"] = {"reasons": reasons, **nums}
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
