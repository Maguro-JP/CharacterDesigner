"""画像処理の道具をまとめて呼べるようにする。人物と背景を分ける技術を、分野ごとの呼び名のまま使えるようにした。

  python3 tools/gen/imgproc.py segment  IN OUT_DIR          セグメンテーション（部位ごとの領域と、人物ごとの領域）
  python3 tools/gen/imgproc.py matte    IN OUT.png          イメージマッティング（髪や半透明の縁のアルファ値を細かく出す）
  python3 tools/gen/imgproc.py remove   IN OUT.png          背景除去（人物だけを残し、背景を透明にする）
  python3 tools/gen/imgproc.py cutout   IN OUT.png [--path OUT.svg]   切り抜き（輪郭で抜く。--path でクリッピングパスを SVG で書く）
  python3 tools/gen/imgproc.py chroma   IN OUT.png [--key #00b140] [--tol 60]   クロマキー（指定の色を消す。色を省くと四隅の色）
  python3 tools/gen/imgproc.py roto     IN.gif|DIR OUT_DIR    ロトスコーピング（コマごとに人物を抜き、透明 PNG と輪郭の動きを書く）
  python3 tools/gen/imgproc.py shade    IN OUT.png [--style cel2|cel3|soft|rim|back] [--light x,y,z]   影の付け方（立体を計算して光を当てる）
  python3 tools/gen/imgproc.py aitells  IN                    AI っぽさを数える（つや、色数、色むら、線のにじみ、線の均一さ、奥行きの無さ）
  python3 tools/gen/imgproc.py recolor IN OUT.png --from #969696 --to #c02020 [--tol 40]   色の置き換え（影の明るさは残す）
  python3 tools/gen/imgproc.py grade   IN OUT.png [--brightness 1.1] [--contrast 1] [--saturation 1] [--warmth 0.2]   色調補正
  python3 tools/gen/imgproc.py match   IN REF OUT.png [--amount 1]   色合わせ（REF の色の平均と幅に寄せる）
  python3 tools/gen/imgproc.py denoise IN OUT.png [--weight 0.08]   ノイズ除去（平らな面のざらつきを消し、境目は残す）
  python3 tools/gen/imgproc.py sharpen IN OUT.png [--radius 3] [--amount 1.5]   ぼかし除去（境目を急にする）
  python3 tools/gen/imgproc.py deai     IN OUT.png [--steps 10]   （使わない: 絵を崩すだけだった。docs/knowledge/ai-look.md）

どれも結果を画像で書き出し、数字（残した画素の割合など）を標準出力に出す。描いた絵の上でも写真の上でも動く。
重い部品（切り抜きのモデル、部位分けのモデル）は使うときだけ読む。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _rgba(im: Image.Image, alpha: np.ndarray) -> Image.Image:
    out = im.convert("RGBA")
    out.putalpha(Image.fromarray(np.clip(alpha * 255, 0, 255).astype("uint8")))
    return out


def _stats(alpha: np.ndarray) -> dict:
    return {"kept": round(float((alpha > 0.5).mean()), 4), "soft_edge": round(float(((alpha > 0.02) & (alpha < 0.98)).mean()), 4)}


# ---- セグメンテーション ----

def segment(src: str, outdir: str) -> dict:
    """セマンティック（画素ごとに「髪・服・肌・背景」などの意味を付ける）と、インスタンス（人物を1人ずつ分ける）の2つを出す。
    セマンティックは部位分けのモデル（edit.parts、服の部位分け）、インスタンスは人物の範囲を繋がった塊ごとに番号を振る。
    人が重なって1つの塊になった場合は1人として数える（重なりを分けるモデルは使っていない）"""
    import edit
    from scipy import ndimage
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    lab = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
    names = {v: k for k, v in edit.LABELS.items()}
    rng = np.random.default_rng(3)
    pal = rng.integers(40, 255, (max(edit.LABELS.values()) + 1, 3)).astype("uint8")
    pal[0] = 0
    Image.fromarray(pal[lab]).save(out / "semantic.png")
    person = lab != 0
    person = ndimage.binary_closing(person, iterations=3)
    inst, n = ndimage.label(person)
    sizes = ndimage.sum(person, inst, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= 0.002 * person.size]   # 小さな欠片は人物に数えない
    ipal = rng.integers(60, 255, (n + 1, 3)).astype("uint8")
    ipal[0] = 0
    vis = np.where(np.isin(inst, keep)[..., None], ipal[inst], 0).astype("uint8")
    Image.fromarray(vis).save(out / "instance.png")
    for k, i in enumerate(keep):
        _rgba(im, (inst == i).astype(float)).save(out / f"person-{k + 1}.png")
    found = {names.get(int(v), str(v)): round(float((lab == v).mean()), 4) for v in np.unique(lab) if v != 0}
    return {"labels": found, "people": len(keep)}


# ---- イメージマッティング ----

def matte(src: str, out: str, band: int = 6) -> dict:
    """まず切り抜きのモデルで大まかな人物の範囲を出し、縁の帯（band 画素）だけを「分からない所」としてマッティングで解く。
    髪の房や半透明の布の、背景が透ける割合（アルファ値）を色から逆算する（pymatting の closed-form）。
    帯の外は前景か背景かが決まっているので解かない（全部を解くと遅く、背景の模様を拾う）"""
    from pymatting import estimate_alpha_cf, estimate_foreground_ml
    from scipy import ndimage
    im = Image.open(src).convert("RGB")
    from rembg import new_session, remove
    import os
    os.environ.setdefault("U2NET_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "gen" / "u2net"))
    a0 = np.asarray(remove(im, session=new_session("isnet-anime"), only_mask=True).convert("L")) / 255.0
    fg = a0 > 0.5
    sure_fg = ndimage.binary_erosion(fg, iterations=band)
    sure_bg = ~ndimage.binary_dilation(fg, iterations=band)
    trimap = np.full(fg.shape, 0.5)
    trimap[sure_fg] = 1.0
    trimap[sure_bg] = 0.0
    rgb = np.asarray(im).astype(float) / 255.0
    # 元の大きさのまま解く。縮めて解くと、髪の外に房の影のようなもやが出た（帯も 12 から 6 に狭めた）
    alpha = estimate_alpha_cf(rgb, trimap)
    alpha = np.clip(alpha, 0, 1)
    # 縁の色から背景の色を抜く（白い背景の上の髪の縁が白く光らないように）
    fgc = estimate_foreground_ml(rgb, alpha)
    res = Image.fromarray((np.clip(fgc, 0, 1) * 255).astype("uint8"))
    _rgba(res, alpha).save(out)
    return _stats(alpha)


# ---- 背景除去 ----

def remove_bg(src: str, out: str) -> dict:
    """背景を透明にして人物だけを残す。アニメの人物に合わせた切り抜きのモデル（isnet-anime）で抜き、一番大きい塊だけ残す"""
    import layers
    cut = layers.anime_cut(src)
    cut.save(out)
    return _stats(np.asarray(cut.getchannel("A")) / 255.0)


# ---- 切り抜き（クリッピングパス） ----

def cutout(src: str, out: str, path_svg: str | None = None, simplify: float = 1.5) -> dict:
    """輪郭がくっきりした切り抜き（アルファ値は 0 か 1）。--path を付けると輪郭をベクターのパス（SVG）で書き出す。
    クリッピングパスは印刷や DTP で使う形（ぼかしの無い閉じた線）なので、縁のやわらかさは捨てる"""
    from skimage import measure
    import layers
    cut = layers.anime_cut(src)
    a = np.asarray(cut.getchannel("A")) > 128
    im = Image.open(src).convert("RGB")
    _rgba(im, a.astype(float)).save(out)
    info = {"kept": round(float(a.mean()), 4)}
    if path_svg:
        contours = measure.find_contours(np.pad(a, 1).astype(float), 0.5)
        ds = []
        for c in contours:
            if len(c) < 20:   # 小さな穴や欠片の輪郭は捨てる
                continue
            c = measure.approximate_polygon(c, tolerance=simplify) - 1
            ds.append("M " + " L ".join(f"{x:.1f},{y:.1f}" for y, x in c) + " Z")
        Path(path_svg).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{im.width}" height="{im.height}" viewBox="0 0 {im.width} {im.height}">'
            f'<path fill-rule="evenodd" fill="#000" d="{" ".join(ds)}"/></svg>\n')
        info["paths"] = len(ds)
        info["points"] = sum(d.count("L") + 1 for d in ds)
    return info


# ---- クロマキー ----

def chroma(src: str, out: str, key: str | None = None, tol: float = 35.0, soft: float = 25.0, despill: bool = True) -> dict:
    """指定の色（グリーンバックなど）に近い画素を透明にする。色を省くと四隅の色の中央値を背景の色とみなす。
    距離が tol 以下は完全に透明、tol から tol+soft の間はなだらかに残す（縁がギザギザにならないように）。
    緑と白・灰の色みの距離は約 83。tol 60・soft 30 では白い肌や髪が半ば透けたので、既定を tol 35・soft 25 にした
    despill: 縁に映り込んだ背景の色（緑かぶり）を、その色の成分を周りの成分まで下げて消す"""
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(float)
    if key:
        k = np.array([int(key[i:i + 2], 16) for i in (1, 3, 5)], float)
    else:
        h, w = rgb.shape[:2]
        corners = np.concatenate([rgb[:8, :8].reshape(-1, 3), rgb[:8, -8:].reshape(-1, 3), rgb[-8:, :8].reshape(-1, 3), rgb[-8:, -8:].reshape(-1, 3)])
        k = np.median(corners, axis=0)
    # 明るさの違いに引きずられないよう、色み（YCbCr の Cb, Cr）で距離を測る
    def cbcr(x):
        r, g, b = x[..., 0], x[..., 1], x[..., 2]
        return np.stack([-0.1687 * r - 0.3313 * g + 0.5 * b, 0.5 * r - 0.4187 * g - 0.0813 * b], -1)
    d = np.linalg.norm(cbcr(rgb) - cbcr(k[None, None, :]), axis=-1)
    alpha = np.clip((d - tol) / max(soft, 1e-6), 0, 1)
    if despill:
        ch = int(np.argmax(k))   # 背景の色で一番強い成分（緑なら G）
        others = [c for c in range(3) if c != ch]
        limit = np.max(rgb[..., others], axis=-1)
        rgb[..., ch] = np.minimum(rgb[..., ch], limit)
    _rgba(Image.fromarray(rgb.astype("uint8")), alpha).save(out)
    return {"key": "#%02x%02x%02x" % tuple(int(v) for v in k), **_stats(alpha)}


# ---- ロトスコーピング ----

def roto(src: str, outdir: str) -> dict:
    """動く絵（GIF、またはコマの PNG を並べたフォルダ）から、コマごとに人物を抜く。
    コマどうしで輪郭がちらつかないよう、前後のコマのアルファ値と平均して滑らかにする（動きの大きい所はそのコマを優先）。
    結果は透明 PNG の連番と、透明な GIF、各コマの人物の範囲（外接矩形）を書いた roto.json"""
    from rembg import new_session, remove
    import os
    os.environ.setdefault("U2NET_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "gen" / "u2net"))
    p = Path(src)
    if p.is_dir():
        frames = [Image.open(f).convert("RGB") for f in sorted(p.glob("*.png")) + sorted(p.glob("*.jpg"))]
        dur = 100
    else:
        g = Image.open(src)
        frames, dur = [], g.info.get("duration", 100)
        for i in range(getattr(g, "n_frames", 1)):
            g.seek(i)
            frames.append(g.convert("RGB"))
    if not frames:
        raise SystemExit("コマが無い")
    sess = new_session("isnet-anime")
    raw = [np.asarray(remove(f, session=sess, only_mask=True).convert("L")) / 255.0 for f in frames]
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    boxes, cuts = [], []
    for i, f in enumerate(frames):
        a = raw[i]
        if 0 < i < len(frames) - 1:
            avg = (raw[i - 1] + a + raw[i + 1]) / 3
            moving = np.abs(raw[i - 1] - raw[i + 1]) > 0.5
            a = np.where(moving, a, avg)
        c = _rgba(f, a)
        c.save(out / f"frame-{i:04d}.png")
        cuts.append(c)
        bb = Image.fromarray((a > 0.5).astype("uint8") * 255).getbbox()
        boxes.append(list(bb) if bb else None)
    cuts[0].save(out / "roto.gif", save_all=True, append_images=cuts[1:], duration=dur, loop=0, disposal=2)
    (out / "roto.json").write_text(json.dumps({"frames": len(frames), "boxes": boxes}, ensure_ascii=False))
    return {"frames": len(frames), "kept_mean": round(float(np.mean([(r > 0.5).mean() for r in raw])), 4)}


# ---- 影の付け方（立体を計算して光を当てる） ----

SHADE_STYLES = ("cel2", "cel3", "soft", "rim", "back")


def height_field(src: str, alpha: np.ndarray, inflate: float = 0.6) -> np.ndarray:
    """人物の立体を高さの地形（手前ほど高い）として作る。
    奥行きの推定（Depth Anything V2 Small）は顔や胸の起伏を拾うが、輪郭の際で急に落ちない（板のように平ら）。
    そこで輪郭から膨らませた丸み（inflate_dome）を足し、縁で面が奥へ回り込む形にする"""
    from scipy import ndimage
    from transformers import pipeline
    im = Image.open(src).convert("RGB")
    import device
    est = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=device.name())(im)["predicted_depth"]
    d = est.squeeze().numpy() if hasattr(est, "numpy") else np.asarray(est)
    d = np.asarray(Image.fromarray(d.astype("float32")).resize(im.size, Image.BILINEAR))
    inside = alpha > 0.5
    d = (d - d[inside].min()) / max(d[inside].max() - d[inside].min(), 1e-6)
    bulge = inflate_dome(inside)
    h = (1 - inflate) * d + inflate * bulge
    h = ndimage.gaussian_filter(np.where(inside, h, 0.0), 2.0)
    # 高さの単位を画素にそろえる（人物の幅の 1/4 を最も高い所の高さとみなす。法線の傾きと落ち影の長さが絵の大きさで変わらないように）
    w = inside.any(0).sum()
    return h * (w * 0.25)


def inflate_dome(inside: np.ndarray) -> np.ndarray:
    """シルエットを風船のように膨らませた高さ（0〜1）。ポアソン方程式（∇²h = -1、輪郭で h = 0）を解き、平方根をとる。
    輪郭からの距離をそのまま使うと、体の中心線に折り目（尾根）が出て、顔と胴に斜めの影の線が入った。
    ポアソンの解は折り目の無いなめらかな山になり、細い所（腕、脚）は低く、太い所（胴）は高くなる（筒の太さに比例した丸み）。
    平方根で縁の傾きを急にし、断面を円に近づける"""
    small = Image.fromarray(inside.astype("uint8") * 255)
    k = 4
    sw, sh = max(inside.shape[1] // k, 8), max(inside.shape[0] // k, 8)
    m = np.asarray(small.resize((sw, sh), Image.BILINEAR)) > 127
    h = np.zeros(m.shape)
    for _ in range(1500):   # ヤコビ法。1/4 の大きさなので数秒で収まる
        nb = np.zeros_like(h)
        nb[1:, :] += h[:-1, :]; nb[:-1, :] += h[1:, :]; nb[:, 1:] += h[:, :-1]; nb[:, :-1] += h[:, 1:]
        h = np.where(m, (nb + 1.0) / 4.0, 0.0)
    h = np.sqrt(h / max(h.max(), 1e-6))
    big = np.asarray(Image.fromarray((h * 65535).astype("uint16")).resize((inside.shape[1], inside.shape[0]), Image.BILINEAR)) / 65535.0
    return np.where(inside, big, 0.0)


def normals(h: np.ndarray) -> np.ndarray:
    """高さの地形から面の向き（法線、x 右・y 上・z 手前、長さ 1）を出す"""
    gy, gx = np.gradient(h)
    n = np.dstack([-gx, gy, np.ones_like(h)])
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def cast_shadow(h: np.ndarray, light: np.ndarray, reach: float | None = None, steps: int = 24) -> np.ndarray:
    """光の方向へ地形の上をたどり、途中に光より高い所があれば影（1）にする。髪が顔に落とす影、腕が胴に落とす影のような落ち影"""
    lx, ly, lz = light
    plane = np.hypot(lx, ly)
    if plane < 1e-6:
        return np.zeros_like(h)
    dx, dy = lx / plane, -ly / plane          # 画面では y が下向き
    rise = lz / plane                          # 横に1画素進むごとに光の線が上がる高さ
    H, W = h.shape
    # たどる距離は人物の幅の 12% まで。遠くまでたどると、膨らみの山が反対側の太もも全体に影を落とした
    reach = reach or 0.12 * max((h > 0).any(0).sum(), 1)
    margin = 0.02 * h.max()
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    shadow = np.zeros_like(h)
    for k in range(1, steps + 1):
        t = reach * k / steps
        sx = np.clip(np.round(xx + dx * t).astype(int), 0, W - 1)
        sy = np.clip(np.round(yy + dy * t).astype(int), 0, H - 1)
        shadow = np.maximum(shadow, (h[sy, sx] > h + rise * t + margin).astype(float))
    return shadow


def shade(src: str, out: str, style: str = "cel2", light: str = "-1,1,1.2", shadow_color: str = "#8a7fb0", strength: float = 0.55) -> dict:
    """絵に、立体を計算した影を付ける。
    1. 人物を抜く（背景除去） 2. 高さの地形を作る（height_field） 3. 法線を出す 4. 光の向きとの角度で明るさ（ランバート）
    5. 落ち影をたどる（cast_shadow） 6. 塗りの作風で明るさを段に分け、影の色を掛ける。線画と元の色はそのまま残す
    style: cel2（アニメ塗り2段）、cel3（2段＋濃い影）、soft（なめらか）、rim（縁の光を足す）、back（逆光: 前が暗く縁が光る）
    light: 光の向き x,y,z（x 右、y 上、z 手前）。影の色は青みの紫（アニメ塗りの影は黒でなく寒色を掛けると肌が濁らない）"""
    if style not in SHADE_STYLES:
        raise SystemExit(f"style は {', '.join(SHADE_STYLES)}")
    im = Image.open(src).convert("RGB")
    from rembg import new_session, remove
    import os
    os.environ.setdefault("U2NET_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "gen" / "u2net"))
    alpha = np.asarray(remove(im, session=new_session("isnet-anime"), only_mask=True).convert("L")) / 255.0
    L = np.array([float(v) for v in light.split(",")])
    if style == "back":
        L = np.array([L[0] * 0.3, 0.3, -1.0])     # 光は人物の後ろから
    L = L / np.linalg.norm(L)
    h = height_field(src, alpha)
    n = normals(h)
    lam = np.clip((n * L).sum(-1), 0, 1)
    cs = cast_shadow(h, L) if L[2] > 0 else np.zeros_like(h)
    lit = lam * (1 - cs)
    if style == "cel2":
        dark = (lit < 0.35).astype(float)
    elif style == "cel3":
        dark = np.where(lit < 0.12, 1.6, np.where(lit < 0.4, 1.0, 0.0))
    elif style == "soft":
        dark = np.clip((0.6 - lit) / 0.6, 0, 1)
    elif style == "rim":
        dark = (lit < 0.35).astype(float)
    else:  # back
        dark = np.full_like(lit, 0.9)
    from scipy import ndimage
    dark = ndimage.gaussian_filter(dark, 0.8) * (alpha > 0.5)     # 段の境目のギザギザだけ消す（ぼかしすぎると塗りの段が消える）
    rgb = np.asarray(im).astype(float) / 255.0
    sc = np.array([int(shadow_color[i:i + 2], 16) for i in (1, 3, 5)]) / 255.0
    shaded = rgb * (1 - np.clip(dark * strength, 0, 1)[..., None] * (1 - sc))
    if style in ("rim", "back"):
        # 縁の光: 面が横を向いている所（法線の z が小さい）で、光の側にある所を明るくする
        side = np.clip(1 - n[..., 2], 0, 1) ** 3
        toward = np.clip(n[..., 0] * np.sign(L[0] or 1) * 0.5 + 0.5, 0, 1) if style == "rim" else 1.0
        rim = side * toward * (alpha > 0.5)
        shaded = shaded + (1 - shaded) * np.clip(rim * 0.9, 0, 1)[..., None]
    res = Image.fromarray((np.clip(shaded, 0, 1) * 255).astype("uint8"))
    res = Image.composite(res, im, Image.fromarray((alpha * 255).astype("uint8")))
    res.save(out)
    Image.fromarray(((n * 0.5 + 0.5) * 255 * (alpha > 0.5)[..., None]).astype("uint8")).save(str(Path(out).with_suffix("")) + "-normal.png")
    Image.fromarray((cs * 255).astype("uint8")).save(str(Path(out).with_suffix("")) + "-castshadow.png")
    inside = alpha > 0.5
    return {"style": style, "light": [round(v, 2) for v in L], "shadow_area": round(float((dark > 0.5)[inside].mean()), 3),
            "cast_shadow_area": round(float(cs[inside].mean()), 3)}


# ---- AI っぽさを測る・消す ----

def _person_alpha(src: str, im: Image.Image) -> np.ndarray:
    from rembg import new_session, remove
    import os
    os.environ.setdefault("U2NET_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "gen" / "u2net"))
    return np.asarray(remove(im, session=new_session("isnet-anime"), only_mask=True).convert("L")) / 255.0 > 0.5


def _lines(rgb: np.ndarray) -> np.ndarray:
    """線画の画素: 周り（9px）より十分暗い所"""
    from scipy import ndimage
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    return (ndimage.median_filter(lum, 9) - lum) > 35


def ai_tells(src: str) -> dict:
    """AI の絵と見抜かれやすい所を数える（人物の中だけ）。どれも大きいほど AI っぽい。目安は docs/knowledge/ai-look.md。
    gloss: つや（小さく孤立した白い点）の数、人物 10 万画素あたり。肌や髪や目が濡れたように光るほど増える
    colors: 32 段に丸めた色の数 ÷ 100。アニメ塗りは塗りの段が少ない。AI は境目なくなめらかに塗り分けて色数が増える
    noise: 塗りの中の細かい色むら（色み Cb/Cr の高周波の強さ）
    line_soft: 線の縁のにじみ（線の画素のうち、まわりとの差が半端な画素の割合）
    line_uniform: 線の太さのばらつきの少なさ（1 - 変動係数）。手描きは入り抜きで太さが変わる
    flat_depth: 背景と人物の細かさの比。背景も人物と同じほど描き込まれていると 1 に近い（奥行きが無い）"""
    from scipy import ndimage
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(float)
    person = _person_alpha(src, im)
    hsv = np.asarray(im.convert("HSV")).astype(float) / 255.0
    spec = (hsv[..., 2] > 0.96) & (hsv[..., 1] < 0.08) & person
    lab, n = ndimage.label(spec)
    sizes = ndimage.sum(spec, lab, range(1, n + 1)) if n else np.array([])
    # つやは小さく孤立した白い点。広い白（白い服）は数えない。数は人物の大きさ 10 万画素あたり
    gloss = float(((sizes > 0) & (sizes < 0.0005 * person.sum())).sum() / max(person.sum(), 1) * 1e5)
    q = (rgb[person] // 8).astype(int)
    colors = len(np.unique(q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2])) / 100
    cb = -0.1687 * rgb[..., 0] - 0.3313 * rgb[..., 1] + 0.5 * rgb[..., 2]
    cr = 0.5 * rgb[..., 0] - 0.4187 * rgb[..., 1] - 0.0813 * rgb[..., 2]
    lines = _lines(rgb)
    flat = person & ~ndimage.binary_dilation(lines, iterations=2)
    hf = np.abs(cb - ndimage.gaussian_filter(cb, 1.5)) + np.abs(cr - ndimage.gaussian_filter(cr, 1.5))
    noise = float(hf[flat].mean()) if flat.any() else 0.0
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    ring = ndimage.binary_dilation(lines, iterations=1) & ~lines & person
    contrast = (ndimage.median_filter(lum, 9) - lum)
    line_soft = float(((contrast > 10) & (contrast <= 35) & ring).sum() / max((lines & person).sum(), 1))
    skel_w = ndimage.distance_transform_edt(lines & person)
    widths = skel_w[(skel_w > 0) & (ndimage.maximum_filter(skel_w, 3) == skel_w)]
    line_uniform = float(1 - widths.std() / max(widths.mean(), 1e-6)) if widths.size else 0.0
    lap = np.abs(ndimage.laplace(ndimage.gaussian_filter(lum, 0.8)))
    bg = ~ndimage.binary_dilation(person, iterations=8)
    flat_depth = float(lap[bg].mean() / max(lap[person].mean(), 1e-6)) if bg.any() else 0.0
    return {k: round(v, 3) for k, v in dict(gloss=gloss, colors=colors, noise=noise, line_soft=line_soft,
                                             line_uniform=line_uniform, flat_depth=flat_depth).items()}


def de_ai(src: str, out: str, steps: int = 10, line_boost: float = 1.0) -> dict:
    """使わない（2026-10-10、利用者の指摘）。AI の特徴を消すと、線と塗りを崩した下手な絵になるだけだった。docs/knowledge/ai-look.md
    AI っぽさを消す（人物の中だけ。背景は手を入れない）。色み（色相と彩度）は変えない。
    1. 塗りを平らにする: 線を避けて縁を保つならし（中央値）を重ね、細かい色むらを消す。そのあと明るさだけを steps 段に丸め、
       なめらかな塗り分けをアニメ塗りの段に戻す
    2. つやを抑える: 小さく孤立した白い点（つや）だけを、まわりの塗りの色で埋める。広く明るい所（白い服、明るい肌）は触らない
    3. 線を締める: 線の画素を元の濃さより暗くし、縁の半端なにじみを消す。太さは元のまま（入り抜きを壊さない）
    前の版は、明るい所を全部抑えて肌が灰色になり、色を 28 色に減らして目と水着の色が肌に吸われた"""
    from scipy import ndimage
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(float)
    person = _person_alpha(src, im)
    lines = _lines(rgb)
    fill = person & ~ndimage.binary_dilation(lines, iterations=1)
    # 1. ならし（線をまたがないよう、線の所は元の色のまま毎回戻す）
    sm = rgb.copy()
    for _ in range(3):
        sm = ndimage.median_filter(sm, size=(5, 5, 1))
        sm = np.where(fill[..., None], sm, rgb)
    hsv = np.asarray(Image.fromarray(sm.astype("uint8")).convert("HSV")).astype(float)
    v = hsv[..., 2] / 255.0
    vq = (np.round(v * steps) / steps).clip(0, 1)
    hsv[..., 2] = np.where(fill, vq * 255, hsv[..., 2])
    flat = np.asarray(Image.fromarray(hsv.astype("uint8"), "HSV").convert("RGB")).astype(float)
    flat = np.where(fill[..., None], flat, rgb)
    # 2. つや: 白く彩度の低い小さな塊（人物の 0.05% 未満）を、まわりの色の中央値で埋める
    hsv0 = np.asarray(im.convert("HSV")).astype(float) / 255.0
    spec = (hsv0[..., 2] > 0.96) & (hsv0[..., 1] < 0.08) & person
    lab, n = ndimage.label(spec)
    removed = 0
    if n:
        sizes = ndimage.sum(spec, lab, range(1, n + 1))
        small = np.isin(lab, [i + 1 for i, sz in enumerate(sizes) if sz < 0.0005 * person.sum()])
        ring = ndimage.binary_dilation(small, iterations=3) & ~small & person
        fillcol = ndimage.median_filter(np.where(small[..., None], np.nan_to_num(flat), flat), size=(7, 7, 1))
        flat = np.where(small[..., None], fillcol, flat)
        removed = int(small.sum())
    # 3. 線
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    darkness = np.clip((ndimage.median_filter(lum, 9) - lum) / 120, 0, 1)
    ink = np.clip(darkness * (1.4 * line_boost), 0, 1)
    ink = np.where(ink > 0.35, np.minimum(ink * 1.3, 1), np.where(ink < 0.15, 0, ink)) * person
    line_col = rgb * 0.35   # 線の色は元の色を暗くしたもの（真っ黒にしない。アニメの色トレス）
    res = flat * (1 - ink[..., None]) + line_col * ink[..., None]
    res = np.where(person[..., None], res, rgb)
    Image.fromarray(np.clip(res, 0, 255).astype("uint8")).save(out)
    return {"gloss_px_removed": removed, "before": ai_tells(src), "after": ai_tells(out)}

def notan(src: str, out: str, size: int = 96) -> dict:
    """明暗の設計を見る（ノタン）。上手い絵は、縮めて白黒にすると明・中・暗の3つの大きな塊で読める。
    縮小 → 明るさを3段（多段の大津）に分け、塊の数と細切れの割合を数える。細切れが多いほど、明暗が設計されていない。
    見せ場: 明暗差（3段の境目）が一番集まる場所を、人物の外接枠の中の位置（上からの割合）で返す。顔の周りなら 0.1〜0.3。
    out には3段の図を元の大きさに拡大して保存する（目で見て判定するため）"""
    from scipy import ndimage
    from skimage.filters import threshold_multiotsu
    im = Image.open(src).convert("RGB")
    w, h = im.size
    k = size / max(w, h)
    small = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    lum = np.asarray(small).astype(float) @ np.array([0.299, 0.587, 0.114])
    t = threshold_multiotsu(lum, classes=3)
    val = np.digitize(lum, t)
    blobs, frag = 0, 0
    for v in range(3):
        lab, n = ndimage.label(val == v)
        if n:
            sz = ndimage.sum(val == v, lab, range(1, n + 1))
            big = sz >= 0.01 * val.size
            blobs += int(big.sum())
            frag += int(sz[~big].sum())
    edge = (np.abs(np.diff(val, axis=0, prepend=val[:1])) + np.abs(np.diff(val, axis=1, prepend=val[:, :1]))) > 0
    dens = ndimage.uniform_filter(edge.astype(float), size=max(3, size // 8))
    person = np.asarray(Image.fromarray(_person_alpha(src, im).astype("uint8") * 255).resize(small.size)) > 127
    # 見せ場は人物の中で探す。背景を描いた絵では、床の反射や窓の明暗差が一番強いことがある（人物の外を見せ場と取り違えた）
    fy, fx = np.unravel_index(int((dens * person if person.any() else dens).argmax()), dens.shape)
    ys, xs = np.nonzero(person) if person.any() else (np.array([0, val.shape[0] - 1]), np.array([0, val.shape[1] - 1]))
    focal_y = (fy - ys.min()) / max(ys.max() - ys.min(), 1)
    shades = np.array([40, 128, 225], dtype="uint8")[val]
    Image.fromarray(shades).resize((w, h), Image.NEAREST).save(out)
    return {"masses": blobs, "fragment_ratio": round(frag / val.size, 3), "focal_y_in_person": round(float(focal_y), 2),
            "focal_xy": [round(fx / val.shape[1], 2), round(fy / val.shape[0], 2)]}


def line_weight(src: str) -> dict:
    """線の強弱の意図を見る。上手い絵は外形の線が太く、内側の線（服のしわ、髪の筋、目鼻）は細い。
    人物の縁から 4px 以内の線を外形、それより内側の線を内側として、線の中心での太さ（距離変換の2倍）の平均を比べる。
    ratio が 1 に近いほど、どこも同じ太さ（意図の無い線）。外形を太くした絵では 1 を超える"""
    from scipy import ndimage
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(float)
    person = _person_alpha(src, im)
    # _lines（周り 9px の中央値との差）は 5px を超える太い線を拾えず、どの絵も 2px と出てしまう。
    # ここでは 15px の閉じ（暗い所を周りの明るさで埋める）との差で、15px までの太さの線を拾う
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    lines = ((ndimage.grey_closing(lum, size=15) - lum) > 35) & ndimage.binary_dilation(person, iterations=3)
    rim = ndimage.binary_dilation(person, iterations=4) & ~ndimage.binary_erosion(person, iterations=4)
    dist = ndimage.distance_transform_edt(lines)
    ridge = (dist > 0) & (ndimage.maximum_filter(dist, 3) == dist)
    outer, inner = dist[ridge & rim] * 2, dist[ridge & ~rim] * 2
    med = lambda a: float(a.mean()) if a.size else 0.0   # 太さは 1px 刻みなので、中央値だと差が消える。平均で比べる
    return {"outer_px": round(med(outer), 2), "inner_px": round(med(inner), 2),
            "ratio": round(med(outer) / max(med(inner), 1e-6), 2), "samples": [int(outer.size), int(inner.size)]}


def _box_mask(size, box, grow=0):
    m = Image.new("L", size, 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m).rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], fill=255)
    return m


def inpaint(src: str, out: str, prompt: str, box=None, mask=None, grow: int = 8, seed: int = 7) -> dict:
    """任意の範囲を描き直す（インペインティング）。範囲は --box x0,y0,x1,y1 か、白黒の --mask 画像で渡す。
    部位で選ぶ描き直しは edit.py inpaint。こちらは部位に当たらない所（背景の物、小物、手の中）を直すためのもの。
    描くのは範囲を grow 画素広げた所、結果に使うのは範囲の中だけ（つながりを保ち、外は1画素も変えない）"""
    import edit
    im = Image.open(src).convert("RGB")
    if mask:
        keep = Image.open(mask).convert("L").point(lambda v: 255 if v > 127 else 0).resize(im.size)
        gen = keep.filter(ImageFilter.MaxFilter(grow * 2 + 1)) if grow else keep
    else:
        keep, gen = _box_mask(im.size, box), _box_mask(im.size, box, grow)
    res = edit.inpaint_mask(im, gen, keep, prompt, seed=seed)
    res.save(out)
    return {"region_px": sum(keep.histogram()[1:]), "outside_changed": edit.outside_changed(im, res, keep)}


def outpaint(src: str, out: str, prompt: str, pad=(0, 0, 0, 0), seed: int = 7) -> dict:
    """絵の外側を描き足す（アウトペインティング）。pad は 左,上,右,下 に足す画素数。
    足した所は、まず元の縁の色を引き伸ばして埋め（灰色や黒から描かせると、境目に帯が出やすい）、
    足した所に元の縁から 16 画素を重ねた範囲を描き、足した所だけを結果に使う"""
    import edit
    im = Image.open(src).convert("RGB")
    l, t, r, b = pad
    W, H = im.width + l + r, im.height + t + b
    canvas = im.resize((W, H)).filter(ImageFilter.GaussianBlur(24))
    canvas.paste(im, (l, t))
    keep = Image.new("L", (W, H), 255)
    ImageDraw.Draw(keep).rectangle([l, t, l + im.width - 1, t + im.height - 1], fill=0)
    gen = Image.new("L", (W, H), 255)
    ov = 16
    ImageDraw.Draw(gen).rectangle([l + (ov if l else 0), t + (ov if t else 0),
                                   l + im.width - 1 - (ov if r else 0), t + im.height - 1 - (ov if b else 0)], fill=0)
    res = edit.inpaint_mask(canvas, gen, keep, prompt, seed=seed, noise=0)
    res.save(out)
    inner = res.crop((l, t, l + im.width, t + im.height))
    changed = int((np.abs(np.asarray(inner).astype(int) - np.asarray(im).astype(int)).max(axis=2) > 0).sum())
    return {"size": [W, H], "added_px": W * H - im.width * im.height, "original_changed": changed}


def lineart(src: str, out: str, sigma: float = 1.4, k: float = 1.6, tau: float = 0.995, eps: float = -0.005,
            phi: float = 40.0, clean: int = 12) -> dict:
    """線画を抜き出す（塗り絵や清書の下地）。XDoG（ぼかし2枚の差を、なめらかな段で白黒にする）。
    模型を使わないので数秒で済み、塗りの濃淡は消えて輪郭と描き込みの線だけが残る。
    clean より小さい黒の点（雑音・網点）は消す。返り値の line_ratio は線の画素の割合"""
    from PIL import ImageFilter
    g = np.asarray(Image.open(src).convert("L")).astype(float) / 255.0
    im = Image.fromarray((g * 255).astype("uint8"))
    a = np.asarray(im.filter(ImageFilter.GaussianBlur(sigma))).astype(float) / 255.0
    b = np.asarray(im.filter(ImageFilter.GaussianBlur(sigma * k))).astype(float) / 255.0
    d = a - tau * b
    e = np.where(d >= eps, 1.0, 1.0 + np.tanh(phi * (d - eps)))
    line = e < 0.5
    if clean:
        # 小さい黒の点を消す（4近傍の塊の大きさで判定）
        from collections import deque
        H, W = line.shape
        seen = np.zeros_like(line)
        for y0, x0 in zip(*np.nonzero(line)):
            if seen[y0, x0]:
                continue
            comp, q = [], deque([(y0, x0)])
            seen[y0, x0] = True
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and line[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
            if len(comp) < clean:
                for y, x in comp:
                    line[y, x] = False
    Image.fromarray(np.where(line, 0, 255).astype("uint8")).save(out)
    return {"line_ratio": round(float(line.mean()), 4), "size": list(line.shape[::-1])}


def face_region(src: str, im: Image.Image) -> np.ndarray:
    """部位分けの顔（11）のうち、一番大きな塊だけ。部位分けは腰や肩の小さな切れ端も顔と取ることがあり、
    全部を使うと外接枠が絵のほぼ全体（騎士で 0,0〜832,908）に広がった"""
    sys.path.insert(0, str(Path(__file__).parent))
    import edit
    from scipy import ndimage
    face = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST)) == 11
    lab, n = ndimage.label(face)
    if n == 0:
        return face
    sizes = np.bincount(lab.ravel())[1:]
    return lab == (int(sizes.argmax()) + 1)


def face_box(src: str, im: Image.Image, margin: float = 0.9):
    """部位分けの顔の外接枠を正方形に広げた枠。顔が見つからなければ None"""
    face = face_region(src, im)
    if face.sum() < 200:
        return None
    ys, xs = np.nonzero(face)
    cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
    half = int(max(ys.max() - ys.min(), xs.max() - xs.min()) * margin) + 16
    return (max(cx - half, 0), max(cy - half, 0), min(cx + half, im.width), min(cy + half, im.height))


def face_mask(src: str, im: Image.Image, grow: float = 0.12) -> Image.Image:
    """部位分けの顔（11）を、顔の大きさの grow 倍だけ広げた範囲（白）。縁はぼかす。
    楕円の枠で貼ると胸から上が丸ごと描き直され、表情ごとに鎧や襟巻きの形が変わった。顔だけに絞る"""
    from scipy import ndimage
    face = face_region(src, im)
    ys, xs = np.nonzero(face)
    r = max(int(max(ys.max() - ys.min(), xs.max() - xs.min()) * grow), 2)
    grown = ndimage.binary_dilation(face, iterations=r)
    m = Image.fromarray((grown * 255).astype("uint8"))
    return m.filter(ImageFilter.GaussianBlur(max(r // 2, 1)))


def face_redraw(im: Image.Image, box, prompt: str, negative: str = "", strength: float = 0.35, seed: int = 7,
                ref: Image.Image | None = None, ref_scale: float = 0.4, mask: Image.Image | None = None,
                pipe=None, steps: int = 24, guidance: float = 6.0) -> Image.Image:
    """枠の中（顔）を 1024 に拡大して描き直し、元の大きさに戻して、縁をぼかした楕円で貼る。髪・服・体は元のまま残る。
    顔の手直し（弱く）と、表情差分（強めに、表情の言葉で）が共有する。
    ref（手本の顔）を渡すと IP-Adapter で顔つきを寄せる。手本を読ませる部品を付けたまま ref を渡さないと、描く模型が
    image_embeds が無いと言って止まった（設定資料集で手本つきの絵を描いた直後）"""
    import torch
    import demi
    import design
    sys.path.insert(0, str(Path(__file__).parent))
    import free_text
    crop = im.crop(box)
    big = crop.resize((1024, 1024), Image.LANCZOS)
    # pipe を渡すと、その模型で描き直す（描いたのと同じ処理なら模型を読み直さない。読み直しは冷えた状態で 552 秒かかった）
    pipe = pipe or demi.img2img()
    pos, neg = free_text.full_prompt(prompt, negative)
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    extra = {}
    if ref is not None:
        pipe.set_ip_adapter_scale(ref_scale)
        extra["ip_adapter_image"] = ref
    elif getattr(pipe.unet, "encoder_hid_proj", None) is not None:
        pipe.unload_ip_adapter()
    redrawn = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                   image=big, strength=strength, num_inference_steps=steps, guidance_scale=guidance,
                   generator=torch.Generator().manual_seed(seed), **extra).images[0]
    small = redrawn.resize(crop.size, Image.LANCZOS)
    w, h = crop.size
    if mask is not None:
        m = mask.crop(box)          # 顔だけを貼る（表情差分）
    else:
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).ellipse([w * 0.08, h * 0.08, w * 0.92, h * 0.92], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(max(w // 16, 2)))
    out = im.copy()
    out.paste(small, box[:2], m)
    return out


FACE_FIX_NEGATIVE = "beauty mark, mole, freckles, white spot, sparkle on cheek, tear, face paint, heterochromia"


def face_fix(src: str, out: str, prompt: str = "1girl, detailed face, detailed eyes", strength: float = 0.35, seed: int = 7,
             negative: str = FACE_FIX_NEGATIVE) -> dict:
    """顔だけを拡大して描き直し、元の大きさに戻して貼る（人の描き手が目と顔を最後に拡大して描き込むのと同じ）。
    全身の絵では顔が小さく、描く模型の解像度では目が崩れやすい。部位分けの顔（11）の外接枠を 1024 に拡大して
    弱く（0.35）描き直し、縁をぼかして元へ戻す。
    打ち消しを渡さないと、SDXL の全身絵で2枚続けて頬や鼻先に白い点が描き足された"""
    im = Image.open(src).convert("RGB")
    box = face_box(src, im)
    if box is None:
        return {"fixed": False, "why": "顔が見つからない"}
    face_redraw(im, box, prompt, negative=negative, strength=strength, seed=seed).save(out)
    return {"fixed": True, "box": [int(v) for v in box]}


# ---- 色 ----

def _hex(color: str) -> np.ndarray:
    c = color.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], float)


def _ycc(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).convert("YCbCr")).astype(float)


def recolor(src: str, out: str, from_color: str, to_color: str, tol: float = 40.0, soft: float = 15.0, box=None) -> dict:
    """from_color に近い所の色を to_color に置き換える。明るさの比は残す（布の明るい面と影の面の差を消さない）。
    近さは色み（Cb・Cr）で測り、明るさは tol の2倍の幅まで許す。明るさまで同じ幅で測ると、灰色の布の影の面が外れた。
    白地と灰色は色みが同じなので、明るさの幅で白地を外す。色みの幅は tol の 0.4 倍にする（肌は灰色から色みで 31 しか離れず、
    tol のままだと顔まで赤くなった）。
    box（左,上,右,下）を渡すとその中だけを変える。同じ灰色の鎧と襟巻きのように、色だけでは分けられない物があるため"""
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(float)
    ycc = _ycc(rgb)
    f, t = _ycc(_hex(from_color)[None, None]), _ycc(_hex(to_color)[None, None])
    hue = np.hypot(ycc[..., 1] - f[..., 1], ycc[..., 2] - f[..., 2])
    light = np.abs(ycc[..., 0] - f[..., 0])
    near = 0.4 * tol
    w = np.clip((near + soft / 2 - hue) / (soft / 2), 0, 1) * np.clip((2 * tol + soft - light) / soft, 0, 1)
    # 白地は変えない。明るい灰色（203）を置き換えると、白地（255）も明るさの幅に入り、枠の形に桃色が付いた
    if f[0, 0, 0] < 240:
        w = w * (ycc[..., 0] < 245)
    if box is not None:
        inside = np.zeros(w.shape)
        x0, y0, x1, y1 = box
        inside[max(y0, 0):y1, max(x0, 0):x1] = 1
        w = w * inside
    new = ycc.copy()
    new[..., 0] = ycc[..., 0] * (t[..., 0] / max(f[0, 0, 0], 1.0))
    new[..., 1:] = t[..., 1:]
    res = np.asarray(Image.fromarray(np.clip(new, 0, 255).astype("uint8"), "YCbCr").convert("RGB")).astype(float)
    mixed = rgb * (1 - w[..., None]) + res * w[..., None]
    Image.fromarray(np.clip(np.rint(mixed), 0, 255).astype("uint8")).save(out)
    return {"out": out, "changed": round(float((w > 0.5).mean()), 4)}


def grade(src: str, out: str, brightness: float = 1.0, contrast: float = 1.0, saturation: float = 1.0, warmth: float = 0.0) -> dict:
    """色調補正: 明るさ・コントラスト・彩度（1 で元のまま）と色温度（正で暖かく、負で冷たく）"""
    from PIL import ImageEnhance
    im = Image.open(src).convert("RGB")
    for enh, v in ((ImageEnhance.Brightness, brightness), (ImageEnhance.Contrast, contrast), (ImageEnhance.Color, saturation)):
        if v != 1.0:
            im = enh(im).enhance(v)
    if warmth:
        a = np.asarray(im).astype(float)
        a[..., 0] += 64 * warmth
        a[..., 2] -= 64 * warmth
        im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    im.save(out)
    return {"out": out, "mean": [round(float(v), 1) for v in np.asarray(im).reshape(-1, 3).mean(0)]}


def match(src: str, ref: str, out: str, amount: float = 1.0) -> dict:
    """色合わせ: src の色の平均と幅を、ref の色の平均と幅へ amount だけ寄せる（RGB の各成分ごと）。
    場面ごとの絵の色を、決めた1枚（設定画など）にそろえるのに使う。
    PIL の Lab 変換を通すと、半分だけ寄せた色が元と手本の間に来なかったので、RGB で合わせる"""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(float)
    r = np.asarray(Image.open(ref).convert("RGB")).astype(float)
    ma, sa = a.reshape(-1, 3).mean(0), a.reshape(-1, 3).std(0) + 1e-3
    mr, sr = r.reshape(-1, 3).mean(0), r.reshape(-1, 3).std(0) + 1e-3
    tm, ts = ma + (mr - ma) * amount, sa + (sr - sa) * amount
    res = Image.fromarray(np.clip(np.rint((a - ma) / sa * ts + tm), 0, 255).astype("uint8"))
    res.save(out)
    ref_mean = np.asarray(Image.open(ref).convert("RGB")).reshape(-1, 3).mean(0)
    dist = lambda x: round(float(np.abs(np.asarray(x).reshape(-1, 3).mean(0) - ref_mean).max()), 1)
    return {"out": out, "before": dist(im), "after": dist(res)}


# ---- ノイズ除去・ぼかし除去 ----

def _noise(a: np.ndarray) -> float:
    """ざらつきの目安: 隣り合う画素の差のうち、30 未満の小さな差の平均（線や境目の大きな差は数えない）。
    中央値にすると、平らな面の多いアニメ絵では前後とも 0 になり、目安にならなかった"""
    d = np.abs(np.diff(a.mean(-1), axis=1))
    small = d[d < 30]
    return float(small.mean()) if small.size else 0.0


def _edge(a: np.ndarray) -> float:
    """境目の急さの目安: 隣り合う画素の差の上位 1%"""
    g = a.mean(-1)
    return float(np.percentile(np.abs(np.diff(g, axis=1)), 99))


def denoise(src: str, out: str, weight: float = 0.08) -> dict:
    """ノイズ除去: 全変動（TV）で平らな面のざらつきを消し、境目は残す。
    アニメ絵は平らな面と線でできているので、ぼかして消す方式（ガウス）より境目が崩れにくい。weight を上げるほど強く消す"""
    from skimage.restoration import denoise_tv_chambolle
    a = np.asarray(Image.open(src).convert("RGB")).astype(float) / 255
    res = denoise_tv_chambolle(a, weight=weight, channel_axis=-1)
    Image.fromarray(np.clip(np.rint(res * 255), 0, 255).astype("uint8")).save(out)
    return {"out": out, "noise_before": round(_noise(a * 255), 2), "noise_after": round(_noise(res * 255), 2)}


def sharpen(src: str, out: str, radius: float = 3.0, amount: float = 1.5) -> dict:
    """ぼかし除去: アンシャープマスク（ぼかした絵との差を足す）で境目を急にする。平らな所は差が無いので変わらない。
    拡大した絵や、描き直しでぼやけた範囲に使う。強すぎると境目の両側に白と黒の縁が出る"""
    # skimage の unsharp_mask は、この環境では 1e289 のような壊れた値を返した。同じ計算を scipy のぼかしで行う
    from scipy.ndimage import gaussian_filter
    a = np.asarray(Image.open(src).convert("RGB")).astype(float) / 255
    blur = gaussian_filter(a, sigma=(radius, radius, 0))
    res = np.clip(a + amount * (a - blur), 0, 1)
    Image.fromarray(np.clip(np.rint(res * 255), 0, 255).astype("uint8")).save(out)
    return {"out": out, "edge_before": round(_edge(a * 255), 1), "edge_after": round(_edge(res * 255), 1)}



def spot_fill(src: str, out: str, min_ratio: float = 0.002) -> dict:
    """顔の中の、肌に囲まれた白い点（逆光なのに鼻筋に出る照り返し）を、周りの肌の色で埋める。
    作画監督の scene.backlit_spot と同じ探し方（measure.face_spots）。目のハイライトは触らない。
    描き直し（detail.py）では点が残った（強さ 0.4・0.5 とも）ので、点だけを画素で直す"""
    import edit
    import measure
    from scipy import ndimage
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im, dtype=np.float32) / 255.0
    seg = np.asarray(edit.parts(src))
    fm = measure.face_mask(seg, edit.LABELS)
    ratio, spots = measure.face_spots(rgb.mean(-1), fm)
    if ratio < min_ratio:
        im.save(out)
        return {"filled": 0, "ratio": ratio}
    area = ndimage.binary_dilation(spots, iterations=2)
    ring = ndimage.binary_dilation(area, iterations=3) & ~area & fm
    skin = np.median(rgb[ring], axis=0) if ring.any() else np.median(rgb[fm], axis=0)
    # 縁をぼかして混ぜる。べた塗りの円にすると、点の形がそのまま残って見えた
    a = ndimage.gaussian_filter(area.astype(np.float32), 1.2)[..., None]
    fixed = rgb * (1 - a) + skin[None, None, :] * a
    Image.fromarray((np.clip(fixed, 0, 1) * 255).round().astype(np.uint8)).save(out)
    return {"filled": int(area.sum()), "ratio": ratio}

def super_res(src: str, out: str, long: int = 4096) -> dict:
    """超解像: Real-ESRGAN のアニメ絵用で、長い辺が long 画素になるまで拡大する（tools/gen/upscale.py）"""
    import time
    import upscale
    t = time.time()
    size = upscale.upscale(src, out, long)
    return {"size": list(size), "seconds": round(time.time() - t, 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("segment", "matte", "remove", "roto"):
        s = sub.add_parser(name)
        s.add_argument("src")
        s.add_argument("out")
    c = sub.add_parser("cutout")
    c.add_argument("src"); c.add_argument("out"); c.add_argument("--path", default=None)
    k = sub.add_parser("chroma")
    k.add_argument("src"); k.add_argument("out"); k.add_argument("--key", default=None)
    k.add_argument("--tol", type=float, default=35.0); k.add_argument("--soft", type=float, default=25.0)
    sh = sub.add_parser("shade")
    sh.add_argument("src"); sh.add_argument("out"); sh.add_argument("--style", default="cel2", choices=SHADE_STYLES)
    sh.add_argument("--light", default="-1,1,1.2"); sh.add_argument("--shadow-color", default="#8a7fb0")
    t = sub.add_parser("aitells"); t.add_argument("src")
    de = sub.add_parser("deai"); de.add_argument("src"); de.add_argument("out"); de.add_argument("--steps", type=int, default=10)
    nt = sub.add_parser("notan"); nt.add_argument("src"); nt.add_argument("out"); nt.add_argument("--size", type=int, default=96)
    lw = sub.add_parser("lineweight"); lw.add_argument("src")
    ff = sub.add_parser("facefix"); ff.add_argument("src"); ff.add_argument("out"); ff.add_argument("--prompt", default="1girl, detailed face, detailed eyes")
    la = sub.add_parser("lineart"); la.add_argument("src"); la.add_argument("out"); la.add_argument("--sigma", type=float, default=1.4)
    ip = sub.add_parser("inpaint"); ip.add_argument("src"); ip.add_argument("out"); ip.add_argument("--prompt", required=True)
    ip.add_argument("--box", default=None); ip.add_argument("--mask", default=None); ip.add_argument("--seed", type=int, default=7)
    op = sub.add_parser("outpaint"); op.add_argument("src"); op.add_argument("out"); op.add_argument("--prompt", required=True)
    op.add_argument("--pad", default="0,0,0,0", help="左,上,右,下 に足す画素数"); op.add_argument("--seed", type=int, default=7)
    rc = sub.add_parser("recolor"); rc.add_argument("src"); rc.add_argument("out"); rc.add_argument("--from", dest="from_color", required=True)
    rc.add_argument("--to", required=True); rc.add_argument("--tol", type=float, default=40.0)
    rc.add_argument("--box", default=None, help="左,上,右,下。この中だけを変える")
    gr = sub.add_parser("grade"); gr.add_argument("src"); gr.add_argument("out")
    for k in ("brightness", "contrast", "saturation"):
        gr.add_argument(f"--{k}", type=float, default=1.0)
    gr.add_argument("--warmth", type=float, default=0.0)
    mt = sub.add_parser("match"); mt.add_argument("src"); mt.add_argument("ref"); mt.add_argument("out"); mt.add_argument("--amount", type=float, default=1.0)
    dn = sub.add_parser("denoise"); dn.add_argument("src"); dn.add_argument("out"); dn.add_argument("--weight", type=float, default=0.08)
    sp = sub.add_parser("sharpen"); sp.add_argument("src"); sp.add_argument("out")
    sp.add_argument("--radius", type=float, default=3.0); sp.add_argument("--amount", type=float, default=1.5)
    sf = sub.add_parser("spotfill"); sf.add_argument("src"); sf.add_argument("out")
    sr = sub.add_parser("upscale"); sr.add_argument("src"); sr.add_argument("out"); sr.add_argument("--long", type=int, default=4096)
    a = ap.parse_args()
    fn = {"spotfill": lambda: spot_fill(a.src, a.out), "upscale": lambda: super_res(a.src, a.out, a.long),"denoise": lambda: denoise(a.src, a.out, a.weight), "sharpen": lambda: sharpen(a.src, a.out, a.radius, a.amount),
          "recolor": lambda: recolor(a.src, a.out, a.from_color, a.to, a.tol,
                                     box=tuple(int(v) for v in a.box.split(",")) if a.box else None),
          "grade": lambda: grade(a.src, a.out, a.brightness, a.contrast, a.saturation, a.warmth),
          "match": lambda: match(a.src, a.ref, a.out, a.amount),"segment": lambda: segment(a.src, a.out), "matte": lambda: matte(a.src, a.out), "remove": lambda: remove_bg(a.src, a.out),
          "roto": lambda: roto(a.src, a.out), "cutout": lambda: cutout(a.src, a.out, a.path),
          "chroma": lambda: chroma(a.src, a.out, a.key, a.tol, a.soft),
          "shade": lambda: shade(a.src, a.out, a.style, a.light, a.shadow_color),
          "aitells": lambda: ai_tells(a.src), "deai": lambda: de_ai(a.src, a.out, a.steps),
          "notan": lambda: notan(a.src, a.out, a.size), "lineweight": lambda: line_weight(a.src),
          "lineart": lambda: lineart(a.src, a.out, a.sigma),
          "facefix": lambda: face_fix(a.src, a.out, a.prompt),
          "inpaint": lambda: inpaint(a.src, a.out, a.prompt, tuple(int(v) for v in a.box.split(",")) if a.box else None, a.mask, seed=a.seed),
          "outpaint": lambda: outpaint(a.src, a.out, a.prompt, tuple(int(v) for v in a.pad.split(",")), seed=a.seed)}[a.cmd]
    print(json.dumps(fn(), ensure_ascii=False))


if __name__ == "__main__":
    main()

