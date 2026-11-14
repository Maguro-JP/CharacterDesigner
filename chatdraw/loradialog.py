"""模型の管理から開く LoRA の窓。手元のファイル、Civitai・Hugging Face の URL かモデル ID から足し、一覧で見て消す。
取るのは裏の糸で回し、窓は固めない。取り方そのものは chatdraw/lora.py"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from chatdraw import lora


class _Relay(QObject):
    said = Signal(str)
    done = Signal(str, str)   # 足した道, 失敗の理由


class LoraDialog(QDialog):
    def __init__(self, parent=None, model_family: str = ""):
        super().__init__(parent)
        self.setWindowTitle("LoRA")
        self.resize(480, 380)
        self.model_family = model_family
        self.list = QListWidget()
        self.status = QLabel("")
        self.status.setObjectName("cardMeta")
        self.status.setWordWrap(True)
        self.source = QLineEdit()
        self.source.setPlaceholderText("Civitai か Hugging Face の URL・モデル ID")
        self.source.setToolTip("例: https://civitai.com/models/12345 、 12345@67890（モデル ID@版）、 持ち主/名前 、"
                               "Hugging Face のファイルの URL。取ってくるだけで、こちらから何も上げません")
        self.source.returnPressed.connect(self.fetch)
        self.fetch_button = QPushButton("取る")
        self.fetch_button.setToolTip("URL かモデル ID の LoRA を置き場に取ります。系統ときっかけの言葉も一緒に残します")
        self.fetch_button.clicked.connect(self.fetch)
        top = QHBoxLayout()
        top.addWidget(self.source, 1)
        top.addWidget(self.fetch_button)
        row = QHBoxLayout()
        for text, tip, fn in (("ファイルから足す…", "手元の .safetensors を置き場に写して足します", self.pick_file),
                              ("消す", "選んだ LoRA を置き場から消します", self.remove_selected),
                              ("閉じる", "", self.accept)):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addLayout(top)
        lay.addLayout(row)
        lay.addWidget(self.status)
        self.relay = _Relay()
        self.relay.said.connect(self.status.setText, Qt.QueuedConnection)
        self.relay.done.connect(self._done, Qt.QueuedConnection)
        self.worker: threading.Thread | None = None
        self.refill()

    def refill(self):
        self.list.clear()
        for p in lora.loras():
            fam = lora.family_of(p)
            ok, why = lora.compatible(fam, self.model_family) if self.model_family else (True, "")
            it = QListWidgetItem(f"{lora.label(p)}　{lora.FAMILY_JA.get(fam, fam)}")
            it.setData(Qt.UserRole, str(p))
            words = ", ".join(lora.trigger_words(p))
            it.setToolTip("\n".join(x for x in (str(p), why, f"きっかけの言葉: {words}" if words else "") if x))
            if not ok:
                it.setForeground(Qt.gray)
            self.list.addItem(it)
        if not self.list.count():
            self.status.setText("まだ LoRA がありません。ファイルか URL から足してください")

    def pick_file(self, path: str | None = None):
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(self, "LoRA を選ぶ", "", "LoRA (*.safetensors)")
        if not path:
            return
        try:
            got = lora.add_file(path)
        except (OSError, ValueError) as e:
            self.status.setText(f"足せませんでした（{e}）")
            return
        self.status.setText(f"足しました: {got.name}（{lora.FAMILY_JA.get(lora.family_of(got), '')}）")
        self.refill()

    def fetch(self, text: str | None = None, wait: bool = False, **kw):
        text = (text if isinstance(text, str) else self.source.text()).strip()
        if not text or (self.worker is not None and self.worker.is_alive()):
            return
        self.fetch_button.setEnabled(False)
        self.status.setText("取っています…")

        def run():
            try:
                got = lora.add_from(text, say=self.relay.said.emit, **kw)
                self.relay.done.emit(str(got), "")
            except Exception as e:   # 通信、形の違い。窓に理由を出す
                self.relay.done.emit("", str(e))
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        if wait:
            self.worker.join()

    def _done(self, path: str, err: str):
        self.fetch_button.setEnabled(True)
        if err:
            self.status.setText(f"取れませんでした（{err}）")
            return
        self.source.clear()
        from pathlib import Path
        self.status.setText(f"取りました: {Path(path).name}（{lora.FAMILY_JA.get(lora.family_of(path), '')}）")
        self.refill()

    def remove_selected(self):
        it = self.list.currentItem()
        if it:
            lora.remove(it.data(Qt.UserRole))
            self.refill()
