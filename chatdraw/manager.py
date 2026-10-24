"""模型の管理。手元の模型の一覧と大きさ、使っている印、削除と、確かめ済みの推奨の模型の取得と更新。

見せるのは、名前・大きさ・使っているか、だけにする（内部の点数や置き場の道は見せない）。
消すのは、利用者がこの画面で選んで確かめたときだけ。使っている模型は消せない。
"""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from chatdraw.models import IMAGES, WORDS, offered_images, offered_words
from chatdraw.paths import GGUF, HUB, OWN_LLM
from chatdraw.setup import AUTO, Fetcher, folder_gb


@dataclass
class Item:
    kind: str        # "image" か "words"
    name: str
    path: Path
    gb: float
    key: str         # 設定に書く値（絵は repo、言葉は道）


def installed() -> list[Item]:
    """手元にある模型。絵を描く模型（model_index.json がある物）と .gguf。部品（ラフ用など）は出さない"""
    items: list[Item] = []
    names = {m.repo: m.name for m in IMAGES}
    if HUB.is_dir():
        for d in sorted(HUB.glob("models--*")):
            if any(s.joinpath("model_index.json").exists() for s in d.glob("snapshots/*")):
                repo = d.name[len("models--"):].replace("--", "/")
                items.append(Item("image", names.get(repo, repo.split("/")[-1]), d, folder_gb(d), repo))
    files = {m.file: m.name for m in WORDS}
    seen = set()
    for d in (GGUF, OWN_LLM):
        for f in sorted(d.glob("*.gguf")) if d.is_dir() else []:
            if f.is_symlink() or f.name in seen:
                continue
            seen.add(f.name)
            items.append(Item("words", files.get(f.name, f.stem), f, f.stat().st_size / 1e9, str(f)))
    return items


def delete(item: Item):
    """模型を消す。共有の置き場（と前の版の置き場）の中の物だけを消す"""
    root = HUB if item.kind == "image" else item.path.parent
    if root not in (HUB, GGUF, OWN_LLM) or not item.path.resolve().is_relative_to(root.resolve()):
        raise ValueError("置き場の外の物は消しません")
    if item.path.is_dir():
        shutil.rmtree(item.path)
    else:
        item.path.unlink()


class ModelManager(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("模型の管理")
        self.setMinimumWidth(520)
        self.body = QVBoxLayout(self)
        self.list = QVBoxLayout()
        self.body.addLayout(self.list)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("cardMeta")
        self.body.addWidget(self.bar)
        self.body.addWidget(self.status)
        row = QHBoxLayout()
        self.update_button = QPushButton("更新を確かめる")
        self.update_button.clicked.connect(self.update_all)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        row.addWidget(self.update_button)
        row.addStretch()
        row.addWidget(close)
        self.body.addLayout(row)
        self.fetcher = Fetcher()
        self.fetcher.progress.connect(lambda msg, pct: (self.status.setText(msg), self.bar.setValue(pct)), Qt.QueuedConnection)
        self.fetcher.finished.connect(self._fetched, Qt.QueuedConnection)
        self.refresh()

    def in_use(self, item: Item) -> bool:
        key = self.settings.get("image_model" if item.kind == "image" else "words_model")
        if key == AUTO:
            return False
        return key == item.key if item.kind == "image" else Path(key).name == item.path.name

    def refresh(self):
        """絵の模型と言葉の模型を分けて並べる。それぞれ、手元にある物の下に、まだ取っていない推奨の物を出す"""
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        have = installed()
        for kind, title, offered in (("image", "絵の模型", offered_images()), ("words", "言葉の模型", offered_words())):
            head = QLabel(title)
            head.setObjectName("dialogTitle")
            self.list.addWidget(head)
            mine = [it for it in have if it.kind == kind]
            for it in mine:
                self.list.addWidget(self._row(it.name, f"{it.gb:.1f}GB", "使用中" if self.in_use(it) else "削除",
                                              None if self.in_use(it) else (lambda _=False, it=it: self.ask_delete(it))))
            names = {it.name for it in mine}
            for m in offered:
                if m.name not in names:
                    self.list.addWidget(self._row(m.name, f"{m.gb:.1f}GB", "取る", lambda _=False, m=m: self.fetch(m)))
            if not mine and not offered:
                self.list.addWidget(QLabel("ありません"))

    def _row(self, name: str, size: str, action: str, fn) -> QWidget:
        box = QFrame()
        box.setObjectName("card")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 6, 8, 6)
        row.addWidget(QLabel(name), 1)
        meta = QLabel(size)
        meta.setObjectName("cardMeta")
        row.addWidget(meta)
        b = QPushButton(action)
        b.setEnabled(fn is not None)
        if fn is not None:
            b.clicked.connect(fn)
        row.addWidget(b)
        return box

    def ask_delete(self, it: Item):
        ok = QMessageBox.question(self, "模型を消す",
                                  f"{it.name} を消しますか？\nほかの自作アプリも使っていることがあります。要るときは、もう一度取れます。",
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok != QMessageBox.Yes:
            return
        try:
            delete(it)
            self.status.setText(f"{it.name} を消しました")
        except Exception as e:
            self.status.setText(f"消せませんでした: {e}")
        self.refresh()

    def fetch(self, m):
        self.bar.setVisible(True)
        image = m if m in IMAGES else None
        words = m if m in WORDS else None
        threading.Thread(target=self.fetcher.run, args=(image, words), daemon=True).start()

    def update_all(self):
        """手元にある確かめ済みの模型に新しい版があれば取る"""
        from chatdraw.setup import has_image, has_words
        self.bar.setVisible(True)
        images = [m for m in IMAGES if has_image(m)]
        words = [m for m in WORDS if has_words(m)]

        def run():
            for m in images:
                self.fetcher.run(m, None, True)
            for m in words:
                self.fetcher.run(None, m, True)
        threading.Thread(target=run, daemon=True).start()

    def _fetched(self, err: str):
        self.bar.setVisible(False)
        self.status.setText(err or "終わりました")
        self.refresh()
