"""画像処理の道具をまとめて呼べるようにする。人物と背景を分ける技術を、分野ごとの呼び名のまま使えるようにした。

  python3 tools/gen/imgproc.py segment  IN OUT_DIR          セグメンテーション（部位ごとの領域と、人物ごとの領域）
  python3 tools/gen/imgproc.py matte    IN OUT.png          イメージマッティング（髪や半透明の縁のアルファ値を細かく出す）
  python3 tools/gen/imgproc.py remove   IN OUT.png          背景除去（人物だけを残し、背景を透明にする）
  python3 tools/gen/imgproc.py cutout   IN OUT.png [--path OUT.svg]   切り抜き（輪郭で抜く。--path でクリッピングパスを SVG で書く）
  python3 tools/gen/imgproc.py chroma   IN OUT.png [--key #00b140] [--tol 60]   クロマキー（指定の色を消す。色を省くと四隅の色）
  python3 tools/gen/imgproc.py roto     IN.gif|DIR OUT_DIR    ロトスコーピング（コマごとに人物を抜き、透明 PNG と輪郭の動きを書く）
  python3 tools/gen/imgproc.py shade    IN OUT.png [--style cel2|cel3|soft|rim|back] [--light x,y,z]   影の付け方（立体を計算して光を当てる）
  python3 tools/gen/imgproc.py aitells  IN                    AI っぽさを数える（つや、色数、色むら、線のにじみ、線の均一さ、奥行きの無さ）
  python3 tools/gen/imgproc.py deai     IN OUT.png [--steps 10]   AI っぽさを消す（塗りを段に、つやを抑え、線を締める）

どれも結果を画像で書き出し、数字（残した画素の割合など）を標準出力に出す。描いた絵の上でも写真の上でも動く。
重い部品（切り抜きのモデル、部位分けのモデル）は使うときだけ読む。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

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
    est = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device="cpu")(im)["predicted_depth"]
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
    """AI っぽさを消す（人物の中だけ。背景は手を入れない）。色み（色相と彩度）は変えない。
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
    a = ap.parse_args()
    fn = {"segment": lambda: segment(a.src, a.out), "matte": lambda: matte(a.src, a.out), "remove": lambda: remove_bg(a.src, a.out),
          "roto": lambda: roto(a.src, a.out), "cutout": lambda: cutout(a.src, a.out, a.path),
          "chroma": lambda: chroma(a.src, a.out, a.key, a.tol, a.soft),
          "shade": lambda: shade(a.src, a.out, a.style, a.light, a.shadow_color),
          "aitells": lambda: ai_tells(a.src), "deai": lambda: de_ai(a.src, a.out, a.steps)}[a.cmd]
    print(json.dumps(fn(), ensure_ascii=False))


if __name__ == "__main__":
    main()
