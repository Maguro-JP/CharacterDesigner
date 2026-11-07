"""色の欄。色相の輪の帯・彩度と明度の四角・色相/彩度/明度の数字・透明度・16 進の入力・描く色と背景色・スポイト・
色の出方（単色・虹色・2 色の行き来）・見本の色・自分のパレット（足す・消す・保存・読み込み）・最近使った色を持つ"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from chatdraw.canvas import COLOR_MODES

SWATCHES = ("#000000", "#3a3a3c", "#7a7a7e", "#c7c7cc", "#ffffff", "#f6d7c3", "#e8b79a", "#b97a56",
            "#e5322d", "#ff7a1a", "#ffc93c", "#7ccf5a", "#2fb3a3", "#3d7bff", "#7b5cff", "#e255a1")


class SVSquare(QWidget):
    """彩度（横）と明度（縦）を選ぶ四角"""
    picked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.hue, self.s, self.v = 0.0, 1.0, 1.0
        self.setMinimumSize(160, 130)
        self.setMaximumHeight(220)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, QColor("white"))
        g.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 8, 8)
        g2 = QLinearGradient(r.topLeft(), r.bottomLeft())
        g2.setColorAt(0, QColor(0, 0, 0, 0))
        g2.setColorAt(1, QColor(0, 0, 0, 255))
        p.setBrush(g2)
        p.drawRoundedRect(r, 8, 8)
        c = QPointF(r.left() + self.s * r.width(), r.top() + (1 - self.v) * r.height())
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(c, 6, 6)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawEllipse(c, 7.5, 7.5)

    def _at(self, pos):
        self.s = min(1.0, max(0.0, pos.x() / max(1, self.width())))
        self.v = 1 - min(1.0, max(0.0, pos.y() / max(1, self.height())))
        self.update()
        self.picked.emit(self.s, self.v)

    def mousePressEvent(self, e):
        self._at(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._at(e.position())


class HueBar(QWidget):
    """色相を選ぶ横の帯"""
    picked = Signal(float)

    def __init__(self):
        super().__init__()
        self.hue = 0.0
        self.setFixedHeight(16)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 3, -0.5, -3)
        g = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(7):
            g.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1, 1))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 5, 5)
        x = r.left() + self.hue * r.width()
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(QColor.fromHsvF(self.hue, 1, 1))
        p.drawEllipse(QPointF(x, self.height() / 2), 6.5, 6.5)

    def _at(self, pos):
        self.hue = min(0.999, max(0.0, pos.x() / max(1, self.width())))
        self.update()
        self.picked.emit(self.hue)

    def mousePressEvent(self, e):
        self._at(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._at(e.position())


class AlphaPreview(QWidget):
    """描く色を、市松模様の上に透明度ごと見せる見本（透明度は色の四角だけでは見えないため）"""

    def __init__(self):
        super().__init__()
        self.color = QColor("#000000")
        self.setFixedSize(44, 22)
        self.setToolTip("今の描く色の見本（市松模様が透けて見えるほど薄い）")

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        k = 6
        for y in range(0, r.height(), k):
            for x in range(0, r.width(), k):
                p.fillRect(x, y, k, k, QColor("#ffffff") if (x // k + y // k) % 2 == 0 else QColor("#c8c8cc"))
        p.fillRect(r, self.color)
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.drawRect(r.adjusted(0, 0, -1, -1))


def chip(color: str, size: int = 20) -> QPushButton:
    b = QPushButton()
    b.setFixedSize(size, size)
    b.setToolTip(color)
    b.setObjectName("chip")
    b.setStyleSheet(f"QPushButton#chip {{ background:{color}; border-radius:{size // 4}px; border:1px solid rgba(255,255,255,40); padding:0; }}"
                    "QPushButton#chip:hover { border:1px solid #ff7a1a; }")
    return b


class ColorPanel(QWidget):
    """描く色を変えたら color_changed を出す。背景色の入れ替え（X）と白黒に戻す（D）は Canvas が持つ"""
    color_changed = Signal(QColor)
    eyedropper_wanted = Signal()   # スポイトの丸を押した（窓がスポイトの道具に持ち替える）
    mode_changed = Signal(str)     # 色の出方を変えた

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.recent: list[str] = []
        self.mine: list[str] = []   # 自分のパレット（足した順）
        self.square = SVSquare()
        self.hue = HueBar()
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setPlaceholderText("#rrggbb")
        self.hex.editingFinished.connect(self._hex_entered)
        self.fg = QPushButton()
        self.bg = QPushButton()
        for b, tip in ((self.fg, "描く色"), (self.bg, "背景色（押すと描く色と入れ替え。X キー）")):
            b.setFixedSize(30, 30)
            b.setToolTip(tip)
        self.bg.clicked.connect(canvas.swap_colors)
        swap = QPushButton("⇄")
        swap.setFixedSize(26, 26)
        swap.setObjectName("small")
        swap.setToolTip("描く色と背景色を入れ替える（X）")
        swap.clicked.connect(canvas.swap_colors)
        reset = QPushButton("◐")
        reset.setFixedSize(26, 26)
        reset.setObjectName("small")
        reset.setToolTip("黒と白に戻す（D）")
        reset.clicked.connect(canvas.reset_colors)
        top = QHBoxLayout()
        top.addWidget(self.fg)
        top.addWidget(self.bg)
        top.addWidget(swap)
        top.addWidget(reset)
        from chatdraw.icons import icon
        drop = QPushButton()
        drop.setIcon(icon("eyedropper"))
        drop.setFixedSize(26, 26)
        drop.setObjectName("small")
        drop.setToolTip("スポイト。絵の上で押した所の色を描く色にする（I）")
        drop.clicked.connect(self.eyedropper_wanted.emit)
        top.addWidget(drop)
        top.addStretch()
        top.addWidget(self.hex)
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, c in enumerate(SWATCHES):
            b = chip(c)
            b.clicked.connect(lambda _=False, c=c: self.set_color(QColor(c)))
            grid.addWidget(b, i // 8, i % 8)
        self.recent_row = QHBoxLayout()
        self.recent_row.setSpacing(4)
        self.recent_row.addStretch()
        # タブで「カラー」（色を作る）と「パレット」（見本と最近使った色）を切り替える。描く色と背景色はどちらでも見える
        pick = QWidget()
        pl = QVBoxLayout(pick)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.addWidget(self.square, 1)
        pl.addWidget(self.hue)
        # 数字でも合わせられるように、色相（0〜359）・彩度・明度（0〜100）を並べる
        nums = QHBoxLayout()
        nums.setSpacing(4)
        self.h_box, self.s_box, self.v_box = QSpinBox(), QSpinBox(), QSpinBox()
        for box, label, top_, tip in ((self.h_box, "色相", 359, "色相（0〜359 度）"), (self.s_box, "彩度", 100, "彩度（0〜100）"),
                                      (self.v_box, "明度", 100, "明度（0〜100）")):
            box.setRange(0, top_)
            box.setToolTip(tip)
            box.valueChanged.connect(self._from_numbers)
            nums.addWidget(QLabel(label))
            nums.addWidget(box)
        pl.addLayout(nums)
        # 透明度（0 で透明、100 で不透明）。ブラシの濃さとは別に、色そのものの透け方として残す
        arow = QHBoxLayout()
        arow.setSpacing(4)
        arow.addWidget(QLabel("透明度"))
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setToolTip("描く色の不透明さ（0 で透明、100 で透けない）。ペン・塗りつぶし・形・文字に効きます")
        self.alpha_box = QSpinBox()
        self.alpha_box.setRange(0, 100)
        self.alpha_box.setSuffix("%")
        self.alpha_box.setToolTip(self.alpha_slider.toolTip())
        self.alpha_preview = AlphaPreview()
        self.alpha_slider.valueChanged.connect(self.alpha_box.setValue)
        self.alpha_box.valueChanged.connect(self.alpha_slider.setValue)
        self.alpha_box.valueChanged.connect(self._alpha_changed)
        arow.addWidget(self.alpha_slider, 1)
        arow.addWidget(self.alpha_box)
        arow.addWidget(self.alpha_preview)
        pl.addLayout(arow)
        self.mode = QComboBox()
        self.mode.addItems(COLOR_MODES)
        self.mode.setToolTip("ペンとスプレーの色の出方。虹色は線を引くほど色相が回り、行き来は描く色と背景色の間を行き来する")
        self.mode.currentTextChanged.connect(self._mode_picked)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("色の出方"))
        mrow.addWidget(self.mode, 1)
        pl.addLayout(mrow)
        pal = QWidget()
        al = QVBoxLayout(pal)
        al.setContentsMargins(0, 6, 0, 0)
        al.addLayout(grid)
        recent = QLabel("最近の色")
        recent.setObjectName("cardMeta")
        al.addWidget(recent)
        al.addLayout(self.recent_row)
        mine = QLabel("自分のパレット")
        mine.setObjectName("cardMeta")
        al.addWidget(mine)
        self.mine_grid = QGridLayout()
        self.mine_grid.setSpacing(4)
        al.addLayout(self.mine_grid)
        mbar = QHBoxLayout()
        for text, tip, fn in (("＋", "今の描く色をパレットに足す", self.add_to_palette),
                              ("保存", "自分のパレットをファイルに保存する", self._save_dialog),
                              ("読み込み", "保存したパレットのファイルを読み込む", self._load_dialog)):
            b = QPushButton(text)
            b.setObjectName("small")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            mbar.addWidget(b)
        mbar.addStretch()
        al.addLayout(mbar)
        al.addStretch()
        self.tabs = QTabWidget()
        self.tabs.addTab(pick, "カラー")
        self.tabs.addTab(pal, "パレット")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(self.tabs)
        lay.addLayout(top)
        lay.addStretch(1)   # 欄が縦に長くても、色の四角は伸ばさずに上へ詰める
        self.square.picked.connect(lambda s, v: self._from_hsv())
        self.hue.picked.connect(lambda h: self._from_hsv())
        canvas.color_picked.connect(lambda c: self.show_color())
        self.show_color()

    def _from_hsv(self):
        self.square.hue = self.hue.hue
        self.square.update()
        c = QColor.fromHsvF(self.hue.hue, self.square.s, self.square.v)
        c.setAlpha(self.canvas.color.alpha())   # 色を選び直しても透明度は残す
        self.canvas.color = c
        self._paint_chips()
        self.color_changed.emit(c)

    def _from_numbers(self):
        if getattr(self, "_showing", False):
            return
        self.set_color(QColor.fromHsv(self.h_box.value(), round(self.s_box.value() * 2.55), round(self.v_box.value() * 2.55)))

    def _alpha_changed(self, v: int):
        if getattr(self, "_showing", False):
            return
        c = QColor(self.canvas.color)
        c.setAlpha(int(v * 255 / 100 + 0.5))
        self.canvas.color = c
        self._paint_chips()
        self.color_changed.emit(c)

    def _mode_picked(self, mode: str):
        self.canvas.color_mode = mode
        self.mode_changed.emit(mode)

    # ---- 自分のパレット ----
    def add_to_palette(self, name: str | None = None):
        name = QColor(name).name() if name else self.canvas.color.name()
        if name not in self.mine:
            self.mine.append(name)
        self._paint_mine()

    def remove_from_palette(self, name: str):
        if name in self.mine:
            self.mine.remove(name)
        self._paint_mine()

    def _paint_mine(self):
        while self.mine_grid.count():
            it = self.mine_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, n in enumerate(self.mine):
            b = chip(n, 18)
            b.setToolTip(f"{n}（右クリックでパレットから消す）")
            b.clicked.connect(lambda _=False, n=n: self.set_color(QColor(n)))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p, n=n: self.remove_from_palette(n))
            self.mine_grid.addWidget(b, i // 10, i % 10)

    def save_palette(self, path: str):
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps({"colors": self.mine}, ensure_ascii=False, indent=1), encoding="utf-8")

    def load_palette(self, path: str) -> int:
        """読み込んだ色の数を返す。読めない色は飛ばす（壊れたファイルでパレットを空にしない）"""
        import json
        from pathlib import Path
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        colors = data.get("colors", []) if isinstance(data, dict) else data
        got = [QColor(c).name() for c in colors if isinstance(c, str) and QColor(c).isValid()]
        if got:
            self.mine = list(dict.fromkeys(got))
            self._paint_mine()
        return len(got)

    def _save_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "パレットを保存", "palette.json", "パレット (*.json)")
        if path:
            self.save_palette(path)

    def _load_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "パレットを読み込む", "", "パレット (*.json)")
        if path:
            try:
                self.load_palette(path)
            except (OSError, ValueError):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "パレット", "このファイルはパレットとして読めませんでした")

    def _hex_entered(self):
        c = QColor(self.hex.text().strip())
        if c.isValid():
            self.set_color(c)

    def set_color(self, c: QColor):
        """見本・16 進・スポイトで選んだ色にする。透けない色が来たら、今の透明度を残す"""
        c = QColor(c)
        if c.alpha() == 255:
            c.setAlpha(self.canvas.color.alpha())
        self.canvas.color = c
        self.show_color()
        self.color_changed.emit(c)

    def show_color(self):
        """Canvas の色に合わせて、輪と四角と見本を描き直す"""
        c = self.canvas.color
        h, s, v, _ = c.getHsvF()
        if h >= 0:
            self.hue.hue = h
        self.square.hue, self.square.s, self.square.v = self.hue.hue, s, v
        self.hue.update()
        self.square.update()
        self._paint_chips()

    def _paint_chips(self):
        c, b = self.canvas.color, self.canvas.bg_color
        self.fg.setStyleSheet(f"background:{c.name()}; border:2px solid #f2f2f2; border-radius:7px;")
        self.bg.setStyleSheet(f"background:{b.name()}; border:1px solid #5a5a60; border-radius:7px;")
        self.hex.setText(c.name())
        if hasattr(self, "h_box"):
            self._showing = True
            h, s, v, _ = c.getHsv()
            if h >= 0:
                self.h_box.setValue(h)
            self.s_box.setValue(round(s / 2.55))
            self.v_box.setValue(round(v / 2.55))
            self.alpha_box.setValue(int(c.alpha() * 100 / 255 + 0.5))
            self.alpha_preview.color = QColor(c)
            self.alpha_preview.update()
            self._showing = False

    def remember(self):
        """描き始めた色を最近使った色に足す（新しい順に 8 色）"""
        name = self.canvas.color.name()
        if name in self.recent:
            self.recent.remove(name)
        self.recent.insert(0, name)
        del self.recent[8:]
        while self.recent_row.count() > 1:
            it = self.recent_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, n in enumerate(self.recent):
            b = chip(n, 18)
            b.clicked.connect(lambda _=False, n=n: self.set_color(QColor(n)))
            self.recent_row.insertWidget(i, b)
