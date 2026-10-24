"""赤ペン先生。絵の上に赤ペンで直してほしい所を囲み、番号ごとに直し方を書くと、AI がその所だけを描き直す。

赤ペンの印は絵とは別に持ち、保存する絵にも AI に渡す絵にも入れない（印ごと描き直されないように）。
1 本の線が 1 か所で、描いた順に番号が付く。囲んだ線は中まで直す所にする（丸で囲めば中身ごと直す）。
指示は「1: 手を直して」「2 帽子を青に」のように番号で書き分ける。番号の無い文は、すべての所に効く。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

RED = QColor("#ff2d2d")
WIDTH = 4          # 画面に出す線の太さ（拡大しても変えない）
MASK_WIDTH = 28    # 直す所にするときの線の太さ（線の周りも少し直す）
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


class RedPen(QGraphicsItem):
    """赤ペンの印（線の並び）。キャンバスのいちばん上に重ねて見せる"""

    def __init__(self):
        super().__init__()
        self.marks: list[list[QPointF]] = []
        self.texts: list[str] = []   # 印ごとに絵の上へ直接書いた指示（空ならチャットの文を使う）
        self.drawing: list[QPointF] | None = None
        self.size = (0, 0)
        self.setZValue(1e9 - 2)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, *self.size)

    def set_size(self, w: int, h: int):
        self.prepareGeometryChange()
        self.size = (w, h)
        self.clear()

    # ---- 描く ----
    def begin(self, pos: QPointF):
        self.drawing = [QPointF(pos)]
        self.marks.append(self.drawing)
        self.texts.append("")
        self.update()

    def add(self, pos: QPointF):
        if self.drawing is not None and (pos - self.drawing[-1]).manhattanLength() >= 2:
            self.drawing.append(QPointF(pos))
            self.update()

    def end(self):
        self.drawing = None
        self.update()

    def undo(self):
        if self.marks:
            self.marks.pop()
            self.texts.pop()
            self.update()

    def clear(self):
        self.marks.clear()
        self.texts.clear()
        self.drawing = None
        self.update()

    # ---- 見せる ----
    def paint(self, p: QPainter, option, widget=None):
        if not self.marks:
            return
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(RED, WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        pen.setCosmetic(True)
        scale = max(0.05, p.worldTransform().m11())
        f = QFont()
        f.setBold(True)
        f.setPixelSize(max(8, int(18 / scale)))
        p.setFont(f)
        for n, pts in enumerate(self.marks, 1):
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(_path(pts))
            r = 13 / scale
            c = pts[0] + QPointF(-r, -r)
            p.setPen(Qt.NoPen)
            p.setBrush(RED)
            p.drawEllipse(c, r, r)
            p.setPen(QColor("white"))
            p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(n))
            note = self.texts[n - 1] if n - 1 < len(self.texts) else ""
            if note:   # 絵の上に書いた指示を、番号の横に赤い札で見せる
                fm = p.fontMetrics()
                box = QRectF(c.x() + r * 1.3, c.y() - r, fm.horizontalAdvance(note) + 12 / scale, 2 * r)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 45, 45, 225))
                p.drawRoundedRect(box, 6 / scale, 6 / scale)
                p.setPen(QColor("white"))
                p.drawText(box, Qt.AlignCenter, note)

    def number_at(self, pos: QPointF, scale: float = 1.0) -> int:
        """pos にある番号の丸（1 から）。無ければ 0。丸をダブルクリックすると指示を書き直せる"""
        r = 13 / max(0.05, scale)
        for n, pts in enumerate(self.marks, 1):
            c = pts[0] + QPointF(-r, -r)
            if (pos - c).manhattanLength() <= r * 1.6:
                return n
        return 0

    # ---- AI に渡す ----
    def masks(self) -> list[QImage]:
        """印ごとの直す所（白が直す所、絵と同じ大きさ）。囲んだ線は中まで白にする"""
        out = []
        w, h = self.size
        for pts in self.marks:
            m = QImage(w, h, QImage.Format_Grayscale8)
            m.fill(0)
            q = QPainter(m)
            q.setRenderHint(QPainter.Antialiasing)
            path = _path(pts)
            if _closed(pts):
                q.fillPath(path, QColor("white"))
            q.setPen(QPen(QColor("white"), MASK_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            q.drawPath(path)
            q.end()
            out.append(m)
        return out


def _path(pts: list[QPointF]) -> QPainterPath:
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    if len(pts) == 1:
        path.addEllipse(pts[0], 1, 1)
    return path


def _closed(pts: list[QPointF]) -> bool:
    """線の始めと終わりが近ければ、囲んだとみなす（囲みの大きさの 3 割まで離れていてよい）"""
    if len(pts) < 8:
        return False
    xs, ys = [p.x() for p in pts], [p.y() for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    return (pts[0] - pts[-1]).manhattanLength() <= max(30.0, span * 0.3)


def merge(texts: list[str], text: str) -> list[str]:
    """絵の上に書いた指示を先に使い、書いていない印はチャットの文（番号ごとの指示か、全体の指示）を使う"""
    chat = notes(text, len(texts)) if text else [""] * len(texts)
    return [t.strip() or c for t, c in zip(texts, chat)]


def notes(text: str, count: int) -> list[str]:
    """チャットの文から、印の番号ごとの指示を取り出す。番号の無い文は、すべての印に付ける"""
    per: dict[int, list[str]] = {}
    common: list[str] = []
    for part in re.split(r"[\n、。]|(?=[①-⑳])|(?=(?<!\d)\d+\s*[:：.)）番\s])", text):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([①-⑳]|\d+)\s*(?:番(?:目)?(?:は|を)?|[:：.)）])?\s*(.*)$", part)
        if m and (m.group(1) in CIRCLED or m.group(1).isdigit()) and m.group(2):
            n = CIRCLED.index(m.group(1)) + 1 if m.group(1) in CIRCLED else int(m.group(1))
            if 1 <= n <= count:
                per.setdefault(n, []).append(m.group(2).strip())
                continue
        common.append(part)
    return ["、".join(per.get(n, []) + common) for n in range(1, count + 1)]
