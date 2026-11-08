"""操作の名前で探して呼ぶ窓（Ctrl+K）と、描いた絵を並べて比べる窓。
メニューの奥にある操作を、名前の一部を打つだけで呼べるようにする。どちらも今あるメニューの QAction をそのまま使い、
別の働きを作らない（同じ名前で違う動きになるのを避ける）"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QDialog, QGridLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMenuBar,
                               QScrollArea, QVBoxLayout, QWidget)


def menu_actions(bar: QMenuBar) -> list[tuple[str, QAction]]:
    """メニューの中の、押せる操作を「メニュー › 名前」で集める（区切りと中のメニューそのものは除く）"""
    out: list[tuple[str, QAction]] = []
    seen: set[int] = set()

    def walk(menu: QMenu, path: str):
        for act in menu.actions():
            if act.isSeparator():
                continue
            sub = act.menu()
            name = act.text().replace("&", "")
            if sub is not None:
                walk(sub, f"{path} › {name}" if path else name)
            elif name and id(act) not in seen and act.isVisible():
                seen.add(id(act))
                out.append((f"{path} › {name}", act))

    for top in bar.actions():
        if top.menu() is not None:
            walk(top.menu(), top.text().replace("&", ""))
    return out


class CommandPalette(QDialog):
    """名前の一部を打つと、合う操作が並ぶ。Enter かダブルクリックで、その操作を押したのと同じ動きをする"""

    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("操作を探す")
        self.setModal(True)
        self.resize(520, 420)
        self.window_ = window
        self.box = QLineEdit()
        self.box.setPlaceholderText("操作の名前を打つ（例: 保存、拡大、レイヤー）")
        self.box.setClearButtonEnabled(True)
        self.list = QListWidget()
        self.empty = QLabel("合う操作がありません。別の言葉で打ってください")
        self.empty.setObjectName("stateDetail")
        lay = QVBoxLayout(self)
        lay.addWidget(self.box)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.empty)
        self.box.textChanged.connect(self.fill)
        self.box.returnPressed.connect(self.run_current)
        self.list.itemActivated.connect(lambda _it: self.run_current())
        self.box.installEventFilter(self)
        self.fill("")

    def eventFilter(self, obj, ev):
        # 打つ欄にいたまま、上下のキーで候補を選べる
        from PySide6.QtCore import QEvent
        if obj is self.box and ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return super().eventFilter(obj, ev)

    def fill(self, text: str):
        words = text.lower().split()
        self.list.clear()
        for label, act in menu_actions(self.window_.menuBar()):
            hay = (label + " " + act.toolTip()).lower()
            if all(w in hay for w in words):
                keys = act.shortcut().toString()
                it = QListWidgetItem(label + (f"　（{keys}）" if keys else ""))
                it.setData(Qt.UserRole, act)
                it.setToolTip(act.toolTip() if act.toolTip() and act.toolTip() != act.text() else label)
                if not act.isEnabled():
                    it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
                self.list.addItem(it)
        first = next((i for i in range(self.list.count()) if self.list.item(i).flags() & Qt.ItemIsEnabled), -1)
        self.list.setCurrentRow(first)
        self.empty.setVisible(self.list.count() == 0)

    def run_current(self):
        it = self.list.currentItem()
        act = it.data(Qt.UserRole) if it else None
        if act is None or not act.isEnabled():
            return
        self.accept()
        act.trigger()


class CompareDialog(QDialog):
    """描いた絵を横に並べて比べる。絵を押すとキャンバスに出す（元に戻すで戻せる）"""

    def __init__(self, window, items: list[tuple[str, str]]):
        super().__init__(window)
        self.setWindowTitle(f"並べて比べる（{len(items)} 枚）")
        self.resize(min(1200, 300 * max(1, len(items)) + 40), 520)
        inner = QWidget()
        grid = QGridLayout(inner)
        self.cells: list[QLabel] = []
        cols = 4 if len(items) > 4 else max(1, len(items))
        for i, (path, tip) in enumerate(items):
            pic = QLabel()
            pic.setAlignment(Qt.AlignCenter)
            pm = QPixmap(path)
            pic.setPixmap(pm.scaled(280, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pm.isNull() else pm)
            pic.setToolTip((tip + "\n" if tip else "") + "押すとキャンバスに出します")
            pic.setCursor(Qt.PointingHandCursor)
            pic.mousePressEvent = lambda _e, p=path: (window.show_history_image(p), self.accept())
            self.cells.append(pic)
            grid.addWidget(pic, (i // cols) * 2, i % cols)
            cap = QLabel(tip.split("\n")[0] if tip else "")
            cap.setObjectName("stateDetail")
            cap.setAlignment(Qt.AlignCenter)
            grid.addWidget(cap, (i // cols) * 2 + 1, i % cols)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        lay = QVBoxLayout(self)
        lay.addWidget(scroll)
