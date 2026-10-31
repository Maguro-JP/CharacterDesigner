"""チャットの欄。発言を吹き出しで積み、複数行で書ける欄から送る。

前は 1 行の欄と文字の流れだけで、描く頼みと操作と質問が同じ欄に混ざり、会話として読み返せなかった。
描く内容は AI の欄に移し、ここは相談と操作の場にする。答えに描く内容の案があれば、吹き出しのボタンで AI の欄に入れる。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)


class EnterEdit(QPlainTextEdit):
    """複数行の書く欄。Enter で送り、Shift+Enter で改行する。QLineEdit と同じ text / setText も持つ"""
    returnPressed = Signal()

    def __init__(self, placeholder: str = "", lines: int = 2):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        h = self.fontMetrics().lineSpacing() * lines + 14
        self.setMinimumHeight(h)
        self.setMaximumHeight(h * 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(h)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.returnPressed.emit()
            return
        super().keyPressEvent(e)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str):
        self.setPlainText(text)
        c = self.textCursor()
        c.movePosition(c.MoveOperation.End)
        self.setTextCursor(c)


class Bubble(QFrame):
    def __init__(self, who: str, text: str):
        super().__init__()
        self.who, self.text = who, text
        self.setObjectName("bubbleMe" if who == "user" else "bubbleAi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setContextMenuPolicy(Qt.NoContextMenu)
        lay.addWidget(self.label)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(4)
        lay.addLayout(self.buttons)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.label.customContextMenuRequested.connect(lambda p: self._menu(self.label.mapTo(self, p)))

    def copy(self):
        QGuiApplication.clipboard().setText(self.text)

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("文をコピー", self.copy)
        m.exec(self.mapToGlobal(pos))

    def add_button(self, label: str, tip: str, fn) -> QPushButton:
        b = QPushButton(label)
        b.setObjectName("suggest")
        b.setToolTip(tip)
        b.clicked.connect(fn)
        self.buttons.addWidget(b)
        return b


class ChatPanel(QWidget):
    sent = Signal(str)

    def __init__(self):
        super().__init__()
        self.turns: list[tuple[str, str]] = []   # 言葉の模型に渡す会話（("user"|"ai", 文)）
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(4)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("scrollInner")
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(6)
        self.list.addStretch()
        self.scroll.setWidget(inner)
        bar = self.scroll.verticalScrollBar()
        self._follow = True   # いちばん下を見ているときだけ、新しい吹き出しで下へ送る（読み返している所を動かさない）
        # 自分の関数につなぐ。前は bar を閉じ込めた lambda で、欄を閉じたあとも呼ばれて
        # 「QScrollBar already deleted」の例外を出し続けた（自分の関数なら、欄と一緒に切れる）
        bar.valueChanged.connect(self._scrolled)
        bar.rangeChanged.connect(self._grown)
        lay.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        self.input = EnterEdit("AI に話しかける（使い方の質問、絵の相談、「ペンにして」などの操作）", lines=2)
        self.input.setToolTip("Enter で送ります。Shift+Enter で改行します")
        self.input.returnPressed.connect(self.send)
        self.send_button = QPushButton("送る")
        self.send_button.setToolTip("書いた言葉を AI に送ります（Enter）")
        self.send_button.clicked.connect(self.send)
        self.clear_button = QPushButton("消す")
        self.clear_button.setToolTip("会話の履歴を消します")
        self.clear_button.clicked.connect(self.clear)
        side = QVBoxLayout()
        side.setSpacing(2)
        side.addWidget(self.send_button)
        side.addWidget(self.clear_button)
        row.addWidget(self.input, 1)
        row.addLayout(side)
        lay.addLayout(row)

    def bubbles(self) -> list[Bubble]:
        return [self.list.itemAt(i).widget() for i in range(self.list.count()) if isinstance(self.list.itemAt(i).widget(), Bubble)]

    def add(self, who: str, text: str, remember: bool = True) -> Bubble:
        """吹き出しを足して、いちばん下まで送る。who は "user" か "ai" """
        b = Bubble(who, text)
        self.list.addWidget(b, 0, Qt.AlignRight if who == "user" else Qt.AlignLeft)
        self._fit(b)
        if remember:
            self.turns.append((who, text))
            del self.turns[:-20]
        self._follow = True
        return b

    def _scrolled(self, v: int):
        self._follow = v >= self.scroll.verticalScrollBar().maximum() - 4

    def _grown(self, _lo: int, hi: int):
        if self._follow:
            self.scroll.verticalScrollBar().setValue(hi)

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.sent.emit(text)

    def clear(self):
        for b in self.bubbles():
            self.list.removeWidget(b)
            b.deleteLater()
        self.turns.clear()

    def set_busy(self, on: bool):
        self.send_button.setEnabled(not on)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for b in self.bubbles():
            self._fit(b)

    def _fit(self, b: Bubble):
        """吹き出しの幅を文の長さに合わせる（寄せて並べると、折り返す文の幅が 1 字まで縮んだ）。広くても欄の 85% まで"""
        most = max(160, int(self.scroll.viewport().width() * 0.85))
        lines = b.label.text().split("\n")
        want = max(b.label.fontMetrics().horizontalAdvance(x) for x in lines) + 24
        want = max(want, b.buttons.sizeHint().width() + 24)
        b.setFixedWidth(min(most, want))
