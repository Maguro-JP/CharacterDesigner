"""Civitai から模型と LoRA を探して取る窓（chatdraw/civitai.py）。見本の絵を並べ、選んで取る。

探す・見本を取る・模型を取るは裏の糸で動かし、画面は止めない。取った物は置き場に置くだけで、すぐ一覧に出る。
API キーは設定（QSettings の civitai/key）に置く。キーの要る模型だけで使い、ほかへは送らない。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QVBoxLayout)

from chatdraw import civitai

KEY = "civitai/key"


class _Bus(QObject):
    found = Signal(int, object)        # (探した回, 一覧 か 例外)
    thumb = Signal(int, int, bytes)    # (探した回, 行, 絵のバイト)
    progress = Signal(int, int)
    done = Signal(object)              # 置いた道 か 例外


class CivitaiDialog(QDialog):
    def __init__(self, store, parent=None, search=civitai.search, fetch=civitai.fetch, get=civitai._get):
        super().__init__(parent)
        self.store, self._search, self._fetch, self._get = store, search, fetch, get
        self.setWindowTitle("Civitai から探す")
        self.resize(760, 560)
        self.items: list = []
        self.round = 0
        self.got = None
        self.bus = _Bus()
        self.bus.found.connect(self._show)
        self.bus.thumb.connect(self._set_thumb)
        self.bus.progress.connect(lambda g, t: (self.bar.setMaximum(max(t, 1)), self.bar.setValue(g)))
        self.bus.done.connect(self._fetched)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for label, k in civitai.KINDS.items():
            self.kind.addItem(label, k)
        self.kind.setCurrentIndex(1)
        self.kind.setToolTip("探す物。模型は絵の模型、LoRA は模型に重ねる作風")
        self.query = QLineEdit()
        self.query.setPlaceholderText("探す言葉（例: anime、lineart）")
        self.query.returnPressed.connect(self.run_search)
        self.go = QPushButton("探す")
        self.go.setToolTip("Civitai で探します（全年齢向けの物だけ、取られた数の多い順）")
        self.go.clicked.connect(self.run_search)
        row.addWidget(self.kind)
        row.addWidget(self.query, 1)
        row.addWidget(self.go)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(civitai.THUMB // 2, civitai.THUMB * 3 // 4))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._select)
        lay.addWidget(self.list, 1)
        self.info = QLabel("言葉を入れて「探す」を押してください")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.info.setOpenExternalLinks(False)
        lay.addWidget(self.info)
        bottom = QHBoxLayout()
        self.key = QLineEdit(str(store.value(KEY, "") or ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Civitai の API キー（要る模型だけ）")
        self.key.setToolTip("Civitai の設定（Account → API Keys）で作ったキー。キーの要る模型を取るときだけ使います")
        self.key.editingFinished.connect(lambda: self.store.setValue(KEY, self.key.text().strip()))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.take = QPushButton("取る")
        self.take.setToolTip("選んだ物を取り、模型は絵の模型の一覧に、LoRA は LoRA の一覧に入れます")
        self.take.setEnabled(False)
        self.take.clicked.connect(self.run_fetch)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        bottom.addWidget(QLabel("API キー"))
        bottom.addWidget(self.key, 1)
        bottom.addWidget(self.bar)
        bottom.addWidget(self.take)
        bottom.addWidget(close)
        lay.addLayout(bottom)

    # ---- 探す ----
    def run_search(self):
        self.round += 1
        n, q, k = self.round, self.query.text(), self.kind.currentData()
        self.info.setText("探しています")
        self.go.setEnabled(False)

        def work():
            try:
                self.bus.found.emit(n, self._search(q, k))
            except Exception as e:   # noqa: BLE001  繋がらないときも理由を出す
                self.bus.found.emit(n, e)
        threading.Thread(target=work, daemon=True).start()

    def _show(self, n, got):
        if n != self.round:
            return   # 前の探しの返り
        self.go.setEnabled(True)
        if isinstance(got, Exception):
            self.info.setText(f"探せませんでした（{got}）。繋がりを確かめて、もう一度押してください")
            return
        self.items = list(got)
        self.list.clear()
        for it in self.items:
            w = QListWidgetItem(f"{it.name[:28]}\n{it.base}・{it.size_mb:.0f}MB")
            w.setToolTip(self._detail(it, html=False))
            w.setSizeHint(QSize(civitai.THUMB // 2 + 16, civitai.THUMB * 3 // 4 + 48))
            self.list.addItem(w)
        self.info.setText(f"{len(self.items)} 件見つかりました。選ぶと詳しく出ます" if self.items else "見つかりませんでした。言葉を替えてください")
        for row, it in enumerate(self.items):
            if it.images:
                threading.Thread(target=self._load_thumb, args=(n, row, it.images[0]), daemon=True).start()

    def _load_thumb(self, n, row, url):
        try:
            self.bus.thumb.emit(n, row, self._get(url))
        except Exception:   # noqa: BLE001  見本が取れなくても一覧は使える
            pass

    def _set_thumb(self, n, row, data):
        if n != self.round or row >= self.list.count():
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self.list.item(row).setIcon(QIcon(pix))

    def _detail(self, it, html=True) -> str:
        lines = [it.name, f"{it.base}・{it.size_mb:.0f}MB・{it.downloads:,} 回取られた・作者 {it.creator}・{it.commercial}"]
        if it.words:
            lines.append("効かせる言葉: " + ", ".join(it.words[:6]))
        if it.kind != "LORA" and it.family == "unknown":
            lines.append(f"この世代（{it.base}）はこのアプリではまだ読めません")
        if it.note:
            lines.append(it.note)
        return ("<br>" if html else "\n").join(lines)

    def _select(self, row):
        it = self.items[row] if 0 <= row < len(self.items) else None
        self.take.setEnabled(bool(it and it.safe and (it.kind == "LORA" or it.family != "unknown")))
        if it is not None:
            self.info.setText(self._detail(it))

    # ---- 取る ----
    def run_fetch(self):
        it = self.items[self.list.currentRow()]
        self.store.setValue(KEY, self.key.text().strip())
        self.take.setEnabled(False)
        self.bar.show()
        self.info.setText(f"{it.name} を取っています（{it.size_mb:.0f}MB）")
        key = self.key.text().strip()

        def work():
            try:
                self.bus.done.emit(self._fetch(it, key, progress=lambda g, t: self.bus.progress.emit(int(g // 1024), int(t // 1024))))
            except Exception as e:   # noqa: BLE001
                self.bus.done.emit(e)
        threading.Thread(target=work, daemon=True).start()

    def _fetched(self, got):
        self.bar.hide()
        self.take.setEnabled(True)
        if isinstance(got, Exception):
            self.info.setText(f"取れませんでした: {got}")
            return
        self.got = got
        self.info.setText(f"取りました: {got.name}。" + ("「詳しい設定」の LoRA から選べます" if "lora" in str(got.parent).lower()
                                                         else "AI のメニューの絵の模型から選べます"))
