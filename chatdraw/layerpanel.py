"""レイヤーの欄。縮小図・表示・ロック・名前・選ぶ・並べ替え・消す。

前は名前と表示の印だけの一覧で、どのレイヤーに描いているかが選択の色でしか分からず、
AI の絵のレイヤーに線を描いてしまったり、名前を変えられなかったりした。
上にあるレイヤーを上に並べる（作画ソフトと同じ順）。選んでいるレイヤーは太字と「✎」で示す。
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
    shared: dict = {}   # 窓の共の操作（コピー・貼り付けなど）。窓が渡す。無ければ右クリックは欄の中の操作だけ

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
                ("add", "＋", "新しいレイヤーを選んでいるレイヤーの上に足します（Ctrl+Shift+N）", canvas.add_layer),
                ("delete", "－", "選んでいるレイヤーを消します（Delete。元に戻すで戻せます）", self._delete),
                ("up_b", "▲", "選んでいるレイヤーを 1 つ上へ（ドラッグでも並べ替えられます）", lambda: canvas.move_layer(1)),
                ("down_b", "▼", "選んでいるレイヤーを 1 つ下へ", lambda: canvas.move_layer(-1))):
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
        pen = getattr(self.canvas, "redpen", None)
        return len(self.canvas.layers) - 1 - index + (len(pen.marks) if pen is not None else 0)

    def refresh(self):
        c = self.canvas
        # 赤ペンの行を選んでいたら、作り直したあとも同じ行を選ぶ。前は描くレイヤーの行に戻り、
        # 「－」を押すと選んだ印ではなくレイヤーが消えた
        old = self.list.currentItem()
        keep = old.data(ROLE_INDEX) if old is not None else None
        self.list.blockSignals(True)
        self.list.clear()
        pen = getattr(c, "redpen", None)
        keep_item = None
        # 赤ペンの印は 1 つずつ別の行にし、一番上に置く（隠す・消す・指示を書き直すを印ごとにできるように）。
        # 指示は絵の上に札で出しっぱなしにすると絵が隠れるので、行の名前と説明に持つ
        for n in (reversed(range(1, len(pen.marks) + 1)) if pen is not None else ()):
            note = pen.texts[n - 1] if n - 1 < len(pen.texts) else ""
            item = QListWidgetItem(f"赤ペン {n}" + (f": {note}" if note else ""))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            item.setCheckState(Qt.Unchecked if pen.hidden[n - 1] else Qt.Checked)
            item.setData(ROLE_INDEX, -n)
            item.setForeground(QColor("#ff2d2d"))
            item.setToolTip((f"指示: {note}\n" if note else "指示はまだありません。\n") +
                            "ダブルクリックで指示を書き直す。チェックで隠す・出す（隠した印は直しません）。「－」か Delete でこの印を消す。\n"
                            "保存する絵には入りません")
            self.list.addItem(item)
            if keep == -n:
                keep_item = item
        for i in reversed(range(len(c.layers))):
            layer = c.layers[i]
            on = i == c.current
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
            if on and keep_item is None:
                self.list.setCurrentItem(item)
        if keep_item is not None:
            self.list.setCurrentItem(keep_item)
        if c.layers:
            layer = c.layers[c.current]
            self.opacity.blockSignals(True)
            self.opacity.setValue(int(layer.opacity * 100))
            self.opacity.blockSignals(False)
            self.buttons["lock"].setChecked(layer.locked)
            state = "（ロック中）" if layer.locked else "（隠しています）" if not layer.visible else ""
            self.active.setText(f"✎ 描くレイヤー: {layer.name}{state}")
        self.buttons["delete"].setEnabled(len(c.layers) > 1 or bool(pen is not None and pen.marks))
        self.buttons["up"].setEnabled(c.current < len(c.layers) - 1)
        self.buttons["up_b"].setEnabled(c.current < len(c.layers) - 1)
        self.buttons["down_b"].setEnabled(c.current > 0)
        self.buttons["down"].setEnabled(c.current > 0)
        self.list.blockSignals(False)

    def _selected(self, row: int):
        item = self.list.item(row)
        if item is None:
            return
        i = item.data(ROLE_INDEX)
        pen = getattr(self.canvas, "redpen", None)
        if pen is not None:
            pen.set_focus(-i if i is not None and i < 0 else 0)   # 選んだ印だけ、絵の上に指示を出す
        if i is not None and i >= 0:
            self.canvas.select(i)

    def _changed(self, item: QListWidgetItem):
        i = item.data(ROLE_INDEX)
        if i is not None and i < 0:
            pen, n = self.canvas.redpen, -i
            pen.set_hidden(n, item.checkState() != Qt.Checked)
            text = item.text()
            head = f"赤ペン {n}"
            note = text[len(head):].lstrip(":： ") if text.startswith(head) else text
            if note.strip() != pen.texts[n - 1]:
                pen.set_text(n, note)
            QTimer.singleShot(0, self.refresh)
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
        """ドラッグで並べ替えたとき。一覧の行（上が一番上のレイヤー）をキャンバスの順に直す"""
        item_rows = [self.list.item(r).data(ROLE_INDEX) for r in range(self.list.count())]
        layer_rows = [i for i in item_rows if i is not None and i >= 0]
        n = len(self.canvas.layers)
        moved = self.list.item(row if row < start else row - 1)
        i = moved.data(ROLE_INDEX) if moved is not None else None
        if i is None or i < 0 or i not in layer_rows:
            QTimer.singleShot(0, self.refresh)
            return
        j = n - 1 - layer_rows.index(i)
        QTimer.singleShot(0, lambda: self.canvas.move_layer_to(i, j))

    def _menu(self, pos):
        self.context_menu(pos).exec(self.list.viewport().mapToGlobal(pos))

    def context_menu(self, pos):
        """右クリックの窓の中身（試験からも同じ項目を押せるよう、開くのと分ける）"""
        from PySide6.QtWidgets import QMenu
        item = self.list.itemAt(pos)
        m = QMenu(self)
        m.setToolTipsVisible(True)
        m.addAction("新しいレイヤー", self.canvas.add_layer)
        if item is not None:
            if item.data(ROLE_INDEX) < 0:
                n = -item.data(ROLE_INDEX)
                m.addAction(f"赤ペン {n} の指示を書き直す", lambda: self.list.editItem(item))
                m.addAction(f"赤ペン {n} を消す", lambda: self.canvas.redpen.remove(n))
                m.addAction("赤ペンの印を全部消す", self.canvas.redpen.clear)
            else:
                self.canvas.select(item.data(ROLE_INDEX))
                S = self.shared
                # コピー・切り取り・貼り付け・複製は、メニューと同じ操作（同じキー）を出す
                if S:
                    m.addAction(S["dup_layer"])
                    m.addSeparator()
                    for k in ("layer_cut", "layer_copy", "layer_paste"):
                        m.addAction(S[k])
                    m.addAction(S["via_copy"])
                    m.addSeparator()
                m.addAction("このレイヤーを消す（Delete）", self._delete).setEnabled(len(self.canvas.layers) > 1)
                if S:
                    m.addAction(S["clear_layer"])
                m.addAction("1 つ上へ", lambda: self.canvas.move_layer(1))
                m.addAction("1 つ下へ", lambda: self.canvas.move_layer(-1))
                if S:
                    m.addAction(S["flip_layer_h"])
                    m.addAction(S["flip_layer_v"])
                    m.addAction(S["merge_down"])
                else:
                    m.addAction("下のレイヤーと結合", self.canvas.merge_down)
                m.addAction("名前を変える", self.rename_current)
                m.addAction("ロックを切り替える", self.toggle_lock)
        m.addAction("見えているレイヤーを結合", self.canvas.merge_visible)
        return m

    def _delete(self):
        """「－」。赤ペンの行を選んでいればその印だけを消し、ほかは選んでいるレイヤーを消す"""
        item = self.list.currentItem()
        if item is not None and item.data(ROLE_INDEX) is not None and item.data(ROLE_INDEX) < 0:
            self.canvas.redpen.remove(-item.data(ROLE_INDEX))
            return
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
