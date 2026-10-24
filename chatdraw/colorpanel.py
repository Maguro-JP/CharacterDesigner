"""色の欄。色相の輪の帯・彩度と明度の四角・16 進の入力・描く色と背景色・見本の色・最近使った色を持つ（作画ソフトと同じ並び）"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

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

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.recent: list[str] = []
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
        pal = QWidget()
        al = QVBoxLayout(pal)
        al.setContentsMargins(0, 6, 0, 0)
        al.addLayout(grid)
        recent = QLabel("最近の色")
        recent.setObjectName("cardMeta")
        al.addWidget(recent)
        al.addLayout(self.recent_row)
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
        self.canvas.color = c
        self._paint_chips()
        self.color_changed.emit(c)

    def _hex_entered(self):
        c = QColor(self.hex.text().strip())
        if c.isValid():
            self.set_color(c)

    def set_color(self, c: QColor):
        self.canvas.color = QColor(c)
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
