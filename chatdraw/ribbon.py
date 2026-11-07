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
        # 頁が窓より広いときは横に流して見せる（頁の幅がそのまま窓の最小の幅になり、1280 の画面に収まらなかった）
        from PySide6.QtWidgets import QScrollArea
        from PySide6.QtCore import Qt
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setMinimumHeight(page.sizeHint().height())
        self.addTab(area, title)

    def _clicked(self, i: int):
        """開いているタブをもう 1 回押すと畳む。畳んでいるときにタブを押すと広げる"""
        if self.collapsed:
            self.set_collapsed(False)
        elif i == self.currentIndex():
            self.set_collapsed(True)
            win = self.window()
            if hasattr(win, "feature_tour"):
                win.feature_tour("ribbon")

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


def move_tabs(ribbon: QTabWidget, names: list[str]) -> None:
    """リボンのタブを names の順に並べる（タブを動かすと tabMoved が出て、並びが残る）"""
    bar = ribbon.tabBar()
    for i, name in enumerate(names):
        j = next((k for k in range(ribbon.count()) if ribbon.tabText(k) == name), -1)
        if j >= 0 and j != i:
            bar.moveTab(j, i)


class OrderDialog:
    """リボンのタブの並びを変える窓。行をドラッグするか、上へ・下へで動かし、「決める」で当てる"""

    def __init__(self, ribbon: QTabWidget, parent=None):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QPushButton
        self.ribbon = ribbon
        self.dialog = d = QDialog(parent)
        d.setWindowTitle("リボンの並び")
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setToolTip("行をドラッグして並べ替えます")
        for k in range(ribbon.count()):
            self.list.addItem(ribbon.tabText(k))
        self.list.setCurrentRow(0)
        up, down = QPushButton("上へ"), QPushButton("下へ")
        up.setToolTip("選んだタブを 1 つ前（左）へ")
        down.setToolTip("選んだタブを 1 つ後ろ（右）へ")
        up.clicked.connect(lambda: self.step(-1))
        down.clicked.connect(lambda: self.step(1))
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("決める")
        box.button(QDialogButtonBox.Cancel).setText("やめる")
        box.accepted.connect(self.apply)
        box.rejected.connect(d.reject)
        side = QVBoxLayout()
        side.addWidget(up)
        side.addWidget(down)
        side.addStretch()
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(side)
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("左から右の並びを、上から下に並べています"))
        lay.addLayout(row)
        lay.addWidget(box)
        self.up, self.down, self.buttons = up, down, box

    def names(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def step(self, d: int):
        i = self.list.currentRow()
        j = i + d
        if 0 <= i < self.list.count() and 0 <= j < self.list.count():
            it = self.list.takeItem(i)
            self.list.insertItem(j, it)
            self.list.setCurrentRow(j)

    def apply(self):
        move_tabs(self.ribbon, self.names())
        self.dialog.accept()

    def exec(self) -> int:
        return self.dialog.exec()
