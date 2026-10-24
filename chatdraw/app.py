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

try:
    import PySide6  # noqa: F401
except ImportError:
    # 初めての起動だけ、ウィンドウの部品（PySide6）を入れる
    import subprocess
    lib = ROOT / ".cache" / "simple" / "lib"
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(lib), "PySide6-Essentials"], check=True)
    sys.path.insert(0, str(lib))

import re  # noqa: E402

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal  # noqa: E402
from PySide6.QtGui import QAction, QIcon, QPalette, QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QGraphicsPixmapItem, QGraphicsScene,  # noqa: E402
                               QGraphicsView, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget)

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


class Canvas(QGraphicsView):
    """真ん中の絵の欄。ホイールで拡大・縮小し、ドラッグで動かす"""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.scene().addItem(self.item)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#2b2b2b"))

    def show_image(self, path: str):
        self.item.setPixmap(QPixmap(path))
        self.scene().setSceneRect(self.item.boundingRect())
        self.fit()

    def fit(self):
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)

    def actual(self):
        self.resetTransform()

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)


class Window(QMainWindow):
    """作画ソフトの並び: 左に頼みの欄、真ん中に絵、右に描いた絵の一覧、下に進み"""

    def __init__(self, studio: Studio | None = None):
        super().__init__()
        self.studio = studio or Studio()
        self.setWindowTitle("CharacterDesigner")
        self.resize(1400, 900)
        self.images: list[str] = []
        self.thread: QThread | None = None

        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)

        # 左: 頼み（チャット）
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("描いてほしい絵を書いてください")
        self.entry.returnPressed.connect(self.send)
        self.button = QPushButton("描く")
        self.button.clicked.connect(self.send)
        row = QHBoxLayout()
        row.addWidget(self.entry)
        row.addWidget(self.button)
        left = QVBoxLayout()
        left.addWidget(self.chat)
        left.addLayout(row)
        box = QWidget()
        box.setLayout(left)
        dock = QDockWidget("頼み", self)
        dock.setWidget(box)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [360], Qt.Horizontal)

        # 右: 描いた絵の一覧。押すと真ん中に出す
        self.history = QListWidget()
        self.history.setViewMode(QListWidget.IconMode)
        self.history.setIconSize(QSize(120, 176))
        self.history.setResizeMode(QListWidget.Adjust)
        self.history.currentItemChanged.connect(lambda cur, _: cur and self.canvas.show_image(cur.data(Qt.UserRole)))
        hist = QDockWidget("描いた絵", self)
        hist.setWidget(self.history)
        hist.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, hist)
        self.resizeDocks([hist], [180], Qt.Horizontal)

        # 下: 進み
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(240)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("頼みを書いて「描く」を押してください")

        # 上: メニュー
        file = self.menuBar().addMenu("ファイル")
        save = QAction("名前を付けて保存…", self, shortcut="Ctrl+S", triggered=self.save_as)
        file.addAction(save)
        file.addSeparator()
        file.addAction(QAction("終了", self, shortcut="Ctrl+Q", triggered=self.close))
        view = self.menuBar().addMenu("表示")
        view.addAction(QAction("全体を表示", self, shortcut="Ctrl+0", triggered=self.canvas.fit))
        view.addAction(QAction("100%", self, shortcut="Ctrl+1", triggered=self.canvas.actual))

    def say(self, text: str, who: str = "CharacterDesigner"):
        self.chat.append(f"<b>{who}</b>: {text}")

    def send(self):
        text = self.entry.text().strip()
        if not text or self.thread:
            return
        self.entry.clear()
        self.say(text, "あなた")
        self.button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.thread = QThread()
        self.job = Job(self.studio, text, int(time.time()))
        self.job.moveToThread(self.thread)
        self.thread.started.connect(self.job.run)
        self.job.status.connect(self.on_status)
        self.job.done.connect(self.finish)
        self.job.failed.connect(self.fail)
        self.thread.start()

    def on_status(self, msg: str):
        self.statusBar().showMessage(msg)
        m = re.search(r"（(\d+)/(\d+)）", msg)
        if m:
            self.progress.setMaximum(int(m.group(2)))
            self.progress.setValue(int(m.group(1)))

    def finish(self, prompt: str, path: str):
        self.images.append(path)
        item = QListWidgetItem(QIcon(QPixmap(path).scaledToWidth(240, Qt.SmoothTransformation)), "")
        item.setData(Qt.UserRole, path)
        self.history.insertItem(0, item)
        self.history.setCurrentItem(item)
        self.canvas.show_image(path)
        self.say("描きました")
        self._end("できました")

    def fail(self, why: str):
        self.say(why)
        self._end(why)

    def save_as(self):
        if not self.images:
            return
        cur = self.history.currentItem()
        src = cur.data(Qt.UserRole) if cur else self.images[-1]
        dst, _ = QFileDialog.getSaveFileName(self, "名前を付けて保存", Path(src).name, "PNG (*.png)")
        if dst:
            QPixmap(src).save(dst)

    def _end(self, msg: str):
        self.statusBar().showMessage(msg)
        self.progress.setVisible(False)
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.button.setEnabled(True)


def dark(app: QApplication):
    """作画ソフトと同じ暗い色にする（絵の色が見やすい）"""
    app.setStyle("Fusion")
    p = QPalette()
    for role, c in ((QPalette.Window, "#3c3c3c"), (QPalette.WindowText, "#e6e6e6"), (QPalette.Base, "#2b2b2b"),
                    (QPalette.AlternateBase, "#353535"), (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#454545"),
                    (QPalette.ButtonText, "#e6e6e6"), (QPalette.Highlight, "#d9480f"), (QPalette.HighlightedText, "#ffffff")):
        p.setColor(role, QColor(c))
    app.setPalette(p)


def main():
    app = QApplication(sys.argv)
    dark(app)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
