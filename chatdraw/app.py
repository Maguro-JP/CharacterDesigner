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

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, Signal  # noqa: E402
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog,  # noqa: E402
                               QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QColorDialog, QLabel, QProgressBar, QPushButton, QSlider, QSpinBox, QTextEdit, QToolBar, QVBoxLayout, QWidget)

from chatdraw.canvas import Canvas  # noqa: E402
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


# 欄は動かせて、外に出せて、閉じられる（作画ソフトと同じ）
PANEL = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable


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
        dock.setObjectName("chat")
        dock.setFeatures(PANEL)
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
        hist.setObjectName("history")
        hist.setFeatures(PANEL)
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
        tools.setObjectName("tools")
        self.addToolBar(Qt.LeftToolBarArea, tools)
        group = QActionGroup(self)
        self.tool_actions = {}
        for key, label, short in (("pen", "ペン", "P"), ("eraser", "消しゴム", "E"), ("fill", "塗りつぶし", "G"),
                                  ("eyedropper", "スポイト", "I"), ("hand", "手のひら", "H")):
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
        tools.addWidget(QLabel("濃さ"))
        self.flow = QSlider(Qt.Horizontal)
        self.flow.setRange(1, 100)
        self.flow.setValue(100)
        self.flow.setMaximumWidth(70)
        self.flow.valueChanged.connect(lambda v: setattr(self.canvas, "brush_opacity", v / 100))
        tools.addWidget(self.flow)
        self.canvas.color_picked.connect(lambda _c: self._show_color())

        # 右下: レイヤー
        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self._layer_toggled)
        self.layer_list.currentRowChanged.connect(self._layer_selected)
        self.layer_opacity = QSlider(Qt.Horizontal)
        self.layer_opacity.setRange(0, 100)
        self.layer_opacity.valueChanged.connect(lambda v: self.canvas.set_opacity(v / 100))
        buttons = QHBoxLayout()
        for label, fn in (("＋", self.canvas.add_layer), ("－", self.canvas.delete_layer),
                          ("↑", lambda: self.canvas.move_layer(1)), ("↓", lambda: self.canvas.move_layer(-1))):
            b = QPushButton(label)
            b.setFixedWidth(34)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        lay = QVBoxLayout()
        lay.addWidget(self.layer_list)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("不透明度"))
        row2.addWidget(self.layer_opacity)
        lay.addLayout(row2)
        lay.addLayout(buttons)
        lbox = QWidget()
        lbox.setLayout(lay)
        ldock = QDockWidget("レイヤー", self)
        ldock.setWidget(lbox)
        ldock.setObjectName("chat")
        dock.setFeatures(PANEL)
        self.addDockWidget(Qt.RightDockWidgetArea, ldock)
        self.canvas.changed.connect(self._refresh_layers)
        self._refresh_layers()

        view = self.menuBar().addMenu("表示")
        view.addAction(QAction("全体を表示", self, shortcut="Ctrl+0", triggered=self.canvas.fit))
        view.addAction(QAction("100%", self, shortcut="Ctrl+1", triggered=self.canvas.actual))
        view.addAction(QAction("左に回す", self, shortcut="Ctrl+[", triggered=lambda: self.canvas.rotate_view(-15)))
        view.addAction(QAction("右に回す", self, shortcut="Ctrl+]", triggered=lambda: self.canvas.rotate_view(15)))
        view.addAction(QAction("回転を戻す", self, shortcut="Ctrl+\\", triggered=self.canvas.reset_rotation))
        layer_menu = self.menuBar().addMenu("レイヤー")
        layer_menu.addAction(QAction("新しいレイヤー", self, shortcut="Ctrl+Shift+N", triggered=self.canvas.add_layer))
        layer_menu.addAction(QAction("レイヤーを消す", self, triggered=self.canvas.delete_layer))
        layer_menu.addAction(QAction("画像をレイヤーとして読み込む…", self, triggered=self.import_layer))

        # ウィンドウ: 欄ごとの表示と、並べ方（整列・別ウィンドウ・自由配置）
        self.panels = {"chat": (dock, Qt.LeftDockWidgetArea), "history": (hist, Qt.RightDockWidgetArea),
                       "layers": (ldock, Qt.RightDockWidgetArea)}
        self.tools = tools
        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AnimatedDocks)
        win = self.menuBar().addMenu("ウィンドウ")
        for d, _area in self.panels.values():
            win.addAction(d.toggleViewAction())
        win.addAction(tools.toggleViewAction())
        win.addSeparator()
        win.addAction(QAction("整列", self, triggered=self.arrange))
        win.addAction(QAction("すべて別ウィンドウにする", self, triggered=self.float_all))
        win.addAction(QAction("自由配置（欄をドラッグして好きな所に置く）", self, triggered=self.free_layout))
        self.settings = QSettings("CharacterDesigner", "chatdraw")
        self.default_state = self.saveState()
        state = self.settings.value("state")
        if state is not None:
            self.restoreGeometry(self.settings.value("geometry"))
            self.restoreState(state)

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

    def arrange(self):
        """欄をすべてウィンドウの左右に戻して並べる"""
        self.restoreState(self.default_state)
        for d, area in self.panels.values():
            d.setFloating(False)
            self.addDockWidget(area, d)
            d.show()
        self.addToolBar(Qt.LeftToolBarArea, self.tools)
        self.tools.show()

    def float_all(self):
        """欄をすべて別のウィンドウにして、少しずつずらして並べる"""
        x, y = self.geometry().right() - 380, self.geometry().top() + 40
        for i, (d, _area) in enumerate(self.panels.values()):
            d.show()
            d.setFloating(True)
            d.resize(360, 520)
            d.move(x - i * 40, y + i * 40)

    def free_layout(self):
        """欄の見出しをドラッグすると、左右上下のどこにでも置け、重ねるとタブになる"""
        for d, _area in self.panels.values():
            d.show()
            d.setFeatures(PANEL)
        self.tools.setMovable(True)
        self.statusBar().showMessage("欄の見出しをドラッグして、好きな所に置いてください。外へ出すと別ウィンドウになります")

    def closeEvent(self, e):
        # 次に開いたときも同じ並びにする
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        super().closeEvent(e)

    def _refresh_layers(self):
        # 上にあるレイヤーを上に並べる（作画ソフトと同じ順）
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for i in reversed(range(len(self.canvas.layers))):
            layer = self.canvas.layers[i]
            item = QListWidgetItem(layer.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            item.setData(Qt.UserRole, i)
            self.layer_list.addItem(item)
            if i == self.canvas.current:
                self.layer_list.setCurrentItem(item)
        if self.canvas.layers:
            self.layer_opacity.blockSignals(True)
            self.layer_opacity.setValue(int(self.canvas.layers[self.canvas.current].opacity * 100))
            self.layer_opacity.blockSignals(False)
        self.layer_list.blockSignals(False)

    def _layer_selected(self, row: int):
        item = self.layer_list.item(row)
        if item is not None:
            self.canvas.select(item.data(Qt.UserRole))

    def _layer_toggled(self, item: QListWidgetItem):
        self.canvas.set_visible(item.data(Qt.UserRole), item.checkState() == Qt.Checked)

    def import_layer(self):
        path, _ = QFileDialog.getOpenFileName(self, "画像をレイヤーとして読み込む", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.canvas.add_image_layer(path, Path(path).stem)

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "開く", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.canvas.show_image(path)

    def save_as(self):
        if not self.canvas.layers:
            return
        dst, _ = QFileDialog.getSaveFileName(self, "名前を付けて保存", "drawing.png", "PNG (*.png)")
        if dst:
            self.canvas.flatten().save(dst)

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
