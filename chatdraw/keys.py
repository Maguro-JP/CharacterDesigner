"""キーの割り当て。メニューと道具の操作に付けるキーを、利用者が設定の窓で変えられる。

割り当ては QSettings の keys/<操作の名前> に持ち、起動のたびに当てる。既定はコードに書いたキー。
名前は操作の見出し（メニューに出る文字）で、同じ見出しの操作が 2 つあるときは、メニューの道（「ファイル/保存」）を付ける。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QMenu,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

PREFIX = "keys/"


def collect(window) -> dict[str, QAction]:
    """割り当てを変えられる操作。メニューの中の操作と、道具の操作"""
    found: dict[str, QAction] = {}
    # メニューの見出しの操作から中のメニューを引くのに QAction.menu() を使わない。PySide6 6.9 では、呼ぶと別の包みが作られ、
    # 窓が持っていたメニューの包み（self.ai_menu、self.theme_menu など）が「消えた」扱いになった。開くたびに作り直す中身が
    # 作れず（RuntimeError）、AI のメニューの模型の一覧が起動の時のまま古くなった。窓の子のメニューから、見出しの操作で引く
    menus = {m.menuAction(): m for m in window.findChildren(QMenu)}

    def walk(menu: QMenu, path: str):
        for act in menu.actions():
            sub = menus.get(act)
            text = act.text().replace("&", "").strip()
            if sub is not None:
                walk(sub, f"{path}/{text}" if path else text)
            elif text and not act.isSeparator():
                name = text if text not in found else f"{path}/{text}"
                found.setdefault(name, act)
    for top in window.menuBar().actions():
        if top in menus:
            walk(menus[top], top.text().replace("&", "").strip())
    for key, act in getattr(window, "tool_actions", {}).items():
        found.setdefault(f"道具/{act.text()}", act)
    for act in getattr(window, "extra_key_actions", []):
        found.setdefault(act.text(), act)
    return found


def apply(window, store):
    """保存した割り当てを当てる。初めて見る操作は、今のキーを既定として覚える"""
    window.key_defaults = getattr(window, "key_defaults", {})
    for name, act in collect(window).items():
        window.key_defaults.setdefault(name, act.shortcut().toString())
        saved = store.value(PREFIX + name)
        if saved is not None:
            act.setShortcut(QKeySequence(str(saved)))


def conflicts(table: dict[str, str]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for name, seq in table.items():
        if seq:
            seen.setdefault(seq, []).append(name)
    return {k: v for k, v in seen.items() if len(v) > 1}


class KeyDialog(QDialog):
    """キーの設定の窓。行を選んでキーを押すと割り当てる。消す・既定に戻すもできる"""

    def __init__(self, window, store, parent=None):
        super().__init__(parent or window)
        self.setWindowTitle("キーの設定")
        self.resize(560, 520)
        self.window_, self.store = window, store
        self.actions = collect(window)
        self.defaults = getattr(window, "key_defaults", {})
        lay = QVBoxLayout(self)
        self.search = QLineEdit(placeholderText="操作の名前で探す")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.table = QTableWidget(len(self.actions), 2)
        self.table.setHorizontalHeaderLabels(["操作", "キー"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        for row, (name, act) in enumerate(sorted(self.actions.items())):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(act.shortcut().toString(QKeySequence.NativeText)))
            self.table.item(row, 0).setData(Qt.UserRole, name)
            self.table.item(row, 1).setData(Qt.UserRole, act.shortcut().toString())
        self.table.currentCellChanged.connect(lambda r, *_: self._pick(r))
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("キー:"))
        self.edit = QKeySequenceEdit()
        self.edit.setMaximumSequenceLength(1)
        self.edit.editingFinished.connect(self._set)
        row.addWidget(self.edit, 1)
        clear = QPushButton("外す")
        clear.clicked.connect(lambda: self._store_row(""))
        reset = QPushButton("既定に戻す")
        reset.clicked.connect(self._reset_row)
        reset_all = QPushButton("すべて既定に戻す")
        reset_all.clicked.connect(self._reset_all)
        for b in (clear, reset, reset_all):
            row.addWidget(b)
        lay.addLayout(row)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        lay.addWidget(self.warning)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("やめる")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _filter(self, text: str):
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, text.strip() not in self.table.item(r, 0).text())
        r = self.table.currentRow()
        if r >= 0 and self.table.isRowHidden(r):
            # 選んだ行が隠れたら選択を外す（そのままキーを押すと、見えない行に割り当たった）
            self.table.setCurrentCell(-1, -1)
            self.edit.clear()

    def _pick(self, row: int):
        if row >= 0:
            self.edit.setKeySequence(QKeySequence(self.table.item(row, 1).data(Qt.UserRole)))

    def _store_row(self, seq: str):
        r = self.table.currentRow()
        if r < 0 or self.table.isRowHidden(r):
            return
        item = self.table.item(r, 1)
        item.setData(Qt.UserRole, seq)
        item.setText(QKeySequence(seq).toString(QKeySequence.NativeText))
        self.edit.setKeySequence(QKeySequence(seq))
        self._check()

    def _set(self):
        self._store_row(self.edit.keySequence().toString())

    def _reset_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self._store_row(self.defaults.get(self.table.item(r, 0).data(Qt.UserRole), ""))

    def _reset_all(self):
        for r in range(self.table.rowCount()):
            seq = self.defaults.get(self.table.item(r, 0).data(Qt.UserRole), "")
            self.table.item(r, 1).setData(Qt.UserRole, seq)
            self.table.item(r, 1).setText(QKeySequence(seq).toString(QKeySequence.NativeText))
        self._check()

    def table_now(self) -> dict[str, str]:
        return {self.table.item(r, 0).data(Qt.UserRole): self.table.item(r, 1).data(Qt.UserRole) or ""
                for r in range(self.table.rowCount())}

    def _check(self) -> bool:
        clash = conflicts(self.table_now())
        self.warning.setText("".join(f"{QKeySequence(k).toString(QKeySequence.NativeText)} が {'、'.join(v)} で重なっています。\n"
                                     for k, v in clash.items()))
        return not clash

    def save(self):
        if not self._check():
            return   # 重なったまま保存すると、どちらの操作が動くか分からなくなる
        for name, seq in self.table_now().items():
            if seq == self.defaults.get(name, ""):
                self.store.remove(PREFIX + name)
            else:
                self.store.setValue(PREFIX + name, seq)
            self.actions[name].setShortcut(QKeySequence(seq))
        self.accept()
