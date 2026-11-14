"""上部のリボン。タブ（ホーム・描く・AI・表示）ごとに、よく使う操作を大きなアイコンと名前で並べる。

メニューを開かなくても、見れば何ができるか分かることを目指す。タブを 2 回押すと畳み、もう 1 回押すと広げる（作業の場所を広く取る）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QTabWidget, QToolButton, QVBoxLayout, QWidget

HOLD_MS = 450   # 押し続けて中の道具を出すまでの時間（Photoshop・CLIP STUDIO PAINT と同じく、長押しでも▼でも開く）


@dataclass
class Family:
    """同じ系統の道具を 1 つのボタンにまとめる（ペン系、選択、図形など）。ボタンは最後に選んだ道具を出す"""
    name: str
    actions: list = field(default_factory=list)
    tip: str = ""
    icon: object = None   # 渡すと、ボタンの顔を系統の名前とこのアイコンに固める（定規・対称のように、選ぶ物が設定のとき）


class FamilyButton(QToolButton):
    """系統のボタン。押すと今の道具、▼か長押しで中の道具を選ぶ。説明はツールチップに出す"""

    def __init__(self, fam: Family):
        super().__init__()
        self.family = fam
        self.setObjectName("ribbonFamily")
        m = QMenu(self)
        m.setToolTipsVisible(True)
        for a in fam.actions:
            m.addAction(a)
        self.setMenu(m)
        if fam.icon is not None:
            # 設定を選ぶ系統（定規・対称）。押すとすぐ中を出す。今の設定は印で見える
            self.setIcon(fam.icon)
            self.setText(fam.name)
            self.setToolTip((fam.tip or fam.name) + "。押して選びます")
            self.setPopupMode(QToolButton.InstantPopup)
            return
        self.setPopupMode(QToolButton.MenuButtonPopup)
        self.hold = QTimer(self, singleShot=True, interval=HOLD_MS, timeout=self.showMenu)
        self.pressed.connect(self.hold.start)
        self.released.connect(self.hold.stop)
        self.show_action(next((a for a in fam.actions if a.isCheckable() and a.isChecked()), fam.actions[0]))
        for a in fam.actions:
            # 中の道具を選んだときと、キーで道具が変わったときに、ボタンの顔をその道具にする。
            # lambda で繋ぐと、窓を閉じてボタンが消えたあとに道具の切り替えが届いて落ちた（Qt の中で 139）。
            # ボタンの関数に繋ぎ、ボタンが消えると繋ぎも切れるようにする
            a.triggered.connect(self._picked)
            if a.isCheckable():
                a.toggled.connect(self._toggled)

    def _picked(self, _checked=False):
        a = self.sender()
        if isinstance(a, QAction):
            self.show_action(a)

    def _toggled(self, on: bool):
        if on:
            self._picked()

    def fit(self):
        """名前が「全…示」のように切れないよう、名前の幅に合わせる（▼の分を足す）。広げすぎると 1280 の窓で頁が横に流れ、
        帯の名前が流し棒に隠れたので上限を置く"""
        extra = 18 if self.popupMode() == QToolButton.MenuButtonPopup else 4
        self.setMinimumWidth(min(84 + extra, max(52, self.fontMetrics().horizontalAdvance(self.text()) + 12 + extra)))

    def show_action(self, a: QAction):
        if self.defaultAction() is not a:
            self.setDefaultAction(a)
            self._retip()
            self.fit()

    def _retip(self):
        a = self.defaultAction()
        names = "・".join(x.text().split("（")[0] for x in self.family.actions)
        head = self.family.tip or f"{self.family.name}（{names}）"
        self.tip = f"{a.toolTip() or a.text()}\n{head}。▼か長押しで切り替えます"
        if self.toolTip() != self.tip:
            self.setToolTip(self.tip)

    def actionEvent(self, e):
        # 道具が変わる（checked が動く）たびに、Qt はボタンの説明を道具の説明だけに戻す。系統の説明を付け直す
        # 窓を閉じて消すときの ActionRemoved でも付け直すと、消えかけのボタンを触って 139 で落ちた。ActionChanged だけを見る
        super().actionEvent(e)
        if e.type() == QEvent.ActionChanged and self.family.icon is None and self.defaultAction() is not None:
            self._retip()


def group(title: str, actions: list) -> QWidget:
    """名前の付いたまとまり。アイコンの下に名前を出す"""
    box = QWidget()
    box.setObjectName("ribbonGroup")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(6, 2, 6, 0)
    lay.setSpacing(0)
    row = QHBoxLayout()
    row.setSpacing(2)
    for act in actions:
        if isinstance(act, Family) and len(act.actions) == 1:
            act = act.actions[0]
        b = FamilyButton(act) if isinstance(act, Family) else QToolButton()
        if not isinstance(act, Family):
            b.setDefaultAction(act)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(22, 22))
        if isinstance(b, FamilyButton):
            b.fit()
        else:
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
