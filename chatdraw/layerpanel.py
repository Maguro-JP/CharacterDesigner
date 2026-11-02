"""レイヤーの欄。縮小図・表示・ロック・名前・選ぶ・並べ替え・消す。

前は名前と表示の印だけの一覧で、どのレイヤーに描いているかが選択の色でしか分からず、
AI の絵のレイヤーに線を描いてしまったり、名前を変えられなかったりした。
上にあるレイヤーを上に並べる（作画ソフトと同じ順）。選んでいるレイヤーは太字と「✎」で示す。

赤ペンの印は、印ごとに「赤ペン 1」「赤ペン 2」… の行を一番上に出す。行の番号は印の番号で、ROLE_INDEX には
-番号 を持つ（絵のレイヤーは 0 から）。指示はその行のコメント（名前の横の短い文とツールチップ）として見せる。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

THUMB = 40
ROLE_INDEX = Qt.UserRole
NOTE_SHORT = 14   # 行の名前の横に出す指示の長さ（長い指示はツールチップで全部見せる）


def mark_of(index) -> int:
    """行の ROLE_INDEX から赤ペンの印の番号（1 から）。印の行でなければ 0"""
    return -index if isinstance(index, int) and index < 0 else 0


def short_note(note: str) -> str:
    note = " ".join(note.split())
    return note if len(note) <= NOTE_SHORT else note[:NOTE_SHORT - 1] + "…"


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
                ("add", "＋", "新しいレイヤーを選んでいるレイヤーの上に足します（Ctrl+Shift+N）", canvas.add_layer),
                ("delete", "－", "選んでいるレイヤーを消します（Delete。元に戻すで戻せます）", self._delete),
                ("up_b", "▲", "選んでいるレイヤーを 1 つ上へ（ドラッグでも並べ替えられます）", lambda: self._move(1)),
                ("down_b", "▼", "選んでいるレイヤーを 1 つ下へ", lambda: self._move(-1))):
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
        """レイヤーの番号から一覧の行。一覧の上には赤ペンの印の行が印の数だけ並ぶ"""
        pen = self._pen()
        return len(self.canvas.layers) - 1 - index + (len(pen.marks) if pen is not None else 0)

    def refresh(self):
        c = self.canvas
        self.list.blockSignals(True)
        self.list.clear()
        pen = getattr(c, "redpen", None)
        marked = None
        if pen is not None and pen.marks:   # 赤ペンの印は印ごとに、絵とは別の一番上の行として出す（隠す・消す・並べ替え）
            pen._sync()
            for n in range(1, len(pen.marks) + 1):
                note = pen.texts[n - 1]
                item = QListWidgetItem(f"赤ペン {n}" + (f"　{short_note(note)}" if note else "　（指示なし）"))
                item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                item.setCheckState(Qt.Unchecked if pen.hidden[n - 1] else Qt.Checked)
                item.setData(ROLE_INDEX, -n)
                item.setForeground(QColor("#ff2d2d"))
                item.setToolTip(f"赤ペン {n} の指示: {note or '（まだ書いていません。チャットの文を使います）'}\n"
                                "AI に直してほしい所の印です。保存する絵には入りません。\n"
                                "選ぶと絵の上に指示が出ます。チェックで隠す・出す、「－」か Delete で消す、"
                                "ドラッグか ▲▼ で並べ替え。右クリックで指示を書き直す")
                self.list.addItem(item)
                if n == pen.active:
                    marked = item
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
            if on and marked is None:
                self.list.setCurrentItem(item)
        if marked is not None:
            self.list.setCurrentItem(marked)
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
        n = mark_of(marked.data(ROLE_INDEX)) if marked is not None else 0
        self.buttons["up_b"].setEnabled(n > 1 if n else c.current < len(c.layers) - 1)
        self.buttons["down_b"].setEnabled(n < len(pen.marks) if n else c.current > 0)
        self.buttons["down"].setEnabled(c.current > 0)
        self.list.blockSignals(False)

    def _pen(self):
        return getattr(self.canvas, "redpen", None)

    def current_mark(self) -> int:
        """選んでいる行が赤ペンの印なら、その番号（1 から）。違えば 0"""
        item = self.list.currentItem()
        return mark_of(item.data(ROLE_INDEX)) if item is not None else 0

    def _selected(self, row: int):
        item = self.list.item(row)
        if item is None:
            return
        n = mark_of(item.data(ROLE_INDEX))
        pen = self._pen()
        if pen is not None:
            pen.set_active(n)   # 印の行を選んでいる間だけ、その印の指示を絵の上に出す
        if n:
            self.buttons["up_b"].setEnabled(n > 1)
            self.buttons["down_b"].setEnabled(n < len(pen.marks))
        else:
            self.canvas.select(item.data(ROLE_INDEX))

    def _changed(self, item: QListWidgetItem):
        i = item.data(ROLE_INDEX)
        if mark_of(i):
            n, hide = mark_of(i), item.checkState() != Qt.Checked
            QTimer.singleShot(0, lambda: self._pen().set_hidden(n, hide))
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
        moved = self.list.item(row if row < start else row - 1)
        n = mark_of(moved.data(ROLE_INDEX)) if moved is not None else 0
        if n:   # 赤ペンの行どうしの並べ替え。行の並びの中で何番目になったかを、その印の新しい番号にする
            order = [mark_of(i) for i in item_rows if mark_of(i)]
            QTimer.singleShot(0, lambda: self._pen().move(n, order.index(n) + 1))
            return
        layer_rows = [i for i in item_rows if i is not None and i >= 0]
        n = len(self.canvas.layers)
        i = moved.data(ROLE_INDEX) if moved is not None else None
        if i is None or i < 0 or i not in layer_rows:
            QTimer.singleShot(0, self.refresh)
            return
        j = n - 1 - layer_rows.index(i)
        QTimer.singleShot(0, lambda: self.canvas.move_layer_to(i, j))

    def _menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.list.itemAt(pos)
        m = QMenu(self)
        m.addAction("新しいレイヤー", self.canvas.add_layer)
        if item is not None:
            n = mark_of(item.data(ROLE_INDEX))
            if n:
                pen = self._pen()
                pen.set_active(n)
                m.addAction(f"赤ペン {n} の指示を書き直す", lambda: self.canvas.note_wanted.emit(n))
                m.addAction(f"赤ペン {n} を消す（Delete）", lambda: pen.remove(n))
                m.addAction("1 つ上へ", lambda: pen.move(n, n - 1)).setEnabled(n > 1)
                m.addAction("1 つ下へ", lambda: pen.move(n, n + 1)).setEnabled(n < len(pen.marks))
                m.addAction("赤ペンの印を全部消す", pen.clear)
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
        """「－」。赤ペンの行を選んでいればその印だけを消し（元に戻すで戻せる）、ほかは選んでいるレイヤーを消す"""
        n = self.current_mark()
        if n:
            self._pen().remove(n)
            return
        self.canvas.delete_layer()

    def _move(self, step: int):
        """▲▼。赤ペンの行を選んでいれば印の順を、ほかはレイヤーの順を変える（一覧の上が 1 番）"""
        n = self.current_mark()
        if n:
            self._pen().move(n, n - step)
            return
        self.canvas.move_layer(step)

    def rename_current(self):
        item = self.list.item(self.row_of(self.canvas.current))
        if item is not None:
            self.list.editItem(item)

    def toggle_lock(self):
        c = self.canvas
        if c.layers:
            c.set_locked(c.current, not c.layers[c.current].locked)
            self.refresh()
