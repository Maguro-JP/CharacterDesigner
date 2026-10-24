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
    # 初めての起動だけ、ウィンドウの部品（PySide6）を入れる。6.12.0 は Python 3.11 で None の参照数を減らしすぎ、
    # 線を数百本引くと落ちた。落ちないことを確かめた 6.9.3 に固定する
    import subprocess
    lib = ROOT / ".cache" / "simple" / "lib"
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(lib), "PySide6-Essentials==6.9.3"], check=True)
    sys.path.insert(0, str(lib))

import re  # noqa: E402

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, Signal  # noqa: E402
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog,  # noqa: E402
                               QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QColorDialog, QComboBox, QFormLayout, QLabel, QProgressBar, QPushButton, QSlider, QSpinBox, QTextEdit, QToolBar, QVBoxLayout, QWidget)

from PIL import Image  # noqa: E402

from chatdraw.canvas import Canvas  # noqa: E402
from chatdraw.engine import Painter, Studio, Words  # noqa: E402
from chatdraw.settings import Settings, SettingsDialog  # noqa: E402


class Job(QObject):
    status = Signal(str)
    done = Signal(str, str)
    failed = Signal(str)

    def __init__(self, studio: Studio, text: str, seed: int, base=None, strength: float = 0.6, size=None):
        super().__init__()
        self.studio, self.text, self.seed = studio, text, seed
        self.base, self.strength, self.size = base, strength, size

    def run(self):
        try:
            prompt, path = self.studio.draw(self.text, self.seed, on_status=self.status.emit,
                                            base=self.base, strength=self.strength, size=self.size)
            self.done.emit(prompt, str(path))
        except Exception as e:  # 描けなかった理由をそのまま会話に出す
            self.failed.emit(f"描けませんでした: {e}")


def qimage_to_pil(img):
    """キャンバスの絵（QImage）を描く模型に渡せる形（PIL）にする"""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()), "raw", "RGBA",
                            img.bytesPerLine(), 1).convert("RGB")


class PanelTitle(QWidget):
    """欄の見出し。畳む（最小化）・別ウィンドウにする・隠す の 3 つのボタンを持つ。見出しをダブルクリックしても畳める"""

    def __init__(self, dock: "QDockWidget"):
        super().__init__(dock)
        self.dock = dock
        self.collapsed = False
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 2, 2)
        row.setSpacing(2)
        self.label = QLabel(dock.windowTitle())
        row.addWidget(self.label)
        row.addStretch()
        for text, tip, fn in (("▁", "畳む（見出しだけにする）", self.toggle), ("⧉", "別ウィンドウにする・戻す", self.float_),
                              ("✕", "隠す（「ウィンドウ」メニューで戻せます）", dock.hide)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(22, 20)
            b.setFlat(True)
            b.clicked.connect(fn)
            row.addWidget(b)
            if text == "▁":
                self.collapse_button = b

    def toggle(self):
        self.collapsed = not self.collapsed
        body = self.dock.widget()
        if body is not None:
            body.setVisible(not self.collapsed)
        if self.collapsed:
            self.dock.setMaximumHeight(self.sizeHint().height() + 4)
        else:
            self.dock.setMaximumHeight(16777215)
        self.collapse_button.setText("▔" if self.collapsed else "▁")

    def float_(self):
        self.dock.setFloating(not self.dock.isFloating())

    def mouseDoubleClickEvent(self, e):
        self.toggle()


# 欄は動かせて、外に出せて、閉じられる（作画ソフトと同じ）
PANEL = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable


class Window(QMainWindow):
    """作画ソフトの並び: 左に頼みの欄、真ん中に絵、右に描いた絵の一覧、下に進み"""

    def __init__(self, studio: Studio | None = None):
        super().__init__()
        self.settings = Settings()
        self.studio = studio or self._studio_from_settings()
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
        self.stop_button = QPushButton("止める")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        row = QHBoxLayout()
        row.addWidget(self.entry)
        row.addWidget(self.button)
        row.addWidget(self.stop_button)
        # 描き方: 新しく描くか、キャンバスの絵（下描き・ラフ）を元に描き直すか
        self.mode = QComboBox()
        self.mode.addItems(["新しく描く", "キャンバスを元に描く"])
        self.size_pick = QComboBox()
        for label, wh in (("縦長 832×1216", (832, 1216)), ("横長 1216×832", (1216, 832)), ("正方形 1024×1024", (1024, 1024))):
            self.size_pick.addItem(label, wh)
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(10, 95)
        self.strength.setValue(int(self.settings.get("rough_strength") * 100))
        self.strength_label = QLabel("元から変える強さ 0.60")
        self.strength.valueChanged.connect(lambda v: self.strength_label.setText(f"元から変える強さ {v / 100:.2f}"))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed(0)
        form = QFormLayout()
        form.addRow("描き方", self.mode)
        form.addRow("大きさ", self.size_pick)
        form.addRow(self.strength_label, self.strength)
        left = QVBoxLayout()
        left.addWidget(self.chat)
        left.addLayout(form)
        left.addLayout(row)
        box = QWidget()
        box.setLayout(left)
        dock = QDockWidget("頼み", self)
        dock.setWidget(box)
        dock.setObjectName("chat")
        dock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

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
        file.addAction(QAction("模型を取る…", self, triggered=lambda: self.ask_models(force=True)))
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
        for key, label, short in (("pen", "ペン", "B"), ("eraser", "消しゴム", "E"), ("fill", "塗りつぶし", "G"),
                                  ("eyedropper", "スポイト", "I"), ("hand", "手のひら", "H")):
            act = QAction(label, self, checkable=True, shortcut=short, triggered=lambda _=False, k=key: self.canvas.set_tool(k))
            group.addAction(act)
            tools.addAction(act)
            self.tool_actions[key] = act
        self.tool_actions["pen"].setChecked(True)
        # 左上: ツールの設定（色・太さ・濃さ）
        self.color_button = QPushButton()
        self.color_button.setFixedSize(48, 32)
        self.color_button.clicked.connect(self.pick_color)
        self._show_color()
        self.size_box = QSpinBox()
        self.size_box.setRange(1, 200)
        self.size_box.setValue(self.canvas.size)
        self.size_box.setSuffix(" px")
        self.size_box.valueChanged.connect(lambda v: setattr(self.canvas, "size", v))
        self.flow = QSlider(Qt.Horizontal)
        self.flow.setRange(1, 100)
        self.flow.setValue(100)
        self.flow.valueChanged.connect(lambda v: setattr(self.canvas, "brush_opacity", v / 100))
        opts = QFormLayout()
        opts.addRow("色", self.color_button)
        opts.addRow("太さ", self.size_box)
        opts.addRow("濃さ", self.flow)
        obox = QWidget()
        obox.setLayout(opts)
        odock = QDockWidget("ツールの設定", self)
        odock.setObjectName("toolopts")
        odock.setWidget(obox)
        odock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, odock)
        self.canvas.color_picked.connect(lambda _c: self._show_color())
        self.canvas.brush_changed.connect(self.size_box.setValue)
        self.zoom_label = QLabel("100%")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.canvas.zoomed.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))

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
        ldock.setObjectName("layers")
        ldock.setFeatures(PANEL)
        self.addDockWidget(Qt.RightDockWidgetArea, ldock)
        self.canvas.changed.connect(self._refresh_layers)
        self._refresh_layers()

        view = self.menuBar().addMenu("表示")
        view.addAction(QAction("全体を表示", self, shortcut="Ctrl+0", triggered=self.canvas.fit))
        view.addAction(QAction("100%", self, shortcut="Ctrl+1", triggered=self.canvas.actual))
        view.addAction(QAction("左に回す", self, shortcut="Ctrl+[", triggered=lambda: self.canvas.rotate_view(-15)))
        view.addAction(QAction("右に回す", self, shortcut="Ctrl+]", triggered=lambda: self.canvas.rotate_view(15)))
        view.addAction(QAction("回転を戻す", self, shortcut="Ctrl+\\", triggered=self.canvas.reset_rotation))
        setting_menu = self.menuBar().addMenu("設定")
        setting_menu.addAction(QAction("設定…", self, shortcut="Ctrl+,", triggered=self.open_settings))
        layer_menu = self.menuBar().addMenu("レイヤー")
        layer_menu.addAction(QAction("新しいレイヤー", self, shortcut="Ctrl+Shift+N", triggered=self.canvas.add_layer))
        layer_menu.addAction(QAction("レイヤーを消す", self, triggered=self.canvas.delete_layer))
        layer_menu.addAction(QAction("画像をレイヤーとして読み込む…", self, triggered=self.import_layer))

        # ウィンドウ: 欄ごとの表示と、並べ方（整列・別ウィンドウ・自由配置）
        self.panels = {"toolopts": (odock, Qt.LeftDockWidgetArea), "chat": (dock, Qt.LeftDockWidgetArea),
                       "history": (hist, Qt.RightDockWidgetArea), "layers": (ldock, Qt.RightDockWidgetArea)}
        for d, _area in self.panels.values():
            d.setTitleBarWidget(PanelTitle(d))
            # 欄の境目をドラッグして上下左右に広げ縮めできる。狭めすぎて中身が潰れない大きさだけ決める
            d.setMinimumSize(160, 80)
            d.topLevelChanged.connect(lambda floating, d=d: self._as_window(d, floating))
        self.tools = tools
        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AnimatedDocks)
        win = self.menuBar().addMenu("ウィンドウ")
        keys = {"toolopts": "F5", "chat": "F6", "history": "F7", "layers": "F8"}
        for k, (d, _area) in self.panels.items():
            act = d.toggleViewAction()   # チェックが付いていれば表示中
            act.setShortcut(keys[k])
            win.addAction(act)
        tact = tools.toggleViewAction()
        tact.setShortcut("F4")
        win.addAction(tact)
        win.addSeparator()
        win.addAction(QAction("すべての欄を畳む", self, triggered=lambda: self._collapse_all(True)))
        win.addAction(QAction("すべての欄を広げる", self, triggered=lambda: self._collapse_all(False)))
        win.addAction(QAction("メインウィンドウを最小化", self, shortcut="Ctrl+M", triggered=self.showMinimized))
        win.addSeparator()
        win.addAction(QAction("すべての欄を表示", self, triggered=lambda: self._show_all(True)))
        win.addAction(QAction("すべての欄を隠す（絵だけを見る）", self, shortcut="Tab", triggered=lambda: self._show_all(False)))
        win.addSeparator()
        win.addAction(QAction("整列（初期の配置に戻す）", self, triggered=self.arrange))
        win.addAction(QAction("すべて別ウィンドウにする", self, triggered=self.float_all))
        win.addAction(QAction("自由配置（欄をドラッグして好きな所に置く）", self, triggered=self.free_layout))
        self.layout_store = QSettings("CharacterDesigner", "chatdraw")
        state = self.layout_store.value("state")
        if state is not None:
            self.restoreGeometry(self.layout_store.value("geometry"))
            self.restoreState(state)
        else:
            self.arrange()

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
        self.stop_button.setEnabled(True)
        base = None
        if self.mode.currentIndex() == 1:
            base = qimage_to_pil(self.canvas.flatten())
        self.thread = QThread()
        self.job = Job(self.studio, text, int(time.time()), base=base, strength=self.strength.value() / 100,
                       size=self.size_pick.currentData())
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
        self.place(path)
        self.say("描きました")
        self._end("できました")

    def _studio_from_settings(self) -> Studio:
        g = self.settings.get
        return Studio(Words(Path(g("words_model"))), Painter(g("image_model"), g("steps"), guidance=g("guidance")),
                      Path(g("output_dir")))

    def open_settings(self):
        """設定ウィンドウを開き、保存されたら描く仕組みに当てる。絵の模型を替えたときだけ読み直す"""
        if SettingsDialog(self.settings, self).exec():
            g = self.settings.get
            painter = self.studio.painter
            if getattr(painter, "model", None) != g("image_model"):
                self.studio.painter = Painter(g("image_model"), g("steps"), guidance=g("guidance"))
            else:
                painter.steps, painter.guidance = g("steps"), g("guidance")
            if str(getattr(self.studio.words, "path", "")) != g("words_model"):
                self.studio.words = Words(Path(g("words_model")))
            self.studio.out = Path(g("output_dir"))
            self.strength.setValue(int(g("rough_strength") * 100))
            self.statusBar().showMessage("設定を保存しました")

    def ask_models(self, force: bool = False):
        """描くのに要る模型が足りなければ、取るかどうかを聞く"""
        from chatdraw.setup import SetupDialog, missing
        need = missing()
        if any(need.values()) or force:
            SetupDialog(need, self).exec()

    def place(self, path: str):
        """描けた絵を置く。新しく描いて、まだ何も描いていないキャンバスなら絵を開く。
        キャンバスを元に描いたときと、描いている途中なら、元の絵を残して新しいレイヤーとして重ねる"""
        if self.mode.currentIndex() == 0 and not self.canvas.undo_stack and len(self.canvas.layers) <= 2:
            self.canvas.show_image(path)
        else:
            self.canvas.add_image_layer(path, f"AI の絵 {len(self.images)}")

    def stop(self):
        self.studio.painter.stop = True
        self.statusBar().showMessage("止めています（いまの 1 工程が終わると止まります）")

    def _mode_changed(self, i: int):
        self.size_pick.setEnabled(i == 0)          # 元に描くときはキャンバスの大きさで描く
        self.strength.setEnabled(i == 1)
        self.strength_label.setEnabled(i == 1)

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
        """初期の配置。左に道具・ツールの設定・頼み、右に描いた絵・レイヤー、真ん中を広く絵に使う"""
        opt, chat = self.panels["toolopts"][0], self.panels["chat"][0]
        hist, layers = self.panels["history"][0], self.panels["layers"][0]
        for d, _area in self.panels.values():
            d.setFloating(False)
            d.show()
        self.addToolBar(Qt.LeftToolBarArea, self.tools)
        self.tools.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, opt)
        self.splitDockWidget(opt, chat, Qt.Vertical)
        self.addDockWidget(Qt.RightDockWidgetArea, hist)
        self.splitDockWidget(hist, layers, Qt.Vertical)
        w, h = max(self.width(), 1200), max(self.height(), 800)
        side = min(320, max(240, int(w * 0.17)))   # 真ん中の絵を広く取る
        self.resizeDocks([opt, hist], [side, side], Qt.Horizontal)
        self.resizeDocks([opt, chat], [140, h - 140], Qt.Vertical)   # ツールの設定は中身の高さだけ
        self.resizeDocks([hist, layers], [int(h * 0.4), int(h * 0.6)], Qt.Vertical)

    def _as_window(self, d: QDockWidget, floating: bool):
        """別ウィンドウにした欄を、ふつうのウィンドウの枠にする。上下左右と四隅の端をつかんで大きさを変えられ、最大化もできる"""
        if floating:
            d.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
            d.show()

    def _collapse_all(self, on: bool):
        for d, _area in self.panels.values():
            title = d.titleBarWidget()
            if isinstance(title, PanelTitle) and title.collapsed != on:
                title.toggle()

    def _show_all(self, on: bool):
        for d, _area in self.panels.values():
            d.setVisible(on)
        self.tools.setVisible(on)

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
        self.layout_store.setValue("geometry", self.saveGeometry())
        self.layout_store.setValue("state", self.saveState())
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
        self.stop_button.setEnabled(False)
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
    w.ask_models()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
