"""描いた絵に後から掛ける画風の加工。構図と形は元の絵のまま、見た目だけを変える。

模型を使わず、Pillow と numpy だけで動く（1 枚 数秒、GPU も通信も要らない）。
画像生成で画風ごとに描き直すと、画風ごとに形が崩れ、足の数や向きまで変わる。
同じ 1 枚から加工で全部の画風を作れば、形は 1 回検品すれば済み、画風の違いだけを比べられる。

  python3 tools/gen/stylize.py 元.png 出力ディレクトリ [画風 ...]   画風を省くと全部
  python3 tools/gen/stylize.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# 乱数は種で固定し、同じ元絵からは毎回同じ加工が出るようにする
SEED = 7


def _arr(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0


def _img(a: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def _gray(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def _edges(im: Image.Image, blur: float = 1.0) -> np.ndarray:
    """輪郭の強さ 0〜1。ぼかしてから差分を取り、紙のざらつきを線と見誤らないようにする"""
    g = im.convert("L").filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(g, dtype=np.float32) / 255.0
    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1] = a[:, 2:] - a[:, :-2]
    gy[1:-1, :] = a[2:, :] - a[:-2, :]
    m = np.hypot(gx, gy)
    return np.clip(m / (np.percentile(m, 99) + 1e-6), 0, 1)


def _paper(h: int, w: int, tone=(0.97, 0.95, 0.90), grain: float = 0.03) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    n = rng.normal(0, grain, (h, w, 1)).astype(np.float32)
    n = np.asarray(Image.fromarray(((n[..., 0] + 0.5) * 255).clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)), dtype=np.float32)[..., None] / 255.0 - 0.5
    return np.clip(np.array(tone, dtype=np.float32) + n, 0, 1)


def _streaks(h: int, w: int, angle: float, density: float = 0.5, blur: float = 0.7) -> np.ndarray:
    """斜めの筆の目 0〜1。大きめに作って回してから切り出し、回した角に地が出ないようにする"""
    n = int(np.hypot(h, w)) + 2
    rng = np.random.default_rng(SEED)
    g = Image.fromarray(((rng.random((n, n)) < density) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))
    g = g.resize((n, n // 4)).resize((n, n), Image.BILINEAR).rotate(angle, resample=Image.BILINEAR)
    y0, x0 = (n - h) // 2, (n - w) // 2
    return np.asarray(g, dtype=np.float32)[y0:y0 + h, x0:x0 + w] / 255.0


def _quantize(im: Image.Image, colors: int) -> Image.Image:
    return im.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")


def _kuwahara(a: np.ndarray, r: int) -> np.ndarray:
    """4 つの区画のうち色のばらつきが最も小さい区画の平均を取る。筆で塗ったように平らになり、輪郭は残る"""
    h, w, _ = a.shape
    g = _gray(a)
    pad = r
    ap = np.pad(a, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    gp = np.pad(g, pad, mode="edge")
    # 積分画像で区画の平均と分散を一度に出す
    def integ(x):
        return np.pad(x, ((1, 0), (1, 0)) + ((0, 0),) * (x.ndim - 2)).cumsum(0).cumsum(1)
    ia, ig, ig2 = integ(ap), integ(gp), integ(gp * gp)

    def box(i, y0, x0):
        y1, x1 = y0 + r + 1, x0 + r + 1
        return i[y1:y1 + h, x1:x1 + w] - i[y0:y0 + h, x1:x1 + w] - i[y1:y1 + h, x0:x0 + w] + i[y0:y0 + h, x0:x0 + w]
    n = (r + 1) ** 2
    best_v = np.full((h, w), np.inf, dtype=np.float32)
    out = np.zeros_like(a)
    for y0, x0 in ((0, 0), (0, r), (r, 0), (r, r)):
        m = box(ig, y0, x0) / n
        v = box(ig2, y0, x0) / n - m * m
        c = box(ia, y0, x0) / n
        pick = v < best_v
        best_v = np.where(pick, v, best_v)
        out[pick] = c[pick]
    return out


# --- 画風 ---------------------------------------------------------------

def mono(im):
    """モノクロ。明暗の幅を少し広げ、色を抜いても形が沈まないようにする"""
    return ImageOps.autocontrast(im.convert("L"), cutoff=1).convert("RGB")


def sepia(im):
    """セピア。明るさを茶色の濃淡に置き換え、古い写真の色にする"""
    g = _gray(_arr(ImageOps.autocontrast(im.convert("RGB"), cutoff=1)))
    tone = np.stack([g * 1.07 + 0.08, g * 0.87 + 0.06, g * 0.62 + 0.03], -1)
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1 - 0.35 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    return _img(tone * vig[..., None])


def sketch(im):
    """鉛筆のデッサン。明るさの反転を覆い焼きで重ね、輪郭と陰だけを鉛筆の濃さで残す"""
    g = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    inv = 1 - g
    b = np.asarray(Image.fromarray((inv * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)), dtype=np.float32) / 255.0
    dodge = np.clip(g / (1 - b + 1e-3), 0, 1)
    h, w = g.shape
    rng = np.random.default_rng(SEED)
    # 斜めの鉛筆の目を陰の所にだけ入れる
    hatch = _streaks(h, w, 35)
    shade = np.clip((0.55 - g) * 1.6, 0, 1)
    out = dodge ** 1.6 * (1 - 0.25 * shade * hatch)
    return _img(np.repeat(out[..., None], 3, -1) * _paper(h, w, (1.0, 0.99, 0.96)))


def _blur(a: np.ndarray, r: float) -> np.ndarray:
    """2 次元のガウスぼかし（縦と横に分けて掛ける）。Pillow の 8 ビットぼかしでは細い差が丸められて線が途切れた"""
    n = max(1, int(r * 3))
    x = np.arange(-n, n + 1, dtype=np.float32)
    k = np.exp(-x * x / (2 * r * r))
    k /= k.sum()
    b = np.pad(a, n, mode="edge")
    b = sum(k[i] * b[:, i:i + a.shape[1]] for i in range(2 * n + 1))
    return sum(k[i] * b[i:i + a.shape[0], :] for i in range(2 * n + 1))


def _box(a: np.ndarray, r: int) -> np.ndarray:
    c = np.pad(a, ((r + 1, r), (r + 1, r))).cumsum(0).cumsum(1)
    h, w = a.shape
    s = 2 * r + 1
    return c[s:s + h, s:s + w] - c[:h, s:s + w] - c[s:s + h, :w] + c[:h, :w]


def _drop_specks(line: np.ndarray, r: int, min_px: int) -> np.ndarray:
    """小さな点（毛並みや紙のざらつきが線に化けたもの）を消す。
    近くの線の量が少ない画素は、つながった線ではなく点とみなす"""
    on = (line > 0.5).astype(np.float32)
    return line * (_box(on, r) >= min_px)


def xdog(im, sigma: float = 0.8, k: float = 1.6, p: float = 22.0, eps: float = -0.02, phi: float = 60.0) -> np.ndarray:
    """XDoG（ぼかしの差を鋭く引き伸ばす）で線の濃さ 0〜1 を出す。
    勾配で取る輪郭は太さが揃わず二重線になったが、XDoG は 1 本の筆の線に近くなった"""
    g = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    # 平らな所の小さなざらつきを先に消し、毛並みが全部線になるのを防ぐ
    g = _blur(g, 0.6)
    d = (1 + p) * _blur(g, sigma) - p * _blur(g, sigma * k)
    v = np.where(d >= eps, 1.0, 1.0 + np.tanh(phi * (d - eps)))
    return np.clip(1 - v, 0, 1)


def _line(im) -> np.ndarray:
    """塗りの上に重ねる主線。線画と同じ XDoG を使い、画風ごとの主線の質をそろえる"""
    s = max(1, min(im.size) // 300)
    return _drop_specks(xdog(im, sigma=0.7 * s), 3 * s, 7 * s)


def lineart(im):
    """線画。XDoG で線を取り、小さな点を消して、白地に黒の線だけを残す。塗りや下地に使える"""
    s = max(1, min(im.size) // 300)
    line = xdog(im, sigma=0.7 * s)
    line = _drop_specks(line, 3 * s, 7 * s)
    return _img(np.repeat((1 - line)[..., None], 3, -1))


def ink(im):
    """水墨画。墨の濃淡 4 段と、にじんだ輪郭。白い所は和紙の地を残す"""
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0
    g = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.5)), dtype=np.float32) / 255.0
    wash = np.round(g * 4) / 4
    wash = np.asarray(Image.fromarray((wash * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), dtype=np.float32) / 255.0
    e = _edges(im, 2.0)
    stroke = np.clip((e - 0.15) * 2.5, 0, 1)
    stroke = np.asarray(Image.fromarray((stroke * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255.0
    v = np.clip(0.25 + wash * 0.8, 0, 1) * (1 - 0.85 * stroke)
    h, w = v.shape
    return _img(v[..., None] * _paper(h, w, (0.96, 0.93, 0.86), 0.04))


def _subject(im) -> np.ndarray:
    """被写体の形 0/1。四辺の色を背景とみなし、背景から色が離れた所を被写体にする。
    描いた動物は無地に近い背景の上にいるので、模型なしでも形が取れる"""
    a = _arr(im.filter(ImageFilter.GaussianBlur(2)))
    h, w, _ = a.shape
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(edge, 0)
    d = np.sqrt(((a - bg) ** 2).sum(-1))
    m = (d > max(0.12, np.percentile(np.sqrt(((edge - bg) ** 2).sum(-1)), 95) * 1.5)).astype(np.uint8) * 255
    # 白い体が白い地にいると色の差では取れない。線（XDoG）も壁にして、四隅から背景を塗りつぶし、
    # 塗られなかった所を被写体とする
    s = max(1, min(h, w) // 300)
    wall = np.maximum(m, (_drop_specks(xdog(im, sigma=0.7 * s), 3 * s, 7 * s) > 0.5) * 255).astype(np.uint8)
    img = Image.fromarray(wall).filter(ImageFilter.MaxFilter(7))
    from PIL import ImageDraw
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if img.getpixel(xy) == 0:
            ImageDraw.floodfill(img, xy, 128)
    m = np.where(np.asarray(img) == 128, 0, 255).astype(np.uint8)
    img = Image.fromarray(m)
    for f in (ImageFilter.MinFilter(5), ImageFilter.ModeFilter(9)):
        img = img.filter(f)
    return np.asarray(img, dtype=np.float32) / 255.0


def kirie(im):
    """切り絵。被写体を黒い紙で切り抜き、明るい所と線の間を窓にして裏の色紙を透かす。
    色を減らすだけの切り絵は背景の明暗まで紙に切られ、顔の形が崩れた"""
    sub = _subject(im)
    g = _gray(_arr(im.filter(ImageFilter.GaussianBlur(1.5))))
    line = _line(im)
    line = np.asarray(_img(np.repeat(line[..., None], 3, -1)).convert("L").filter(ImageFilter.MaxFilter(3)), dtype=np.float32) / 255.0
    # 明るい所を窓にする。窓の境は線で残し、紙が一続きにつながるようにする
    window = (g > np.percentile(g[sub > 0.5], 55) if (sub > 0.5).any() else g > 0.6) & (line < 0.5)
    win = np.asarray(Image.fromarray(window.astype(np.uint8) * 255).filter(ImageFilter.ModeFilter(5)), dtype=np.float32) / 255.0
    # 被写体の外周は必ず紙で縁取る。白い体が白い地に溶けて形が消えるのを防ぐ
    rim = np.asarray(Image.fromarray((sub * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(7)), dtype=np.float32) / 255.0
    win = win * rim
    paper = sub * (1 - win)
    back = np.array([0.80, 0.12, 0.14], dtype=np.float32)
    h, w = g.shape
    ground = _paper(h, w, (0.96, 0.93, 0.86), 0.02)
    out = ground * (1 - sub[..., None]) + back * (sub * win)[..., None] + 0.06 * paper[..., None]
    return _img(out)


def _cells(h: int, w: int, size: int):
    """格子を揺らした点を種に、各画素を一番近い種へ振り分ける（ボロノイ）。ステンドグラスとモザイクで使う"""
    rng = np.random.default_rng(SEED)
    gy, gx = np.mgrid[size // 2:h:size, size // 2:w:size]
    py = (gy + rng.uniform(-size * 0.4, size * 0.4, gy.shape)).ravel()
    px = (gx + rng.uniform(-size * 0.4, size * 0.4, gx.shape)).ravel()
    yy, xx = np.mgrid[0:h, 0:w]
    best = np.full((h, w), np.inf, dtype=np.float32)
    lab = np.zeros((h, w), np.int32)
    for i, (y, x) in enumerate(zip(py, px)):
        y0, y1 = max(0, int(y - size * 1.5)), min(h, int(y + size * 1.5))
        x0, x1 = max(0, int(x - size * 1.5)), min(w, int(x + size * 1.5))
        d = (yy[y0:y1, x0:x1] - y) ** 2 + (xx[y0:y1, x0:x1] - x) ** 2
        sub = best[y0:y1, x0:x1]
        pick = d < sub
        sub[pick] = d[pick]
        lab[y0:y1, x0:x1][pick] = i
    return lab, len(py)


def _cell_mean(a: np.ndarray, lab: np.ndarray, n: int) -> np.ndarray:
    cnt = np.bincount(lab.ravel(), minlength=n).astype(np.float32) + 1e-6
    m = np.stack([np.bincount(lab.ravel(), a[..., c].ravel(), n) / cnt for c in range(3)], -1)
    return m[lab]


def _borders(lab: np.ndarray, width: int) -> np.ndarray:
    b = np.zeros(lab.shape, bool)
    b[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    b[1:, :] |= lab[1:, :] != lab[:-1, :]
    img = Image.fromarray(b.astype(np.uint8) * 255)
    if width > 1:
        img = img.filter(ImageFilter.MaxFilter(width | 1))
    return np.asarray(img, dtype=np.float32) / 255.0


def stainedglass(im):
    """ステンドグラス。被写体は細かい片、背景は大きい片にし、片ごとに色を平らにして鉛の枠で区切る。
    片の大きさを揃えると、被写体の片が粗くて輪郭が消えるか、背景が枠だらけになった"""
    a = _arr(im)
    h, w, _ = a.shape
    sub = _subject(im) > 0.5
    small, ns = _cells(h, w, max(8, min(h, w) // 48))
    big, nb = _cells(h, w, max(16, min(h, w) // 14))
    lab = np.where(sub, small, big + ns)
    m = _cell_mean(a, lab, ns + nb)
    g = _gray(m)[..., None]
    m = np.clip(g + (m - g) * 1.6, 0, 1) * 1.08
    lead = np.maximum(_borders(lab, 3), _line(im))
    return _img(m * (1 - lead[..., None]) + 0.08 * lead[..., None])


def mosaic(im):
    """モザイク（タイル）。小さな石を目地で区切る"""
    a = _arr(im)
    h, w, _ = a.shape
    lab, n = _cells(h, w, max(6, min(h, w) // 70))
    m = _cell_mean(a, lab, n)
    joint = _borders(lab, 1)
    return _img(m * (1 - joint[..., None] * 0.6) + joint[..., None] * 0.45)


def _strokes(im, length: int, width: int, density: float, jitter: float):
    """短い筆の跡を、元の絵の色で、明暗の流れに沿う向きで重ねる。印象派と点描で使う"""
    from PIL import ImageDraw
    a = _arr(im)
    h, w, _ = a.shape
    g = _gray(a)
    gy, gx = np.gradient(np.asarray(Image.fromarray((g * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(4)), dtype=np.float32))
    ang = np.arctan2(gy, gx) + np.pi / 2  # 明暗の境に沿う向き
    base = im.convert("RGB").filter(ImageFilter.GaussianBlur(4))
    canvas = base.copy()
    d = ImageDraw.Draw(canvas)
    rng = np.random.default_rng(SEED)
    n = int(h * w * density / (length * width))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    # 背景に細かい筆を散らすと色の粒に見えた。背景では筆の色の揺れを小さくする
    sub = _subject(im) > 0.5
    for y, x in zip(ys, xs):
        jitter_here = jitter if sub[y, x] else jitter * 0.3
        # 明るさを主にずらし、色相のずれは小さく抑える（白地に虹色の粒が散るのを避ける）
        c = a[y, x] * (1 + rng.uniform(-jitter_here, jitter_here)) + rng.uniform(-jitter_here, jitter_here, 3) * 0.25
        col = tuple(int(v) for v in np.clip(c * 255, 0, 255))
        t = ang[y, x] + rng.uniform(-0.3, 0.3)
        dx, dy = np.cos(t) * length / 2, np.sin(t) * length / 2
        d.line([(x - dx, y - dy), (x + dx, y + dy)], fill=col, width=width)
    return canvas


def impressionist(im):
    """印象派。短い筆の跡を色をずらしながら重ね、輪郭を溶かす"""
    s = max(1, min(im.size) // 256)
    # 筆を大きくすると顔が筆の跡に埋もれる。目鼻が残る長さまで短くする
    return _strokes(im, 10 * s, 3 * s, 2.0, 0.12)


def pointillism(im):
    """点描。点を細かく打ち、色を少しずつ変えて目で混ぜる"""
    from PIL import ImageDraw
    a = _arr(im)
    h, w, _ = a.shape
    r = max(2, min(h, w) // 160)
    canvas = Image.new("RGB", (w, h), (246, 242, 232))
    d = ImageDraw.Draw(canvas)
    rng = np.random.default_rng(SEED)
    n = int(h * w / (r * r) * 0.9)
    sub = _subject(im) > 0.5
    for y, x in zip(rng.integers(0, h, n), rng.integers(0, w, n)):
        j = 0.2 if sub[y, x] else 0.05
        c = np.clip((a[y, x] * (1 + rng.uniform(-j, j)) + rng.uniform(-j / 4, j / 4, 3)) * 255, 0, 255).astype(int)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(int(v) for v in c))
    return canvas


def oil(im):
    """油彩。桑原フィルターで筆で塗った平らな面を作り、明るい所に絵の具の盛りを付ける"""
    a = _arr(im)
    r = max(3, min(a.shape[:2]) // 90)
    k = _kuwahara(a, r)
    g = _gray(k)
    emb = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).filter(ImageFilter.EMBOSS), dtype=np.float32) / 255.0 - 0.5
    return _img(k + emb[..., None] * 0.18)


def watercolor(im):
    """水彩。色をにじませて薄め、色の溜まる縁を濃くし、紙の白を透かす"""
    a = _arr(im)
    k = _kuwahara(a, max(2, min(a.shape[:2]) // 140))
    blur = np.asarray(_img(k).filter(ImageFilter.GaussianBlur(2)), dtype=np.float32) / 255.0
    light = 1 - (1 - blur) * 0.75
    e = _edges(_img(k), 1.5)
    pool = np.clip((e - 0.1) * 1.2, 0, 1)
    out = light * (1 - 0.25 * pool[..., None])
    h, w, _ = a.shape
    return _img(out * _paper(h, w, (1.0, 0.99, 0.96), 0.05))


def anime(im):
    """アニメ塗り。明暗を 3 段の影に分け、色数を減らし、主線を入れる"""
    a = _arr(im)
    k = _kuwahara(a, max(2, min(a.shape[:2]) // 150))
    q = _arr(_quantize(_img(k), 12))
    g = _gray(k)[..., None]
    cel = np.where(g > 0.62, 1.06, np.where(g > 0.35, 0.92, 0.72))
    q = np.clip(q * cel, 0, 1)
    gq = _gray(q)[..., None]
    q = np.clip(gq + (q - gq) * 1.25, 0, 1)
    line = _line(im)
    return _img(q * (1 - 0.85 * line[..., None]))


def manga(im):
    """漫画（少年漫画の型）。主線・ベタ・トーンの組み方は manga.py に 1 か所だけ置き、ここはそれを呼ぶ"""
    import manga as _manga
    return _manga.shonen(im)


def ukiyoe(im):
    """浮世絵（木版）。色を版の数（7 色）に減らし、色を少し褪せさせ、墨の輪郭線と和紙を足す"""
    q = _arr(_quantize(im.filter(ImageFilter.ModeFilter(5)), 7))
    g = _gray(q)[..., None]
    q = g + (q - g) * 0.8
    q = q * np.array([1.0, 0.96, 0.86], dtype=np.float32) + 0.03
    line = _line(im)
    h, w, _ = q.shape
    return _img(q * (1 - 0.8 * line[..., None]) * _paper(h, w, (0.98, 0.94, 0.85), 0.04))


def popart(im):
    """ポップアート。4 色に塗り分け、網点を重ねる"""
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0
    pal = np.array([[0.1, 0.1, 0.35], [0.9, 0.15, 0.3], [1.0, 0.8, 0.1], [0.98, 0.95, 0.88]], dtype=np.float32)
    idx = np.clip((g * 4).astype(int), 0, 3)
    out = pal[idx]
    line = _line(im)
    return _img(out * (1 - line[..., None]))


def pixel(im):
    """ドット絵。縦 96 ドットに縮め、24 色に減らして、拡大で戻す"""
    w, h = im.size
    th = 96
    tw = max(1, round(w * th / h))
    small = _quantize(im.convert("RGB").resize((tw, th), Image.LANCZOS), 24)
    return small.resize((w, h), Image.NEAREST)


def blueprint(im):
    """青写真。輪郭を白い線で、紺の地に"""
    line = _line(im)[..., None]
    bg = np.array([0.08, 0.2, 0.45], dtype=np.float32)
    return _img(bg * (1 - line) + np.array([0.9, 0.95, 1.0]) * line)


def charcoal(im):
    """木炭。荒い黒の面と、こすったぼかし"""
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=3), dtype=np.float32) / 255.0
    h, w = g.shape
    rng = np.random.default_rng(SEED)
    grain = np.asarray(Image.fromarray((rng.random((h, w)) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0)), dtype=np.float32) / 255.0
    smudge = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), dtype=np.float32) / 255.0
    v = np.clip(smudge ** 1.3 + (grain - 0.5) * 0.35 * (1 - smudge), 0, 1)
    line = _line(im)
    v = v * (1 - 0.7 * line)
    return _img(v[..., None] * _paper(h, w, (0.97, 0.96, 0.93)))


def engraving(im):
    """銅版画。暗さに応じて細い平行線の密度と太さを変え、主線を重ねる"""
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0
    g = _blur(g, 1.0)
    h, w = g.shape
    p = max(4, min(h, w) // 110)
    yy, xx = np.mgrid[0:h, 0:w]
    wave = np.abs(((yy + 0.6 * xx + 3 * np.sin(xx / 40.0)) % p) / p - 0.5) * 2  # 0 が線の芯
    hatch = (wave < (1 - g) * 0.9).astype(np.float32)
    cross = (np.abs(((yy - 0.6 * xx) % p) / p - 0.5) * 2 < (0.45 - g) * 1.2).astype(np.float32)
    ink = np.maximum(np.maximum(hatch, cross), _line(im))
    return _img(np.repeat((1 - ink)[..., None], 3, -1) * _paper(h, w, (0.97, 0.95, 0.9), 0.02))


def colorpencil(im):
    """色鉛筆。紙の白を残し、斜めの細かい筆の目で色を乗せる"""
    a = _arr(im)
    h, w, _ = a.shape
    rng = np.random.default_rng(SEED)
    grain = _streaks(h, w, 30, 0.5)
    cover = np.clip((1 - _gray(a)) * 1.3 + 0.15, 0, 1)
    take = (grain < cover).astype(np.float32)[..., None] * 0.85 + 0.15
    paper = _paper(h, w, (0.99, 0.98, 0.95))
    out = paper * (1 - take) + a * take
    return _img(out * (1 - 0.6 * _line(im)[..., None]))


def neon(im):
    """ネオン。黒地に、元の色で光る線"""
    line = _line(im)
    a = _arr(im)
    g = _gray(a)[..., None]
    col = np.clip(g + (a - g) * 2.2 + 0.25, 0, 1)
    glow = _blur(line, 4.0)[..., None]
    core = line[..., None]
    return _img(col * np.clip(glow * 2.2, 0, 1) * 0.8 + core * 0.9)


def silhouette(im):
    """影絵。被写体を黒一色にし、夕焼けの色の地に置く"""
    sub = _subject(im)
    h, w = sub.shape
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    sky = np.array([0.98, 0.78, 0.35]) * (1 - t) + np.array([0.85, 0.3, 0.25]) * t
    return _img(np.broadcast_to(sky, (h, w, 3)) * (1 - sub[..., None]) + 0.04 * sub[..., None])


def pastel(im):
    """パステル。色を淡くし、粉のざらつきと擦れを入れる"""
    a = _arr(im)
    k = _kuwahara(a, max(2, min(a.shape[:2]) // 120))
    soft = 1 - (1 - k) * 0.6
    g = _gray(soft)[..., None]
    soft = g + (soft - g) * 0.8
    h, w, _ = a.shape
    rng = np.random.default_rng(SEED)
    dust = np.asarray(Image.fromarray((rng.random((h, w)) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32)[..., None] / 255.0
    return _img(soft * (0.92 + 0.12 * dust) * _paper(h, w, (0.99, 0.97, 0.93)))


def linocut(im):
    """版画（リノカット）。白と黒の 2 値に彫り、彫り跡の筋を少し残す"""
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0
    g = _blur(g, 1.5)
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    gouge = 0.08 * np.sin((xx * 0.3 + yy * 0.9) / max(2, min(h, w) // 200))
    ink = ((g + gouge) < 0.5).astype(np.float32)
    ink = np.maximum(ink, _line(im))
    ink = np.asarray(Image.fromarray((ink * 255).astype(np.uint8)).filter(ImageFilter.ModeFilter(3)), dtype=np.float32) / 255.0
    return _img(np.repeat((1 - ink)[..., None], 3, -1) * _paper(h, w, (0.97, 0.94, 0.87), 0.02))


STYLES = {
    "mono": mono, "sepia": sepia, "sketch": sketch, "charcoal": charcoal, "lineart": lineart, "ink": ink,
    "kirie": kirie, "stainedglass": stainedglass, "mosaic": mosaic, "impressionist": impressionist,
    "pointillism": pointillism, "oil": oil, "watercolor": watercolor, "anime": anime, "manga": manga,
    "ukiyoe": ukiyoe, "popart": popart, "pixel": pixel, "blueprint": blueprint,
    "engraving": engraving, "colorpencil": colorpencil, "neon": neon, "silhouette": silhouette,
    "pastel": pastel, "linocut": linocut,
}


def apply(src: str, outdir: str, names: list[str] | None = None) -> list[str]:
    im = Image.open(src).convert("RGB")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in names or list(STYLES):
        p = out / f"{Path(src).stem}-{n}.png"
        STYLES[n](im).save(p)
        paths.append(str(p))
    return paths


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print("\n".join(STYLES))
        return
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    for p in apply(sys.argv[1], sys.argv[2], sys.argv[3:] or None):
        print(p)


if __name__ == "__main__":
    main()
