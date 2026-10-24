"""上部のリボン。タブ（ホーム・描く・AI・表示）ごとに、よく使う操作を大きなアイコンと名前で並べる。

メニューを開かなくても、見れば何ができるか分かることを目指す。タブを 2 回押すと畳み、もう 1 回押すと広げる（作業の場所を広く取る）。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTabWidget, QToolButton, QVBoxLayout, QWidget


def group(title: str, actions: list[QAction]) -> QWidget:
    """名前の付いたまとまり。アイコンの下に名前を出す"""
    box = QWidget()
    box.setObjectName("ribbonGroup")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(6, 2, 6, 0)
    lay.setSpacing(0)
    row = QHBoxLayout()
    row.setSpacing(2)
    for act in actions:
        b = QToolButton()
        b.setDefaultAction(act)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(22, 22))
        b.setMinimumWidth(52)
        b.setAutoRaise(True)
        row.addWidget(b)
    lay.addLayout(row)
    name = QLabel(title)
    name.setAlignment(Qt.AlignCenter)
    name.setObjectName("ribbonGroupName")
    lay.addWidget(name)
    return box


class Ribbon(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("ribbon")
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)   # タブの下の白い線を消す
        self.collapsed = False
        self.tabBarClicked.connect(self._clicked)

    def add_page(self, title: str, groups: list[tuple[str, list[QAction]]]):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(0)
        for i, (name, acts) in enumerate(groups):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.VLine)
                line.setObjectName("ribbonSep")
                lay.addWidget(line)
            lay.addWidget(group(name, acts))
        lay.addStretch()
        self.addTab(page, title)

    def _clicked(self, i: int):
        """開いているタブをもう 1 回押すと畳む。畳んでいるときにタブを押すと広げる"""
        if self.collapsed:
            self.set_collapsed(False)
        elif i == self.currentIndex():
            self.set_collapsed(True)

    def set_collapsed(self, on: bool):
        """畳む・広げる。高さを動かして見せる"""
        from chatdraw.motion import resize_height
        self.collapsed = on
        head = self.tabBar().sizeHint().height() + 2
        if on:
            self.full = self.height()

            def done():
                for i in range(self.count()):
                    self.widget(i).setVisible(False)
            resize_height(self, self.full, head, then=done)
        else:
            for i in range(self.count()):
                self.widget(i).setVisible(True)
            resize_height(self, head, getattr(self, "full", 110) or 110, then=lambda: self.setMaximumHeight(16777215))
