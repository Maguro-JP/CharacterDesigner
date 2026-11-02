"""レイヤーの欄。縮小図・表示・ロック・名前・選ぶ・並べ替え・消す。

前は名前と表示の印だけの一覧で、どのレイヤーに描いているかが選択の色でしか分からず、
AI の絵のレイヤーに線を描いてしまったり、名前を変えられなかったりした。
上にあるレイヤーを上に並べる（作画ソフトと同じ順）。選んでいるレイヤーは太字と「✎」で示す。
並びは下から、透明のレイヤー 1、AI の絵、足したレイヤー・加工の結果・赤ペン（足した順）。
赤ペンも並びの 1 行で、選ぶ・隠す・消す・並べ替える・下と結合するが、ほかのレイヤーと同じ操作で効く。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

THUMB = 40
ROLE_INDEX = Qt.UserRole


def thumbnail(image, size: int = THUMB) -> QPixmap:
    """透明の所が分かるよう、市松の上に縮めた絵を置く"""
    pm = QPixmap(size, size)
    pm.fill(QColor("#d0d0d0"))
    p = QPainter(pm)
    s = size // 4
    for y in range(4):
        for x in range(4):
            if (x + y) % 2:
                p.fillRect(x * s, y * s, s, s, QColor("#f4f4f4"))
    if not image.isNull():
        small = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((size - small.width()) // 2, (size - small.height()) // 2, small)
    p.end()
    return pm


class LayerPanel(QWidget):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.list = QListWidget()
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setToolTip("押すと選び、そのレイヤーに描きます。印で表示を切り替え、ダブルクリックで名前を変えます")
        self.list.setEditTriggers(QListWidget.DoubleClicked | QListWidget.EditKeyPressed)
        self.list.itemChanged.connect(self._changed)
        # ドラッグで並べ替える。右クリックで消す・上下へ・名前・結合。Delete キーで消す
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.model().rowsMoved.connect(self._moved)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence.Delete, self.list, activated=self._delete)
        self.list.currentRowChanged.connect(self._selected)
        self.active = QLabel()
        self.active.setToolTip("線を描くレイヤー")
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setToolTip("レイヤーの不透明度")
        self.opacity.valueChanged.connect(lambda v: self.canvas.set_opacity(v / 100))
        # よく使う「足す・消す」だけをボタンにし、並べ替え・ロック・名前は「…」のプルダウンにまとめる（欄を狭く保つ）
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu, QToolButton
        self.buttons = {}
        row = QHBoxLayout()
        row.setSpacing(2)
        for key, label, tip, fn in (
                ("add", "＋", "新しいレイヤーを一番上に足します（Ctrl+Shift+N）", canvas.add_layer),
                ("delete", "－", "選んでいるレイヤーを消します。赤ペンなら印を全部消します（Delete。元に戻すで戻せます）", self._delete),
                ("up_b", "▲", "選んでいるレイヤーを 1 つ上へ（ドラッグでも並べ替えられます）", lambda: canvas.move_layer(1)),
                ("down_b", "▼", "選んでいるレイヤーを 1 つ下へ", lambda: canvas.move_layer(-1)),
                ("merge_b", "⤓", "選んでいるレイヤーを下のレイヤーと結合します（元に戻すで戻せます）", canvas.merge_down)):
            bt = QPushButton(label)
            bt.setFixedWidth(34)
            bt.setToolTip(tip)
            bt.clicked.connect(fn)
            row.addWidget(bt)
            self.buttons[key] = bt
        self.more = QToolButton()
        self.more.setText("…")
        self.more.setToolTip("並べ替え・ロック・名前を変える")
        self.more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more)
        for key, label, fn in (("up", "1 つ上へ", lambda: canvas.move_layer(1)),
                               ("down", "1 つ下へ", lambda: canvas.move_layer(-1)),
                               ("lock", "ロックする（描けなくする）", self.toggle_lock),
                               ("rename", "名前を変える", self.rename_current)):
            act = QAction(label, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
            self.buttons[key] = act
        self.buttons["lock"].setCheckable(True)
        self.more.setMenu(menu)
        row.addWidget(self.more)
        row.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.active)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.opacity)
        lay.addLayout(row)
        # 線を引くたびに縮小図を作り直すと重いので、手を離してから少し待って 1 回だけ作る
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        canvas.changed.connect(self.refresh)
        canvas.stroke_done.connect(self.timer.start)
        canvas.history_changed.connect(self.timer.start)
        self.refresh()

    def row_of(self, index: int) -> int:
        """絵のレイヤー index が、一覧の何行目か（上が一番上）"""
        for r in range(self.list.count()):
            if self.list.item(r).data(ROLE_INDEX) == index:
                return r
        return -1

    def refresh(self):
        c = self.canvas
        self.list.blockSignals(True)
        self.list.clear()
        pen = getattr(c, "redpen", None)
        stack = c.stack() if hasattr(c, "stack") else list(c.layers)
        layer_index = {id(layer): i for i, layer in enumerate(c.layers)}
        for entry in reversed(stack):
            if not hasattr(entry, "image"):   # 赤ペン。絵とは別の印だが、並びの 1 枚として出す
                on = c.redpen_current
                item = QListWidgetItem(QIcon(thumbnail(self._redpen_image())), f"赤ペン（{len(pen.marks)} か所）")
                item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                item.setCheckState(Qt.Checked if pen.isVisible() else Qt.Unchecked)
                item.setData(ROLE_INDEX, -1)
                item.setForeground(QColor("#ff2d2d"))
                f = QFont(item.font())
                f.setBold(on)
                item.setFont(f)
                item.setToolTip("AI に直してほしい所の印です。保存する絵には入りません。\n"
                                "チェックで隠す・出す、選んで「－」で全部消す、▲▼やドラッグで並べ替える、⤓で下のレイヤーに描き込む。\n"
                                "1 つだけ消すときは絵の上の番号を右クリック")
                self.list.addItem(item)
                if on:
                    self.list.setCurrentItem(item)
                continue
            i = layer_index[id(entry)]
            layer = entry
            on = i == c.current and not getattr(c, "redpen_current", False)
            item = QListWidgetItem(QIcon(thumbnail(layer.image)), layer.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            item.setData(ROLE_INDEX, i)
            f = QFont(item.font())
            f.setBold(on)
            item.setFont(f)
            marks = ("✎ " if on else "") + ("ロック中 " if layer.locked else "")
            item.setToolTip(marks + layer.name + ("（隠しています）" if not layer.visible else ""))
            self.list.addItem(item)
            if on:
                self.list.setCurrentItem(item)
        if getattr(c, "redpen_current", False) and pen is not None and pen.marks:
            self.active.setText("✎ 選んでいるレイヤー: 赤ペン（線は描けません）" + ("（隠しています）" if not pen.isVisible() else ""))
        elif c.layers:
            layer = c.layers[c.current]
            self.opacity.blockSignals(True)
            self.opacity.setValue(int(layer.opacity * 100))
            self.opacity.blockSignals(False)
            self.buttons["lock"].setChecked(layer.locked)
            state = "（ロック中）" if layer.locked else "（隠しています）" if not layer.visible else ""
            self.active.setText(f"✎ 描くレイヤー: {layer.name}{state}")
        pos = c.current_pos() if hasattr(c, "current_pos") else c.current
        on_pen = getattr(c, "redpen_current", False) and bool(pen is not None and pen.marks)
        self.buttons["delete"].setEnabled(len(c.layers) > 1 or on_pen)
        self.buttons["up"].setEnabled(pos < len(stack) - 1)
        self.buttons["up_b"].setEnabled(pos < len(stack) - 1)
        self.buttons["down_b"].setEnabled(pos > 0)
        self.buttons["down"].setEnabled(pos > 0)
        below = stack[pos - 1] if pos > 0 else None
        self.buttons["merge_b"].setEnabled(below is not None and hasattr(below, "image"))
        self.list.blockSignals(False)

    def _redpen_image(self):
        """赤ペンの縮小図に使う絵（印だけを透明の上に描く）。ほかの行と同じ高さにそろえるため"""
        from PySide6.QtGui import QImage
        w, h = self.canvas.size_px()
        img = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self.canvas.redpen.paint(p, None)
        p.end()
        return img

    def _selected(self, row: int):
        item = self.list.item(row)
        if item is None:
            return
        if item.data(ROLE_INDEX) == -1:
            self.canvas.select_redpen()
        else:
            self.canvas.select(item.data(ROLE_INDEX))

    def _changed(self, item: QListWidgetItem):
        i = item.data(ROLE_INDEX)
        if i == -1:
            on = item.checkState() == Qt.Checked
            QTimer.singleShot(0, lambda: self.canvas.set_redpen_visible(on))
            return
        if i is None or not 0 <= i < len(self.canvas.layers):
            return
        layer = self.canvas.layers[i]
        visible = item.checkState() == Qt.Checked
        if visible != layer.visible:
            self.canvas.set_visible(i, visible)
        if item.text().strip() and item.text() != layer.name:
            # 一覧の中で一覧を作り直すと、編集中の項目を消して落ちることがあるので、あとで描き直す
            name = item.text()
            QTimer.singleShot(0, lambda: self.canvas.rename_layer(i, name))
        else:
            QTimer.singleShot(0, self.refresh)

    def _moved(self, _parent, start, _end, _dest, row):
        """ドラッグで並べ替えたとき。一覧の行（上が一番上）を、キャンバスの並び（下から）の場所に直す。赤ペンも同じ"""
        n = self.list.count()
        new_row = row if row < start else row - 1
        if not (0 <= start < n and 0 <= new_row < n) or start == new_row:
            QTimer.singleShot(0, self.refresh)
            return
        src, dst = n - 1 - start, n - 1 - new_row
        QTimer.singleShot(0, lambda: self.canvas.move_entry_to(src, dst))

    def _menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.list.itemAt(pos)
        m = QMenu(self)
        m.addAction("新しいレイヤー", self.canvas.add_layer)
        if item is not None:
            if item.data(ROLE_INDEX) == -1:
                self.canvas.select_redpen()
                m.addAction("赤ペンの印を全部消す（Delete）", self.canvas.clear_redpen)
                m.addAction("1 つ上へ", lambda: self.canvas.move_layer(1))
                m.addAction("1 つ下へ", lambda: self.canvas.move_layer(-1))
                m.addAction("下のレイヤーに描き込む（結合）", self.canvas.merge_down)
            else:
                self.canvas.select(item.data(ROLE_INDEX))
                m.addAction("このレイヤーを消す（Delete）", self._delete).setEnabled(len(self.canvas.layers) > 1)
                m.addAction("1 つ上へ", lambda: self.canvas.move_layer(1))
                m.addAction("1 つ下へ", lambda: self.canvas.move_layer(-1))
                m.addAction("下のレイヤーと結合", self.canvas.merge_down)
                m.addAction("名前を変える", self.rename_current)
                m.addAction("ロックを切り替える", self.toggle_lock)
        m.addAction("見えているレイヤーを結合", self.canvas.merge_visible)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _delete(self):
        """「－」。赤ペンを選んでいれば印を全部消し、ほかは選んでいるレイヤーを消す"""
        item = self.list.currentItem()
        if item is not None and item.data(ROLE_INDEX) == -1:
            self.canvas.select_redpen()
        self.canvas.delete_layer()

    def rename_current(self):
        item = self.list.item(self.row_of(self.canvas.current))
        if item is not None:
            self.list.editItem(item)

    def toggle_lock(self):
        c = self.canvas
        if c.layers:
            c.set_locked(c.current, not c.layers[c.current].locked)
            self.refresh()
