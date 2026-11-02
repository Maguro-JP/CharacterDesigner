"""作画の欄。レイヤー、筆圧つきのペン、消しゴム、ぼかし、スポイト、塗りつぶし、グラデーション、直線・四角・楕円、
移動、四角の選択範囲、元に戻す、拡大・回転を持つ。

描くたびに全部を描き直すと、大きな絵（4096 画素）で線が遅れる。レイヤーごとに絵の部品を持ち、
線を引いた所の四角だけを描き直す。元に戻すは、触ったレイヤーの分だけを覚える。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from chatdraw.brush import PRESETS, Brush, Dabs, stamp

UNDO_BYTES = 1_500_000_000   # 元に戻すに使うメモリの上限（約 1.5GB）
TOOL_NAMES = {"redpen": "赤ペン", "eraser": "消しゴム", "blur": "ぼかし", "fill": "塗りつぶし", "gradient": "グラデーション", "line": "直線",
              "rect": "四角", "ellipse": "楕円", "move": "移動", "select": "選択範囲を消す"}
CURSOR_STYLES = ("十字と筆の輪", "点と筆の輪", "筆の輪だけ", "矢印")   # 設定の「カーソル」で選ぶ形
BRUSH_TOOLS = ("pen", "eraser", "blur")                       # なぞって描く道具（筆の輪を出す）
DRAG_TOOLS = ("line", "rect", "ellipse", "gradient", "move", "select")   # 押した所から離した所までで決まる道具
REDPEN = "redpen"   # レイヤーの並び（stack）の中で、赤ペンの印の場所を示す印
FIRST_LAYER = "レイヤー 1"   # キャンバスの一番下に置く透明のレイヤー


@dataclass
class Layer:
    name: str
    image: QImage
    visible: bool = True
    opacity: float = 1.0
    locked: bool = False   # ロックしたレイヤーには描けない（AI の絵を線で汚さないため）

    def copy(self) -> "Layer":
        return Layer(self.name, self.image.copy(), self.visible, self.opacity, self.locked)


_PRELOADED: dict[str, tuple[int, QImage]] = {}


def preload(path) -> None:
    """絵を裏の糸で先に読んでおく（PNG を戻すのに 832×1216 で 25〜50 ミリ秒かかり、置くたびに画面が止まった）。
    次に同じ絵を _load で読むときに使う。ファイルが替わっていれば使わない"""
    import os
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return
    img = QImage(str(path))
    if not img.isNull():
        _PRELOADED[str(path)] = (stamp, img.convertToFormat(QImage.Format_ARGB32_Premultiplied))
        while len(_PRELOADED) > 4:   # 置かれなかった絵で覚えが膨らまないように、古い物から捨てる
            _PRELOADED.pop(next(iter(_PRELOADED)))


def _load(path: str) -> QImage:
    """絵を読む。読めない絵で置き換えると 0×0 のキャンバスになり、何も出なくなったので先に止める"""
    import os
    got = _PRELOADED.pop(str(path), None)
    if got is not None:
        try:
            if os.stat(path).st_mtime_ns == got[0]:
                return got[1]
        except OSError:
            pass
    img = QImage(str(path))
    if img.isNull():
        raise ValueError(f"絵を読めません: {path}")
    return img.convertToFormat(QImage.Format_ARGB32_Premultiplied)


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
    history_changed = Signal()  # 元に戻すの積み重ねが変わった（操作の履歴の欄を描き直す）
    refused = Signal(str)       # 描けなかった理由（隠した・ロックしたレイヤー）。黙って描けないと壊れて見えた
    moved = Signal(int, int)    # カーソルのキャンバス上の位置（下の帯の座標に出す）
    used_color = Signal()       # 描く色で描き始めた（最近使った色に足す）
    marked = Signal()           # 赤ペンで印を付けた（AI の欄を「直す」にする）
    note_wanted = Signal(int)   # 赤ペンの印に、絵の上で指示を書く（印の番号、1 から）
    menu_wanted = Signal(QPoint)  # 右クリック（動かさずに離した）。画面の位置で右クリックのメニューを出す
    stroke_done = Signal()        # 線・塗り・レイヤーが 1 回変わった（タイムラプスの写しを撮る）

    def drawBackground(self, painter, rect):
        """絵の周りはテーマの模様。画面に貼り付けて描く（拡大や移動で模様が流れない）"""
        if self.backdrop is None:
            super().drawBackground(painter, rect)
        else:
            painter.save()
            painter.resetTransform()
            self.backdrop(painter, self.viewport().rect())
            painter.restore()
        self._draw_paper(painter, rect)

    def _draw_paper(self, painter, rect):
        """紙の所に薄い市松を敷く。一番下のレイヤー 1 は透明なので、敷かないと暗い周りが透けて黒い線が見えなかった。
        市松は画面だけで、保存する絵にも AI に渡す絵にも入らない"""
        page = self.sceneRect().intersected(QRectF(rect))
        if page.isEmpty():
            return
        cell = 16 / max(0.05, self.zoom())   # 拡大しても升目は画面の上で同じ大きさ
        painter.save()
        painter.fillRect(page, QColor("#ffffff"))
        light = QColor("#ececec")
        y0 = int(page.top() // cell)
        x0 = int(page.left() // cell)
        y = y0
        while y * cell < page.bottom():
            x = x0
            while x * cell < page.right():
                if (x + y) % 2:
                    painter.fillRect(QRectF(x * cell, y * cell, cell, cell).intersected(page), light)
                x += 1
            y += 1
        painter.restore()

    def update_margins(self):
        """紙の外だけを描き直す。動く模様のために、毎回紙の中（レイヤー）まで描き直さない"""
        from PySide6.QtGui import QRegion
        page = self.mapFromScene(self.sceneRect()).boundingRect()
        self.viewport().update(QRegion(self.viewport().rect()).subtracted(QRegion(page)))

    # 全体表示のままか。初めは全体表示にし、窓の大きさが変わっても絵の全体が収まるように合わせ直す。
    # 利用者が自分で拡大・縮小したら外し、窓の大きさが変わっても勝手に全体へ戻さない
    auto_fit = True

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
        self.backdrop = None          # 絵の周りの模様を描く関数 (painter, 画面の四角)。None なら無地
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
        self.undo_names: list[str] = []
        self.redo_names: list[str] = []
        self.redo_stack: list[tuple] = []
        self.last: QPointF | None = None
        self.pressure = 1.0
        self.angle = 0.0
        self.held: str | None = None   # Space や Alt を押している間だけ持ち替える前の道具
        # 筆の輪。白だけだと白い紙の上で見えなかったので、黒い輪の内側に白い輪を重ねる
        self.cursor_ring = QGraphicsEllipseItem()
        self.cursor_ring.setPen(QPen(QColor(0, 0, 0, 200), 0))
        self.cursor_ring.setZValue(1e9)
        self.scene().addItem(self.cursor_ring)
        self.cursor_ring_in = QGraphicsEllipseItem(self.cursor_ring)
        self.cursor_ring_in.setPen(QPen(QColor(255, 255, 255, 220), 0))
        self.cursor_style = CURSOR_STYLES[0]
        self.sel_item = QGraphicsRectItem()
        pen = QPen(QColor("#ff7a1a"), 0, Qt.DashLine)
        self.sel_item.setPen(pen)
        self.sel_item.setBrush(QColor(255, 122, 26, 18))
        self.sel_item.setZValue(1e9 - 1)
        self.sel_item.setVisible(False)
        self.scene().addItem(self.sel_item)
        from chatdraw.redpen import RedPen
        self.redpen = RedPen()   # 赤ペン先生の印。保存する絵にも AI に渡す絵にも入れない
        self.scene().addItem(self.redpen)
        # 赤ペンはレイヤーの並びの 1 枚として扱う（選ぶ・隠す・消す・並べ替える・結合する）。
        # 印の線は絵の画素ではないので self.layers には入れず、並びの中の場所（下にある絵のレイヤーの数）だけを持つ
        self.redpen_pos = 0
        self.redpen_current = False   # レイヤーの欄で赤ペンを選んでいる
        self._redpen_shown = False    # 赤ペンが並びに入っている（印が 1 つ以上ある）
        self.redpen.on_layers = self._redpen_layers
        self.set_tool("pen")
        # 右ボタンでつかんで動かす。押して動かさずに離したら右クリックのメニュー
        self.pan_from: QPoint | None = None
        self.panned = False
        # 止まって少したったらカーソルを隠す（絵を見るときに邪魔にならない）。動かすとすぐ出る
        from PySide6.QtCore import QTimer
        self.hide_cursor_after = 1500
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.timeout.connect(self._hide_cursor)

    def _hide_cursor(self):
        if self.last is None and self.drag_start is None and self.pan_from is None and self.underMouse():
            self.viewport().setCursor(Qt.BlankCursor)
            self.cursor_ring.setVisible(False)

    def _wake_cursor(self):
        if self.viewport().cursor().shape() == Qt.BlankCursor and not (self.tool in BRUSH_TOOLS and self.cursor_style == "筆の輪だけ"):
            self._apply_cursor()
        elif self.tool in BRUSH_TOOLS and not self.cursor_ring.isVisible():
            self.cursor_ring.setVisible(True)
        if self.hide_cursor_after > 0:
            self.idle.start(self.hide_cursor_after)

    # ---- 書類 ----
    def size_px(self) -> tuple[int, int]:
        return (self.layers[0].image.width(), self.layers[0].image.height()) if self.layers else (0, 0)

    # レイヤーの重ね方: 一番下に透明の「レイヤー 1」、その上に AI の絵（開いた絵）、その上に利用者が足すレイヤー・
    # 加工の結果・赤ペンを足した順に重ねる。前は白い「背景」や AI の絵が一番下で、空のレイヤーが上に来ていた
    def new_canvas(self, w: int = 1200, h: int = 1600):
        self._reset([Layer(FIRST_LAYER, blank(w, h))], 0)

    def _base_with(self, name: str, img: QImage) -> list[Layer]:
        """透明のレイヤー 1 を一番下に、その上に絵を置いた並び"""
        return [Layer(FIRST_LAYER, blank(img.width(), img.height())), Layer(name, img)]

    def show_image(self, path: str):
        """絵を開く。透明のレイヤー 1 の上に絵を置いて選ぶ"""
        img = QImage(path).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._reset(self._base_with("絵", img), 1)

    def replace_with_image(self, path: str, name: str = "AI の絵"):
        """AI が新しく描いた絵に、キャンバスを置き換える。透明のレイヤー 1 の上に絵を置いて選ぶ。
        前の絵の上に重ねると、大きさの違う絵が重なって見分けられなかった。前の状態は「元に戻す」で戻せる"""
        img = _load(path)
        if not self.layers:
            self._reset(self._base_with(name, img), 1)
            return
        self.snapshot_all()
        self.layers = self._base_with(name, img)
        self.current = 1
        self.redpen_pos = len(self.layers)   # 残っている赤ペンの印は、新しい絵の上に置く
        self.redpen_current = False
        self.set_selection(None)
        self.rebuild()
        self.fit()

    def place_result(self, path: str, name: str, replace: bool = False):
        """AI が描いた・直した・加工した結果を、一番上の新しいレイヤーに置いて選ぶ。
        前は結果を一番下に入れて空のレイヤーを上に選んでいたため、結果が出たことに気づけなかった。
        replace は新しく描いた絵・大きさの変わる結果（拡大・広げる）で、キャンバスを結果 1 枚に置き換える
        （大きさの違う前の絵とは重ねられない）。どちらも前の状態は「元に戻す」で戻せる"""
        img = _load(path)
        if not self.layers:
            self._reset(self._base_with(name, img), 1)
            return
        resized = (img.width(), img.height()) != self.size_px()
        if not replace and resized:
            return self.add_image_layer(path, name)   # 大きさだけ違う結果は、キャンバスに合わせて一番上に重ねる
        self.snapshot_all()
        if replace:
            self.layers = self._base_with(name, img)
            self.redpen_pos = len(self.layers)
        else:
            self.layers.append(Layer(name, img))   # 赤ペンより上に、足した順に重ねる
        self.current = len(self.layers) - 1
        self.redpen_current = False
        if replace:
            self.set_selection(None)
        self.rebuild()
        if replace and resized:
            self.fit()

    def add_image_layer(self, path: str, name: str = "絵"):
        img = _load(path)
        if not self.layers:
            self._reset(self._base_with(name, img), 1)
            return
        w, h = self.size_px()
        self.snapshot_all()
        layer = blank(w, h)
        p = QPainter(layer)
        p.drawImage(0, 0, img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.end()
        # 一番上に重ねる。選んでいたレイヤーの真上に差し込むと、利用者の線の下に入ったり、次の線が AI の絵に描かれたりした
        self.layers.append(Layer(name, layer))
        self.current = len(self.layers) - 1
        self.redpen_current = False
        self.rebuild()

    def _reset(self, layers: list[Layer], current: int):
        self.layers, self.current = layers, current
        self.redpen_pos, self.redpen_current = len(layers), False
        self.set_selection(None)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.undo_names.clear()
        self.redo_names.clear()
        self.history_changed.emit()
        self.rebuild()
        w, h = self.size_px()
        self.scene().setSceneRect(QRectF(0, 0, w, h))
        self.redpen.set_size(w, h)
        self.fit()

    def merge_visible(self, name: str = "結合した絵"):
        """見えているレイヤーを 1 枚に結合する（隠したレイヤーは捨てる）。元に戻すで戻せる"""
        if not self.layers:
            return
        img = self.flatten()
        self.snapshot_all()
        self.layers = [Layer(name, img)]
        self.current = 0
        self.redpen_pos, self.redpen_current = 1, False   # 赤ペンは AI への指示なので絵に焼き込まず、上に残す
        self.rebuild()
        self.changed.emit()

    def merge_down(self):
        """選んでいるレイヤーを下のレイヤーに結合する。元に戻すで戻せる。
        赤ペンを選んでいれば、見えている印を下のレイヤーに描き込む。すぐ下が赤ペンなら結合しない（印は絵の画素ではない）"""
        if self.redpen_current and self.redpen.marks:
            return self.merge_redpen_down()
        i = self.current
        if i <= 0 or i >= len(self.layers):
            return
        if self.redpen.marks and self.redpen_pos == i:
            self.refused.emit("すぐ下が「赤ペン」なので結合できません。赤ペンを上か下へ動かしてから結合してください")
            return
        upper, lower = self.layers[i], self.layers[i - 1]
        self.snapshot_all()
        img = QImage(lower.image)
        p = QPainter(img)
        if upper.visible:
            p.setOpacity(upper.opacity)
            p.drawImage(0, 0, upper.image)
        p.end()
        lower.image = img
        del self.layers[i]
        if i < self.redpen_pos:   # 赤ペンより下のレイヤーが 1 枚減った
            self.redpen_pos -= 1
        self.current = i - 1
        self.rebuild()
        self.changed.emit()

    def merge_redpen_down(self):
        """赤ペンの印を、すぐ下のレイヤーに赤い線として描き込み、赤ペンを並びから外す。元に戻すで戻せる"""
        pos = self.redpen_pos
        if not self.redpen.marks or pos <= 0 or pos > len(self.layers):
            return
        self.snapshot_all(marks=True)
        lower = self.layers[pos - 1]
        if self.redpen.isVisible():
            img = QImage(lower.image)
            p = QPainter(img)
            self.redpen.paint(p, None)
            p.end()
            lower.image = img
        self.current, self.redpen_current = pos - 1, False
        self.redpen.clear()
        self.rebuild()

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
        w, h = self.size_px()
        if self.scene().sceneRect() != QRectF(0, 0, w, h):   # 元に戻すで大きさの違う絵に戻ったとき
            self.scene().setSceneRect(QRectF(0, 0, w, h))
            self.redpen.set_size(w, h)
        self._place_redpen()
        self.changed.emit()

    # ---- 赤ペン（並びの 1 枚） ----
    def _place_redpen(self):
        """赤ペンを、並びの場所のレイヤーの間に重ねる（下のレイヤーの z は 0, 1, …）"""
        self.redpen_pos = max(0, min(self.redpen_pos, len(self.layers)))
        self.redpen.setZValue(self.redpen_pos - 0.5)

    def _redpen_layers(self):
        """印が増えた・消えたとき。初めの印で赤ペンを一番上に足し、印が無くなったら並びから外す"""
        if self.redpen.marks:
            if not self._redpen_shown:
                self._redpen_shown = True
                self.redpen_pos = len(self.layers)
        else:
            self._redpen_shown = False
            self.redpen_current = False
        self._place_redpen()
        self.changed.emit()

    def stack(self) -> list:
        """下から上へのレイヤーの並び。赤ペンに印があれば、その場所に REDPEN を入れる"""
        s: list = list(self.layers)
        if self.redpen.marks:
            s.insert(max(0, min(self.redpen_pos, len(s))), REDPEN)
        return s

    def _index_of(self, layer: Layer) -> int:
        return next(i for i, x in enumerate(self.layers) if x is layer)

    def current_pos(self) -> int:
        """選んでいるもの（レイヤーか赤ペン）の、並びの中の場所"""
        s = self.stack()
        if self.redpen_current and REDPEN in s:
            return s.index(REDPEN)
        if not self.layers:
            return 0
        cur = self.layers[self.current]
        return next(i for i, x in enumerate(s) if x is cur)

    def _set_stack(self, s: list, chosen):
        """並べ替えた並びを、絵のレイヤーと赤ペンの場所に戻す。chosen は選ぶもの（Layer か REDPEN）"""
        self.layers = [x for x in s if x is not REDPEN]
        if any(x is REDPEN for x in s):
            self.redpen_pos = next(i for i, x in enumerate(s) if x is REDPEN)
        if chosen is REDPEN:
            self.redpen_current = True
        else:
            self.redpen_current = False
            self.current = self._index_of(chosen)

    def select_redpen(self):
        if self.redpen.marks:
            self.redpen_current = True
            self.changed.emit()

    def set_redpen_visible(self, on: bool):
        self.redpen.setVisible(on)
        self.changed.emit()

    def clear_redpen(self):
        """赤ペンの印を全部消し、並びから外す。元に戻すで戻せる"""
        if not self.redpen.marks:
            return
        self.snapshot_all(marks=True)
        self.redpen.clear()
        self.rebuild()

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
    def _new_name(self) -> str:
        """使っていない「レイヤー n」。数を len で決めると、消したあとに同じ名前が 2 つできた"""
        used = {layer.name for layer in self.layers}
        n = 1
        while f"レイヤー {n}" in used:
            n += 1
        return f"レイヤー {n}"

    def add_layer(self):
        if not self.layers:
            return
        w, h = self.size_px()
        self.snapshot_all()
        # 一番上に、足した順に重ねる。選んでいるレイヤーの真上に差し込むと、足したレイヤーが赤ペンや結果の下に隠れた
        self.layers.append(Layer(self._new_name(), blank(w, h)))
        self.current = len(self.layers) - 1
        self.redpen_current = False
        self.rebuild()

    def delete_layer(self):
        """選んでいるレイヤーを消す。赤ペンを選んでいれば印を全部消す。元に戻すで戻せる"""
        if self.redpen_current and self.redpen.marks:
            return self.clear_redpen()
        if len(self.layers) <= 1:
            return
        self.snapshot_all()
        s = self.stack()
        i = self.current_pos()
        del s[i]
        below = next((x for x in reversed(s[:i]) if x is not REDPEN), None)
        above = next((x for x in s[i:] if x is not REDPEN), None)
        self._set_stack(s, below or above)
        self.rebuild()

    def move_layer(self, step: int):
        """選んでいるもの（レイヤーか赤ペン）を並びの中で step だけ動かす。+1 が上"""
        i = self.current_pos()
        self.move_entry_to(i, i + step)

    def move_entry_to(self, i: int, j: int):
        """並び（stack）の i 番目を j 番目へ動かす（ドラッグでの並べ替え）。元に戻すで戻せる"""
        s = self.stack()
        n = len(s)
        if not (0 <= i < n and 0 <= j < n) or i == j:
            return
        self.snapshot_all()
        item = s.pop(i)
        s.insert(j, item)
        self._set_stack(s, item)
        self.rebuild()

    def move_layer_to(self, i: int, j: int):
        """絵のレイヤー i を、レイヤー j のあった場所へ動かす。元に戻すで戻せる"""
        n = len(self.layers)
        if not (0 <= i < n and 0 <= j < n) or i == j:
            return
        s = self.stack()
        src = next(k for k, x in enumerate(s) if x is self.layers[i])
        dst = next(k for k, x in enumerate(s) if x is self.layers[j])
        self.move_entry_to(src, dst)

    def select(self, i: int):
        if 0 <= i < len(self.layers):
            self.current = i
            self.redpen_current = False
            self.changed.emit()

    def set_visible(self, i: int, on: bool):
        if 0 <= i < len(self.layers):
            self.layers[i].visible = on
            self.items[i].update()

    def set_locked(self, i: int, on: bool):
        if 0 <= i < len(self.layers):
            self.layers[i].locked = on

    def rename_layer(self, i: int, name: str):
        """名前を変える（元に戻すで戻せる）。空の名前にはしない"""
        name = name.strip()
        if 0 <= i < len(self.layers) and name and name != self.layers[i].name:
            self.snapshot_all()
            self.layers[i].name = name
            self.changed.emit()

    def set_opacity(self, value: float):
        self.layers[self.current].opacity = value
        self.items[self.current].update()

    # ---- 元に戻す ----
    # 線や塗りは触ったレイヤー 1 枚だけを覚える。並びを変えたときだけ全部を覚える
    def snapshot(self):
        self._push(("one", self.current, self.layers[self.current].image.copy()))

    def _redpen_state(self, marks: bool) -> dict:
        state = {"pos": self.redpen_pos, "sel": self.redpen_current}
        if marks:   # 赤ペンを消す・結合する操作だけ、印そのものも覚える（印を足す操作は赤ペンの元に戻すが持つ）
            state.update(marks=[list(m) for m in self.redpen.marks], texts=list(self.redpen.texts),
                         visible=self.redpen.isVisible())
        return state

    def snapshot_all(self, marks: bool = False):
        self._push(("all", [layer.copy() for layer in self.layers], self.current, self._redpen_state(marks)))

    def _push(self, entry):
        self.undo_stack.append(entry)
        self.undo_names.append(self.action_name(entry))
        self.redo_stack.clear()
        self.redo_names.clear()
        while len(self.undo_stack) > 1 and sum(self._bytes(e) for e in self.undo_stack) > UNDO_BYTES:
            self.undo_stack.pop(0)
            self.undo_names.pop(0)
        self.history_changed.emit()

    def action_name(self, entry) -> str:
        """操作の履歴に出す名前。並びを変えた操作はレイヤー、ほかは今の道具の名前"""
        if entry[0] == "all":
            return "レイヤー"
        return TOOL_NAMES.get(self.tool, "描く") if self.tool != "pen" else self.brush.name

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
            _, layers, cur, *rest = entry
            state = rest[0] if rest else {}
            other.append(("all", [layer.copy() for layer in self.layers], self.current,
                          self._redpen_state("marks" in state)))
            self.layers, self.current = layers, cur
            if "marks" in state:
                pen = self.redpen
                pen.marks, pen.texts = [list(m) for m in state["marks"]], list(state["texts"])
                pen.drawing = None
                pen.setVisible(state["visible"])
                self._redpen_shown = bool(pen.marks)
                pen.update()
            self.redpen_pos = state.get("pos", self.redpen_pos)
            self.redpen_current = bool(state.get("sel")) and bool(self.redpen.marks)
            self.rebuild()
            if "marks" in state:
                self.redpen._changed()   # AI の欄（直す）と赤ペンの並びを、戻した印に合わせる

    def undo(self):
        # 赤ペンで描いている間の元に戻すは、最後の印を外す（絵の元に戻すと混ぜない）
        if self.tool == "redpen" and self.redpen.undo():
            self.history_changed.emit()
            return
        if self.undo_stack:
            self._apply(self.undo_stack.pop(), self.redo_stack)
            self.redo_names.append(self.undo_names.pop())
            self.history_changed.emit()

    def redo(self):
        if self.tool == "redpen" and self.redpen.redo():
            self.history_changed.emit()
            return
        if self.redo_stack:
            self._apply(self.redo_stack.pop(), self.undo_stack)
            self.undo_names.append(self.redo_names.pop())
            self.history_changed.emit()

    def go_to(self, done: int):
        """操作の履歴で選んだ所まで戻す・進める（done は済んだ操作の数）"""
        while len(self.undo_stack) > done and self.undo_stack:
            self.undo()
        while len(self.undo_stack) < done and self.redo_stack:
            self.redo()

    # ---- 表示 ----
    def fit(self):
        """絵の全体が窓に収まる大きさで出す。以後、窓の大きさが変わっても全体表示を保つ"""
        self.auto_fit = True
        if self.layers:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            self.zoomed.emit(self.zoom())

    def resizeEvent(self, e):
        # 起動したときは窓が出る前に絵を開くので、そのときの大きさで合わせると小さすぎた。窓が決まってから合わせ直す
        super().resizeEvent(e)
        if self.auto_fit and self.layers:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            self.zoomed.emit(self.zoom())

    def actual(self):
        self.auto_fit = False
        self.resetTransform()
        self.angle = 0.0
        self.zoomed.emit(1.0)

    def zoom(self) -> float:
        t = self.transform()
        return (t.m11() ** 2 + t.m12() ** 2) ** 0.5

    def set_zoom(self, z: float):
        """拡大率を z（1.0 で等倍）にする。回転はそのまま"""
        cur = self.zoom()
        self.auto_fit = False
        if cur > 0:
            f = z / cur
            self.scale(f, f)
            self.zoomed.emit(self.zoom())

    def rotate_view(self, deg: float):
        self.angle = (self.angle + deg) % 360
        self.rotate(deg)

    def reset_rotation(self):
        self.rotate(-self.angle)
        self.angle = 0.0

    def wheelEvent(self, e):
        self.auto_fit = False
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.zoomed.emit(self.zoom())

    # ---- 道具 ----
    def set_tool(self, tool: str):
        if tool == "pen" and getattr(self, "brush", None) is not None and self.brush.name == "消しゴム":
            self.brush = self.brushes["ペン"]   # ペンに持ち替えたのに消しゴムのブラシのままにしない
        self.tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == "hand" else QGraphicsView.NoDrag)
        self._apply_cursor()

    def set_cursor_style(self, style: str):
        """絵の上のカーソルの形を変える（設定の「カーソル」）"""
        self.cursor_style = style if style in CURSOR_STYLES else CURSOR_STYLES[0]
        self._apply_cursor()

    def _apply_cursor(self):
        tool = self.tool
        cursors = {"hand": Qt.OpenHandCursor, "move": Qt.SizeAllCursor, "zoom": Qt.PointingHandCursor}
        brush = tool in BRUSH_TOOLS
        if tool in cursors:
            shape = cursors[tool]
        elif self.cursor_style == "点と筆の輪":
            shape = _dot_cursor()
        elif self.cursor_style == "矢印":
            shape = Qt.ArrowCursor
        elif brush and self.cursor_style == "筆の輪だけ":
            shape = Qt.BlankCursor
        else:
            shape = Qt.CrossCursor
        self.viewport().setCursor(shape)
        self.cursor_ring.setVisible(brush)

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
        k = 1.0 / max(self.zoom(), 1e-6)   # 内側の輪は画面で 1 画素だけ内に置く
        self.cursor_ring_in.setRect(pos.x() - r + k, pos.y() - r + k, max(0.0, r * 2 - 2 * k), max(0.0, r * 2 - 2 * k))

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
            a = c.alphaF()   # 透明の所は紙の白に重ねた色を取る（一番下のレイヤー 1 は透明なので、そのままだと黒になった）
            c = QColor(round(c.red() * a + 255 * (1 - a)), round(c.green() * a + 255 * (1 - a)),
                       round(c.blue() * a + 255 * (1 - a)))
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

    def selection_mask(self) -> QImage | None:
        """四角の選択範囲を、直す所の形（白が直す所）にする。選択が無ければ None"""
        if self.selection is None or self.selection.isEmpty():
            return None
        w, h = self.size_px()
        m = QImage(w, h, QImage.Format_Grayscale8)
        m.fill(0)
        q = QPainter(m)
        q.fillRect(self.selection, QColor("white"))
        q.end()
        return m

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
        if self.tool == "redpen" and self.layers:
            if not self.redpen.isVisible():   # 隠した赤ペンに描くと印が見えないので、出してから描く
                self.set_redpen_visible(True)
            if not self.redpen.marks:   # 初めの印は、描いている間から一番上に重ねる
                self._redpen_shown, self.redpen_pos = True, len(self.layers)
                self._place_redpen()
            self.redpen.begin(pos)
            self.marked.emit()
            return True
        if not self.layers:
            return False
        if self.redpen_current and self.redpen.marks and self.tool not in ("eyedropper", "zoom", "select"):
            self.refused.emit("「赤ペン」のレイヤーには線を描けません。赤ペン（T）で囲むか、ほかのレイヤーを選んでください")
            return True
        if self.tool not in ("eyedropper", "zoom", "select"):
            layer = self.layers[self.current]
            if not layer.visible or layer.locked:
                self.refused.emit(f"「{layer.name}」は{'隠して' if not layer.visible else 'ロックして'}いるので描けません。"
                                  "レイヤーの欄で出すか、ロックを外すか、ほかのレイヤーを選んでください")
                return True
        if self.tool == "eyedropper":
            self.pick(pos)
            return True
        if self.tool == "fill":
            self.fill(pos)
            return True
        if self.tool == "zoom":
            f = 1 / 1.25 if self.zoom_out else 1.25
            self.auto_fit = False
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
        if e.button() == Qt.RightButton and self.tool != "zoom":
            self.pan_from, self.panned = e.position().toPoint(), False
            return
        self.zoom_out = bool(e.modifiers() & Qt.ShiftModifier) or e.button() == Qt.RightButton and self.tool == "zoom"
        if self.tool == "zoom" and e.button() == Qt.RightButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        if e.button() == Qt.LeftButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self.setFocus()   # 絵の上に来たらキー（Space、Alt、[ ]）を受ける
        super().enterEvent(e)

    def mouseDoubleClickEvent(self, e):
        """赤ペンの番号の丸をダブルクリックすると、その印の指示を書き直す"""
        n = self.redpen.number_at(self.mapToScene(e.position().toPoint()), self.zoom())
        if n:
            self.redpen.drawing = None
            self.note_wanted.emit(n)
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        self._wake_cursor()
        if self.pan_from is not None:
            now = e.position().toPoint()
            d = now - self.pan_from
            if self.panned or abs(d.x()) + abs(d.y()) > 4:   # 少し動かしただけでは、右クリックのままにする
                if not self.panned:
                    self.viewport().setCursor(Qt.ClosedHandCursor)
                self.panned = True
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
                self.pan_from = now
            return
        pos = self.mapToScene(e.position().toPoint())
        self._ring(pos)
        self.moved.emit(int(pos.x()), int(pos.y()))
        if self.drag_start is not None:
            self.drag(self.drag_start, pos)
            return
        if self.redpen.drawing is not None:
            self.redpen.add(pos)
            return
        if self.last is not None:
            self.stroke(self.last, pos, self.pressure)
            self.last = pos
            return
        if self.tool == "eyedropper" and e.buttons() & Qt.LeftButton:
            self.pick(pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton and self.pan_from is not None:
            moved, self.pan_from = self.panned, None
            self._apply_cursor()
            if not moved:
                self.menu_wanted.emit(e.globalPosition().toPoint())
            return
        if self.redpen.drawing is not None:
            short = len(self.redpen.drawing) < 3
            self.redpen.end()
            if short:
                self.redpen.undo()   # 押しただけ（ダブルクリックの 1 回目など）は印にしない
            else:
                self.note_wanted.emit(len(self.redpen.marks))   # 囲んだらすぐ、その横に指示を書ける
            return
        if self.drag_start is not None:
            self.end_drag(self.drag_start, self.mapToScene(e.position().toPoint()))
            self.drag_start = None
            self.stroke_done.emit()
            return
        if self.last is not None:
            self.end_stroke()
            self.last = None
            self.pressure = 1.0
            self.stroke_done.emit()
            return
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and self.tool in ("fill", "move", "select", "line", "rect", "ellipse", "gradient"):
            self.stroke_done.emit()

    def tabletEvent(self, e):
        # ペンタブレットの筆圧で太さと濃さを変える
        pos = self.mapToScene(e.position().toPoint())
        self.pressure = max(0.05, e.pressure())
        self._ring(pos)
        t = e.type()
        if t == e.Type.TabletPress:
            self._press(pos, self.pressure)
        elif t == e.Type.TabletMove and self.redpen.drawing is not None:
            self.redpen.add(pos)
        elif t == e.Type.TabletRelease and self.redpen.drawing is not None:
            self.redpen.end()
            self.note_wanted.emit(len(self.redpen.marks))
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
            self.stroke_done.emit()
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


def _dot_cursor():
    """真ん中に小さな点だけのカーソル（白い縁の黒い点。どの色の上でも見える）"""
    from PySide6.QtGui import QCursor, QPainter, QPixmap
    pm = QPixmap(9, 9)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255), 1.5))
    p.setBrush(QColor(0, 0, 0))
    p.drawEllipse(2, 2, 5, 5)
    p.end()
    return QCursor(pm, 4, 4)
