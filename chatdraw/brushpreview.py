"""ブラシの欄の見本の線。今のブラシ・太さ・色・濃さ・硬さ・色の出方で、S 字の線を 1 本描いて見せる。

数字の欄だけでは、硬さや間隔を変えたときに線がどう変わるか分からなかった。描く前に見えるよう、
キャンバスと同じ stamp で描く（見本と本物の線がずれないように、描き方を 2 つ持たない）。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from chatdraw.brush import Dabs, stamp


class BrushPreview(QWidget):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.dabs = Dabs()
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("今のブラシで描いたときの線の見本（太さ・色・濃さ・硬さを変えるとすぐ変わる）")

    def render(self, w: int, h: int) -> QImage:
        """見本の線の絵。太さは欄の高さに収まるよう縮める（太さの数字は右下に出す）"""
        c = self.canvas
        img = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        size = max(1.0, min(float(c.size), h * 0.6))
        tool = c.tool if c.tool in ("pen", "eraser", "spray") else "pen"
        pad = size / 2 + 4
        pts = [QPointF(pad + (w - 2 * pad) * i / 40, h / 2 + (h / 2 - pad) * 0.8 * math.sin(i / 40 * 2 * math.pi))
               for i in range(41)]
        line = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
        line.fill(Qt.transparent)
        brush = c.brushes["消しゴム"] if tool == "eraser" else c.brush
        carry, length = 0.0, 0.0
        keep = c.stroke_len, c.size
        c.size = int(size)
        try:
            for i in range(1, len(pts)):
                a, b = pts[i - 1], pts[i]
                c.stroke_len = length
                color = QColor("#8a8a90") if tool == "eraser" else c.stroke_color()
                pressure = 0.35 + 0.65 * math.sin(i / 40 * math.pi)   # 筆圧の効き方も見えるよう、入りと抜きを弱くする
                if tool == "spray":
                    c.spray(line, b, 1.0)
                else:
                    _r, carry = stamp(line, brush, self.dabs, a, b, size, color, pressure, carry)
                length += math.hypot(b.x() - a.x(), b.y() - a.y())
        finally:
            c.stroke_len, c.size = keep
        p = QPainter(img)
        p.setOpacity(c.brush_opacity)
        p.drawImage(0, 0, line)
        p.end()
        return img

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        # 白い紙の上に描く（暗いテーマでも黒い線が見える）
        p.fillRect(r, QColor("#ffffff"))
        p.drawImage(0, 0, self.render(r.width(), r.height()))
        p.setPen(QColor("#5a5a60"))
        p.drawRect(r.adjusted(0, 0, -1, -1))
        p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignRight | Qt.AlignBottom, f"{self.canvas.size}px")
        p.end()
