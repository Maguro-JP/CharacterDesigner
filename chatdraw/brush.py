"""ブラシ。線を「点（ダブ）」の連なりで描く。硬さ・流量・間隔・筆圧で太さと濃さが変わる。

1 本の線は線用の下書き（ストロークの一時の絵）に描き、手を離したときに濃さを掛けてレイヤーへ重ねる。
こうすると 1 本の線の中で点が重なっても濃くなりすぎず、作画ソフトの「不透明度」と同じ振る舞いになる。
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient


@dataclass
class Brush:
    name: str
    hardness: float = 1.0        # 1 で縁がくっきり、0 でぼやける
    flow: float = 1.0            # 1 つの点の濃さ。小さいほど重ねて濃くなる
    spacing: float = 0.1         # 点の間隔（太さに対する割合）
    size_pressure: bool = True   # 筆圧で太さが変わる
    opacity_pressure: bool = False   # 筆圧で濃さが変わる
    grain: float = 0.0           # 紙の目（鉛筆のざらつき）。0 で無し
    min_size: float = 0.15       # 筆圧が弱いときの太さの下限（太さに対する割合）

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS = [
    Brush("ペン", hardness=0.95, flow=1.0, spacing=0.08, size_pressure=True),
    Brush("鉛筆", hardness=0.8, flow=0.7, spacing=0.12, size_pressure=True, opacity_pressure=True, grain=0.55),
    Brush("筆", hardness=0.6, flow=0.5, spacing=0.06, size_pressure=True, opacity_pressure=True, min_size=0.3),
    Brush("エアブラシ", hardness=0.0, flow=0.08, spacing=0.05, size_pressure=False, opacity_pressure=True, min_size=1.0),
    Brush("マーカー", hardness=0.9, flow=1.0, spacing=0.08, size_pressure=False, min_size=1.0),
    Brush("消しゴム", hardness=0.85, flow=1.0, spacing=0.08, size_pressure=False, min_size=1.0),
]


class Dabs:
    """点の絵を大きさ・硬さ・色ごとに作り置きする（同じ点を何度も作らない）"""

    def __init__(self):
        self.cache: dict = {}

    def get(self, diameter: float, hardness: float, color: QColor, alpha: float, grain: float) -> QImage:
        d = max(1, int(round(diameter)))
        key = (d, round(hardness, 2), color.rgb(), round(alpha, 2), round(grain, 2))
        img = self.cache.get(key)
        if img is None:
            img = QImage(d + 2, d + 2, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            r = d / 2
            c = QColor(color)
            c.setAlphaF(max(0.0, min(1.0, alpha)))
            g = QRadialGradient(QPointF(r + 1, r + 1), r)
            edge = QColor(c)
            edge.setAlphaF(0)
            g.setColorAt(0, c)
            g.setColorAt(max(0.0, min(0.999, hardness)), c)
            g.setColorAt(1, edge)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(r + 1, r + 1), r, r)
            p.end()
            if grain > 0 and d > 2:
                # 紙の目: 点のいくつかの画素を薄くして、鉛筆のようなざらつきを出す（numpy でまとめて計算する）
                import numpy as np
                buf = np.frombuffer(img.bits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
                rng = np.random.default_rng(d)
                hit = rng.random(buf.shape[:2]) < grain * 0.5
                buf[hit] = (buf[hit] * (1 - grain)).astype(np.uint8)   # 前乗算の色なので 4 つとも同じ割合で薄める
            if len(self.cache) > 512:
                self.cache.clear()
            self.cache[key] = img
        return img


def stamp(target: QImage, brush: Brush, dabs: Dabs, a: QPointF, b: QPointF, size: float, color: QColor,
          pressure: float, carry: float, erase: bool = False) -> tuple[QRectF, float]:
    """a から b まで点を並べて描く。carry は前の区切りから持ち越した距離（間隔をそろえるため）。描いた四角と次の carry を返す"""
    psize = size * (max(brush.min_size, pressure) if brush.size_pressure else 1.0)
    alpha = brush.flow * (max(0.05, pressure) if brush.opacity_pressure else 1.0)
    dab = dabs.get(psize, brush.hardness, color, alpha, brush.grain)
    step = max(0.5, psize * brush.spacing)
    dist = math.hypot(b.x() - a.x(), b.y() - a.y())
    p = QPainter(target)
    if erase:
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    half = dab.width() / 2
    t = carry
    if dist == 0:
        p.drawImage(QPointF(a.x() - half, a.y() - half), dab)
        t = step
    while t <= dist:
        x = a.x() + (b.x() - a.x()) * t / dist
        y = a.y() + (b.y() - a.y()) * t / dist
        p.drawImage(QPointF(x - half, y - half), dab)
        t += step
    p.end()
    pad = half + 2
    return QRectF(a, b).normalized().adjusted(-pad, -pad, pad, pad), t - dist
