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


def _has_pixels(img) -> bool:
    """透明でない画素が 1 つでもあるか。何も描いていないレイヤーは消す前に聞かない"""
    from PySide6.QtGui import QImage
    if img.isNull():
        return False
    if img.format() != QImage.Format_ARGB32_Premultiplied:
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    import numpy as np
    a = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
    return bool(a[3::4].any())


class LayerPanel(QWidget):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.w = None   # 窓。確かめの窓の覚えた答えを引く（窓の側で入れる）
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
                               ("lock", "ロック", self.toggle_lock),
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
        """右クリックの窓の中身（試験からも同じ項目を押せるよう、開くのと分ける）。
        よく使う物を上、消す物は区切り線の下。今使えない項目は押せなくし、理由をカーソルを合わせたときに出す"""
        from PySide6.QtWidgets import QMenu
        c = self.canvas
        item = self.list.itemAt(pos)
        m = QMenu(self)
        m.setToolTipsVisible(True)
        m.addAction("新しいレイヤー", c.add_layer).setToolTip("選んでいるレイヤーの上に新しいレイヤーを足します（Ctrl+Shift+N）")
        if item is not None and item.data(ROLE_INDEX) is not None and item.data(ROLE_INDEX) < 0:
            n = -item.data(ROLE_INDEX)
            m.addAction("指示を書き直す", lambda: self.list.editItem(item))
            m.addSeparator()
            m.addAction(f"赤ペン {n} を消す…", lambda: self.remove_mark(n)).setToolTip("元に戻すで戻せます")
            m.addAction("赤ペンの印を全部消す…", self.clear_marks)
            return m
        if item is not None:
            c.select(item.data(ROLE_INDEX))
            i, n = c.current, len(c.layers)
            for label, fn, ok, why in (("1 つ上へ", lambda: c.move_layer(1), i < n - 1, "一番上のレイヤーです"),
                                       ("1 つ下へ", lambda: c.move_layer(-1), i > 0, "一番下のレイヤーです"),
                                       ("下と結合", c.merge_down, i > 0, "下にレイヤーがありません")):
                a = m.addAction(label, fn)
                a.setEnabled(ok)
                a.setToolTip("" if ok else why)
            m.addAction("名前を変える", self.rename_current)
            lock = m.addAction("ロック", self.toggle_lock)
            lock.setCheckable(True)
            lock.setChecked(bool(c.layers and c.layers[i].locked))
            lock.setToolTip("ロックしたレイヤーには描けません")
        vis = sum(1 for x in c.layers if x.visible)
        a = m.addAction("見えているレイヤーを結合", c.merge_visible)
        a.setEnabled(vis >= 2)
        a.setToolTip("隠したレイヤーは捨てます。元に戻すで戻せます" if vis >= 2 else "見えているレイヤーが 2 枚以上ありません")
        if item is not None:
            m.addSeparator()
            m.addAction("レイヤーを消す…", self.delete_layer).setToolTip(
                "選んでいるレイヤーを消します（Delete）。元に戻すで戻せます" if len(c.layers) > 1 else "1 枚だけなので、絵を消して透明にします")
        return m

    def _ask(self, kind: str, title: str, text: str) -> bool:
        """消す前の確かめの窓。窓が無い（欄だけで使う）ときは聞かずに進める"""
        if self.w is None:
            return True
        from chatdraw import confirm
        return confirm.ask(self.w, kind, title, text, [("yes", "消す")]) == "yes"

    def delete_layer(self):
        """選んでいるレイヤーを消す。何も描いていないレイヤーは聞かずに消す（聞くと邪魔になる）"""
        c = self.canvas
        if not c.layers:
            return
        layer = c.layers[c.current]
        if _has_pixels(layer.image) and not self._ask(
                "delete_layer", "レイヤーを消す", f"「{layer.name}」を消します。元に戻す（Ctrl+Z）で戻せます。"):
            return
        c.delete_layer()

    def remove_mark(self, n: int):
        if self._ask("delete_marks", "赤ペンの印を消す", f"赤ペン {n} の印と指示を消します。元に戻す（Ctrl+Z）で戻せます。"):
            self.canvas.redpen.remove(n)

    def clear_marks(self):
        pen = self.canvas.redpen
        if pen.marks and self._ask("delete_marks", "赤ペンの印を消す",
                                   f"赤ペンの印 {len(pen.marks)} 個と指示を全部消します。元に戻すでは戻せません。"):
            pen.clear()

    def _delete(self):
        """「－」と Delete。赤ペンの行を選んでいればその印だけを消し、ほかは選んでいるレイヤーを消す"""
        item = self.list.currentItem()
        if item is not None and item.data(ROLE_INDEX) is not None and item.data(ROLE_INDEX) < 0:
            self.remove_mark(-item.data(ROLE_INDEX))
            return
        self.delete_layer()

    def rename_current(self):
        item = self.list.item(self.row_of(self.canvas.current))
        if item is not None:
            self.list.editItem(item)

    def toggle_lock(self):
        c = self.canvas
        if c.layers:
            c.set_locked(c.current, not c.layers[c.current].locked)
            self.refresh()
