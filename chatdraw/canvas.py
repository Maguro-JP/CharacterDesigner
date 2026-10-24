"""作画の欄。レイヤー、筆圧つきのペン、消しゴム、スポイト、塗りつぶし、元に戻す、拡大・回転を持つ。"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

UNDO_LIMIT = 50


@dataclass
class Layer:
    name: str
    image: QImage
    visible: bool = True
    opacity: float = 1.0

    def copy(self) -> "Layer":
        return Layer(self.name, self.image.copy(), self.visible, self.opacity)


def blank(w: int, h: int, color: QColor | None = None) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(color or QColor(0, 0, 0, 0))
    return img


class Canvas(QGraphicsView):
    changed = Signal()          # レイヤーの並びや中身が変わった（レイヤーの欄を描き直す）
    color_picked = Signal(QColor)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#2b2b2b"))
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.layers: list[Layer] = []
        self.current = 0
        self.tool = "pen"
        self.color = QColor("#000000")
        self.size = 6
        self.brush_opacity = 1.0
        self.undo_stack: list[tuple[list[Layer], int]] = []
        self.redo_stack: list[tuple[list[Layer], int]] = []
        self.last: QPointF | None = None
        self.pressure = 1.0
        self.angle = 0.0
        self.set_tool("pen")

    # ---- 書類 ----
    def size_px(self) -> tuple[int, int]:
        return (self.layers[0].image.width(), self.layers[0].image.height()) if self.layers else (0, 0)

    def new_canvas(self, w: int = 1200, h: int = 1600):
        self._reset([Layer("背景", blank(w, h, QColor("white"))), Layer("レイヤー 1", blank(w, h))], 1)

    def show_image(self, path: str):
        """絵を開く。絵を下に置き、その上に描くための空のレイヤーを足す"""
        img = QImage(path).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._reset([Layer("絵", img), Layer("レイヤー 1", blank(img.width(), img.height()))], 1)

    def add_image_layer(self, path: str, name: str = "絵"):
        img = QImage(path).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        if not self.layers:
            self._reset([Layer(name, img)], 0)
            return
        w, h = self.size_px()
        self.snapshot()
        layer = blank(w, h)
        p = QPainter(layer)
        p.drawImage(0, 0, img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.end()
        self.layers.insert(self.current + 1, Layer(name, layer))
        self.current += 1
        self.render()

    def _reset(self, layers: list[Layer], current: int):
        self.layers, self.current = layers, current
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.render()
        self.scene().setSceneRect(self.item.boundingRect())
        self.fit()

    def flatten(self) -> QImage:
        w, h = self.size_px()
        out = blank(w, h)
        p = QPainter(out)
        for layer in self.layers:
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.drawImage(0, 0, layer.image)
        p.end()
        return out

    def render(self):
        self.item.setPixmap(QPixmap.fromImage(self.flatten()) if self.layers else QPixmap())
        self.changed.emit()

    # ---- レイヤー ----
    def add_layer(self):
        w, h = self.size_px()
        self.snapshot()
        n = len(self.layers)
        self.layers.insert(self.current + 1, Layer(f"レイヤー {n}", blank(w, h)))
        self.current += 1
        self.render()

    def delete_layer(self):
        if len(self.layers) <= 1:
            return
        self.snapshot()
        del self.layers[self.current]
        self.current = max(0, self.current - 1)
        self.render()

    def move_layer(self, step: int):
        j = self.current + step
        if 0 <= j < len(self.layers):
            self.snapshot()
            self.layers[self.current], self.layers[j] = self.layers[j], self.layers[self.current]
            self.current = j
            self.render()

    def select(self, i: int):
        if 0 <= i < len(self.layers):
            self.current = i
            self.changed.emit()

    def set_visible(self, i: int, on: bool):
        self.layers[i].visible = on
        self.render()

    def set_opacity(self, value: float):
        self.layers[self.current].opacity = value
        self.render()

    # ---- 元に戻す ----
    def snapshot(self):
        self.undo_stack.append(([layer.copy() for layer in self.layers], self.current))
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(([layer.copy() for layer in self.layers], self.current))
            self.layers, self.current = self.undo_stack.pop()
            self.render()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(([layer.copy() for layer in self.layers], self.current))
            self.layers, self.current = self.redo_stack.pop()
            self.render()

    # ---- 表示 ----
    def fit(self):
        if self.layers:
            self.fitInView(self.item, Qt.KeepAspectRatio)

    def actual(self):
        self.resetTransform()
        self.angle = 0.0

    def rotate_view(self, deg: float):
        self.angle = (self.angle + deg) % 360
        self.rotate(deg)

    def reset_rotation(self):
        self.rotate(-self.angle)
        self.angle = 0.0

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    # ---- 道具 ----
    def set_tool(self, tool: str):
        self.tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == "hand" else QGraphicsView.NoDrag)
        self.setCursor(Qt.OpenHandCursor if tool == "hand" else Qt.CrossCursor)

    def stroke(self, a: QPointF, b: QPointF, pressure: float = 1.0):
        layer = self.layers[self.current].image
        p = QPainter(layer)
        p.setRenderHint(QPainter.Antialiasing)
        width = max(0.5, self.size * pressure)
        if self.tool == "eraser":
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            pen = QPen(QColor(0, 0, 0, int(255 * self.brush_opacity)), width * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        else:
            c = QColor(self.color)
            c.setAlphaF(self.brush_opacity * c.alphaF())
            pen = QPen(c, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        if a == b:
            p.drawPoint(a)   # 押しただけでも点が付くように
        else:
            p.drawLine(a, b)
        p.end()
        self.render()

    def pick(self, pos: QPointF):
        img = self.flatten()
        x, y = int(pos.x()), int(pos.y())
        if 0 <= x < img.width() and 0 <= y < img.height():
            c = img.pixelColor(x, y)
            c.setAlpha(255)
            self.color = c
            self.color_picked.emit(c)

    def fill(self, pos: QPointF, tolerance: int = 24):
        """見えている絵で色の近い続きの範囲を、今のレイヤーに塗る"""
        import numpy as np
        x, y = int(pos.x()), int(pos.y())
        w, h = self.size_px()
        if not (0 <= x < w and 0 <= y < h):
            return
        src = self.flatten().convertToFormat(QImage.Format_RGBA8888)
        arr = np.frombuffer(src.constBits(), np.uint8).reshape(h, src.bytesPerLine() // 4, 4)[:, :w].astype(np.int16)
        near = (np.abs(arr - arr[y, x]).max(axis=2) <= tolerance)
        mask = np.zeros((h, w), bool)
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if mask[cy, cx] or not near[cy, cx]:
                continue
            # 1 行ずつ左右へ広げる（点ごとより速い）
            lx = cx
            while lx > 0 and near[cy, lx - 1] and not mask[cy, lx - 1]:
                lx -= 1
            rx = cx
            while rx < w - 1 and near[cy, rx + 1] and not mask[cy, rx + 1]:
                rx += 1
            mask[cy, lx:rx + 1] = True
            for ny in (cy - 1, cy + 1):
                if 0 <= ny < h:
                    row = near[ny, lx:rx + 1] & ~mask[ny, lx:rx + 1]
                    starts = np.flatnonzero(row & np.concatenate(([True], ~row[:-1])))   # 続きの始まりだけ積む
                    stack.extend((lx + int(k), ny) for k in starts)
        self.snapshot()
        c = QColor(self.color)
        c.setAlphaF(self.brush_opacity)
        paint = np.zeros((h, w, 4), np.uint8)
        paint[mask] = (c.red(), c.green(), c.blue(), c.alpha())
        overlay = QImage(paint.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        p = QPainter(self.layers[self.current].image)
        p.drawImage(0, 0, overlay)
        p.end()
        self.render()

    # ---- マウスとペンタブレット ----
    def _press(self, pos: QPointF, pressure: float):
        if not self.layers or not self.layers[self.current].visible:
            return False
        if self.tool == "eyedropper":
            self.pick(pos)
            return True
        if self.tool == "fill":
            self.fill(pos)
            return True
        if self.tool in ("pen", "eraser"):
            self.snapshot()
            self.last = pos
            self.stroke(pos, pos, pressure)
            return True
        return False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.last is not None:
            pos = self.mapToScene(e.position().toPoint())
            self.stroke(self.last, pos, self.pressure)
            self.last = pos
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.last is not None:
            self.last = None
            self.pressure = 1.0
            return
        super().mouseReleaseEvent(e)

    def tabletEvent(self, e):
        # ペンタブレットの筆圧で太さと濃さを変える
        pos = self.mapToScene(e.position().toPoint())
        self.pressure = max(0.05, e.pressure())
        t = e.type()
        if t == e.Type.TabletPress:
            self._press(pos, self.pressure)
        elif t == e.Type.TabletMove and self.last is not None:
            self.stroke(self.last, pos, self.pressure)
            self.last = pos
        elif t == e.Type.TabletRelease:
            self.last = None
        e.accept()
