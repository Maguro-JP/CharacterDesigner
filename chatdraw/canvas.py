"""作画の欄。レイヤー、筆圧つきのペン、消しゴム、ぼかし、スポイト、塗りつぶし、グラデーション、直線・四角・楕円、
移動、四角の選択範囲、元に戻す、拡大・回転を持つ。

描くたびに全部を描き直すと、大きな絵（4096 画素）で線が遅れる。レイヤーごとに絵の部品を持ち、
線を引いた所の四角だけを描き直す。元に戻すは、触ったレイヤーの分だけを覚える。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from chatdraw.brush import PRESETS, Brush, Dabs, stamp

UNDO_BYTES = 1_500_000_000   # 元に戻すに使うメモリの上限（約 1.5GB）
BRUSH_TOOLS = ("pen", "eraser", "blur")                       # なぞって描く道具（筆の輪を出す）
DRAG_TOOLS = ("line", "rect", "ellipse", "gradient", "move", "select")   # 押した所から離した所までで決まる道具


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


class LayerItem(QGraphicsItem):
    """1 枚のレイヤーを、頼まれた四角だけ描く"""

    def __init__(self, layer: Layer):
        super().__init__()
        self.layer = layer
        self.buffer: QImage | None = None   # 描いている途中の線（手を離すとレイヤーへ重ねる）
        self.buffer_opacity = 1.0

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.layer.image.width(), self.layer.image.height())

    def paint(self, p: QPainter, option, widget=None):
        if not self.layer.visible:
            return
        r = option.exposedRect.toAlignedRect().intersected(self.layer.image.rect())
        p.setOpacity(self.layer.opacity)
        p.drawImage(r.topLeft(), self.layer.image, r)
        if self.buffer is not None:
            p.setOpacity(self.layer.opacity * self.buffer_opacity)
            p.drawImage(r.topLeft(), self.buffer, r)


class Canvas(QGraphicsView):
    changed = Signal()          # レイヤーの並びや中身が変わった（レイヤーの欄を描き直す）
    color_picked = Signal(QColor)
    zoomed = Signal(float)
    brush_changed = Signal(int)
    used_color = Signal()       # 描く色で描き始めた（最近使った色に足す）

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#0e0f11"))
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.layers: list[Layer] = []
        self.items: list[LayerItem] = []
        self.current = 0
        self.tool = "pen"
        self.color = QColor("#000000")
        self.bg_color = QColor("#ffffff")   # 背景色（X で描く色と入れ替える）
        self.selection: QRect | None = None   # 四角の選択範囲。あれば描く・消す・塗るはこの中だけに効く
        self.drag_start: QPointF | None = None
        self.fill_shapes = False   # 四角と楕円を塗りつぶすか（線だけか）
        self.size = 6
        self.brush_opacity = 1.0
        self.brushes = {b.name: Brush(**b.to_dict()) for b in PRESETS}
        self.brush = self.brushes["ペン"]
        self.dabs = Dabs()
        self.buffer: QImage | None = None
        self.carry = 0.0
        self.undo_stack: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.last: QPointF | None = None
        self.pressure = 1.0
        self.angle = 0.0
        self.held: str | None = None   # Space や Alt を押している間だけ持ち替える前の道具
        self.cursor_ring = QGraphicsEllipseItem()
        self.cursor_ring.setPen(QPen(QColor(255, 255, 255, 200), 0))
        self.cursor_ring.setZValue(1e9)
        self.scene().addItem(self.cursor_ring)
        self.sel_item = QGraphicsRectItem()
        pen = QPen(QColor("#ff7a1a"), 0, Qt.DashLine)
        self.sel_item.setPen(pen)
        self.sel_item.setBrush(QColor(255, 122, 26, 18))
        self.sel_item.setZValue(1e9 - 1)
        self.sel_item.setVisible(False)
        self.scene().addItem(self.sel_item)
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
        self.snapshot_all()
        layer = blank(w, h)
        p = QPainter(layer)
        p.drawImage(0, 0, img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.end()
        self.layers.insert(self.current + 1, Layer(name, layer))
        self.current += 1
        self.rebuild()

    def _reset(self, layers: list[Layer], current: int):
        self.layers, self.current = layers, current
        self.set_selection(None)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.rebuild()
        w, h = self.size_px()
        self.scene().setSceneRect(QRectF(0, 0, w, h))
        self.fit()

    def flatten(self) -> QImage:
        w, h = self.size_px()
        out = blank(w, h)
        p = QPainter(out)
        for i, layer in enumerate(self.layers):
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.drawImage(0, 0, layer.image)
                if self.buffer is not None and i == self.current:
                    p.setOpacity(layer.opacity * self.brush_opacity)
                    p.drawImage(0, 0, self.buffer)
        p.end()
        return out

    def rebuild(self):
        """レイヤーの並びが変わったときだけ、絵の部品を作り直す"""
        for it in self.items:
            self.scene().removeItem(it)
        self.items = []
        for z, layer in enumerate(self.layers):
            it = LayerItem(layer)
            it.setZValue(z)
            self.scene().addItem(it)
            self.items.append(it)
        self.changed.emit()

    # ---- AI が描いている途中の絵 ----
    def show_overlay(self, img: QImage | None):
        """AI の途中の絵を、キャンバスいっぱいに薄く重ねて見せる。None で消す"""
        if not hasattr(self, "overlay"):
            from PySide6.QtWidgets import QGraphicsPixmapItem
            self.overlay = QGraphicsPixmapItem()
            self.overlay.setZValue(1e8)
            self.overlay.setTransformationMode(Qt.SmoothTransformation)
            self.scene().addItem(self.overlay)
        if img is None:
            self.overlay.setVisible(False)
            return
        w, h = self.size_px()
        self.overlay.setPixmap(QPixmap.fromImage(img).scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        self.overlay.setVisible(True)

    # ---- レイヤー ----
    def add_layer(self):
        w, h = self.size_px()
        self.snapshot_all()
        self.layers.insert(self.current + 1, Layer(f"レイヤー {len(self.layers)}", blank(w, h)))
        self.current += 1
        self.rebuild()

    def delete_layer(self):
        if len(self.layers) <= 1:
            return
        self.snapshot_all()
        del self.layers[self.current]
        self.current = max(0, self.current - 1)
        self.rebuild()

    def move_layer(self, step: int):
        j = self.current + step
        if 0 <= j < len(self.layers):
            self.snapshot_all()
            self.layers[self.current], self.layers[j] = self.layers[j], self.layers[self.current]
            self.current = j
            self.rebuild()

    def select(self, i: int):
        if 0 <= i < len(self.layers):
            self.current = i
            self.changed.emit()

    def set_visible(self, i: int, on: bool):
        self.layers[i].visible = on
        self.items[i].update()

    def set_opacity(self, value: float):
        self.layers[self.current].opacity = value
        self.items[self.current].update()

    # ---- 元に戻す ----
    # 線や塗りは触ったレイヤー 1 枚だけを覚える。並びを変えたときだけ全部を覚える
    def snapshot(self):
        self._push(("one", self.current, self.layers[self.current].image.copy()))

    def snapshot_all(self):
        self._push(("all", [layer.copy() for layer in self.layers], self.current))

    def _push(self, entry):
        self.undo_stack.append(entry)
        self.redo_stack.clear()
        while len(self.undo_stack) > 1 and sum(self._bytes(e) for e in self.undo_stack) > UNDO_BYTES:
            self.undo_stack.pop(0)

    @staticmethod
    def _bytes(entry) -> int:
        if entry[0] == "one":
            return entry[2].sizeInBytes()
        return sum(layer.image.sizeInBytes() for layer in entry[1])

    def _apply(self, entry, other: list):
        if entry[0] == "one":
            _, i, img = entry
            other.append(("one", i, self.layers[i].image.copy()))
            self.layers[i].image = img
            self.current = i
            self.items[i].layer = self.layers[i]
            self.items[i].update()
            self.changed.emit()
        else:
            _, layers, cur = entry
            other.append(("all", [layer.copy() for layer in self.layers], self.current))
            self.layers, self.current = layers, cur
            self.rebuild()

    def undo(self):
        if self.undo_stack:
            self._apply(self.undo_stack.pop(), self.redo_stack)

    def redo(self):
        if self.redo_stack:
            self._apply(self.redo_stack.pop(), self.undo_stack)

    # ---- 表示 ----
    def fit(self):
        if self.layers:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            self.zoomed.emit(self.zoom())

    def actual(self):
        self.resetTransform()
        self.angle = 0.0
        self.zoomed.emit(1.0)

    def zoom(self) -> float:
        t = self.transform()
        return (t.m11() ** 2 + t.m12() ** 2) ** 0.5

    def rotate_view(self, deg: float):
        self.angle = (self.angle + deg) % 360
        self.rotate(deg)

    def reset_rotation(self):
        self.rotate(-self.angle)
        self.angle = 0.0

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.zoomed.emit(self.zoom())

    # ---- 道具 ----
    def set_tool(self, tool: str):
        if tool == "pen" and getattr(self, "brush", None) is not None and self.brush.name == "消しゴム":
            self.brush = self.brushes["ペン"]   # ペンに持ち替えたのに消しゴムのブラシのままにしない
        self.tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == "hand" else QGraphicsView.NoDrag)
        cursors = {"hand": Qt.OpenHandCursor, "move": Qt.SizeAllCursor, "zoom": Qt.PointingHandCursor}
        self.viewport().setCursor(cursors.get(tool, Qt.CrossCursor))
        self.cursor_ring.setVisible(tool in BRUSH_TOOLS)

    def hold(self, tool: str):
        """キーを押している間だけ道具を持ち替える（Space で手のひら、Alt でスポイト）"""
        if self.held is None and self.last is None:
            self.held = self.tool
            self.set_tool(tool)

    def release(self):
        if self.held is not None:
            self.set_tool(self.held)
            self.held = None

    def resize_brush(self, factor: float):
        self.size = max(1, min(500, max(self.size + 1, round(self.size * factor)) if factor > 1 else int(self.size * factor) or 1))
        self.brush_changed.emit(self.size)

    def _ring(self, pos: QPointF):
        r = (self.size * (2 if self.tool in ("eraser", "blur") and self.brush.name != "消しゴム" else 1)) / 2
        self.cursor_ring.setRect(pos.x() - r, pos.y() - r, r * 2, r * 2)

    def set_brush(self, name: str):
        self.brush = self.brushes[name]
        self.set_tool("eraser" if name == "消しゴム" else "pen")

    def begin_stroke(self):
        """線の描き始め。消しゴムはレイヤーから直接消し、ほかは線用の下書きに描く"""
        self.carry = 0.0
        if self.tool not in ("eraser", "blur"):
            w, h = self.size_px()
            self.buffer = blank(w, h)
            it = self.items[self.current]
            it.buffer, it.buffer_opacity = self.buffer, self.brush_opacity

    def end_stroke(self):
        """手を離したら、下書きの線を濃さを掛けてレイヤーへ重ねる"""
        if self.buffer is not None:
            p = QPainter(self.layers[self.current].image)
            if self.selection is not None:
                p.setClipRect(self.selection)
            p.setOpacity(self.brush_opacity)
            p.drawImage(0, 0, self.buffer)
            p.end()
            it = self.items[self.current]
            it.buffer = None
            it.update()
            self.buffer = None
        elif self.selection is not None and self.undo_stack and self.undo_stack[-1][0] == "one":
            self._keep_outside(self.undo_stack[-1][2])

    def _keep_outside(self, before: QImage):
        """じかにレイヤーを変えた道具（消しゴム・ぼかし）の、選択範囲の外を元に戻す"""
        img = self.layers[self.current].image
        outside = QPainterPath()
        outside.addRect(QRectF(img.rect()))
        inside = QPainterPath()
        inside.addRect(QRectF(self.selection))
        p = QPainter(img)
        p.setClipPath(outside.subtracted(inside))
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, before)
        p.end()
        self.items[self.current].update()

    def stroke(self, a: QPointF, b: QPointF, pressure: float = 1.0):
        """a から b まで今のブラシで描く。線の途中でなければ、その 1 区切りだけで線を描き終える"""
        if self.tool == "blur":
            self.blur(a, b)
            return
        alone = self.buffer is None and self.tool != "eraser"
        if alone:
            self.begin_stroke()
        erase = self.tool == "eraser"
        target = self.layers[self.current].image if erase else self.buffer
        brush = self.brushes["消しゴム"] if erase and self.brush.name != "消しゴム" else self.brush
        size = self.size * (2 if erase and brush is not self.brush else 1)
        color = QColor(0, 0, 0) if erase else self.color
        dirty, self.carry = stamp(target, brush, self.dabs, a, b, size, color, pressure, self.carry, erase=erase)
        self.items[self.current].update(dirty)   # 線を引いた四角だけ描き直す
        if alone:
            self.end_stroke()

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
        if self.selection is not None:
            keep = np.zeros_like(mask)
            r = self.selection
            keep[r.top():r.bottom() + 1, r.left():r.right() + 1] = True
            mask &= keep
        self.snapshot()
        c = QColor(self.color)
        c.setAlphaF(self.brush_opacity)
        paint = np.zeros((h, w, 4), np.uint8)
        paint[mask] = (c.red(), c.green(), c.blue(), c.alpha())
        overlay = QImage(paint.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        p = QPainter(self.layers[self.current].image)
        p.drawImage(0, 0, overlay)
        p.end()
        self.items[self.current].update()

    def blur(self, a: QPointF, b: QPointF):
        """なぞった所をぼかす。筆の大きさの円の中を、縮めて戻した絵で置き換える"""
        img = self.layers[self.current].image
        r = max(2, self.size // 2)
        n = max(1, int(((b.x() - a.x()) ** 2 + (b.y() - a.y()) ** 2) ** 0.5 / max(1, r / 2)))
        dirty = QRect()
        p = QPainter(img)
        if self.selection is not None:
            p.setClipRect(self.selection)
        for k in range(n + 1):
            t = k / n
            x, y = int(a.x() + (b.x() - a.x()) * t), int(a.y() + (b.y() - a.y()) * t)
            box = QRect(x - r, y - r, r * 2, r * 2).intersected(img.rect())
            if box.isEmpty():
                continue
            part = img.copy(box)
            small = part.scaled(max(1, box.width() // 4), max(1, box.height() // 4), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            soft = small.scaled(box.width(), box.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            path = QPainterPath()
            path.addEllipse(QRectF(box))
            p.save()
            p.setClipPath(path, Qt.IntersectClip)
            p.setOpacity(0.5 * self.brush_opacity)
            p.drawImage(box.topLeft(), soft)
            p.restore()
            dirty = dirty.united(box)
        p.end()
        self.items[self.current].update(QRectF(dirty))

    # ---- 押して離すまでで決まる道具 ----
    def set_selection(self, rect: QRect | None):
        if rect is not None:
            w, h = self.size_px()
            rect = rect.normalized().intersected(QRect(0, 0, w, h))
            if rect.width() < 2 or rect.height() < 2:
                rect = None
        self.selection = rect
        self.sel_item.setVisible(rect is not None)
        if rect is not None:
            self.sel_item.setRect(QRectF(rect))

    def select_all(self):
        w, h = self.size_px()
        self.set_selection(QRect(0, 0, w, h))

    def clear_selection_area(self):
        """選択範囲の中を消す（Delete）。範囲が無ければ何もしない"""
        if self.selection is None:
            return
        self.snapshot()
        p = QPainter(self.layers[self.current].image)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.selection, Qt.transparent)
        p.end()
        self.items[self.current].update()

    def swap_colors(self):
        self.color, self.bg_color = self.bg_color, self.color
        self.color_picked.emit(self.color)

    def reset_colors(self):
        self.color, self.bg_color = QColor("#000000"), QColor("#ffffff")
        self.color_picked.emit(self.color)

    def drag(self, a: QPointF, b: QPointF):
        """押した所 a から今の所 b までの形を、描き途中として見せる（手を離すと決まる）"""
        it = self.items[self.current]
        if self.tool == "move":
            it.setPos(b - a)
            return
        if self.tool == "select":
            self.sel_item.setVisible(True)
            self.sel_item.setRect(QRectF(a, b).normalized())
            return
        self.buffer.fill(Qt.transparent)
        p = QPainter(self.buffer)
        p.setRenderHint(QPainter.Antialiasing)
        if self.tool == "gradient":
            g = QLinearGradient(a, b)
            g.setColorAt(0, self.color)
            g.setColorAt(1, self.bg_color)
            p.fillRect(self.buffer.rect(), QBrush(g))
        else:
            p.setPen(QPen(self.color, self.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(self.color if self.fill_shapes and self.tool != "line" else Qt.NoBrush)
            if self.tool == "line":
                p.drawLine(a, b)
            elif self.tool == "rect":
                p.drawRect(QRectF(a, b).normalized())
            else:
                p.drawEllipse(QRectF(a, b).normalized())
        p.end()
        it.update()

    def end_drag(self, a: QPointF, b: QPointF):
        it = self.items[self.current]
        if self.tool == "move":
            it.setPos(0, 0)
            d = (b - a).toPoint()
            if d.isNull():
                return
            img = self.layers[self.current].image
            moved = blank(img.width(), img.height())
            p = QPainter(moved)
            p.drawImage(d, img)
            p.end()
            self.layers[self.current].image = moved
            it.update()
            self.changed.emit()
            return
        if self.tool == "select":
            self.set_selection(QRectF(a, b).toAlignedRect())
            return
        self.end_stroke()

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
        if self.tool == "zoom":
            f = 1 / 1.25 if self.zoom_out else 1.25
            self.scale(f, f)
            self.zoomed.emit(self.zoom())
            return True
        if self.tool in DRAG_TOOLS:
            if self.tool not in ("move", "select"):
                self.used_color.emit()
            if self.tool != "select":
                self.snapshot()
            if self.tool not in ("move", "select"):
                w, h = self.size_px()
                self.buffer = blank(w, h)
                it = self.items[self.current]
                it.buffer, it.buffer_opacity = self.buffer, self.brush_opacity
            self.drag_start = pos
            return True
        if self.tool in BRUSH_TOOLS:
            if self.tool == "pen":
                self.used_color.emit()
            self.snapshot()
            self.begin_stroke()
            self.last = pos
            self.stroke(pos, pos, pressure)
            return True
        return False

    zoom_out = False

    def mousePressEvent(self, e):
        self.zoom_out = bool(e.modifiers() & Qt.ShiftModifier) or e.button() == Qt.RightButton and self.tool == "zoom"
        if self.tool == "zoom" and e.button() == Qt.RightButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        if e.button() == Qt.LeftButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self.setFocus()   # 絵の上に来たらキー（Space、Alt、[ ]）を受ける
        super().enterEvent(e)

    def mouseMoveEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        self._ring(pos)
        if self.drag_start is not None:
            self.drag(self.drag_start, pos)
            return
        if self.last is not None:
            self.stroke(self.last, pos, self.pressure)
            self.last = pos
            return
        if self.tool == "eyedropper" and e.buttons() & Qt.LeftButton:
            self.pick(pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.drag_start is not None:
            self.end_drag(self.drag_start, self.mapToScene(e.position().toPoint()))
            self.drag_start = None
            return
        if self.last is not None:
            self.end_stroke()
            self.last = None
            self.pressure = 1.0
            return
        super().mouseReleaseEvent(e)

    def tabletEvent(self, e):
        # ペンタブレットの筆圧で太さと濃さを変える
        pos = self.mapToScene(e.position().toPoint())
        self.pressure = max(0.05, e.pressure())
        self._ring(pos)
        t = e.type()
        if t == e.Type.TabletPress:
            self._press(pos, self.pressure)
        elif t == e.Type.TabletMove and self.drag_start is not None:
            self.drag(self.drag_start, pos)
        elif t == e.Type.TabletRelease and self.drag_start is not None:
            self.end_drag(self.drag_start, pos)
            self.drag_start = None
        elif t == e.Type.TabletMove and self.last is not None:
            self.stroke(self.last, pos, self.pressure)
            self.last = pos
        elif t == e.Type.TabletRelease:
            self.end_stroke()
            self.last = None
        e.accept()

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() == Qt.Key_Space:
            self.hold("hand")
        elif e.key() == Qt.Key_Alt:
            self.hold("eyedropper")
        elif e.key() == Qt.Key_BracketRight:
            self.resize_brush(1.25)
        elif e.key() == Qt.Key_BracketLeft:
            self.resize_brush(0.8)
        elif e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.clear_selection_area()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() in (Qt.Key_Space, Qt.Key_Alt):
            self.release()
        else:
            super().keyReleaseEvent(e)
