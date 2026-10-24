"""道具の絵（アイコン）。画像ファイルを持たず、線で描く。どの大きさでもにじまず、明るさの切り替えにも色を合わせられる"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap


def _path(key: str) -> QPainterPath:
    """24×24 の升目に描く線の形"""
    p = QPainterPath()
    if key == "move":
        for a, b in (((12, 2), (12, 22)), ((2, 12), (22, 12))):
            p.moveTo(*a)
            p.lineTo(*b)
        for tip, l, r in (((12, 2), (9, 5), (15, 5)), ((12, 22), (9, 19), (15, 19)),
                          ((2, 12), (5, 9), (5, 15)), ((22, 12), (19, 9), (19, 15))):
            p.moveTo(*l)
            p.lineTo(*tip)
            p.lineTo(*r)
    elif key == "select":
        for x0, y0, x1, y1 in ((4, 4, 9, 4), (12, 4, 15, 4), (18, 4, 20, 4), (20, 7, 20, 10), (20, 13, 20, 16), (20, 19, 20, 20),
                               (17, 20, 12, 20), (9, 20, 4, 20), (4, 17, 4, 12), (4, 9, 4, 4)):
            p.moveTo(x0, y0)
            p.lineTo(x1, y1)
    elif key == "pen":
        p.moveTo(4, 20)
        p.lineTo(5.5, 15)
        p.lineTo(16, 4.5)
        p.lineTo(19.5, 8)
        p.lineTo(9, 18.5)
        p.closeSubpath()
        p.moveTo(14, 6.5)
        p.lineTo(17.5, 10)
    elif key == "eraser":
        p.moveTo(9, 20)
        p.lineTo(4, 15)
        p.lineTo(14, 5)
        p.lineTo(20, 11)
        p.lineTo(11, 20)
        p.lineTo(20, 20)
        p.moveTo(8, 11)
        p.lineTo(14, 17)
    elif key == "blur":
        p.moveTo(12, 3)
        p.cubicTo(16, 9, 19, 12, 19, 15)
        p.cubicTo(19, 19, 15.5, 21, 12, 21)
        p.cubicTo(8.5, 21, 5, 19, 5, 15)
        p.cubicTo(5, 12, 8, 9, 12, 3)
    elif key == "fill":
        p.moveTo(5, 11)
        p.lineTo(11, 5)
        p.lineTo(18, 12)
        p.lineTo(12, 18)
        p.closeSubpath()
        p.moveTo(5, 11)
        p.lineTo(18, 11)
        p.moveTo(20, 15)
        p.cubicTo(21.5, 17, 21.5, 19.5, 20, 19.5)
        p.cubicTo(18.5, 19.5, 18.5, 17, 20, 15)
    elif key == "gradient":
        p.addRoundedRect(QRectF(3, 5, 18, 14), 3, 3)
        for x in (8, 12, 16):
            p.moveTo(x, 5)
            p.lineTo(x, 19)
    elif key == "line":
        p.moveTo(4, 20)
        p.lineTo(20, 4)
        p.addEllipse(QPointF(4, 20), 1.6, 1.6)
        p.addEllipse(QPointF(20, 4), 1.6, 1.6)
    elif key == "rect":
        p.addRoundedRect(QRectF(4, 6, 16, 12), 1.5, 1.5)
    elif key == "ellipse":
        p.addEllipse(QRectF(3, 6, 18, 12))
    elif key == "eyedropper":
        p.moveTo(4, 20)
        p.lineTo(5, 16)
        p.lineTo(13, 8)
        p.lineTo(16, 11)
        p.lineTo(8, 19)
        p.closeSubpath()
        p.moveTo(13, 8)
        p.lineTo(17, 4)
        p.cubicTo(18.5, 2.5, 21.5, 5.5, 20, 7)
        p.lineTo(16, 11)
    elif key == "hand":
        p.moveTo(7, 13)
        p.lineTo(7, 6)
        p.cubicTo(7, 4.5, 9.5, 4.5, 9.5, 6)
        p.lineTo(9.5, 11)
        p.lineTo(9.5, 4.5)
        p.cubicTo(9.5, 3, 12, 3, 12, 4.5)
        p.lineTo(12, 11)
        p.lineTo(12, 5.5)
        p.cubicTo(12, 4, 14.5, 4, 14.5, 5.5)
        p.lineTo(14.5, 11)
        p.lineTo(14.5, 7.5)
        p.cubicTo(14.5, 6, 17, 6, 17, 7.5)
        p.lineTo(17, 14)
        p.cubicTo(17, 18, 15, 21, 11, 21)
        p.cubicTo(8, 21, 6.5, 19, 5, 16.5)
        p.lineTo(3.5, 13.5)
        p.cubicTo(3, 12, 5, 11, 6, 12.5)
        p.lineTo(7, 14)
    elif key == "zoom":
        p.addEllipse(QRectF(3, 3, 13, 13))
        p.moveTo(14, 14)
        p.lineTo(21, 21)
        p.moveTo(9.5, 6.5)
        p.lineTo(9.5, 12.5)
        p.moveTo(6.5, 9.5)
        p.lineTo(12.5, 9.5)
    elif key == "palette":
        p.moveTo(12, 3)
        p.cubicTo(6, 3, 3, 7.5, 3, 12)
        p.cubicTo(3, 17, 7, 21, 12, 21)
        p.cubicTo(14, 21, 14, 18.5, 13, 17.5)
        p.cubicTo(12, 16, 13, 14.5, 15, 14.5)
        p.lineTo(17, 14.5)
        p.cubicTo(19.5, 14.5, 21, 13, 21, 10.5)
        p.cubicTo(21, 6.5, 17, 3, 12, 3)
        for cx, cy in ((7.5, 11), (9.5, 7), (14, 6.5), (17.5, 9.5)):
            p.addEllipse(QPointF(cx, cy), 1.1, 1.1)
    elif key == "brush":
        p.moveTo(20, 4)
        p.lineTo(11, 13)
        p.moveTo(11, 13)
        p.cubicTo(8, 13, 6, 15, 6, 17)
        p.cubicTo(6, 19, 5, 20, 3.5, 20.5)
        p.cubicTo(7, 21.5, 11, 20, 11.5, 17)
        p.cubicTo(11.8, 15.5, 11.5, 14, 11, 13)
    elif key == "history":
        p.addEllipse(QRectF(3.5, 3.5, 17, 17))
        p.moveTo(12, 7)
        p.lineTo(12, 12)
        p.lineTo(15.5, 14)
    elif key == "layers":
        p.moveTo(12, 4)
        p.lineTo(21, 8.5)
        p.lineTo(12, 13)
        p.lineTo(3, 8.5)
        p.closeSubpath()
        p.moveTo(3, 12.5)
        p.lineTo(12, 17)
        p.lineTo(21, 12.5)
        p.moveTo(3, 16.5)
        p.lineTo(12, 21)
        p.lineTo(21, 16.5)
    elif key == "help":
        p.addEllipse(QRectF(3.5, 3.5, 17, 17))
        p.moveTo(9.5, 9.5)
        p.cubicTo(9.5, 6.5, 14.5, 6.5, 14.5, 9.5)
        p.cubicTo(14.5, 11.5, 12, 11.5, 12, 14)
        p.addEllipse(QPointF(12, 17), 0.6, 0.6)
    elif key == "new":
        p.moveTo(6, 3)
        p.lineTo(14, 3)
        p.lineTo(19, 8)
        p.lineTo(19, 21)
        p.lineTo(6, 21)
        p.closeSubpath()
        p.moveTo(14, 3)
        p.lineTo(14, 8)
        p.lineTo(19, 8)
    elif key == "open":
        p.moveTo(3, 6)
        p.lineTo(9, 6)
        p.lineTo(11, 8)
        p.lineTo(21, 8)
        p.lineTo(21, 19)
        p.lineTo(3, 19)
        p.closeSubpath()
    elif key == "save":
        p.addRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
        p.moveTo(8, 4)
        p.lineTo(8, 9)
        p.lineTo(16, 9)
        p.lineTo(16, 4)
        p.addRect(QRectF(8, 13, 8, 7))
    elif key in ("undo", "redo"):
        sx = 1 if key == "undo" else -1
        def X(v):
            return 12 + sx * (v - 12)
        p.moveTo(X(8), 5)
        p.lineTo(X(4), 9)
        p.lineTo(X(8), 13)
        p.moveTo(X(4), 9)
        p.lineTo(X(15), 9)
        p.cubicTo(X(19), 9, X(20), 13, X(20), 15)
        p.cubicTo(X(20), 18, X(17), 19, X(15), 19)
        p.lineTo(X(10), 19)
    elif key == "fit":
        for (ax, ay), (bx, by), (cx, cy) in (((4, 9), (4, 4), (9, 4)), ((15, 4), (20, 4), (20, 9)),
                                              ((20, 15), (20, 20), (15, 20)), ((9, 20), (4, 20), (4, 15))):
            p.moveTo(ax, ay)
            p.lineTo(bx, by)
            p.lineTo(cx, cy)
    elif key == "rotate":
        p.moveTo(19, 12)
        p.cubicTo(19, 16, 16, 19.5, 12, 19.5)
        p.cubicTo(8, 19.5, 4.5, 16, 4.5, 12)
        p.cubicTo(4.5, 8, 8, 4.5, 12, 4.5)
        p.lineTo(17, 4.5)
        p.moveTo(14, 1.5)
        p.lineTo(17, 4.5)
        p.lineTo(14, 7.5)
    elif key == "rough":
        p.moveTo(4, 18)
        p.cubicTo(7, 12, 10, 16, 13, 10)
        p.cubicTo(15, 6, 18, 8, 20, 5)
        p.moveTo(4, 21)
        p.lineTo(20, 21)
    elif key == "models":
        p.addRoundedRect(QRectF(4, 4, 7, 7), 1.5, 1.5)
        p.addRoundedRect(QRectF(13, 4, 7, 7), 1.5, 1.5)
        p.addRoundedRect(QRectF(4, 13, 7, 7), 1.5, 1.5)
        p.addRoundedRect(QRectF(13, 13, 7, 7), 1.5, 1.5)
    elif key == "settings":
        p.addEllipse(QPointF(12, 12), 3, 3)
        import math
        for k in range(8):
            a = k * math.pi / 4
            p.moveTo(12 + 6 * math.cos(a), 12 + 6 * math.sin(a))
            p.lineTo(12 + 9 * math.cos(a), 12 + 9 * math.sin(a))
        p.addEllipse(QPointF(12, 12), 6, 6)
    elif key == "chat":
        p.moveTo(4, 5)
        p.lineTo(20, 5)
        p.lineTo(20, 16)
        p.lineTo(11, 16)
        p.lineTo(6, 20)
        p.lineTo(7, 16)
        p.lineTo(4, 16)
        p.closeSubpath()
    elif key == "progress":
        p.addRoundedRect(QRectF(3, 9, 18, 6), 3, 3)
        p.moveTo(6, 12)
        p.lineTo(13, 12)
    elif key == "view":
        p.moveTo(2, 12)
        p.cubicTo(5, 6, 9, 5, 12, 5)
        p.cubicTo(15, 5, 19, 6, 22, 12)
        p.cubicTo(19, 18, 15, 19, 12, 19)
        p.cubicTo(9, 19, 5, 18, 2, 12)
        p.addEllipse(QPointF(12, 12), 3, 3)
    elif key == "layout":
        p.addRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
        p.moveTo(9, 4)
        p.lineTo(9, 20)
        p.moveTo(9, 11)
        p.lineTo(21, 11)
    elif key == "ai":
        # 4 つの角の光（AI が描く）
        for cx, cy, r in ((10, 12, 7), (18.5, 5.5, 3)):
            p.moveTo(cx, cy - r)
            p.quadTo(cx, cy, cx + r, cy)
            p.quadTo(cx, cy, cx, cy + r)
            p.quadTo(cx, cy, cx - r, cy)
            p.quadTo(cx, cy, cx, cy - r)
    return p


class _Engine(QIconEngine):
    """描くたびに今のテーマの色を読むアイコン。テーマを替えても作り直さずに色が合う（明るいテーマで白い線が消えない）"""

    def __init__(self, key: str, color: str | None, active: str | None):
        super().__init__()
        self.key, self.color, self.active = key, color, active

    def _color(self, mode, state) -> QColor:
        from chatdraw.themes import current
        if mode == QIcon.Disabled:
            return QColor(current["muted"])
        if state == QIcon.On:
            return QColor(self.active or current["on"])   # 選んだ道具は差し色の地の上に描く
        if mode in (QIcon.Active, QIcon.Selected):
            return QColor(self.active or current["bartext"])
        return QColor(self.color or current["bartext"])   # アイコンはほとんど帯の上に並ぶ

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(rect.width(), rect.height())
        painter.translate(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2)
        painter.scale(side / 24, side / 24)
        painter.setPen(QPen(self._color(mode, state), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(_path(self.key))
        painter.restore()

    def pixmap(self, size, mode, state):
        pm = QPixmap(size.width() * 2, size.height() * 2)   # 高い画素密度の画面でも細い線がにじまない
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            self.paint(p, QRect(0, 0, size.width(), size.height()), mode, state)
        finally:
            p.end()   # 途中で落ちても描きかけのまま捨てない（捨てると Qt ごと落ちる）
        return pm

    def clone(self):
        return _Engine(self.key, self.color, self.active)


def icon(key: str, color: str | None = None, active: str | None = None, size: int = 24) -> QIcon:
    """key のアイコン。color を渡さなければ今のテーマの文字の色で描く"""
    return QIcon(_Engine(key, color, active))


KEYS = ("chat", "progress", "view", "layout", "new", "open", "save", "undo", "redo", "fit", "rotate", "rough", "models", "settings", "palette", "brush", "history", "layers", "help", "move", "select", "pen", "eraser", "blur", "fill", "gradient", "line", "rect", "ellipse", "eyedropper", "hand", "zoom", "ai")
