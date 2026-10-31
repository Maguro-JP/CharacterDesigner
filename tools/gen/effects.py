"""特殊な加工（エフェクト）。画風ではなく、どの絵にも後から重ねる演出。

集中線・魚眼のような効果は、画像生成の言葉に入れると絵そのものが崩れ（体が渦に巻かれる、線が体を横切る）、
効き方も毎回変わる。形を描いたあとに加工として掛ければ、元の形を壊さずに同じ効き方で何度でも掛けられる。
そのため、ここにある効果は画風（animal_cycle.py の言葉）には入れず、加工だけで使う。

  python3 tools/gen/effects.py 元.png 出力ディレクトリ [効果 ...]   効果を省くと全部
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from stylize import _arr, _blur, _gray, _img, _subject

SEED = 5


def _sample(a: np.ndarray, yy: np.ndarray, xx: np.ndarray) -> np.ndarray:
    """座標 (yy, xx) の色を双線形で拾う。外に出た所は端の色"""
    h, w = a.shape[:2]
    yy = np.clip(yy, 0, h - 1.001)
    xx = np.clip(xx, 0, w - 1.001)
    y0 = yy.astype(int)
    x0 = xx.astype(int)
    fy = (yy - y0)[..., None]
    fx = (xx - x0)[..., None]
    return (a[y0, x0] * (1 - fy) * (1 - fx) + a[y0 + 1, x0] * fy * (1 - fx)
            + a[y0, x0 + 1] * (1 - fy) * fx + a[y0 + 1, x0 + 1] * fy * fx)


def _center(im):
    """効果の中心。被写体の重心（取れなければ絵の中心）"""
    m = _subject(im)
    if m.sum() < 0.01 * m.size:
        return m.shape[0] / 2, m.shape[1] / 2
    ys, xs = np.nonzero(m > 0.5)
    return float(ys.mean()), float(xs.mean())


def focus_lines(im):
    """集中線。中心へ向かう黒い楔の線を外側に引き、中心の被写体の周りは空ける"""
    a = _arr(im)
    h, w = a.shape[:2]
    cy, cx = _center(im)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = np.arctan2(yy - cy, xx - cx)
    r = np.hypot(yy - cy, xx - cx) / np.hypot(h, w)
    rng = np.random.default_rng(SEED)
    n = 360
    k = ((ang + np.pi) / (2 * np.pi) * n).astype(int) % n
    start = 0.18 + 0.12 * rng.random(n)              # 線ごとに始まる半径をばらす
    width = 0.25 + 0.5 * rng.random(n)               # 線ごとの太さ（角度の割合）
    frac = ((ang + np.pi) / (2 * np.pi) * n) % 1
    grow = np.clip((r - start[k]) / 0.25, 0, 1)      # 外へ行くほど太る楔
    ink = (np.abs(frac - 0.5) < width[k] * grow * 0.5).astype(np.float32)
    ink *= (_subject(im) < 0.5)
    return _img(a * (1 - ink[..., None]))


def speed_lines(im):
    """流線（スピード線）。横向きの細い線を背景に流し、被写体には掛けない"""
    a = _arr(im)
    h, w = a.shape[:2]
    rng = np.random.default_rng(SEED)
    rows = rng.random(h) < 0.18
    length = rng.random(h)
    xx = np.arange(w)[None, :] / w
    ink = (rows[:, None] & (np.abs(xx - rng.random(h)[:, None]) < 0.15 + 0.35 * length[:, None])).astype(np.float32)
    ink = _blur(ink, 0.6) > 0.3
    ink = ink & (_subject(im) < 0.5)
    return _img(a * (1 - 0.9 * ink[..., None]))


def fisheye(im):
    """魚眼。中心を膨らませ、縁を丸く縮める（円の外は黒）"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ny, nx = (yy - h / 2) / (h / 2), (xx - w / 2) / (w / 2)
    r = np.hypot(ny, nx)
    # 等距離射影: 見える角度が半径に比例する。r を元の像の tan に戻す
    # 半分の画角を 55 度にした。80 度では中心が 6 倍に拡がり、被写体の一部しか写らなかった
    half = np.deg2rad(55)
    theta = r * half
    src = np.where(r > 0, np.tan(np.minimum(theta, np.deg2rad(85))) / np.tan(half) / np.maximum(r, 1e-6), 1)
    out = _sample(a, h / 2 + ny * src * h / 2, w / 2 + nx * src * w / 2)
    return _img(out * (r <= 1)[..., None])


def vignette(im):
    """周辺減光。縁に向かって暗くする"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot((yy - h / 2) / (h / 2), (xx - w / 2) / (w / 2)) / np.sqrt(2)
    return _img(a * (1 - 0.75 * np.clip(r - 0.35, 0, 1) ** 1.5 / 0.65 ** 1.5)[..., None])


def glitch(im):
    """グリッチ。横の帯をずらし、色の版をずらす"""
    a = _arr(im).copy()
    h, w = a.shape[:2]
    rng = np.random.default_rng(SEED)
    y = 0
    while y < h:
        t = int(rng.integers(2, max(3, h // 25)))
        if rng.random() < 0.3:
            a[y:y + t] = np.roll(a[y:y + t], int(rng.integers(-w // 12, w // 12)), axis=1)
        y += t
    d = max(2, w // 120)
    a[..., 0] = np.roll(a[..., 0], d, 1)
    a[..., 2] = np.roll(a[..., 2], -d, 1)
    return _img(a)


def anaglyph(im):
    """赤青の立体視。赤の版を左、青緑の版を右にずらす"""
    g = _gray(_arr(im))
    d = max(2, im.size[0] // 80)
    return _img(np.stack([np.roll(g, -d, 1), np.roll(g, d, 1), np.roll(g, d, 1)], -1))


def chromatic(im):
    """色収差。縁に行くほど赤と青の版を外へずらす"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    out = a.copy()
    for c, s in ((0, 1.012), (2, 0.988)):
        out[..., c] = _sample(a[..., c:c + 1], h / 2 + (yy - h / 2) / s, w / 2 + (xx - w / 2) / s)[..., 0]
    return _img(out)


def oldphoto(im):
    """古い写真。セピアに退色させ、傷と粒と周辺減光を足す"""
    g = _gray(_arr(im))
    h, w = g.shape
    a = np.stack([g * 1.0 + 0.08, g * 0.88 + 0.05, g * 0.7 + 0.02], -1)
    a = 0.12 + 0.8 * a
    rng = np.random.default_rng(SEED)
    a *= (0.94 + 0.12 * rng.random((h, w)))[..., None]
    for _ in range(12):
        x = int(rng.integers(0, w))
        a[:, x:x + 1] = np.minimum(a[:, x:x + 1] + 0.25, 1)
    return vignette(_img(a))


def tiltshift(im):
    """ミニチュア（ティルトシフト）。上下をぼかして中央の帯だけくっきり、色を濃くする"""
    a = _arr(im)
    h, _ = a.shape[:2]
    b = np.stack([_blur(a[..., c], max(2, h / 80)) for c in range(3)], -1)
    t = np.clip(np.abs(np.arange(h) / h - 0.5) / 0.3, 0, 1)[:, None, None]
    out = a * (1 - t) + b * t
    g = _gray(out)[..., None]
    return _img(g + (out - g) * 1.4)


def bloom(im):
    """光のにじみ。明るい所をぼかして足す"""
    a = _arr(im)
    hi = np.clip(a - 0.7, 0, 1) / 0.3
    r = max(3, min(a.shape[:2]) / 40)
    glow = np.stack([_blur(hi[..., c], r) for c in range(3)], -1)
    return _img(1 - (1 - a) * (1 - 0.8 * glow))


def rays(im):
    """光芒。右上から差す光の筋を重ねる"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = np.arctan2(yy + 0.2 * h, xx - 1.1 * w)
    rng = np.random.default_rng(SEED)
    n = 40
    k = ((ang + np.pi) / (2 * np.pi) * n * 6).astype(int) % n
    beam = (rng.random(n) < 0.4)[k].astype(np.float32)
    beam = _blur(beam, max(2, w / 150)) * np.clip(1 - np.hypot(yy, xx - w) / np.hypot(h, w), 0, 1)
    return _img(1 - (1 - a) * (1 - 0.45 * beam[..., None] * np.array([1, 0.95, 0.8])))


def sparkle(im):
    """キラキラ。背景に十字の光の点を散らす"""
    a = _arr(im).copy()
    h, w = a.shape[:2]
    rng = np.random.default_rng(SEED)
    bg = _subject(im) < 0.5
    s = max(4, min(h, w) // 40)
    for _ in range(30):
        y, x = int(rng.integers(s, h - s)), int(rng.integers(s, w - s))
        if not bg[y, x]:
            continue
        L = int(s * (0.5 + rng.random()))
        for dy, dx in ((0, 1), (1, 0)):
            for t in range(-L, L + 1):
                yy, xx = min(h - 1, max(0, y + dy * t)), min(w - 1, max(0, x + dx * t))
                a[yy, xx] = 1 - (1 - a[yy, xx]) * (abs(t) / L)
    return _img(a)


def kaleidoscope(im):
    """万華鏡。中心の周りを 6 つの鏡で折り返す"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = np.arctan2(yy - h / 2, xx - w / 2)
    r = np.hypot(yy - h / 2, xx - w / 2)
    seg = np.pi / 3
    t = np.abs(((ang % seg) + seg) % seg - seg / 2) - seg / 2 + np.pi / 2
    return _img(_sample(a, h / 2 + r * np.sin(t) * 0.9, w / 2 + r * np.cos(t) * 0.9))


def mirror(im):
    """鏡写し。左半分を右へ折り返す"""
    a = _arr(im)
    w = a.shape[1]
    out = a.copy()
    out[:, w - w // 2:] = a[:, :w // 2][:, ::-1]
    return _img(out)


def swirl(im):
    """渦。中心ほど強くねじる"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dy, dx = yy - h / 2, xx - w / 2
    r = np.hypot(dy, dx)
    t = np.arctan2(dy, dx) + 2.5 * np.clip(1 - r / (0.5 * min(h, w)), 0, 1) ** 2
    return _img(_sample(a, h / 2 + r * np.sin(t), w / 2 + r * np.cos(t)))


def wave(im):
    """波打ち。水面に映ったように横へ揺らす"""
    a = _arr(im)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return _img(_sample(a, yy, xx + np.sin(yy / max(4, h / 30)) * w / 80))


def koma(im):
    """コマ枠。黒い枠線と白い余白で 1 コマに収める"""
    a = _arr(im)
    h, w = a.shape[:2]
    m = max(6, min(h, w) // 25)
    t = max(2, min(h, w) // 200)
    out = np.ones_like(a)
    out[m:h - m, m:w - m] = a[m:h - m, m:w - m]
    out[m - t:m, m - t:w - m + t] = 0
    out[h - m:h - m + t, m - t:w - m + t] = 0
    out[m - t:h - m + t, m - t:m] = 0
    out[m - t:h - m + t, w - m:w - m + t] = 0
    return _img(out)


EFFECTS = {
    "focus_lines": focus_lines, "speed_lines": speed_lines, "fisheye": fisheye, "vignette": vignette,
    "glitch": glitch, "anaglyph": anaglyph, "chromatic": chromatic, "oldphoto": oldphoto,
    "tiltshift": tiltshift, "bloom": bloom, "rays": rays, "sparkle": sparkle,
    "kaleidoscope": kaleidoscope, "mirror": mirror, "swirl": swirl, "wave": wave, "koma": koma,
}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    im = Image.open(sys.argv[1]).convert("RGB")
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for n in sys.argv[3:] or list(EFFECTS):
        p = out / f"{Path(sys.argv[1]).stem}-fx-{n}.png"
        EFFECTS[n](im).save(p)
        print(p)
