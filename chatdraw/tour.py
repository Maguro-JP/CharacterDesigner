"""使い方のツアー。画面を暗くして 1 か所ずつ明るく抜き、その横に短い説明を出す。

初めて起動したときに 1 回出し、あとは「ヘルプ」の「使い方ツアー」からいつでも出せる。
説明は 1 か所につき 2 行まで。読まなくても、明るく抜いた所を見れば何がどこにあるか分かることを目指す。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


@dataclass
class Step:
    target: Callable[[], QWidget | None]   # 明るく抜く部品（無ければ画面の真ん中に説明だけ出す）
    title: str
    text: str
    before: Callable[[], None] | None = None   # 見せる前に開いておく物（隠れた欄など）


class Tour(QWidget):
    def __init__(self, window, steps: list[Step], on_close=None):
        super().__init__(window)
        self.window_, self.steps, self.i, self.on_close = window, steps, 0, on_close
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.card = QFrame(self)
        self.card.setObjectName("tourCard")
        self.card.setAttribute(Qt.WA_StyledBackground)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(16, 14, 16, 12)
        self.count = QLabel()
        self.count.setObjectName("cardMeta")
        self.title = QLabel()
        self.title.setObjectName("dialogTitle")
        self.text = QLabel()
        self.text.setWordWrap(True)
        row = QHBoxLayout()
        self.skip = QPushButton("閉じる")
        self.skip.clicked.connect(self.finish)
        self.back = QPushButton("戻る")
        self.back.clicked.connect(lambda: self.show_step(self.i - 1))
        self.next = QPushButton("次へ")
        self.next.setObjectName("primary")
        self.next.clicked.connect(lambda: self.show_step(self.i + 1))
        row.addWidget(self.skip)
        row.addStretch()
        row.addWidget(self.back)
        row.addWidget(self.next)
        for w in (self.count, self.title, self.text):
            lay.addWidget(w)
        lay.addLayout(row)
        self.card.setFixedWidth(320)
        window.installEventFilter(self)

    def start(self):
        self.setGeometry(self.window_.rect())
        from chatdraw.motion import fade_in
        fade_in(self)
        self.raise_()
        self.show_step(0)

    def hole(self) -> QRect | None:
        w = self.steps[self.i].target()
        if w is None or not w.isVisible():
            return None
        top_left = w.mapTo(self.window_, w.rect().topLeft())
        return QRect(top_left.x(), top_left.y(), w.width(), w.height()).adjusted(-4, -4, 4, 4)   # キャンバスの size は筆の太さ

    def show_step(self, i: int):
        if i >= len(self.steps):
            self.finish()
            return
        self.i = max(0, i)
        step = self.steps[self.i]
        if step.before:
            step.before()
        self.raise_()   # 開いた欄が前に出るので、案内をその上に戻す
        self.count.setText(f"{self.i + 1} / {len(self.steps)}")
        self.title.setText(step.title)
        self.text.setText(step.text)
        one = len(self.steps) == 1   # 機能ごとの短い案内は、数と「戻る」を出さない
        self.count.setVisible(not one)
        self.back.setVisible(not one)
        self.back.setEnabled(self.i > 0)
        self.next.setText("わかった" if one else "はじめる" if self.i == len(self.steps) - 1 else "次へ")
        self.card.adjustSize()
        self._place()
        from chatdraw.motion import slide_in
        slide_in(self.card, self.card.pos(), dy=12)   # 札は次の所へ滑り込ませる
        self.update()

    def _place(self):
        """説明の札を、明るく抜いた所の横（入らなければ下か上）に置く。抜く所が無ければ真ん中"""
        r, W, H = self.hole(), self.width(), self.height()
        cw, ch = self.card.width(), self.card.sizeHint().height()
        if r is None:
            x, y = (W - cw) // 2, (H - ch) // 2
        elif r.right() + 16 + cw < W:
            x, y = r.right() + 16, r.top()
        elif r.left() - 16 - cw > 0:
            x, y = r.left() - 16 - cw, r.top()
        elif r.bottom() + 16 + ch < H:
            x, y = r.left(), r.bottom() + 16
        elif r.top() - 16 - ch > 0:
            x, y = r.left(), r.top() - 16 - ch
        else:
            x, y = r.right() - cw - 16, r.bottom() - ch - 16   # 外に入らない大きな所（キャンバス）は、その中の右下に置く
        self.card.move(max(8, min(x, W - cw - 8)), max(8, min(y, H - ch - 8)))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        r = self.hole()
        if r is not None:
            inner = QPainterPath()
            inner.addRoundedRect(QRectF(r), 10, 10)
            path = path.subtracted(inner)
        p.fillPath(path, QColor(0, 0, 0, 170))
        if r is not None:
            p.setPen(QPen(QColor("#ff7a1a"), 2))
            p.drawRoundedRect(QRectF(r), 10, 10)

    def eventFilter(self, obj, e):
        if obj is self.window_ and e.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(self.window_.rect())
            self._place()
        return False

    def mousePressEvent(self, e):
        e.accept()   # 暗い所を押しても後ろの部品は動かさない

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.finish()
        elif e.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self.show_step(self.i + 1)
        elif e.key() == Qt.Key_Left:
            self.show_step(self.i - 1)

    def finish(self):
        self.window_.removeEventFilter(self)
        if self.on_close:
            self.on_close()
        from chatdraw.motion import fade_out
        fade_out(self, then=self.deleteLater)
