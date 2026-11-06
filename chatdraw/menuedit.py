"""メニューと帯（リボンの下の帯・道具の帯・欄の帯・よく使う帯）を、利用者が自分で並べ替え・出し入れできるようにする。

設定は QSettings（layout_store）の menus/prefs と bars/<帯の名前> に JSON で持つ。版を上げても消さない。
メニューの項目は見出しの文字で覚える（項目に名前の付いた鍵が無い）。新しい版で増えた項目は、覚えた並びの後ろに出る。
隠した項目は、メニューから外すだけで消さない。同じ操作を帯やキーでも使っているので、QAction を隠すと全部から消えた。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QToolBar, QVBoxLayout)

MENU_KEY = "menus/prefs"
BAR_PREFIX = "bars/"
LOCK_KEY = "bars/locked"
SEP = "|"            # 帯の区切りの印
TOP = "（メニューの並び）"


def _text(a: QAction) -> str:
    return a.text().replace("&", "").strip()


def _key(a: QAction, i: int) -> str:
    return f"――{i}" if a.isSeparator() else _text(a)


def _load(store, key: str, empty):
    try:
        v = json.loads(store.value(key) or "null")
        return v if isinstance(v, type(empty)) else empty
    except (TypeError, ValueError):
        return empty


class Menus:
    """メニューの並び・出し入れ。開くたびに作り直すメニュー（AI、テーマ）にも、作ったあとに当てる"""

    def __init__(self, w, store):
        self.w, self.store = w, store
        self.prefs = _load(store, MENU_KEY, {})
        self.menus = {m.menuAction(): m for m in w.findChildren(QMenu)}
        self.bar = w.menuBar()
        self.default_top = list(self.bar.actions())
        self.default_items: dict[str, list[QAction]] = {}
        self.removed: dict[str, list[QAction]] = {}
        for top in self.default_top:
            m = self.menus.get(top)
            if m is None:
                continue
            name = _text(top)
            self.default_items[name] = list(m.actions())
            # 作り直すメニューは、作り直したあとに並べる（先に繋いだ作り直しのあとに呼ばれる）
            m.aboutToShow.connect(lambda name=name, m=m: self.apply_menu(name, m))
        self.apply()

    def top_menus(self) -> dict[str, QMenu]:
        return {_text(t): self.menus[t] for t in self.default_top if t in self.menus}

    @staticmethod
    def _arrange(actions: list[QAction], pref: dict) -> tuple[list[QAction], list[QAction]]:
        """覚えた並びで並べ、隠した物を分ける。覚えていない物（新しい版で増えた物）は元の並びのまま後ろに出す"""
        keyed = [(_key(a, i), a) for i, a in enumerate(actions)]
        order = pref.get("order") or []
        hidden = set(pref.get("hidden") or [])
        rank = {k: i for i, k in enumerate(order)}
        known = sorted((p for p in keyed if p[0] in rank), key=lambda p: rank[p[0]])
        new = [p for p in keyed if p[0] not in rank]
        out = known + new
        return [a for k, a in out if k not in hidden], [a for k, a in out if k in hidden]

    def _current(self, name: str, m: QMenu) -> list[QAction]:
        """今メニューにある物と、前に隠した物。作り直すメニューでは、作り直した同じ見出しの物を使い、古い物は捨てる"""
        from shiboken6 import isValid
        now = list(m.actions())
        texts = {_text(a) for a in now if not a.isSeparator()}
        keep = []
        for a in self.removed.get(name, []):
            if not isValid(a):
                continue
            if a in now:
                continue
            if a.isSeparator() or _text(a) in texts:
                self.w.removeAction(a)   # 作り直しで要らなくなった古い物
                continue
            keep.append(a)
        return now + keep

    def apply_menu(self, name: str, m: QMenu):
        pref = (self.prefs.get("items") or {}).get(name)
        if not pref:
            self.removed[name] = []
            return
        acts = self._current(name, m)
        shown, hidden = self._arrange(acts, pref)
        for a in acts:
            m.removeAction(a)
        for a in shown:
            m.addAction(a)
        for a in hidden:
            self.w.addAction(a)   # キーは効いたままにする
        self.removed[name] = hidden

    def apply(self):
        acts = list(self.default_top)
        shown, hidden = self._arrange(acts, self.prefs.get("top") or {})
        for a in list(self.bar.actions()):
            self.bar.removeAction(a)
        for a in shown:
            self.bar.addAction(a)
        self.removed[TOP] = hidden
        for name, m in self.top_menus().items():
            if m.isEmpty() and name not in (self.prefs.get("items") or {}):
                continue
            self.apply_menu(name, m)

    def entries(self, name: str) -> list[tuple[str, str, bool]]:
        """編集の窓に出す (覚える名前, 見せる文字, 出す) の並び"""
        if name == TOP:
            acts, pref = list(self.default_top), self.prefs.get("top") or {}
        else:
            m = self.top_menus()[name]
            m.aboutToShow.emit()   # 開くたびに作るメニューの中身を作る
            acts = self._current(name, m)
            pref = (self.prefs.get("items") or {}).get(name) or {}
        shown, hidden = self._arrange(acts, pref)
        out = []
        idx = {id(a): i for i, a in enumerate(acts)}
        for a in shown + hidden:
            k = _key(a, idx[id(a)])
            out.append((k, "―― 区切り ――" if a.isSeparator() else _text(a), a in shown))
        return out

    def set(self, name: str, order: list[str], hidden: list[str]):
        pref = {"order": order, "hidden": hidden}
        if name == TOP:
            self.prefs["top"] = pref
        else:
            self.prefs.setdefault("items", {})[name] = pref
        self.store.setValue(MENU_KEY, json.dumps(self.prefs, ensure_ascii=False))
        self.apply()

    def reset(self):
        """初めの並びに戻す。開くたびに作るメニューは次に開いたときに作り直る"""
        self.prefs = {}
        self.store.remove(MENU_KEY)
        for name, m in self.top_menus().items():
            for a in list(m.actions()):
                m.removeAction(a)
            for a in self.default_items.get(name, []):
                m.addAction(a)
            self.removed[name] = []
        self.apply()

    def hidden_actions(self) -> list[QAction]:
        return [a for v in self.removed.values() for a in v]


class Bars:
    """帯の中身（操作と区切り）の並び・足す・外す、と帯の固定"""

    def __init__(self, w, store, bars: dict[str, QToolBar], actions: dict[str, QAction]):
        self.w, self.store, self.bars, self.actions = w, store, bars, actions
        self.defaults = {name: self.ids(bar) for name, bar in bars.items()}
        for name, bar in bars.items():
            saved = _load(store, BAR_PREFIX + bar.objectName(), [])
            if saved:
                self.fill(name, saved)
        self.set_locked(self.locked(), save=False)

    def ids(self, bar: QToolBar) -> list[str]:
        back = {id(a): k for k, a in self.actions.items()}
        return [SEP if a.isSeparator() else back[id(a)] for a in bar.actions() if a.isSeparator() or id(a) in back]

    def label(self, key: str) -> str:
        if key == SEP:
            return "―― 区切り ――"
        a = self.actions.get(key)
        return _text(a) if a is not None and _text(a) else key

    def fill(self, name: str, keys: list[str]):
        bar = self.bars[name]
        for a in list(bar.actions()):
            bar.removeAction(a)
        for k in keys:
            if k == SEP:
                bar.addSeparator()
            elif k in self.actions:
                bar.addAction(self.actions[k])

    def set(self, name: str, keys: list[str]):
        self.fill(name, keys)
        self.store.setValue(BAR_PREFIX + self.bars[name].objectName(), json.dumps(keys, ensure_ascii=False))

    def reset(self, name: str):
        self.fill(name, self.defaults[name])
        self.store.remove(BAR_PREFIX + self.bars[name].objectName())

    def locked(self) -> bool:
        return str(self.store.value(LOCK_KEY, 0)) in ("1", "true", "True")

    def set_locked(self, on: bool, save: bool = True):
        """帯を固定する。固定するとドラッグで動かない（うっかり動かして並びが崩れるのを防ぐ）"""
        for bar in self.w.findChildren(QToolBar):
            if bar.objectName() == "ribbonbar":
                continue
            bar.setMovable(not on)
        ribbon = getattr(self.w, "ribbon", None)
        if ribbon is not None:
            ribbon.tabBar().setMovable(not on)
        if save:
            self.store.setValue(LOCK_KEY, int(on))
        act = getattr(self.w, "lock_bars_action", None)
        if act is not None and act.isChecked() != on:
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)


def _list_box(parent) -> QListWidget:
    lst = QListWidget(parent)
    lst.setDragDropMode(QListWidget.InternalMove)   # ドラッグでも並べ替えられる
    lst.setToolTip("ドラッグか ▲▼ で並べ替えます")
    return lst


def _move(lst: QListWidget, step: int):
    r = lst.currentRow()
    t = r + step
    if r < 0 or not 0 <= t < lst.count():
        return
    it = lst.takeItem(r)
    lst.insertItem(t, it)
    lst.setCurrentRow(t)


def _button(text: str, tip: str, fn) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip)
    b.clicked.connect(fn)
    return b


class MenuEditor(QDialog):
    """メニューを編集する窓。チェックを外すと隠し、▲▼かドラッグで並べ替える。OK で当てて覚える"""

    def __init__(self, w, menus: Menus):
        super().__init__(w)
        self.setWindowTitle("メニューを編集")
        self.menus = menus
        lay = QVBoxLayout(self)
        self.pick = QComboBox()
        self.pick.addItems([TOP] + list(menus.top_menus()))
        self.pick.setToolTip("並べ替えるメニューを選びます")
        lay.addWidget(self.pick)
        row = QHBoxLayout()
        self.list = _list_box(self)
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        side.addWidget(_button("▲", "上へ", lambda: _move(self.list, -1)))
        side.addWidget(_button("▼", "下へ", lambda: _move(self.list, 1)))
        side.addStretch()
        side.addWidget(_button("初めに戻す", "すべてのメニューを初めの並びに戻します", self._reset))
        row.addLayout(side)
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._edits: dict[str, tuple[list[str], list[str]]] = {}
        self._name = None
        self.pick.currentTextChanged.connect(self._show)
        self._show(self.pick.currentText())
        self.resize(360, 460)

    def _keep(self):
        if self._name is None:
            return
        order, hidden = [], []
        for i in range(self.list.count()):
            it = self.list.item(i)
            k = it.data(Qt.UserRole)
            order.append(k)
            if it.checkState() != Qt.Checked:
                hidden.append(k)
        self._edits[self._name] = (order, hidden)

    def _show(self, name: str):
        self._keep()
        self._name = name
        self.list.clear()
        saved = self._edits.get(name)
        entries = self.menus.entries(name)
        if saved:
            by = {k: (k, t, s) for k, t, s in entries}
            entries = [(k, by[k][1], k not in saved[1]) for k in saved[0] if k in by] + [e for e in entries if e[0] not in saved[0]]
        for k, t, on in entries:
            it = QListWidgetItem(t)
            it.setData(Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.list.addItem(it)

    def _reset(self):
        self._edits.clear()
        self.menus.reset()
        self._name = None
        self._show(self.pick.currentText())

    def _ok(self):
        self._keep()
        for name, (order, hidden) in self._edits.items():
            self.menus.set(name, order, hidden)
        self.accept()


class BarEditor(QDialog):
    """帯を編集する窓。操作を足す・外す、区切りを好きな所に入れる、並べ替える、固定する"""

    def __init__(self, w, bars: Bars):
        super().__init__(w)
        self.setWindowTitle("帯を編集")
        self.bars = bars
        lay = QVBoxLayout(self)
        self.pick = QComboBox()
        self.pick.addItems(list(bars.bars))
        self.pick.setToolTip("中身を変える帯を選びます")
        lay.addWidget(self.pick)
        row = QHBoxLayout()
        self.list = _list_box(self)
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        side.addWidget(_button("▲", "上へ（左へ）", lambda: _move(self.list, -1)))
        side.addWidget(_button("▼", "下へ（右へ）", lambda: _move(self.list, 1)))
        side.addWidget(_button("区切り", "選んだ所の下に区切りを入れます", self._sep))
        side.addWidget(_button("外す", "選んだ物を帯から外します", self._remove))
        side.addStretch()
        side.addWidget(_button("初めに戻す", "この帯を初めの中身に戻します", self._reset))
        row.addLayout(side)
        lay.addLayout(row)
        add = QHBoxLayout()
        self.pool = QComboBox()
        self.pool.setToolTip("帯に足せる操作")
        for k, a in sorted(bars.actions.items(), key=lambda p: bars.label(p[0])):
            self.pool.addItem(a.icon(), bars.label(k), k)
        add.addWidget(self.pool, 1)
        add.addWidget(_button("足す", "選んだ操作を帯に足します", self._add))
        lay.addLayout(add)
        self.lock = QCheckBox("帯を固定する")
        self.lock.setToolTip("固定すると帯とリボンのタブをドラッグで動かせなくなります")
        self.lock.setChecked(bars.locked())
        lay.addWidget(self.lock)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._edits: dict[str, list[str]] = {}
        self._name = None
        self.pick.currentTextChanged.connect(self._show)
        self._show(self.pick.currentText())
        self.resize(380, 480)

    def _item(self, k: str) -> QListWidgetItem:
        a = self.bars.actions.get(k)
        it = QListWidgetItem(self.bars.label(k))
        if a is not None:
            it.setIcon(a.icon())
        it.setData(Qt.UserRole, k)
        return it

    def keys(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _show(self, name: str):
        if self._name is not None:
            self._edits[self._name] = self.keys()
        self._name = name
        self.list.clear()
        for k in self._edits.get(name) or self.bars.ids(self.bars.bars[name]):
            self.list.addItem(self._item(k))

    def _insert(self, k: str):
        r = self.list.currentRow()
        r = self.list.count() if r < 0 else r + 1
        self.list.insertItem(r, self._item(k))
        self.list.setCurrentRow(r)

    def _sep(self):
        self._insert(SEP)

    def _add(self):
        k = self.pool.currentData()
        if k and k not in self.keys():   # 同じ帯に同じ操作は 1 つだけ（QAction は 1 つの帯に 2 回置けない）
            self._insert(k)

    def _remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)

    def _reset(self):
        name = self.pick.currentText()
        self._edits.pop(name, None)
        self.bars.reset(name)
        self._name = None
        self._show(name)

    def _ok(self):
        self._edits[self._name] = self.keys()
        for name, keys in self._edits.items():
            if keys != self.bars.ids(self.bars.bars[name]):
                self.bars.set(name, keys)
        self.bars.set_locked(self.lock.isChecked())
        self.accept()
