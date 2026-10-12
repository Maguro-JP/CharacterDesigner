"""空気感と環境の光: 描いた絵に、光の筋・霞・粒・光の斑点・周辺減光などを重ねて「どこにいるか」を伝える。

  python3 tools/gen/atmosphere.py <絵> <出力.png> --mood holy [--strength 0.7] [--light 0.3,0.0]

決まりは docs/knowledge/atmosphere.md。どの空気感も、光の層（明るくする）・空気の層（一色に寄せる）・影の層（暗くする）の
組み合わせで作る。下の絵は壊さず、強さ（strength 0〜1）で混ぜる。light は光源の位置（絵の幅と高さに対する割合、x,y）。

mood:
- holy（神々しい光）: 光源から放射状の太い光の筋、光源の周りのにじみ、暖かい白金、光の粒
- dust（ほこりっぽい）: 細く鋭い筋、黄土色の霞、多くのほこりの粒、彩度を落とす
- komorebi（木漏れ日）: 楕円の光の斑点、斜めの細い筋、緑がかった影
- underground（地下）: 強い周辺減光、光源の近くだけ暖かい橙、影は冷たい青黒、彩度を落とす
- space（宇宙）: 暗く冷たく沈め、星の点、星雲の色むら、片側から色の縁取りの光
- haze（霞・遠近）: 空の色で上ほど濃く覆い、明暗の差を下げる
"""
from __future__ import annotations

import argparse
import json

import numpy as np
from PIL import Image, ImageFilter

MOODS = ("holy", "dust", "komorebi", "underground", "space", "haze")
# 描く言葉に足す言葉（docs/knowledge/atmosphere.md の表と同じ）。生成のときに使う
PROMPT = {
    "holy": "god rays, light rays, divine light, backlighting, glowing, light particles",
    "dust": "dust, dust particles, hazy, sunbeam, abandoned, muted colors",
    "komorebi": "dappled sunlight, sunlight filtering through leaves, forest, light spots",
    "underground": "underground, dungeon, cave, torchlight, dark, dim lighting, warm light",
    "space": "space, starry sky, nebula, galaxy, rim light, cosmic",
    "haze": "atmospheric perspective, fog, mist, depth",
}
# 光源の既定の位置（x, y の割合）
LIGHT = {"holy": (0.25, -0.1), "dust": (0.15, -0.05), "komorebi": (0.7, -0.1), "underground": (0.2, 0.55), "space": (-0.1, 0.3), "haze": (0.5, -0.2)}


def _blur(a: np.ndarray, r: float) -> np.ndarray:
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype("uint8"))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(float(r)))).astype(float) / 255


def _screen(base: np.ndarray, light: np.ndarray) -> np.ndarray:
    """明るくする重ね方（スクリーン）。白に近づくが飛ばない"""
    return 1 - (1 - base) * (1 - light)


def _rays(h: int, w: int, lx: float, ly: float, n: int, width: float, rng) -> np.ndarray:
    """光源から放射状の筋。角度ごとに明るさの帯を作り、光源から離れるほど薄くする"""
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    cx, cy = lx * w, ly * h
    ang = np.arctan2(yy - cy, xx - cx)
    dist = np.hypot(yy - cy, xx - cx) / np.hypot(h, w)
    acc = np.zeros((h, w))
    for _ in range(n):
        a0 = rng.uniform(-np.pi, np.pi)
        wd = width * rng.uniform(0.5, 1.5)
        d = np.angle(np.exp(1j * (ang - a0)))
        acc += np.exp(-(d / wd) ** 2) * rng.uniform(0.4, 1.0)
    acc = np.clip(acc, 0, 1) * np.clip(1.2 - dist * 1.6, 0, 1)
    return _blur(acc, 3)


def _particles(h: int, w: int, count: int, rmax: float, rng) -> np.ndarray:
    """粒（ほこり・光の粒）。大きさをばらし、少しぼかす"""
    a = np.zeros((h, w))
    ys = rng.integers(0, h, count)
    xs = rng.integers(0, w, count)
    for y, x in zip(ys, xs):
        r = max(1, int(rng.uniform(0.5, rmax)))
        a[max(0, y - r):y + r, max(0, x - r):x + r] = np.maximum(a[max(0, y - r):y + r, max(0, x - r):x + r], rng.uniform(0.3, 1.0))
    return _blur(a, 1.2)


def _spots(h: int, w: int, count: int, rng) -> np.ndarray:
    """木漏れ日の光の斑点。葉の隙間が太陽の像を映すので、丸〜横に寝た楕円にする"""
    a = np.zeros((h, w))
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    # 葉の隙間は寄り集まる。種の点の周りに群れで置き、大きさを大きくばらす（同じ大きさで並べると水玉模様に見えた）
    centers = [(rng.uniform(0, h), rng.uniform(0, w)) for _ in range(max(2, count // 12))]
    for _ in range(count):
        gy, gx = centers[rng.integers(len(centers))]
        cy, cx = gy + rng.normal(0, h * 0.12), gx + rng.normal(0, w * 0.15)
        rx = rng.uniform(0.008, 0.07) * w
        ry = rx * rng.uniform(0.4, 0.8)
        a = np.maximum(a, np.clip(1.4 - ((xx - cx) / rx) ** 2 - ((yy - cy) / ry) ** 2, 0, 1))
    return _blur(np.clip(a, 0, 1), 2)


def _vignette(h: int, w: int, cx: float, cy: float, power: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    d = np.hypot((xx / w - cx), (yy / h - cy))
    return np.clip(1 - d ** power * 1.8, 0, 1)


def apply(img: Image.Image, mood: str, strength: float = 0.7, light: tuple[float, float] | None = None, seed: int = 0) -> Image.Image:
    if mood not in MOODS:
        raise ValueError(f"空気感「{mood}」は無い（{', '.join(MOODS)}）")
    s = float(np.clip(strength, 0, 1))
    src = img.convert("RGBA")
    arr = np.asarray(src).astype(float) / 255
    rgb, alpha = arr[..., :3], arr[..., 3:]
    if s == 0:
        return src
    h, w = rgb.shape[:2]
    rng = np.random.default_rng(seed)
    lx, ly = light or LIGHT[mood]
    luma = rgb @ np.array([0.299, 0.587, 0.114])
    out = rgb.copy()

    def tint(color, amount):
        nonlocal out
        out = out * (1 - amount) + np.array(color) * amount

    if mood == "holy":
        warm = np.array([1.0, 0.93, 0.75])
        rays = _rays(h, w, lx, ly, 9, 0.06, rng)
        glow = _vignette(h, w, lx, ly, 0.9)
        light_layer = (rays * 0.8 + glow * 0.5)[..., None] * warm
        # 明るい絵に光を足すだけでは筋が見えなかった。筋の外を少し沈めて、筋を浮かせる
        out = out * (1 - 0.35 * s * (1 - np.clip(rays + glow * 0.5, 0, 1)))[..., None]
        out = _screen(out, light_layer * s)
        out = _screen(out, (_particles(h, w, int(400 * s), 3, rng) * rays)[..., None] * warm * s)
        tint([0.75, 0.82, 0.95], 0.08 * s * (1 - luma)[..., None])          # 影を薄い青へ
    elif mood == "dust":
        ochre = np.array([0.82, 0.72, 0.52])
        rays = _rays(h, w, lx, ly, 5, 0.025, rng)
        mean = out.mean(-1, keepdims=True)
        out = mean + (out - mean) * (1 - 0.45 * s)                            # 彩度を落とす
        depth = np.linspace(0.6, 0.15, h)[:, None, None]
        out = out * (1 - depth * 0.6 * s) + ochre * depth * 0.6 * s           # 黄土の霞（上ほど濃い）
        out = out * (1 - 0.3 * s * (1 - rays))[..., None]                     # 筋の外を沈めて筋を浮かせる
        out = _screen(out, rays[..., None] * ochre * 0.8 * s)
        motes = _particles(h, w, int(1500 * s), 2, rng)
        out = _screen(out, (motes * (0.35 + rays))[..., None] * np.array([1.0, 0.95, 0.85]) * s)
    elif mood == "komorebi":
        sun = np.array([1.0, 0.95, 0.7])
        shade = np.array([0.35, 0.5, 0.4])
        spots = _spots(h, w, int(60 * s) + 10, rng)
        rays = _rays(h, w, lx, ly, 6, 0.02, rng)
        # 斑点の外は木陰（緑がかって暗い）、斑点は暖かい日なた
        shadow = (1 - spots)[..., None] * 0.55 * s
        out = out * (1 - shadow) + out * shade * shadow
        out = _screen(out, spots[..., None] * sun * 0.55 * s)
        out = _screen(out, rays[..., None] * sun * 0.35 * s)
    elif mood == "underground":
        fire = np.array([1.0, 0.55, 0.2])
        pool = _vignette(h, w, lx, ly, 1.3)                                  # 光源の近くだけ明るい（急に落ちる）
        pool = pool ** 2
        mean = out.mean(-1, keepdims=True)
        out = mean + (out - mean) * (1 - 0.5 * s)
        dark = 1 - s * 0.75 * (1 - pool)
        cold = np.array([0.55, 0.65, 0.9])
        out = out * dark[..., None]
        out = out * (1 - (1 - pool)[..., None] * 0.3 * s) + out * cold * (1 - pool)[..., None] * 0.3 * s
        out = _screen(out, pool[..., None] * fire * 0.45 * s)
        out = out * _vignette(h, w, 0.5, 0.5, 1.6)[..., None] ** (0.8 * s)
    elif mood == "space":
        out = out * (1 - 0.85 * s) * np.array([0.85, 0.9, 1.1])              # 暗く冷たく沈める（0.55・0.75 では灰色に残った）
        nebula = np.zeros((h, w, 3))
        for col in ([0.6, 0.25, 0.8], [0.2, 0.4, 0.9], [0.9, 0.35, 0.55]):
            n = _blur(rng.random((h // 8 + 1, w // 8 + 1)), 3)
            n = np.asarray(Image.fromarray((n * 255).astype("uint8")).resize((w, h), Image.BICUBIC)).astype(float) / 255
            nebula += np.clip(n - 0.45, 0, 1)[..., None] * np.array(col) * 1.6
        bg = (1 - luma)[..., None] if alpha.mean() > 0.99 else (1 - alpha)
        out = _screen(out, np.clip(nebula, 0, 1) * 0.6 * s * bg)
        stars = (rng.random((h, w)) > 0.998).astype(float)
        big = (rng.random((h, w)) > 0.99985).astype(float)
        out = _screen(out, np.clip(stars + _blur(big, 1.5) * 8, 0, 1)[..., None] * s * bg)
        # 片側から星雲の色の縁取り（光源の側の明るい所を色で持ち上げる）
        side = np.clip(1 - np.abs(np.linspace(0, 1, w) - max(0.0, lx)) * 1.5, 0, 1)[None, :]
        rim = np.clip(luma - 0.35, 0, 1) * side
        out = _screen(out, rim[..., None] * np.array([0.5, 0.6, 1.0]) * 0.8 * s)
    elif mood == "haze":
        sky = np.array([0.72, 0.78, 0.86])
        depth = np.linspace(0.7, 0.1, h)[:, None, None]
        out = (out - 0.5) * (1 - 0.3 * s) + 0.5
        out = out * (1 - depth * s) + sky * depth * s

    res = np.dstack([np.clip(out, 0, 1), alpha])
    return Image.fromarray((res * 255).astype("uint8"), "RGBA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--mood", choices=MOODS, required=True)
    ap.add_argument("--strength", type=float, default=0.7)
    ap.add_argument("--light", default="", help="光源の位置 x,y（絵に対する割合。絵の外も可）")
    a = ap.parse_args()
    light = tuple(float(v) for v in a.light.split(",")) if a.light else None
    apply(Image.open(a.src), a.mood, a.strength, light).save(a.out)
    print(json.dumps({"mood": a.mood, "prompt": PROMPT[a.mood]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
