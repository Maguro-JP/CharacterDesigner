"""画材や印刷の見た目を足す加工（stylize.py の続き）。形は元の絵のまま、塗りと線の質だけを変える。

stylize.py の加工と同じく模型を使わない。1 ファイルを大きくしないため、新しく足した画材はここに置く。

  python3 tools/gen/paint.py 元.png 出力ディレクトリ [加工 ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

import tones
from stylize import (SEED, _arr, _blur, _borders, _box, _cell_mean, _cells, _gray, _img, _kuwahara, _line,
                     _paper, _quantize, _streaks, _strokes, _subject)


def _sat(a, k):
    g = _gray(a)[..., None]
    return np.clip(g + (a - g) * k, 0, 1)


def softpastel(im):
    """ソフトパステル。チョークの粉を紙目に擦り込む。紙の凹みに粉が乗らず白く残る"""
    a = _arr(im)
    h, w, _ = a.shape
    k = _kuwahara(a, max(2, min(h, w) // 100))
    soft = _sat(1 - (1 - k) * 0.7, 0.85)
    rng = np.random.default_rng(SEED)
    tooth = _blur(rng.random((h, w)).astype(np.float32), 1.0)
    tooth = (tooth - tooth.min()) / (np.ptp(tooth) + 1e-6)
    # 濃い所ほど粉が多く凹みまで埋まる
    cover = np.clip((1 - _gray(soft)) * 1.4 + tooth - 0.35, 0, 1)[..., None]
    smear = _streaks(h, w, 30, 0.4, 1.5)[..., None]
    out = soft * cover + _paper(h, w, (0.98, 0.96, 0.92)) * (1 - cover)
    return _img(out * (0.96 + 0.06 * smear))


def yumekawa(im):
    """ゆめかわ。色を淡いピンク・水色・薄紫に寄せ、明るく霞ませる"""
    a = _arr(im)
    g = _gray(a)
    pal = np.array([[0.72, 0.62, 0.92], [0.98, 0.72, 0.86], [0.70, 0.88, 0.98], [1.0, 0.97, 1.0]], np.float32)
    t = np.clip(g, 0, 0.999) * (len(pal) - 1)
    i = t.astype(int)
    f = (t - i)[..., None]
    mapped = pal[i] * (1 - f) + pal[np.minimum(i + 1, len(pal) - 1)] * f
    out = mapped * 0.75 + (1 - (1 - a) * 0.4) * 0.25
    return _img(out * (1 - 0.35 * _line(im)[..., None] * np.array([0.2, 0.5, 0.1])))


def ballpoint(im):
    """ボールペン画。細い青黒の線を重ねて陰を作る（ハッチング）。線は暗さの段で 1〜3 方向"""
    g = _blur(np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0, 1.0)
    h, w = g.shape
    ink = np.zeros((h, w), np.float32)
    for deg, lo in ((30, 0.75), (-30, 0.5), (80, 0.28)):
        ink = np.maximum(ink, tones._lines(np.full((h, w), 0.18, np.float32), h, w, 160, deg) * (g < lo))
    ink = np.maximum(ink, _line(im))
    pen = np.array([0.12, 0.14, 0.35], np.float32)
    return _img(_paper(h, w) * (1 - ink[..., None]) + pen * ink[..., None])


def marker(im):
    """マーカー（コピック）。平らに塗った面の縁に色が溜まり、塗り重ねた筋が残る"""
    a = _arr(im)
    h, w, _ = a.shape
    q = _arr(_quantize(Image.fromarray((_kuwahara(a, max(2, min(h, w) // 90)) * 255).astype(np.uint8)), 14))
    edge = _borders((q * 255).astype(np.int32) @ np.array([65536, 256, 1]), max(3, min(h, w) // 150))
    st = _streaks(h, w, 0, 0.5, 0.8)[..., None]
    out = q * (1 - 0.18 * edge[..., None]) * (0.95 + 0.07 * st)
    out = _sat(out, 1.2)
    return _img(out * (1 - 0.9 * _line(im)[..., None]))


def cel_noline(im):
    """線なしのセル塗り。アニメ塗りから主線を抜き、影の境目だけで形を見せる（背景美術の塗り）"""
    a = _arr(im)
    q = _arr(_quantize(Image.fromarray((_kuwahara(a, 3) * 255).astype(np.uint8)), 16))
    g = _gray(q)
    cel = np.where(g > 0.62, 1.05, np.where(g > 0.35, 0.92, 0.74))[..., None]
    return _img(_sat(q * cel, 1.2))


def woodcut(im):
    """木版（白黒）。墨の面と、形に沿った彫り跡の線。明るい所ほど彫り跡が太い"""
    g = _blur(np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0, 2.0)
    h, w = g.shape
    gy, gx = np.gradient(_blur(g, 6))
    phase = (np.mgrid[0:h, 0:w][0] * 0.8 + np.mgrid[0:h, 0:w][1] * 0.3) / max(3, min(h, w) / 120)
    phase += 25 * _blur(g, 8)  # 明暗に沿って彫り跡がうねる
    cut = (np.sin(phase) * 0.5 + 0.5) < (g - 0.1) * 1.6
    # 背景まで彫ると全面が縞になった。彫るのは被写体の中だけにし、背景は紙を残す
    ink = (~cut) & (_subject(im) > 0.5)
    ink = np.maximum(ink.astype(np.float32), _line(im))
    return _img(np.repeat((1 - ink)[..., None], 3, -1) * _paper(h, w, (0.96, 0.93, 0.85)))


def crossstitch(im):
    """クロスステッチ。升目ごとに 1 色の × の糸を縫い、布目を見せる"""
    a = _arr(im)
    h, w, _ = a.shape
    c = max(5, min(h, w) // 90)
    small = _quantize(im.resize((w // c, h // c), Image.BILINEAR), 20)
    canvas = Image.new("RGB", (w, h), (238, 232, 218))
    d = ImageDraw.Draw(canvas)
    sa = np.asarray(small)
    bg = np.median(np.concatenate([sa[0], sa[-1], sa[:, 0], sa[:, -1]]), 0)
    for y in range(sa.shape[0]):
        for x in range(sa.shape[1]):
            col = tuple(int(v) for v in sa[y, x])
            if np.abs(sa[y, x].astype(float) - bg).sum() < 30:
                continue  # 地の色は縫わず布を残す
            x0, y0 = x * c, y * c
            # 糸を細くすると布の色が勝って絵が霞んだ。升目の半分の太さで縫う
            t = max(2, c // 2)
            d.line([(x0 + 1, y0 + 1), (x0 + c - 2, y0 + c - 2)], fill=col, width=t)
            d.line([(x0 + c - 2, y0 + 1), (x0 + 1, y0 + c - 2)], fill=col, width=t)
    weave = (np.add.outer(np.arange(h) % c == 0, np.arange(w) % c == 0)).astype(np.float32)[..., None]
    return _img(_arr(canvas) * (1 - 0.06 * weave))


def lowpoly(im):
    """ローポリ。小さな三角に分け、三角ごとに 1 色で塗る。被写体は細かく、背景は粗く"""
    a = _arr(im)
    h, w, _ = a.shape
    sub = _subject(im) > 0.5
    s1, s2 = max(10, min(h, w) // 40), max(20, min(h, w) // 12)
    lab1, n1 = _cells(h, w, s1)
    lab2, n2 = _cells(h, w, s2)
    # ボロノイの片を対角で 2 つに割り、三角の面に見せる
    yy, xx = np.mgrid[0:h, 0:w]
    lab = np.where(sub, lab1 * 2 + ((xx // s1 + yy // s1) % 2), (lab2 + n1) * 2 + ((xx // s2 - yy // s2) % 2))
    m = _cell_mean(a, lab, (n1 + n2) * 2 + 2)
    shade = 0.92 + 0.16 * ((lab * 2654435761) % 97 / 97.0)[..., None]
    return _img(m * shade)


def neontube(im):
    """ネオン管。線画だけを、元の色を明るくした管の光で黒地に光らせる"""
    a = _arr(im)
    line = _line(im)
    h, w = line.shape
    col = np.clip(_sat(a, 2.0) * 1.4 + 0.15, 0, 1)
    core = line[..., None] * (0.6 * col + 0.4)
    r = max(2, min(h, w) / 120)
    glow = np.stack([_blur(line * col[..., c], r) for c in range(3)], -1) * 2.2
    glow2 = np.stack([_blur(line * col[..., c], r * 4) for c in range(3)], -1) * 1.5
    return _img(np.array([0.02, 0.02, 0.05]) + core + glow + glow2)


def chiyogami(im):
    """千代紙の切り絵。被写体を色紙で切り抜き、地に和柄（青海波）を敷く"""
    a = _arr(im)
    h, w, _ = a.shape
    sub = _subject(im)[..., None]
    q = _sat(_arr(_quantize(im.filter(ImageFilter.ModeFilter(7)), 6)), 1.3)
    p = max(10, min(h, w) // 18)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    row = (yy // (p / 2)).astype(int)
    cx = xx + (row % 2) * p / 2
    r = np.hypot((cx % p) - p / 2, (yy % (p / 2)) - p / 2)
    wave = ((r // (p / 8)) % 2).astype(np.float32)[..., None]
    paper = np.array([0.80, 0.22, 0.25]) * (1 - wave) + np.array([0.98, 0.92, 0.80]) * wave
    line = _line(im)[..., None]
    return _img((q * sub + paper * (1 - sub)) * (1 - 0.9 * line))


def marbling(im):
    """墨流し（マーブル）。背景を墨の流れ模様にし、被写体は元のまま"""
    a = _arr(im)
    h, w, _ = a.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rng = np.random.default_rng(SEED)
    f = rng.random(4) * 3 + 2
    v = np.sin(xx / w * f[0] * 6 + 3 * np.sin(yy / h * f[1] * 4) + 2 * np.sin((xx + yy) / w * f[2] * 3))
    band = (np.sin(v * 6) * 0.5 + 0.5)[..., None]
    bg = np.array([0.95, 0.94, 0.90]) * (1 - band) + np.array([0.18, 0.22, 0.38]) * band
    sub = _subject(im)[..., None]
    return _img(a * sub + bg * (1 - sub))


def postimpressionist(im):
    """後期印象派。太く長い筆を、明暗に沿った渦を巻く向きで重ね、色を強くする"""
    s = max(1, min(im.size) // 256)
    base = _strokes(im, 18 * s, 4 * s, 2.4, 0.2)
    return _img(_sat(_arr(base), 1.35))


def pointillism_fine(im):
    """点描（細かい点）。点を小さく密にし、純色に近い点を並べて目で混ぜる"""
    from stylize import pointillism
    a = _arr(im)
    h, w, _ = a.shape
    out = _arr(pointillism(im.resize((w * 2, h * 2))).resize((w, h), Image.LANCZOS))
    return _img(_sat(out, 1.3))


def newspaper(im):
    """新聞の網点（白黒）。粗い網点 1 版で刷り、紙を黄ばませる"""
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32) / 255.0
    h, w = g.shape
    ink = tones.render("dot_coarse", 1 - g, h, w)
    return _img(np.repeat((1 - 0.9 * ink)[..., None], 3, -1) * _paper(h, w, (0.93, 0.90, 0.80), 0.02))


def gouache(im):
    """ガッシュ（不透明水彩）。平らで不透明な面、柔らかい縁、少しの紙目"""
    a = _arr(im)
    h, w, _ = a.shape
    k = _kuwahara(a, max(3, min(h, w) // 80))
    q = _arr(_quantize(Image.fromarray((k * 255).astype(np.uint8)), 20))
    q = np.stack([_blur(q[..., c], 0.8) for c in range(3)], -1)
    return _img(_sat(q, 1.1) * _paper(h, w, (1.0, 0.98, 0.95), 0.025))


def risograph(im):
    """リソグラフ。2 色（蛍光ピンクと青）の版を網点で重ね、版を少しずらす"""
    a = _arr(im)
    h, w, _ = a.shape
    g = _gray(a)
    warm = np.clip(a[..., 0] - a[..., 2] * 0.5 + (1 - g) * 0.4, 0, 1)
    cool = np.clip(1 - g - warm * 0.3, 0, 1)
    pk = tones.render("dot_fine", warm * 0.9, h, w)
    bl = np.roll(tones.render("dot_fine", cool * 0.85, h, w), max(1, w // 300), 1)
    pink = np.array([1.0, 0.28, 0.55])
    blue = np.array([0.1, 0.35, 0.85])
    out = np.ones((h, w, 3)) * np.array([0.98, 0.96, 0.92])
    out = out * (1 - pk[..., None] * (1 - pink)) * (1 - bl[..., None] * (1 - blue))
    return _img(out)


STYLES = {
    "softpastel": softpastel, "yumekawa": yumekawa, "ballpoint": ballpoint, "marker": marker,
    "cel_noline": cel_noline, "woodcut": woodcut, "crossstitch": crossstitch, "lowpoly": lowpoly,
    "neontube": neontube, "chiyogami": chiyogami, "marbling": marbling, "postimpressionist": postimpressionist,
    "pointillism_fine": pointillism_fine, "newspaper": newspaper, "gouache": gouache, "risograph": risograph,
}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    im = Image.open(sys.argv[1]).convert("RGB")
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for n in sys.argv[3:] or list(STYLES):
        p = out / f"{Path(sys.argv[1]).stem}-{n}.png"
        STYLES[n](im).save(p)
        print(p)
