"""CharacterDesigner のウィンドウ。チャットで頼むと絵を描いて並べる。

  python chatdraw/app.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for lib in (ROOT / ".cache" / "simple" / "lib", ROOT / ".cache" / "gen" / "lib", ROOT / ".cache" / "llm" / "lib", ROOT):
    if lib.exists() and str(lib) not in sys.path:
        sys.path.insert(0, str(lib))

from PySide6.QtCore import QObject, Qt, QThread, Signal  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,  # noqa: E402
                               QScrollArea, QVBoxLayout, QWidget)

from chatdraw.engine import Studio  # noqa: E402


class Job(QObject):
    status = Signal(str)
    done = Signal(str, str)
    failed = Signal(str)

    def __init__(self, studio: Studio, text: str, seed: int):
        super().__init__()
        self.studio, self.text, self.seed = studio, text, seed

    def run(self):
        try:
            prompt, path = self.studio.draw(self.text, self.seed, on_status=self.status.emit)
            self.done.emit(prompt, str(path))
        except Exception as e:  # 描けなかった理由をそのまま会話に出す
            self.failed.emit(f"描けませんでした: {e}")


class Window(QMainWindow):
    def __init__(self, studio: Studio | None = None):
        super().__init__()
        self.studio = studio or Studio()
        self.setWindowTitle("CharacterDesigner")
        self.resize(900, 900)
        self.log = QVBoxLayout()
        self.log.addStretch()
        box = QWidget()
        box.setLayout(self.log)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(box)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("描いてほしい絵を書いてください（例: 赤いマフラーの騎士、雪の城の前）")
        self.entry.returnPressed.connect(self.send)
        self.button = QPushButton("描く")
        self.button.clicked.connect(self.send)
        row = QHBoxLayout()
        row.addWidget(self.entry)
        row.addWidget(self.button)
        main = QVBoxLayout()
        main.addWidget(self.scroll)
        main.addLayout(row)
        root = QWidget()
        root.setLayout(main)
        self.setCentralWidget(root)
        self.statusBar().showMessage("頼みを書いて「描く」を押してください")
        self.thread: QThread | None = None
        self.images: list[str] = []

    def say(self, text: str, who: str = "CharacterDesigner"):
        label = QLabel(f"<b>{who}</b>: {text}")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.log.addWidget(label)

    def show_image(self, path: str):
        label = QLabel()
        label.setPixmap(QPixmap(path).scaledToWidth(min(640, self.width() - 80), Qt.SmoothTransformation))
        self.log.addWidget(label)
        self.images.append(path)

    def send(self):
        text = self.entry.text().strip()
        if not text or self.thread:
            return
        self.entry.clear()
        self.say(text, "あなた")
        self.button.setEnabled(False)
        self.thread = QThread()
        self.job = Job(self.studio, text, int(time.time()))
        self.job.moveToThread(self.thread)
        self.thread.started.connect(self.job.run)
        self.job.status.connect(self.statusBar().showMessage)
        self.job.done.connect(self.finish)
        self.job.failed.connect(self.fail)
        self.thread.start()

    def finish(self, prompt: str, path: str):
        self.say(f"描きました（{path}）")
        self.show_image(path)
        self._end("できました")

    def fail(self, why: str):
        self.say(why)
        self._end(why)

    def _end(self, msg: str):
        self.statusBar().showMessage(msg)
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.button.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
