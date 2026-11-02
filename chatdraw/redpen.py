"""赤ペン先生。絵の上に赤ペンで直してほしい所を囲み、番号ごとに直し方を書くと、AI がその所だけを描き直す。

赤ペンの印は絵とは別に持ち、保存する絵にも AI に渡す絵にも入れない（印ごと描き直されないように）。
1 本の線が 1 か所で、描いた順に番号が付く。囲んだ線は中まで直す所にする（丸で囲めば中身ごと直す）。
指示は「1: 手を直して」「2 帽子を青に」のように番号で書き分ける。番号の無い文は、すべての所に効く。

印はレイヤーの欄に 1 つずつ「赤ペン 1」「赤ペン 2」… の行で出し、指示はその行のコメントとして持つ。
前は指示を絵の上の赤い札でいつも出していて、絵が見えず邪魔だった。札は、その印の行を選んでいるときか、
番号の丸にカーソルを合わせたときだけ出す。隠した印は線を見せないが、直すときは使う（隠すのは見た目だけ）。
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
        self.hidden: list[bool] = []   # 印ごとに隠しているか（レイヤーの欄のチェック）
        self.active = 0   # レイヤーの欄で選んでいる印の番号（1 から。0 は選んでいない）。この印だけ札を出す
        self.hover = 0    # カーソルを合わせている番号の丸。この印も札を出す
        self.drawing: list[QPointF] | None = None
        self.size = (0, 0)
        self.undone: list[tuple[list[QPointF], str]] = []   # 元に戻した印（やり直すで戻す）
        self.on_change = None   # 印が増えた・消えたときに呼ぶ（レイヤーの欄に「赤ペン」を出し入れする）
        self.setZValue(1e9 - 2)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, *self.size)

    def set_size(self, w: int, h: int):
        self.prepareGeometryChange()
        self.size = (w, h)
        self.clear()

    # ---- 描く ----
    def begin(self, pos: QPointF):
        self._sync()
        self.drawing = [QPointF(pos)]
        self.marks.append(self.drawing)
        self.texts.append("")
        self.hidden.append(False)
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
        self._sync()
        if self.active > len(self.marks):
            self.active = 0
        if self.hover > len(self.marks):
            self.hover = 0
        if self.on_change is not None:
            self.on_change()

    def _sync(self):
        """隠す印の並びを印の数にそろえる（保存した絵を開いたときなど、印と指示だけを足す所がある）"""
        n = len(self.marks)
        for seq, empty in ((self.hidden, False), (self.texts, "")):   # 並びは作り直さず、その場で足し引きする
            seq.extend([empty] * (n - len(seq)))
            del seq[n:]

    def _take(self, i: int):
        self._sync()
        return self.marks.pop(i), self.texts.pop(i), self.hidden.pop(i)

    def _put(self, item, i: int | None = None):
        pts, note, hide = (tuple(item) + (False,))[:3]
        self._sync()
        i = len(self.marks) if i is None else i
        self.marks.insert(i, pts)
        self.texts.insert(i, note)
        self.hidden.insert(i, hide)

    def undo(self) -> bool:
        """最後の印を外す（やり直すで戻せる）"""
        if not self.marks:
            return False
        self.undone.append(self._take(len(self.marks) - 1))
        self.update()
        self._changed()
        return True

    def redo(self) -> bool:
        if not self.undone:
            return False
        self._put(self.undone.pop())
        self.update()
        self._changed()
        return True

    def remove(self, n: int):
        """番号 n（1 から）の印だけを消す。元に戻すで戻せる"""
        if 1 <= n <= len(self.marks):
            self.undone.append(self._take(n - 1))
            if self.active == n:
                self.active = 0
            elif self.active > n:
                self.active -= 1
            self.update()
            self._changed()

    def move(self, n: int, to: int):
        """番号 n の印を to 番にする（レイヤーの欄の並べ替え）。番号は並びの順に振り直す"""
        if 1 <= n <= len(self.marks) and 1 <= to <= len(self.marks) and n != to:
            keep = self.marks[self.active - 1] if 1 <= self.active <= len(self.marks) else None
            self._put(self._take(n - 1), to - 1)
            if keep is not None:   # 選んでいた印は、番号が変わっても同じ印を選んだままにする
                self.active = next(i for i, pts in enumerate(self.marks, 1) if pts is keep)
            self.update()
            self._changed()

    def set_hidden(self, n: int, hide: bool):
        self._sync()
        if 1 <= n <= len(self.marks) and self.hidden[n - 1] != hide:
            self.hidden[n - 1] = hide
            self.update()
            self._changed()

    def set_note(self, n: int, note: str):
        """番号 n の印の指示（レイヤーの行のコメント）を書き直す"""
        self._sync()
        if 1 <= n <= len(self.marks):
            self.texts[n - 1] = note.strip()
            self.update()
            self._changed()

    def set_active(self, n: int):
        if n != self.active:
            self.active = n if 1 <= n <= len(self.marks) else 0
            self.update()

    def set_hover(self, n: int):
        if n != self.hover:
            self.hover = n
            self.update()

    def shown_notes(self) -> list[int]:
        """絵の上に札を出している印の番号（選んでいる印と、カーソルを合わせた印だけ）"""
        self._sync()
        return [n for n in sorted({self.active, self.hover})
                if 1 <= n <= len(self.marks) and self.texts[n - 1] and not self.hidden[n - 1]]

    def clear(self):
        self.marks.clear()
        self.texts.clear()
        self.hidden.clear()
        self.active = self.hover = 0
        self.drawing = None
        self.update()
        self._changed()

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
        self._sync()
        labels = self.shown_notes()
        for n, pts in enumerate(self.marks, 1):
            if self.hidden[n - 1]:
                continue
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
            note = self.texts[n - 1] if n in labels else ""
            if note:   # 選んでいる印・カーソルを合わせた印だけ、指示を番号の横に赤い札で見せる
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
        self._sync()
        for n, pts in enumerate(self.marks, 1):
            if self.hidden[n - 1]:
                continue
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
