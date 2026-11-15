"""赤ペン先生。絵の上に赤ペンで直してほしい所を囲み、番号ごとに直し方を書くと、AI がその所だけを描き直す。

赤ペンの印は絵とは別に持ち、保存する絵にも AI に渡す絵にも入れない（印ごと描き直されないように）。
1 本の線が 1 か所で、描いた順に番号が付く。囲んだ線は中まで直す所にする（丸で囲めば中身ごと直す）。
印の取り方は 5 つ: 手で描く（free）、丸（ellipse）、四角（rect）、全体（all）、AI の自動選択（auto）。手で描く印は線の並びで持ち、
ほかの印は形（QPainterPath）で持つ。形の印は形の中だけを直す所にし、線の周りを太らせない（囲みの外を変えないため）。
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
        self.shapes: list[QPainterPath | None] = []   # 印ごとの形（手で描いた印は None）
        self.preview: QPainterPath | None = None   # 丸・四角を引いている間の形
        self.hidden: list[bool] = []   # 印ごとに隠したか（レイヤーの欄の「赤ペン n」の印で切り替える）
        self.focus = 0   # 指示を見せる印の番号（カーソルを合わせた・欄で選んだ印だけ。札を出しっぱなしにすると絵が隠れる）
        self.drawing: list[QPointF] | None = None
        self.size = (0, 0)
        self.undone: list[tuple] = []   # 元に戻した印（やり直すで戻す）
        self.on_change = None   # 印が増えた・消えたときに呼ぶ（レイヤーの欄に「赤ペン」を出し入れする）
        self.setZValue(1e9 - 2)
        self.setAcceptHoverEvents(True)

    def hoverMoveEvent(self, e):
        n = self.number_at(e.pos(), max(0.05, self.scene().views()[0].transform().m11()) if self.scene() and self.scene().views() else 1.0)
        if n != self.focus:
            self.focus = n
            self.update()

    def hoverLeaveEvent(self, e):
        if self.focus:
            self.focus = 0
            self.update()

    def set_focus(self, n: int):
        self.focus = n
        self.update()

    def set_hidden(self, n: int, hidden: bool):
        """番号 n（1 から）の印を隠す・出す。隠した印は AI にも渡さない"""
        if 1 <= n <= len(self.hidden):
            self.hidden[n - 1] = hidden
            self.update()

    def set_text(self, n: int, note: str):
        if 1 <= n <= len(self.texts):
            self.texts[n - 1] = note.strip()
            self.update()

    def shown(self) -> list[int]:
        """隠していない印の番号（1 から）"""
        return [n for n in range(1, len(self.marks) + 1) if not (n - 1 < len(self.hidden) and self.hidden[n - 1])]

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
        self.shapes.append(None)
        self.hidden.append(False)
        self.update()

    def add_shape(self, path: QPainterPath) -> int:
        """形の印を 1 つ足す（丸・四角・全体・自動選択）。番号の丸は形の左上に置く。足した印の番号を返す（空の形は 0）"""
        w, h = self.size
        whole = QPainterPath()
        whole.addRect(QRectF(0, 0, w, h))
        path = QPainterPath(path).intersected(whole) if w and h else QPainterPath(path)
        r = path.boundingRect()
        if r.width() < 2 or r.height() < 2:
            return 0
        self.preview = None
        self.marks.append([QPointF(r.left() + 14, r.top() + 14)])
        self.texts.append("")
        self.shapes.append(path)
        self.hidden.append(False)
        self.undone.clear()
        self.update()
        self._changed()
        return len(self.marks)

    def set_preview(self, path: QPainterPath | None):
        self.preview = path
        self.update()

    def add(self, pos: QPointF):
        if self.drawing is not None and (pos - self.drawing[-1]).manhattanLength() >= 2:
            self.drawing.append(QPointF(pos))
            self.update()

    def end(self):
        self.drawing = None
        self.undone.clear()
        self.update()
        self._changed()

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    def undo(self) -> bool:
        """最後の印を外す（やり直すで戻せる）"""
        if not self.marks:
            return False
        self.undone.append((self.marks.pop(), self.texts.pop(), self.shapes.pop() if self.shapes else None))
        self.hidden.pop()
        self.update()
        self._changed()
        return True

    def redo(self) -> bool:
        if not self.undone:
            return False
        pts, note, *rest = self.undone.pop()
        self.marks.append(pts)
        self.texts.append(note)
        self.shapes.append(rest[0] if rest else None)
        self.hidden.append(False)
        self.update()
        self._changed()
        return True

    def remove(self, n: int):
        """番号 n（1 から）の印だけを消す。元に戻すで戻せる"""
        if 1 <= n <= len(self.marks):
            self._fill_shapes()
            self.undone.append((self.marks.pop(n - 1), self.texts.pop(n - 1), self.shapes.pop(n - 1)))
            self.hidden.pop(n - 1)
            self.focus = 0
            self.update()
            self._changed()

    def clear(self):
        self.marks.clear()
        self.texts.clear()
        self.shapes.clear()
        self.preview = None
        self.hidden.clear()
        self.focus = 0
        self.drawing = None
        self.update()
        self._changed()

    def _fill_shapes(self):
        """shapes を marks と同じ長さにする（前の版の作業や、外から marks に足した印は手で描いた印として扱う）"""
        while len(self.shapes) < len(self.marks):
            self.shapes.append(None)

    def shape_of(self, n: int) -> QPainterPath | None:
        """番号 n（1 から）の印の形。手で描いた印は None。
        名前を shape にすると QGraphicsItem.shape()（当たり判定）を上書きし、カーソルを動かすと落ちた"""
        return self.shapes[n - 1] if 1 <= n <= len(self.shapes) else None

    # ---- 見せる ----
    def paint(self, p: QPainter, option, widget=None):
        if self.preview is not None:
            pen = QPen(RED, WIDTH, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(self.preview)
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
            if n - 1 < len(self.hidden) and self.hidden[n - 1]:
                continue
            p.setPen(pen)
            sh = self.shape_of(n)
            p.setBrush(QColor(255, 45, 45, 50) if sh is not None else Qt.NoBrush)
            p.drawPath(sh if sh is not None else _path(pts))
            r = 13 / scale
            c = pts[0] + QPointF(-r, -r)
            p.setPen(Qt.NoPen)
            p.setBrush(RED)
            p.drawEllipse(c, r, r)
            p.setPen(QColor("white"))
            p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(n))
            note = self.texts[n - 1] if n - 1 < len(self.texts) else ""
            if note and n == self.focus:   # 指示の札は、カーソルを合わせた・欄で選んだ印だけに出す（ほかは番号だけ）
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
            if n - 1 < len(self.hidden) and self.hidden[n - 1]:
                continue
            c = pts[0] + QPointF(-r, -r)
            if (pos - c).manhattanLength() <= r * 1.6:
                return n
        return 0

    # ---- AI に渡す ----
    def masks(self) -> list[QImage]:
        """印ごとの直す所（白が直す所、絵と同じ大きさ）。囲んだ線は中まで白にする。
        隠した印は空の白黒（直す所なし）にして、texts と番号の並びを崩さない"""
        out = []
        w, h = self.size
        for i, pts in enumerate(self.marks):
            m = QImage(w, h, QImage.Format_Grayscale8)
            m.fill(0)
            q = QPainter(m)
            q.setRenderHint(QPainter.Antialiasing)
            if i < len(self.hidden) and self.hidden[i]:
                q.end()
                out.append(m)
                continue
            sh = self.shape_of(i + 1)
            if sh is not None:   # 形の印は形の中だけ（線で太らせない）
                q.fillPath(sh, QColor("white"))
                q.end()
                out.append(m)
                continue
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
