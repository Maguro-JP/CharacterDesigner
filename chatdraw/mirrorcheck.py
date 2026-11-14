"""映り込みの矛盾の検品。鏡・水面・窓ガラスに映った物と、映っている元の物の形・色・数・向きを比べる。

模型は鏡の中と外を別々に描くので、同じ物のはずが別の物（色の違う服、無い腕、反転していない向き）になった。
手・足・顔の検品は枠の中しか見ないため、この食い違いは通っていた。

やり方（根拠は docs/knowledge/mirror-check.md）:
1. 絵全体のタグ（mirror、reflection、reflective water など）で、映り込みのある絵かを決める。無ければ何も言わない
2. 鏡の対称の見つけ方（Loy と Eklundh、2006）に倣い、小さな区画の勾配の向きの並びを、反転した絵の区画と突き合わせ、
   組ごとに「軸の位置と縦横のずれ」へ票を入れる。一番票の多い軸に入った組が、元の物と映った物の対応になる
3. 対応の付いた区画どうしで、色（映り込み全体の暗さ・色かぶりを引いたあと）と形（勾配の並び）を比べ、
   元にあって映りに無い物・映りにだけ有る物（数）も数える。反転しない写しの方がよく合えば、向きの矛盾とする
読めなかった（映り込みのタグはあるのに組が見つからない）ときは「比べていない」と返し、崩れが無いことにしない。
"""
from __future__ import annotations

import numpy as np

# 映り込みのある絵と読むタグと下限。water・floor は上下、mirror は左右に反転して映る
TAGS = {"mirror": 0.35, "reflection": 0.35, "reflective water": 0.35, "reflective floor": 0.35,
        "looking at mirror": 0.35, "holding mirror": 0.35, "hand mirror": 0.35, "water reflection": 0.35}
VERTICAL = ("reflective water", "reflective floor", "water reflection")
SIDE = 192          # 測る大きさ（長い辺）
CELL, STEP = 8, 4   # 区画の大きさと間隔（画素、SIDE の上で）
LEAST_PAIRS = 8     # 映り込みと読む組の下限
COLOR_FAR = 48.0    # 色の食い違い（暗さ・色かぶりを引いた RGB の距離）
SHAPE_NEAR = 0.0    # 形が合うと読む、区画の画素の相関の下限
GAP = 2 * CELL      # 元の物と映りの間に要る空き（画素、SIDE の上で）
CORNER = 0.25       # 線だけの区画と読む上限（_corner）
TEXTURE = 0.08      # 物が描かれていると読む区画の勾配の強さ（全体の上位に対する比）


def gated(tags: dict) -> list[str]:
    return [t for t, least in TAGS.items() if tags.get(t, 0.0) >= least]


def _prep(im):
    from PIL import Image
    w, h = im.size
    k = SIDE / max(w, h)
    nw, nh = max(CELL * 2, int(round(w * k / STEP)) * STEP), max(CELL * 2, int(round(h * k / STEP)) * STEP)
    a = np.asarray(im.convert("RGB").resize((nw, nh), Image.BILINEAR), dtype=np.float32)
    return a, (w / nw, h / nh)


def _cells(a):
    """区画ごとの勾配の向きの並び（2x2 の小区画 x 8 向き）、色の平均、勾配の強さ"""
    g = a.mean(axis=2)
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    ang = (np.arctan2(gy, gx) % (2 * np.pi)) / (2 * np.pi) * 8
    bins = np.minimum(ang.astype(int), 7)
    h, w = g.shape
    ys = list(range(0, h - CELL + 1, STEP))
    xs = list(range(0, w - CELL + 1, STEP))
    one = np.zeros((h, w, 8), np.float32)
    np.put_along_axis(one, bins[..., None], mag[..., None], axis=2)
    half = CELL // 2
    desc = np.zeros((len(ys), len(xs), 32), np.float32)
    col = np.zeros((len(ys), len(xs), 3), np.float32)
    strength = np.zeros((len(ys), len(xs)), np.float32)
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            parts = [one[y + dy:y + dy + half, x + dx:x + dx + half].sum(axis=(0, 1))
                     for dy in (0, half) for dx in (0, half)]
            v = np.concatenate(parts)
            strength[i, j] = v.sum()
            desc[i, j] = v / (np.linalg.norm(v) + 1e-6)
            col[i, j] = a[y:y + CELL, x:x + CELL].reshape(-1, 3).mean(axis=0)
    return desc, col, strength, np.array(ys), np.array(xs)


def _corner(d):
    """区画の勾配が、1 本の線（向かい合う 2 向き）以外の向きにどれだけあるか（0〜1）"""
    o = d.reshape(d.shape[:2] + (4, 8)).sum(axis=2)
    line = o + np.roll(o, 4, axis=2)            # 線の両側（逆の向き）を合わせる
    return 1 - line.max(axis=2) / (o.sum(axis=2) + 1e-6)


def _search(a, axis: str, flip: bool):
    """反転（flip）または平行に写した絵の区画と突き合わせ、一番票の多い対応を返す"""
    b = (a[:, ::-1] if axis == "h" else a[::-1]) if flip else a
    d0, c0, s0, ys, xs = _cells(a)
    d1, _c1, s1, _, _ = _cells(b)
    top = np.percentile(s0, 95) + 1e-6
    # まっすぐな線だけの区画は外す。線は線に沿ってずらしても重なるので、どこにでも「写し」が見つかった
    tex0 = (s0 > TEXTURE * top) & (_corner(d0) > CORNER)
    tex1 = (s1 > TEXTURE * top) & (_corner(d1) > CORNER)
    H, W = a.shape[:2]
    P = np.argwhere(tex0)
    Q = np.argwhere(tex1)
    if len(P) < LEAST_PAIRS or len(Q) < LEAST_PAIRS:
        return None
    # b の区画を元の絵の場所に戻す
    qy, qx = ys[Q[:, 0]], xs[Q[:, 1]]
    if flip and axis == "h":
        qx = W - CELL - qx
    elif flip:
        qy = H - CELL - qy
    py, px = ys[P[:, 0]], xs[P[:, 1]]
    sim = d0[tex0] @ d1[tex1].T
    # 隣や自分の左右対称（正面の顔）は映り込みにしない。軸の向きに 3 区画より近い組を外してから一番近い物を選ぶ
    far = np.abs(qx[None] - px[:, None]) if axis == "h" else np.abs(qy[None] - py[:, None])
    sim[far < 3 * CELL] = -1
    best = sim.argmax(axis=1)
    ok = sim[np.arange(len(P)), best] > 0.9
    votes: dict = {}
    for k in np.nonzero(ok)[0]:
        p = (int(py[k]), int(px[k]))
        q = (int(qy[best[k]]), int(qx[best[k]]))
        if flip:
            key = ((p[1] + q[1]) // STEP, (q[0] - p[0]) // STEP) if axis == "h" else ((p[0] + q[0]) // STEP, (q[1] - p[1]) // STEP)
        else:
            # 平行な写しは p→q と q→p が逆向きの票になるので、元の側を軸の手前にそろえてから数える
            if (q[1] < p[1]) if axis == "h" else (q[0] < p[0]):
                p, q = q, p
            key = ((q[1] - p[1]) // STEP, (q[0] - p[0]) // STEP)
        votes.setdefault(key, []).append((p, q))
    if not votes:
        return None
    # 一番票の多い軸から順に見て、元の側と映りの側の間が空いている物を選ぶ。自分の左右対称（正面の顔・丸い物）は、
    # 半分ずつを組にすると間が空かない（楕円 1 つを鏡と読んだ）。間の無い組は映り込みにしない
    for key, pairs in sorted(votes.items(), key=lambda kv: -len(kv[1])):
        if len(pairs) < LEAST_PAIRS:
            break
        if axis == "h":
            pairs = [(p, q) if p[1] < q[1] else (q, p) for p, q in pairs]
        else:
            pairs = [(p, q) if p[0] < q[0] else (q, p) for p, q in pairs]
        pairs = list(dict.fromkeys(pairs))
        sb, rb = _box([p for p, _ in pairs]), _box([q for _, q in pairs])
        gap = rb[0] - sb[2] if axis == "h" else rb[1] - sb[3]
        if len(pairs) >= LEAST_PAIRS and gap >= GAP:
            break
    else:
        return None
    if len(pairs) < LEAST_PAIRS or gap < GAP:
        return None
    return {"axis": axis, "flip": flip, "key": key, "pairs": pairs, "votes": len(pairs)}


def _box(pts):
    ys = [p[0] for p in pts]
    xs = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs) + CELL, max(ys) + CELL]


def _map(found, a, y, x):
    """元の側の区画 (y, x) が映る場所"""
    H, W = a.shape[:2]
    axis, flip, key = found["axis"], found["flip"], found["key"]
    if not flip:
        return y + key[1] * STEP, x + key[0] * STEP
    if axis == "h":
        return y + key[1] * STEP, key[0] * STEP - x
    return key[0] * STEP - y, x + key[1] * STEP


def _blobs(cells: set, join: int = STEP * 2):
    """近い区画をまとめた枠"""
    left = set(cells)
    out = []
    while left:
        stack = [left.pop()]
        grp = []
        while stack:
            c = stack.pop()
            grp.append(c)
            near = [d for d in left if abs(d[0] - c[0]) <= join and abs(d[1] - c[1]) <= join]
            for d in near:
                left.discard(d)
                stack.append(d)
        out.append(grp)
    return out


def compare(a, found) -> list[dict]:
    """対応の付いた映り込みと元の物を比べ、食い違いを枠と言葉で返す（枠は a の画素）"""
    H, W = a.shape[:2]
    src = _box([p for p, _ in found["pairs"]])
    ref = _box([q for _, q in found["pairs"]])
    pad = CELL
    # 元の物の枠を少し広げ、映りの外へはみ出た物（無い腕）も拾う
    x0, y0, x1, y1 = max(0, src[0] - pad), max(0, src[1] - pad), min(W, src[2] + pad), min(H, src[3] + pad)
    g = a.mean(axis=2)
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    top = np.percentile(mag, 95) + 1e-6
    # 映り込みは暗く、色が寄る（ガラスや水の色が混ざる）。対応の付いた組から、色ごとに 映り = a x 元 + b を当てはめてから比べる
    P = np.array([a[p[0]:p[0] + CELL, p[1]:p[1] + CELL].reshape(-1, 3).mean(0) for p, _ in found["pairs"]])
    Q = np.array([a[q[0]:q[0] + CELL, q[1]:q[1] + CELL].reshape(-1, 3).mean(0) for _, q in found["pairs"]])
    fit = []
    for c in range(3):
        A = np.stack([P[:, c], np.ones(len(P))], 1)
        k, b = np.linalg.lstsq(A, Q[:, c], rcond=None)[0]
        fit.append((float(np.clip(k, 0.3, 1.5)), float(b)))
    fit = np.array(fit)
    flipper = (lambda t: t[:, ::-1]) if found["flip"] and found["axis"] == "h" else \
        (lambda t: t[::-1]) if found["flip"] else (lambda t: t)
    color, shape, missing, extra = set(), set(), set(), set()
    for y in range(y0, y1 - CELL + 1, STEP):
        for x in range(x0, x1 - CELL + 1, STEP):
            qy, qx = _map(found, a, y, x)
            if not (0 <= qy <= H - CELL and 0 <= qx <= W - CELL):
                continue
            p = a[y:y + CELL, x:x + CELL]
            q = flipper(a[qy:qy + CELL, qx:qx + CELL])
            mp = mag[y:y + CELL, x:x + CELL].mean() / top
            mq = mag[qy:qy + CELL, qx:qx + CELL].mean() / top
            if mp > 0.25 and mq < 0.03:
                missing.add((qy, qx))
                continue
            if mq > 0.25 and mp < 0.03:
                extra.add((qy, qx))
                continue
            d = np.linalg.norm(q.reshape(-1, 3).mean(0) - (fit[:, 0] * p.reshape(-1, 3).mean(0) + fit[:, 1]))
            if d > COLOR_FAR:
                color.add((qy, qx))
            elif mp > 0.15 and mq > 0.15:
                pa = (p - p.mean()).ravel()
                qa = (q - q.mean()).ravel()
                if pa @ qa / (np.linalg.norm(pa) * np.linalg.norm(qa) + 1e-6) < SHAPE_NEAR:
                    shape.add((qy, qx))
    out = []
    for cells, what, least in ((color, "色が違う", 3), (missing, "物が足りない（元にある物が映っていない）", 3),
                               (extra, "物が多い（元に無い物が映っている）", 3), (shape, "形が違う", 4)):
        for grp in _blobs(cells):
            if len(grp) >= least:
                out.append({"box": _box(grp), "what": what, "cells": len(grp)})
    return out, src, ref


def check(im, tags: dict) -> dict:
    """映り込みの矛盾。返す物: gated（読んだタグ）、found（組の数）、flaws（枠と言葉）、reason（比べられなかった訳）"""
    got = gated(tags or {})
    res: dict = {"gated": got, "flaws": []}
    if not got:
        return res
    a, (kx, ky) = _prep(im)
    axes = ("v",) if all(t in VERTICAL for t in got) else ("h",) if all(t not in VERTICAL and t != "reflection"
                                                                       for t in got) else ("h", "v")
    flipped = [f for f in (_search(a, ax, True) for ax in axes) if f]
    straight = [f for f in (_search(a, ax, False) for ax in axes) if f]
    best = max(flipped, key=lambda f: f["votes"], default=None)
    copy = max(straight, key=lambda f: f["votes"], default=None)
    where = "水面" if axes == ("v",) else "鏡"

    def scale(b):
        return [int(b[0] * kx), int(b[1] * ky), int(b[2] * kx), int(b[3] * ky)]
    if copy and (not best or copy["votes"] > best["votes"] * 1.5):
        ref = _box([q for _, q in copy["pairs"]])
        res["found"] = copy["votes"]
        res["flaws"].append({"box": scale(ref), "bad": [f"矛盾: {where}の中の向きが違う（反転せずに写っている）"]})
        return res
    if not best:
        res["reason"] = f"{where}の映り込み（{'、'.join(got)}）と元の物の組を見つけられず、比べていない"
        return res
    res["found"] = best["votes"]
    found, src, ref = compare(a, best)
    res["source"], res["reflection"] = scale(src), scale(ref)
    for f in found:
        res["flaws"].append({"box": scale(f["box"]), "bad": [f"矛盾: {where}の中の{f['what']}"]})
    return res
