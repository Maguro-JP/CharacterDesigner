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
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QImage, QPainter, QPalette, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QGraphicsPixmapItem, QGraphicsScene,  # noqa: E402
                               QGraphicsView, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QColorDialog, QProgressBar, QPushButton, QSpinBox, QTextEdit, QToolBar, QVBoxLayout, QWidget)

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
    """真ん中の絵の欄。ペンと消しゴムで描け、ホイールで拡大・縮小、手のひらで動かす"""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.scene().addItem(self.item)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#2b2b2b"))
        self.image = QImage()
        self.tool, self.color, self.size = "pen", QColor("#000000"), 6
        self.undo_stack: list[QImage] = []
        self.redo_stack: list[QImage] = []
        self.last = None
        self.set_tool("pen")

    # 絵を出す・新しく作る
    def show_image(self, path: str):
        self.set_image(QImage(path).convertToFormat(QImage.Format_ARGB32))

    def new_canvas(self, w: int = 1200, h: int = 1600):
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(QColor("white"))
        self.set_image(img)

    def set_image(self, img: QImage):
        self.image = img
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.refresh()
        self.scene().setSceneRect(self.item.boundingRect())
        self.fit()

    def refresh(self):
        self.item.setPixmap(QPixmap.fromImage(self.image))

    def fit(self):
        if not self.image.isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)

    def actual(self):
        self.resetTransform()

    # 道具
    def set_tool(self, tool: str):
        self.tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == "hand" else QGraphicsView.NoDrag)
        self.setCursor(Qt.OpenHandCursor if tool == "hand" else Qt.CrossCursor)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.image.copy())
            self.image = self.undo_stack.pop()
            self.refresh()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.image.copy())
            self.image = self.redo_stack.pop()
            self.refresh()

    def stroke(self, a, b):
        p = QPainter(self.image)
        p.setRenderHint(QPainter.Antialiasing)
        if self.tool == "eraser":
            p.setCompositionMode(QPainter.CompositionMode_Source)
            pen = QPen(QColor("white"), self.size * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        else:
            pen = QPen(self.color, self.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        if a == b:
            p.drawPoint(a)   # 押しただけでも点が付くように
        else:
            p.drawLine(a, b)
        p.end()
        self.refresh()

    def mousePressEvent(self, e):
        if self.tool in ("pen", "eraser") and e.button() == Qt.LeftButton and not self.image.isNull():
            self.undo_stack.append(self.image.copy())
            del self.undo_stack[:-50]
            self.redo_stack.clear()
            self.last = self.mapToScene(e.position().toPoint())
            self.stroke(self.last, self.last)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.last is not None:
            pos = self.mapToScene(e.position().toPoint())
            self.stroke(self.last, pos)
            self.last = pos
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.last is not None:
            self.last = None
            return
        super().mouseReleaseEvent(e)

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
        self.canvas.new_canvas()
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
        file.addAction(QAction("新規キャンバス", self, shortcut="Ctrl+N", triggered=lambda: self.canvas.new_canvas()))
        file.addAction(QAction("開く…", self, shortcut="Ctrl+O", triggered=self.open_image))
        file.addAction(QAction("名前を付けて保存…", self, shortcut="Ctrl+S", triggered=self.save_as))
        file.addSeparator()
        file.addAction(QAction("終了", self, shortcut="Ctrl+Q", triggered=self.close))
        edit = self.menuBar().addMenu("編集")
        edit.addAction(QAction("元に戻す", self, shortcut="Ctrl+Z", triggered=self.canvas.undo))
        edit.addAction(QAction("やり直す", self, shortcut="Ctrl+Y", triggered=self.canvas.redo))

        # 左端: 道具
        tools = QToolBar("道具", self)
        tools.setMovable(False)
        self.addToolBar(Qt.LeftToolBarArea, tools)
        group = QActionGroup(self)
        self.tool_actions = {}
        for key, label, short in (("pen", "ペン", "P"), ("eraser", "消しゴム", "E"), ("hand", "手のひら", "H")):
            act = QAction(label, self, checkable=True, shortcut=short, triggered=lambda _=False, k=key: self.canvas.set_tool(k))
            group.addAction(act)
            tools.addAction(act)
            self.tool_actions[key] = act
        self.tool_actions["pen"].setChecked(True)
        tools.addSeparator()
        self.color_button = QPushButton()
        self.color_button.setFixedSize(40, 28)
        self.color_button.clicked.connect(self.pick_color)
        self._show_color()
        tools.addWidget(self.color_button)
        self.size_box = QSpinBox()
        self.size_box.setRange(1, 200)
        self.size_box.setValue(self.canvas.size)
        self.size_box.setSuffix(" px")
        self.size_box.valueChanged.connect(lambda v: setattr(self.canvas, "size", v))
        tools.addWidget(self.size_box)

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

    def pick_color(self):
        c = QColorDialog.getColor(self.canvas.color, self, "色")
        if c.isValid():
            self.canvas.color = c
            self._show_color()

    def _show_color(self):
        self.color_button.setStyleSheet(f"background:{self.canvas.color.name()}; border:1px solid #888")

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "開く", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.canvas.show_image(path)

    def save_as(self):
        if self.canvas.image.isNull():
            return
        dst, _ = QFileDialog.getSaveFileName(self, "名前を付けて保存", "drawing.png", "PNG (*.png)")
        if dst:
            self.canvas.image.save(dst)

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
