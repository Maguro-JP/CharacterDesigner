"""絵の周り（キャンバスの外）の模様と動き。テーマごとに雰囲気を出す。

絵そのもの（紙）には何も重ねない。描いた色を見誤らないよう、模様は地の色に近い薄い色にする。
動きは紙の外だけを描き直す（紙の中は描き直さない）ので、大きな絵でも重くならない。
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

# 模様の名前: 画面に出す名前
# 1 秒に描き直す回数。ゆっくり回る物は少なくして、手元の計算を空ける
FPS = {"stars": 12, "grid": 20, "stripes": 20, "neongrid": 12, "gears": 10, "leaves": 20, "sunburst": 8}

PATTERNS = {"none": "無地", "stars": "星空", "grid": "方眼", "stripes": "斜めの帯", "neongrid": "電飾の格子",
            "gears": "歯車", "leaves": "木の葉", "sunburst": "放射"}


def _c(hex_: str, alpha: int) -> QColor:
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c


def _points(n: int, seed: int):
    r = random.Random(seed)
    return [(r.random(), r.random(), r.random()) for _ in range(n)]


def _gear(cx: float, cy: float, r: float, teeth: int, angle: float) -> QPainterPath:
    p = QPainterPath()
    for i in range(teeth * 2 + 1):
        a = angle + math.pi * i / teeth
        rr = r if i % 2 == 0 else r * 0.82
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        p.lineTo(x, y) if i else p.moveTo(x, y)
    p.addEllipse(QPointF(cx, cy), r * 0.3, r * 0.3)
    return p


def _leaf(x: float, y: float, s: float, a: float) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(0, -s)
    p.quadTo(s * 0.7, 0, 0, s)
    p.quadTo(-s * 0.7, 0, 0, -s)
    p.moveTo(0, -s)
    p.lineTo(0, s)
    from PySide6.QtGui import QTransform
    return QTransform().translate(x, y).rotateRadians(a).map(p)


_tiles: dict = {}


def _tile(kind: str, line: str, a1: str, a2: str):
    key = (kind, line, a1, a2)
    if key in _tiles:
        return _tiles[key]
    from PySide6.QtGui import QPixmap
    if kind == "grid":
        step, n = 24, 5
        pm = QPixmap(step * n, step * n)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setPen(QPen(_c(line, 90), 1))
        for i in range(n):
            q.drawLine(i * step, 0, i * step, step * n)
            q.drawLine(0, i * step, step * n, i * step)
        q.setPen(QPen(_c(a1, 70), 1))
        q.drawLine(0, 0, 0, step * n)
    else:
        step = 46
        side = step * 2 * 3   # 帯 2 本で 1 周期、色は 3 本ごとに替わる
        pm = QPixmap(side, side)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        for i in range(-6, 7):
            x = i * step * 2
            path = QPainterPath()
            path.moveTo(x, 0)
            path.lineTo(x + step, 0)
            path.lineTo(x + step + side, side)
            path.lineTo(x + side, side)
            q.setBrush(_c(a2 if i % 3 else a1, 26))
            q.drawPath(path)
    q.end()
    _tiles[key] = pm
    return pm


def paint(p: QPainter, rect, t: dict, phase: float = 0.0):
    """rect（画面の座標）に、テーマ t の模様を描く。phase は 0 から増える秒数（動きの位置）"""
    w, h = rect.width(), rect.height()
    base = QColor(t["canvas"])
    g = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
    g.setColorAt(0, base.lighter(135) if base.lightness() < 128 else base.lighter(108))
    g.setColorAt(1, base)
    p.fillRect(rect, g)
    kind = t.get("pattern", "none")
    p.setRenderHint(QPainter.Antialiasing)
    a1, a2, line = t["a1"], t["a2"], t["line2"]
    if kind == "stars":
        for i, (x, y, k) in enumerate(_points(140, 7)):
            tw = 0.5 + 0.5 * math.sin(phase * (1.2 + k * 2) + i)
            p.setPen(Qt.NoPen)
            p.setBrush(_c("#ffffff", int(40 + 150 * tw * k)))
            p.drawEllipse(QPointF(x * w, y * h), 0.6 + k * 1.4, 0.6 + k * 1.4)
    elif kind in ("grid", "stripes"):
        # 繰り返す模様は 1 枚の札に描いておき、ずらして敷き詰める（毎回 1 本ずつ描くと 1 回 50 ミリ秒かかった）
        tile = _tile(kind, line, a1, a2)
        speed = 4 if kind == "grid" else 30
        off = (phase * speed) % tile.width()
        p.drawTiledPixmap(QRectF(rect), tile, QPointF(off, off if kind == "grid" else 0))
    elif kind == "neongrid":
        horizon = h * 0.42
        p.setPen(QPen(_c(a2, 120), 1.2))
        for i in range(-14, 15):
            p.drawLine(QPointF(w / 2 + i * 18, horizon), QPointF(w / 2 + i * w / 9, h))
        for k in range(1, 14):
            f = ((k + phase * 0.8) % 14) / 14
            y = horizon + (h - horizon) * f * f
            p.setPen(QPen(_c(a1, int(40 + 160 * f)), 1.2))
            p.drawLine(QPointF(0, y), QPointF(w, y))
        sun = QLinearGradient(0, horizon - 120, 0, horizon)
        sun.setColorAt(0, _c(a2, 0))
        sun.setColorAt(1, _c(a2, 70))
        p.fillRect(QRectF(0, horizon - 120, w, 120), sun)
    elif kind == "gears":
        for i, (x, y, k) in enumerate(_points(14, 3)):
            r = 26 + k * 70
            turn = phase * (0.25 / (0.4 + k)) * (1 if i % 2 else -1)
            p.setPen(QPen(_c(a1 if i % 3 == 0 else line, 110), 2))
            p.setBrush(_c(a2, 14))
            p.drawPath(_gear(x * w, y * h, r, 8 + int(k * 10), turn))
    elif kind == "leaves":
        p.setPen(QPen(_c(a1, 120), 1.2))
        for i, (x, y, k) in enumerate(_points(42, 11)):
            yy = ((y + phase * (0.015 + k * 0.03)) % 1.1 - 0.05) * h
            xx = x * w + math.sin(phase * 0.7 + i) * 18
            p.setBrush(_c(a2 if i % 2 else a1, 40))
            p.drawPath(_leaf(xx, yy, 6 + k * 10, phase * 0.5 + i))
    elif kind == "sunburst":
        cx, cy = w / 2, h * 1.1
        turn = phase * 0.05
        p.setPen(Qt.NoPen)
        rays = 24
        reach = max(w, h) * 2
        for i in range(rays):
            a0 = turn + 2 * math.pi * i / rays
            a1_ = a0 + math.pi / rays
            path = QPainterPath(QPointF(cx, cy))
            path.lineTo(cx + reach * math.cos(a0), cy + reach * math.sin(a0))
            path.lineTo(cx + reach * math.cos(a1_), cy + reach * math.sin(a1_))
            path.closeSubpath()
            p.setBrush(_c(a1 if i % 2 else t["a3"], 30))
            p.drawPath(path)
