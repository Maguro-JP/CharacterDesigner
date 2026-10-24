"""初めての起動で、描くのに使う模型を取る。取るかどうかは利用者が選ぶ。

絵の模型（約 7GB）が無いと絵は描けない。言葉の模型（約 1.1GB）が無いときは、日本語の頼みをそのまま絵の模型に渡す。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from chatdraw.engine import HOME, IMAGE_MODEL, MODEL_FILES, Painter, Words

LLM_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
IMAGE_GB, LLM_GB = 7.0, 1.1


def missing() -> dict:
    """足りない物。絵の模型と言葉の模型（部品と本体）"""
    llm_lib = (HOME / "llm" / "lib" / "llama_cpp").exists()
    return {"image": not Painter().ready(), "words": not (Words().ready() and llm_lib)}


def folder_gb(d: Path) -> float:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e9 if d.exists() else 0.0


class Fetcher(QObject):
    progress = Signal(str, int)
    finished = Signal(str)

    def run(self, image: bool, words: bool):
        try:
            if image:
                self._image()
            if words:
                self._words()
            self.finished.emit("")
        except Exception as e:  # 取れなかった理由をそのまま見せる
            self.finished.emit(f"取れませんでした: {e}")

    def _image(self):
        from huggingface_hub import snapshot_download
        hub = HOME / "gen" / "hf" / "hub"
        start = folder_gb(hub)
        done = threading.Event()

        def watch():
            while not done.wait(2):
                self.progress.emit("絵の模型を取っています", min(99, int((folder_gb(hub) - start) / IMAGE_GB * 100)))
        threading.Thread(target=watch, daemon=True).start()
        try:
            snapshot_download(IMAGE_MODEL, cache_dir=str(hub), **MODEL_FILES)
        finally:
            done.set()

    def _words(self):
        llm = HOME / "llm"
        lib = llm / "lib"
        if not (lib / "llama_cpp").exists():
            self.progress.emit("言葉の模型の部品を入れています", 0)
            # 元のソースから組むと数十分かかり、組み立ての道具も要るので、組み済みの配布物だけを使う
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(lib), "--only-binary", "llama-cpp-python",
                            "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu", "llama-cpp-python>=0.3.16"],
                           check=True)
        dest = llm / "model.gguf"
        if not dest.exists():
            llm.mkdir(parents=True, exist_ok=True)
            part = dest.with_suffix(".part")
            with urllib.request.urlopen(LLM_URL) as r, open(part, "wb") as f:
                total, got = int(r.headers.get("Content-Length") or 0), 0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress.emit("言葉の模型を取っています", got * 100 // total)
            part.replace(dest)


class SetupDialog(QDialog):
    def __init__(self, need: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("初めての設定")
        self.image = QCheckBox(f"絵の模型を取る（約 {IMAGE_GB:.0f}GB。取らないと絵は描けません）")
        self.words = QCheckBox(f"言葉の模型を取る（約 {LLM_GB}GB。日本語の頼みを描く言葉に直します）")
        for box, key in ((self.image, "image"), (self.words, "words")):
            box.setChecked(need[key])
            box.setEnabled(need[key])
        self.label = QLabel("取る物を選んで「取る」を押してください。あとで「ファイル」の「模型を取る」からも取れます。")
        self.label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.go = QPushButton("取る")
        self.go.clicked.connect(self.start)
        self.skip = QPushButton("今は取らない")
        self.skip.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        for w in (self.image, self.words, self.label, self.bar, self.go, self.skip):
            lay.addWidget(w)
        self.fetcher = Fetcher()
        self.fetcher.progress.connect(self._progress, Qt.QueuedConnection)
        self.fetcher.finished.connect(self._finished, Qt.QueuedConnection)

    def start(self):
        if not (self.image.isChecked() or self.words.isChecked()):
            self.reject()
            return
        for w in (self.go, self.skip, self.image, self.words):
            w.setEnabled(False)
        self.bar.setVisible(True)
        threading.Thread(target=self.fetcher.run, args=(self.image.isChecked(), self.words.isChecked()), daemon=True).start()

    def _progress(self, msg: str, pct: int):
        self.label.setText(msg)
        self.bar.setValue(pct)

    def _finished(self, err: str):
        if err:
            self.label.setText(err)
            self.skip.setText("閉じる")
            self.skip.setEnabled(True)
            self.go.setEnabled(True)
            return
        self.accept()
