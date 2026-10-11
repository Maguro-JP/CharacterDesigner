"""線をブラシで引き直す。清書の線（白黒の線の画素）を細線化して1本ずつの筆跡に分け、ブラシの形（太さ・入り抜き・揺れ・粒）で描く。

人の線は1本ずつの筆跡で、端が細く抜け（Gペン・筆）、太さが揺れ、鉛筆なら粒がある。抜き出した線（XDoG）は太さが一定で端が途切れるだけなので、
筆跡として引き直す。ブラシは casts/brushes.json。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def table() -> dict:
    return json.loads((ROOT / "casts" / "brushes.json").read_text())


def strokes(line: np.ndarray, min_len: int = 6) -> list[list[tuple[int, int]]]:
    """線の画素を細線化し、端点や分かれ目で切った画素の列（筆跡）にする"""
    from skimage.morphology import skeletonize
    sk = skeletonize(line)
    H, W = sk.shape
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    ys, xs = np.nonzero(sk)
    pts = set(zip(ys.tolist(), xs.tolist()))
    deg = {p: sum((p[0] + dy, p[1] + dx) in pts for dy, dx in nb) for p in pts}
    seen, out = set(), []
    starts = [p for p in pts if deg[p] != 2] + list(pts)   # 端点と分かれ目から先にたどる（輪は最後）
    for s in starts:
        if s in seen:
            continue
        path, cur = [s], s
        seen.add(s)
        while True:
            nxt = [(cur[0] + dy, cur[1] + dx) for dy, dx in nb if (cur[0] + dy, cur[1] + dx) in pts and (cur[0] + dy, cur[1] + dx) not in seen]
            if not nxt:
                break
            # 分かれ目では切らず、今の向きに一番まっすぐ続く画素へ進む（短い切れ端の筆跡だらけになった）
            if len(path) >= 3:
                vy, vx = cur[0] - path[-3][0], cur[1] - path[-3][1]
                nxt.sort(key=lambda q: -((q[0] - cur[0]) * vy + (q[1] - cur[1]) * vx))
            cur = nxt[0]
            seen.add(cur)
            path.append(cur)
        if len(path) >= min_len:
            out.append(path)
    return out


def _smooth(path, k=3):
    a = np.array(path, dtype=float)
    if len(a) < 2 * k + 1:
        return a
    ker = np.ones(2 * k + 1) / (2 * k + 1)
    return np.stack([np.convolve(np.pad(a[:, i], k, mode="edge"), ker, mode="valid") for i in range(2)], 1)


def render(size, paths, brush: str, scale: float = 1.0, weights=None, color=(40, 30, 40), seed: int = 0) -> Image.Image:
    """筆跡をブラシで描いた RGBA の層。weights は筆跡ごとの太さの倍率（外形・影の側を太く）"""
    b = table()["brushes"][brush]
    rng = np.random.default_rng(seed)
    W, H = size
    s = 2   # 2倍で描いてから縮める（縁をなめらかにする）
    layer = Image.new("L", (W * s, H * s), 0)
    d = ImageDraw.Draw(layer)
    for i, path in enumerate(paths):
        p = _smooth(path)
        n = len(p)
        t = np.linspace(0, 1, n)
        prof = np.ones(n)
        if b["taper"] > 0 and n > 20:
            # 入りと抜き: 端から細くする（Gペンや筆の筆圧）。抜く長さは線の割合で、ただし 30 画素まで（長い線の真ん中は太いまま）
            L = min(b["taper"] * n, 30)
            idx = np.arange(n)
            prof = np.minimum(1, np.minimum(idx / L, (n - 1 - idx) / L) * 0.85 + 0.15)
        jit = 1 + b["jitter"] * np.convolve(rng.normal(0, 1, n), np.ones(9) / 9, mode="same")[:n]
        jit = np.resize(jit, n)
        w = b["width"] * scale * (weights[i] if weights is not None else 1.0) * prof * jit
        for (y, x), r in zip(p, w):
            r = max(r, 0.4) * s / 2
            d.ellipse([x * s - r, y * s - r, x * s + r, y * s + r], fill=255)
    a = np.asarray(layer.resize((W, H), Image.LANCZOS)).astype(float) / 255
    if b["grain"] > 0:
        # 鉛筆の粒: 紙の目の雑音で濃さを抜く
        a *= 1 - b["grain"] * (rng.random(a.shape) > 0.55)
    out = np.zeros((H, W, 4), dtype=np.uint8)
    out[..., :3] = color
    out[..., 3] = (a * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")
