"""描く補助の計算。図形の角度の固定（Shift）、正多角形の角、定規（平行線・同心円・放射・パース）、描いた線の形の認識。

画面の部品に頼らない数の計算だけを置き、キャンバス（chatdraw/canvas.py）から呼ぶ。点は (x, y) の組で受け、組で返す。
形の認識は、描き終えて止めたときに線を直線・円・楕円・四角・三角に整えるためのもの（作画ソフトの QuickShape と同じ働き）。
絵の模型は使わず、点の並びの当てはまりの誤差だけで決める（速く、毎回同じ答えになる）。
"""
from __future__ import annotations

import math

RULERS = {"parallel": "平行線", "concentric": "同心円", "radial": "放射", "persp1": "パース 1 点", "persp2": "パース 2 点"}
RULER_POINTS = {"parallel": 2, "concentric": 1, "radial": 1, "persp1": 1, "persp2": 2}   # 定規ごとの、つかんで動かす点の数
SNAP_DEG = 15


def snap_angle(a, b, step=SNAP_DEG):
    """a から b への向きを step 度ごとに丸めた終わりの点（長さはそのまま）"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    r = math.hypot(dx, dy)
    if r == 0:
        return (b[0], b[1])
    t = math.radians(round(math.degrees(math.atan2(dy, dx)) / step) * step)
    return (a[0] + r * math.cos(t), a[1] + r * math.sin(t))


def square_end(a, b):
    """a から b までの四角を正方形（楕円なら正円）にする終わりの点。長い方の辺にそろえ、向きは b の側"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    s = max(abs(dx), abs(dy))
    return (a[0] + math.copysign(s, dx or 1), a[1] + math.copysign(s, dy or 1))


def regular_polygon(center, vertex, sides):
    """中心と 1 つの角から、正多角形の角の並び"""
    sides = max(3, int(sides))
    r = math.hypot(vertex[0] - center[0], vertex[1] - center[1])
    t0 = math.atan2(vertex[1] - center[1], vertex[0] - center[0])
    return [(center[0] + r * math.cos(t0 + 2 * math.pi * i / sides), center[1] + r * math.sin(t0 + 2 * math.pi * i / sides))
            for i in range(sides)]


def _project_line(p, o, d):
    """p を、o を通り向き d の直線へ下ろした点"""
    n = math.hypot(*d)
    if n == 0:
        return (o[0], o[1])
    ux, uy = d[0] / n, d[1] / n
    t = (p[0] - o[0]) * ux + (p[1] - o[1]) * uy
    return (o[0] + t * ux, o[1] + t * uy)


def ruler_direction(kind, start, pts, now):
    """線の始め start と今の所 now から、定規が決める向きを返す。同心円は None（円の上に乗せる）。
    パース 2 点は、始めに動かした向きに近い方（消失点 1・消失点 2・縦）を選ぶ"""
    if kind == "parallel":
        return (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    if kind in ("radial", "persp1"):
        return (start[0] - pts[0][0], start[1] - pts[0][1])
    if kind == "persp2":
        cands = [(start[0] - q[0], start[1] - q[1]) for q in pts[:2]] + [(0.0, 1.0)]
        mv = (now[0] - start[0], now[1] - start[1])
        mn = math.hypot(*mv) or 1.0

        def fit(d):
            dn = math.hypot(*d) or 1.0
            return abs((d[0] * mv[0] + d[1] * mv[1]) / (dn * mn))
        return max(cands, key=fit)
    return None


def ruler_snap(kind, start, pts, now, direction=None):
    """定規に沿わせた今の所。direction を渡せばその向きの直線に乗せる（パース 2 点で一度決めた向きを保つ）"""
    if kind == "concentric":
        c = pts[0]
        r = math.hypot(start[0] - c[0], start[1] - c[1])
        t = math.atan2(now[1] - c[1], now[0] - c[0])
        return (c[0] + r * math.cos(t), c[1] + r * math.sin(t))
    d = direction or ruler_direction(kind, start, pts, now)
    if d is None or math.hypot(*d) == 0:
        return (now[0], now[1])
    return _project_line(now, start, d)


def ruler_guides(kind, pts, w, h):
    """定規の案内の線（絵の上に薄く出す）。直線は (x0, y0, x1, y1)、円は ("circle", cx, cy, r)"""
    out = []
    big = 2 * (w + h)
    if kind == "parallel":
        dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        step = max(w, h) / 12
        for i in range(-12, 13):
            ox, oy = pts[0][0] - uy * step * i, pts[0][1] + ux * step * i
            out.append((ox - ux * big, oy - uy * big, ox + ux * big, oy + uy * big))
    elif kind == "concentric":
        for i in range(1, 9):
            out.append(("circle", pts[0][0], pts[0][1], max(w, h) / 12 * i))
    else:
        for c in pts[:2]:
            for i in range(24):
                t = 2 * math.pi * i / 24
                out.append((c[0], c[1], c[0] + big * math.cos(t), c[1] + big * math.sin(t)))
    return out


# ---- 描いた線の形の認識 ----

def _dist_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    if n == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _rdp(pts, eps):
    """線を、eps より大きく外れない少ない角の折れ線にする（Ramer–Douglas–Peucker）"""
    if len(pts) < 3:
        return list(pts)
    i, dmax = 0, -1.0
    for k in range(1, len(pts) - 1):
        d = _dist_seg(pts[k], pts[0], pts[-1])
        if d > dmax:
            i, dmax = k, d
    if dmax <= eps:
        return [pts[0], pts[-1]]
    return _rdp(pts[: i + 1], eps)[:-1] + _rdp(pts[i:], eps)


def _length(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def _resample(pts, n=96):
    """長さで等しい間隔に置き直す（ゆっくり描いた所に点が集まって、当てはめが偏らないように）"""
    total = _length(pts)
    if total == 0:
        return list(pts)
    step, out, acc = total / (n - 1), [pts[0]], 0.0
    i, cur = 0, pts[0]
    while i < len(pts) - 1 and len(out) < n:
        nxt = pts[i + 1]
        seg = math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
        if acc + seg >= step and seg > 0:
            t = (step - acc) / seg
            cur = (cur[0] + t * (nxt[0] - cur[0]), cur[1] + t * (nxt[1] - cur[1]))
            out.append(cur)
            acc = 0.0
        else:
            acc += seg
            cur = nxt
            i += 1
    if len(out) < n:
        out.append(pts[-1])
    return out


def _ellipse_fit(pts):
    """主軸の向き・中心・半径の組で楕円を当て、外れの大きさ（半径に対する割合）を返す"""
    n = len(pts)
    cx, cy = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sum((p[0] - cx) ** 2 for p in pts) / n
    syy = sum((p[1] - cy) ** 2 for p in pts) / n
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts) / n
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    c, s = math.cos(theta), math.sin(theta)
    u = [((p[0] - cx) * c + (p[1] - cy) * s, -(p[0] - cx) * s + (p[1] - cy) * c) for p in pts]
    # 半径は主軸に回した点の幅の半分にする。分散から出すと、長さで等間隔に置いた点は細長い楕円の両端に寄り、半径が狂った
    x0, x1 = min(q[0] for q in u), max(q[0] for q in u)
    y0, y1 = min(q[1] for q in u), max(q[1] for q in u)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    cx, cy = cx + mx * c - my * s, cy + mx * s + my * c
    u = [(q[0] - mx, q[1] - my) for q in u]
    a, b = (x1 - x0) / 2, (y1 - y0) / 2
    if a < 1e-6 or b < 1e-6:
        return None, 1.0
    err = sum(abs(math.hypot(q[0] / a, q[1] / b) - 1) for q in u) / n
    return (cx, cy, a, b, math.degrees(theta)), err


def recognize(points, min_size=12.0):
    """描いた線の点の列から形を当てる。返すのは ("line", p0, p1)、("circle", cx, cy, r)、("ellipse", cx, cy, a, b, 角度)、
    ("rect", [角 4 つ])、("triangle", [角 3 つ])、当てはまらなければ None。
    閉じていない線は直線だけを見る（弧を円にすると、描きたかった曲線が消える）"""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 4:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    total = _length(pts)
    if diag < min_size or total == 0:
        return None
    gap = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    closed = gap < 0.2 * diag and total > 1.7 * diag
    if not closed:
        chord = gap
        if chord < min_size:
            return None
        dev = max(_dist_seg(p, pts[0], pts[-1]) for p in pts)
        if dev < 0.06 * chord and total < 1.15 * chord:
            return ("line", pts[0], pts[-1])
        return None
    ring = _resample(pts)
    # 角の多い折れ線にならない形（三角・四角）を先に見る。円を折れ線にすると角が 6 つ以上になる
    poly = _rdp(ring, 0.07 * diag)
    if len(poly) >= 2 and math.hypot(poly[-1][0] - poly[0][0], poly[-1][1] - poly[0][1]) < 0.2 * diag:
        poly = poly[:-1]
    # 描き始めが辺の途中だと、始めの点が余分な角になる。両隣の向きがほぼ同じなら外す
    changed = True
    while changed and len(poly) > 3:
        changed = False
        for k in range(len(poly)):
            a, b, c = poly[k - 1], poly[k], poly[(k + 1) % len(poly)]
            if _dist_seg(b, a, c) < 0.07 * diag:
                poly.pop(k)
                changed = True
                break
    fit, err = _ellipse_fit(ring)
    if len(poly) in (3, 4):
        perr = sum(min(_dist_seg(p, poly[k - 1], poly[k]) for k in range(len(poly))) for p in ring) / len(ring) / diag
        if perr < 0.03 and (fit is None or perr / 0.03 < err / 0.08 or err > 0.08):
            return ("triangle", poly) if len(poly) == 3 else ("rect", _rectify(poly))
    if fit is None or err > 0.08:
        return None
    cx, cy, a, b, ang = fit
    if min(a, b) / max(a, b) > 0.85:
        return ("circle", cx, cy, (a + b) / 2)
    return ("ellipse", cx, cy, a, b, ang)


def _rectify(quad):
    """4 つの角を、向きを保った長方形にそろえる（主軸の向きに回した外の四角）"""
    n = len(quad)
    cx, cy = sum(p[0] for p in quad) / n, sum(p[1] for p in quad) / n
    # 辺の向きの平均（90 度で折り畳む）を長方形の向きにする
    sx = sy = 0.0
    for k in range(n):
        a, b = quad[k - 1], quad[k]
        t = 4 * math.atan2(b[1] - a[1], b[0] - a[0])
        w = math.hypot(b[0] - a[0], b[1] - a[1])
        sx, sy = sx + w * math.cos(t), sy + w * math.sin(t)
    theta = math.atan2(sy, sx) / 4
    c, s = math.cos(theta), math.sin(theta)
    u = [((p[0] - cx) * c + (p[1] - cy) * s, -(p[0] - cx) * s + (p[1] - cy) * c) for p in quad]
    hw = sum(abs(q[0]) for q in u) / n
    hh = sum(abs(q[1]) for q in u) / n
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


def shape_points(shape, steps=180):
    """認識した形を、ブラシでなぞるための点の列にする（閉じた形は始めの点に戻る）"""
    kind = shape[0]
    if kind == "line":
        return [shape[1], shape[2]]
    if kind in ("rect", "triangle"):
        return list(shape[1]) + [shape[1][0]]
    if kind == "circle":
        _, cx, cy, r = shape
        a = b = r
        ang = 0.0
    else:
        _, cx, cy, a, b, ang = shape
    t0 = math.radians(ang)
    c, s = math.cos(t0), math.sin(t0)
    out = []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        x, y = a * math.cos(t), b * math.sin(t)
        out.append((cx + x * c - y * s, cy + x * s + y * c))
    return out


SHAPE_NAMES = {"line": "直線", "circle": "円", "ellipse": "楕円", "rect": "四角", "triangle": "三角"}
