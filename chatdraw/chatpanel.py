"""チャットの欄。ふつうのチャットの形にする: 書く欄はいつも下、会話は上で流れ、吹き出しに時刻、
答えを待つ間は「入力中…」、Enter で送り Shift+Enter で改行、会話は閉じても残る。

前は 1 行の欄と文字の流れだけで、描く頼みと操作と質問が同じ欄に混ざり、会話として読み返せなかった。
描く内容は AI の欄に移し、ここは相談と操作の場にする。答えに描く内容の案があれば、吹き出しのボタンで AI の欄に入れる。
吹き出しの幅は欄の幅から毎回決める（決めた幅のままだと、欄を狭めたときに文が欄の外にはみ出して読めなかった）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

KEEP = 200   # 残す吹き出しの数（多すぎると開くのが遅くなる）


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
    def __init__(self, who: str, text: str, stamp: str | None = None):
        super().__init__()
        self.who, self.text = who, text
        self.stamp = stamp or time.strftime("%m/%d %H:%M")
        self.proposal: str | None = None   # 答えにあった描く内容の案（ボタンで AI の欄に入れる）
        self.setObjectName("bubbleMe" if who == "user" else "bubbleAi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(self.label)
        self.time = QLabel(self.stamp)
        self.time.setObjectName("bubbleTime")
        self.time.setStyleSheet("font-size: 10px; color: palette(mid);")
        self.time.setAlignment(Qt.AlignRight if who == "user" else Qt.AlignLeft)
        lay.addWidget(self.time)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(4)
        lay.addLayout(self.buttons)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.label.customContextMenuRequested.connect(lambda p: self._menu(self.label.mapTo(self, p)))

    def set_text(self, text: str):
        self.text = text
        self.label.setText(text)

    def copy(self):
        QGuiApplication.clipboard().setText(self.text)

    def _menu(self, pos):
        m = self.menu()
        m.exec(self.mapToGlobal(pos))

    def menu(self):
        m = QMenu(self)
        m.addAction("文をコピー", self.copy)
        w = self.window()
        if hasattr(w, "common_menu"):   # どこで右クリックしても、使える操作を出す
            m.addSeparator()
            w.common_menu(m)
        return m

    def add_button(self, label: str, tip: str, fn) -> QPushButton:
        b = QPushButton(label)
        b.setObjectName("suggest")
        b.setToolTip(tip)
        b.clicked.connect(fn)
        self.buttons.addWidget(b)
        return b


class Typing(QFrame):
    """答えを待つ間の「AI が入力中…」。点を動かして、止まっていないことを見せる"""

    def __init__(self):
        super().__init__()
        self.setObjectName("bubbleAi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.label = QLabel("AI が入力中")
        lay.addWidget(self.label)
        self.n = 0
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self.n = (self.n + 1) % 4
        self.setText("AI が入力中" + "・" * self.n)

    def setText(self, text: str):
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()


class ChatPanel(QWidget):
    sent = Signal(str)

    def __init__(self, store: Path | str | None = None):
        super().__init__()
        self.turns: list[tuple[str, str]] = []   # 言葉の模型に渡す会話（("user"|"ai", 文)）
        self.store: Path | None = None
        self.decorate = None   # 読み戻した案つきの吹き出しにボタンを付ける関数（アプリが渡す）
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(4)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inner = QWidget()
        inner.setObjectName("scrollInner")
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(6)
        self.list.addStretch()
        self.typing = Typing()
        self.typing.hide()
        self.list.addWidget(self.typing, 0, Qt.AlignLeft)
        self.scroll.setWidget(inner)
        bar = self.scroll.verticalScrollBar()
        self._follow = True   # いちばん下を見ているときだけ、新しい吹き出しで下へ送る（読み返している所を動かさない）
        bar.valueChanged.connect(self._scrolled)
        bar.rangeChanged.connect(self._range)   # 自分の関数にする（閉じる途中に消えた棒を触って落ちた）
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
        lay.addLayout(row)   # 書く欄は欄の下に固定する（会話の量で上下しない）
        if store is not None:
            self.set_store(store)

    def _scrolled(self, v: int):
        self._follow = v >= self.scroll.verticalScrollBar().maximum() - 4

    def _range(self, _lo: int, hi: int):
        if self._follow:
            self.scroll.verticalScrollBar().setValue(hi)

    def bubbles(self) -> list[Bubble]:
        return [self.list.itemAt(i).widget() for i in range(self.list.count()) if isinstance(self.list.itemAt(i).widget(), Bubble)]

    def add(self, who: str, text: str, remember: bool = True, stamp: str | None = None, save: bool = True) -> Bubble:
        """吹き出しを足して、いちばん下まで送る。who は "user" か "ai"。「入力中…」は常にいちばん下に置く"""
        b = Bubble(who, text, stamp)
        b.remember = remember
        self.list.insertWidget(self.list.indexOf(self.typing), b, 0, Qt.AlignRight if who == "user" else Qt.AlignLeft)
        self._fit(b)
        if remember:
            self.turns.append((who, text))
            del self.turns[:-20]
        self._follow = True
        if save:
            self.save()
        return b

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.sent.emit(text)

    def clear(self):
        for b in self.bubbles():
            self.list.removeWidget(b)
            b.hide()   # 消えるまでの間に、新しい吹き出しと重なって見えないように
            b.deleteLater()
        self.turns.clear()
        self.save()

    def set_busy(self, on: bool):
        """答えを待つ間は送るを止め、「入力中…」を出す"""
        self.send_button.setEnabled(not on)
        self.typing.setVisible(on)
        if on:
            self.typing.n = 0
            self.typing.setText("AI が入力中")
            self.typing.timer.start()
            self._follow = True
        else:
            self.typing.timer.stop()

    # ---- 残す・読み戻す ----
    def set_store(self, path: Path | str):
        """会話を残すファイルを決め、前の会話を読み戻す"""
        self.store = Path(path)
        try:
            rows = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        if not isinstance(rows, list):
            rows = []
        for r in rows[-KEEP:]:
            if not isinstance(r, dict) or r.get("who") not in ("user", "ai") or not isinstance(r.get("text"), str):
                continue
            b = self.add(r["who"], r["text"], remember=bool(r.get("remember", True)), stamp=r.get("time"), save=False)
            if r.get("proposal") and self.decorate is not None:
                self.decorate(b, r["proposal"], restored=True)

    def save(self):
        if self.store is None:
            return
        rows = [{"who": b.who, "text": b.text, "time": b.stamp, "remember": getattr(b, "remember", True),
                 **({"proposal": b.proposal} if b.proposal else {})} for b in self.bubbles()][-KEEP:]
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            part = self.store.with_suffix(".part")
            part.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            part.replace(self.store)
        except OSError:
            pass   # 残せなくても会話は続ける

    # ---- 幅 ----
    def resizeEvent(self, e):
        super().resizeEvent(e)
        for b in self.bubbles():
            self._fit(b)

    def _fit(self, b: Bubble):
        """吹き出しの幅を文の長さに合わせ、欄の 85% までにする。欄が狭いときは欄の幅いっぱいまで縮める
        （下限を決め打ちにすると、狭い欄で吹き出しが欄の外にはみ出した）"""
        room = max(60, self.scroll.viewport().width() - 4)
        most = min(room, max(160, int(room * 0.85)))
        lines = b.label.text().split("\n")
        want = max(b.label.fontMetrics().horizontalAdvance(x) for x in lines) + 26
        want = max(want, b.buttons.sizeHint().width() + 24, b.time.sizeHint().width() + 24)
        width = min(most, want)
        b.setFixedWidth(width)
        # 折り返した文の高さを幅から決める。決めないと、案の行を足したときに前の高さのまま文が重なって読めなかった
        b.label.setMinimumHeight(b.label.heightForWidth(width - 20))
