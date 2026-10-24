"""知らせのポップアップ。ウィンドウの右下に短く出て、数秒で消える（作業を止めない）。

描けた・止めた・保存した・模型を替えた・失敗した、のように、気づいてほしいことだけに使う。
押すと、その知らせに結びついた操作（描いた絵を開く、など）をする。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

COLORS = {"ok": "#7ccf5a", "info": "#ff7a1a", "error": "#e5322d"}


class Notice(QFrame):
    def __init__(self, window, text: str, kind: str = "info", ms: int = 3500, on_click=None, detail: str = ""):
        super().__init__(window)
        self.window_, self.on_click = window, on_click
        self.setObjectName("notice")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet(f"QFrame#notice {{ border-left: 4px solid {COLORS.get(kind, COLORS['info'])}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        col = QVBoxLayout()
        title = QLabel(text)
        title.setObjectName("noticeTitle")
        col.addWidget(title)
        if detail:
            d = QLabel(detail)
            d.setObjectName("cardMeta")
            d.setWordWrap(True)
            col.addWidget(d)
        lay.addLayout(col)
        self.setFixedWidth(300)
        self.adjustSize()
        if on_click:
            self.setCursor(Qt.PointingHandCursor)
        window.installEventFilter(self)
        stack = [n for n in window.findChildren(Notice) if n is not self and n.isVisible()]
        self.offset = sum(n.height() + 8 for n in stack)   # 前の知らせの上に積む
        self._place()
        self.show()
        self.raise_()
        QTimer.singleShot(ms, self.close_)

    def _place(self):
        w = self.window_
        bottom = w.statusBar().height() if w.statusBar().isVisible() else 0
        self.move(w.width() - self.width() - 16, w.height() - bottom - self.height() - 16 - self.offset)

    def eventFilter(self, obj, e):
        if obj is self.window_ and e.type() == QEvent.Resize:
            self._place()
        return False

    def mousePressEvent(self, e):
        if self.on_click:
            self.on_click()
        self.close_()

    def close_(self):
        self.window_.removeEventFilter(self)
        self.hide()
        self.deleteLater()
