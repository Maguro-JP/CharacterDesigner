"""作画の欄。レイヤー、筆圧つきのペン、消しゴム、ぼかし、スポイト、塗りつぶし、グラデーション、直線・四角・楕円、
移動、四角の選択範囲、元に戻す、拡大・回転を持つ。

描くたびに全部を描き直すと、大きな絵（4096 画素）で線が遅れる。レイヤーごとに絵の部品を持ち、
線を引いた所の四角だけを描き直す。元に戻すは、触ったレイヤーの分だけを覚える。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtGui import QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from chatdraw.brush import PRESETS, Brush, Dabs, stamp

UNDO_BYTES = 1_500_000_000   # 元に戻すに使うメモリの上限（約 1.5GB）
TOOL_NAMES = {"redpen": "赤ペン", "eraser": "消しゴム", "blur": "ぼかし", "fill": "塗りつぶし", "gradient": "グラデーション", "line": "直線",
              "rect": "四角", "ellipse": "楕円", "move": "移動", "select": "四角の選択", "lasso": "投げなわの選択", "polygon": "多角形の選択",
              "spray": "スプレー", "smudge": "指先", "text": "文字",
              "polyshape": "多角形", "regpoly": "正多角形"}
COLOR_MODES = ("単色", "虹色", "描く色と背景色を行き来")   # ペンの色の出方（色の欄で選ぶ）
CURSOR_STYLES = ("十字と筆の輪", "点と筆の輪", "筆の輪だけ", "矢印")   # 設定の「カーソル」で選ぶ形
BRUSH_TOOLS = ("pen", "eraser", "blur", "spray", "smudge")                     # なぞって描く道具（筆の輪を出す）
DRAG_TOOLS = ("line", "rect", "ellipse", "regpoly", "gradient", "move", "select", "lasso")   # 押した所から離した所までで決まる道具
SELECT_TOOLS = ("select", "lasso", "polygon")   # 範囲を選ぶ道具。レイヤーを変えないので、隠したレイヤーでも使える
# 対称の形。線対称は左右（縦の軸）・上下（横の軸）・上下左右、点対称は軸の中心の周りに半回転して写す
SYMMETRY = {"lr": "左右（縦の軸）", "ud": "上下（横の軸）", "both": "上下左右", "point": "点対称（中心の周り）"}
AXIS_GRIP = 7   # 軸をつかむ丸の半径（画面の画素）
STABILIZER_MAX = 100   # 手ぶれ補正の強さの上限
QUICKSHAPE_MS = 500    # 描いて止めてから形を整えるまでの時間（ミリ秒）


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
        # 大きさは作ったときに覚える。layer.image を差し替えて大きさが変わったまま場面から外すと、
        # 場面の索引が古い四角で項目を探せず、消したあとの描き直しで落ちた（レイヤーを消すとクラッシュ）
        self._rect = QRectF(0, 0, layer.image.width(), layer.image.height())

    def sync(self):
        """layer.image の大きさが変わったら、場面に知らせてから四角を直す"""
        r = QRectF(0, 0, self.layer.image.width(), self.layer.image.height())
        if r != self._rect:
            self.prepareGeometryChange()
            self._rect = r
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

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
    text_wanted = Signal(QPointF)  # 文字の道具で押した。窓が文字を聞いて place_text で置く
    moved = Signal(int, int)    # カーソルのキャンバス上の位置（下の帯の座標に出す）
    used_color = Signal()       # 描く色で描き始めた（最近使った色に足す）
    marked = Signal()           # 赤ペンで印を付けた（AI の欄を「直す」にする）
    note_wanted = Signal(int)   # 赤ペンの印に、絵の上で指示を書く（印の番号、1 から）
    menu_wanted = Signal(QPoint)  # 右クリック（動かさずに離した）。画面の位置で右クリックのメニューを出す
    stroke_done = Signal()        # 線・塗り・レイヤーが 1 回変わった（タイムラプスの写しを撮る）
    shaped = Signal(str)          # 描いて止めた線を形に整えた（整えた形の名前。下の帯に出す）
    view_changed = Signal()       # 表示の回転・左右反転・グリッドが変わった（つまみと印を合わせる）

    def drawBackground(self, painter, rect):
        """絵の周りはテーマの模様。画面に貼り付けて描く（拡大や移動で模様が流れない）"""
        if self.backdrop is None:
            return super().drawBackground(painter, rect)
        painter.save()
        painter.resetTransform()
        self.backdrop(painter, self.viewport().rect())
        painter.restore()
        self._draw_checker(painter)

    def _draw_checker(self, painter):
        """紙の下に市松模様を敷く。透明の所が模様で見え、透過した絵が透過できたと一目で分かる。
        前は紙の下が絵の周りと同じ暗い模様で、背景のレイヤーを隠しても透明かどうかが見分けにくかった"""
        from PySide6.QtGui import QBrush, QPixmap
        tile = getattr(self, "_checker_tile", None)
        if tile is None:
            tile = QPixmap(16, 16)
            tile.fill(QColor("#ffffff"))
            q = QPainter(tile)
            q.fillRect(0, 0, 8, 8, QColor("#d6d6d6"))
            q.fillRect(8, 8, 8, 8, QColor("#d6d6d6"))
            q.end()
            self._checker_tile = tile
        painter.fillRect(self.sceneRect(), QBrush(tile))

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
        self.selection: QRect | None = None   # 選択範囲の外の四角。あれば描く・消す・塗るはこの中だけに効く
        self.selection_shape: QPainterPath | None = None   # 投げなわ・多角形で選んだ形。None なら四角そのもの
        self.poly_points: list[QPointF] = []   # 投げなわ・多角形の選択で、置きかけの角
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
        self.stabilizer = 0           # 手ぶれ補正（0 で無し、大きいほど線が遅れてなめらかになる）
        self.steady: QPointF | None = None
        self.symmetry = ""            # 対称の形（SYMMETRY の鍵）。"" は切る。描いた線・図形を軸の反対側にも描く
        self.sym_center: QPointF | None = None   # 対称の軸の中心（絵の座標）。None は絵の真ん中
        self._axis_drag = False
        self._over_axis = False
        # 描く補助（chatdraw/assist.py）。Shift の角度の固定、正多角形の辺の数、定規、形の補正
        self.shift = False            # Shift を押しているか（直線は 15 度ごと、四角は正方形、楕円は正円）
        self.poly_sides = 6           # 正多角形の辺の数
        self.shape_points: list[QPointF] = []   # 多角形の道具で置きかけの角
        self.ruler = ""               # 定規の形（assist.RULERS の鍵）。"" は切る
        self.ruler_pts: list[QPointF] = []      # 定規の点（同心円・放射の中心、消失点、平行線の向きの 2 点）
        self.ruler_dir = None         # パース 2 点で、この線に決めた向き
        self._ruler_drag = -1
        self.stroke_start: QPointF | None = None
        self.quickshape = False       # 描いて止めると形を整える
        self.qs_points: list[tuple] = []
        self.qs_shape = None          # 整えた形（整える前の線は qs_raw）
        self.qs_raw: QImage | None = None
        self.color_mode = COLOR_MODES[0]
        self.stroke_len = 0.0         # 線の始めからの長さ（虹色の色相を進める）
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
        self.sel_path_item = QGraphicsPathItem()   # 投げなわ・多角形の形（四角の枠と同じ色）
        self.sel_path_item.setPen(pen)
        self.sel_path_item.setBrush(QColor(255, 122, 26, 18))
        self.sel_path_item.setZValue(1e9 - 1)
        self.sel_path_item.setVisible(False)
        self.scene().addItem(self.sel_path_item)
        self.mirror_item = QGraphicsPathItem()   # 対称の軸（左右は縦の線、上下は横の線、点対称は十字）
        self.mirror_item.setPen(QPen(QColor(61, 123, 255, 200), 0, Qt.DashLine))
        self.mirror_item.setZValue(1e9 - 2)
        self.mirror_item.setVisible(False)
        self.scene().addItem(self.mirror_item)
        # 軸をつかむ丸。拡大しても同じ大きさで見えるよう、表示の拡大を受けない
        self.axis_handle = QGraphicsEllipseItem(-AXIS_GRIP, -AXIS_GRIP, 2 * AXIS_GRIP, 2 * AXIS_GRIP)
        self.axis_handle.setPen(QPen(QColor("white"), 1.5))
        self.axis_handle.setBrush(QColor(61, 123, 255, 220))
        self.axis_handle.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.axis_handle.setZValue(1e9 - 2)
        self.axis_handle.setVisible(False)
        self.axis_handle.setToolTip("ドラッグで対称の軸を動かします")
        self.scene().addItem(self.axis_handle)
        self.ruler_handles: list[QGraphicsEllipseItem] = []
        for _i in range(2):   # 定規の点をつかむ丸（対称の軸の丸と見分けるよう緑にする）
            hd = QGraphicsEllipseItem(-AXIS_GRIP, -AXIS_GRIP, 2 * AXIS_GRIP, 2 * AXIS_GRIP)
            hd.setPen(QPen(QColor("white"), 1.5))
            hd.setBrush(QColor(34, 170, 90, 220))
            hd.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            hd.setZValue(1e9 - 2)
            hd.setVisible(False)
            hd.setToolTip("ドラッグで定規の中心・消失点を動かします")
            self.scene().addItem(hd)
            self.ruler_handles.append(hd)
        from chatdraw.redpen import RedPen
        self.redpen = RedPen()   # 赤ペン先生の印。レイヤーとは別に持ち、保存する絵にも AI に渡す絵にも入れない
        self.scene().addItem(self.redpen)
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
        self.qs_timer = QTimer(self)
        self.qs_timer.setSingleShot(True)
        self.qs_timer.timeout.connect(self.quick_shape)

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

    def new_canvas(self, w: int = 1200, h: int = 1600):
        self._reset([Layer("背景", blank(w, h, QColor("white"))), Layer("レイヤー 1", blank(w, h))], 1)

    def show_image(self, path: str):
        """絵を開く。絵を下に置き、その上に描くための空のレイヤーを足す"""
        img = QImage(path).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._reset([Layer("絵", img), Layer("レイヤー 1", blank(img.width(), img.height()))], 1)

    def replace_with_image(self, path: str, name: str = "AI の絵"):
        """AI が新しく描いた絵に、キャンバスを置き換える。一番下に透明の「レイヤー 1」、その上に AI の絵を置く。
        足したレイヤーは選んだ AI の絵の上に入る（下から 土台・AI の絵・足したレイヤー、赤ペンはいつも一番上）。
        前の絵の上に重ねると、大きさの違う絵が重なって見分けられなかった。前の状態は「元に戻す」で戻せる"""
        img = _load(path)
        if not self.layers:
            self._reset([Layer("レイヤー 1", blank(img.width(), img.height())), Layer(name, img)], 1)
            return
        self.snapshot_all()
        self.layers = [Layer("レイヤー 1", blank(img.width(), img.height())), Layer(name, img)]
        self.current = 1
        self.set_selection(None)
        self.rebuild()
        self.fit()

    def place_result(self, path: str, name: str, replace: bool = False, hide_below: bool = False):
        """AI が描いた・直した・加工した結果を、一番上の新しいレイヤーに置いて選ぶ。
        前は結果を一番下に入れて空のレイヤーを上に選んでいたため、結果が出たことに気づけなかった。
        replace は新しく描いた絵・大きさの変わる結果（拡大・広げる）で、キャンバスを結果 1 枚に置き換える
        （大きさの違う前の絵とは重ねられない）。どちらも前の状態は「元に戻す」で戻せる"""
        img = _load(path)
        if not self.layers:
            self._reset([Layer("レイヤー 1", blank(img.width(), img.height())), Layer(name, img)], 1)
            return
        resized = (img.width(), img.height()) != self.size_px()
        if not replace and resized:
            return self.add_image_layer(path, name)   # 大きさだけ違う結果は、キャンバスに合わせて一番上に重ねる
        self.snapshot_all()
        if replace:   # 一番下は透明の土台、その上に結果（replace_with_image と同じ並び）
            self.layers = [Layer("レイヤー 1", blank(img.width(), img.height())), Layer(name, img)]
        else:
            if hide_below:   # 透過の結果: 下の絵を隠して透明の所を見せる（消さない。目の印で戻せ、元に戻すでも戻る）
                for layer in self.layers:
                    layer.visible = False
            self.layers.append(Layer(name, img))
        self.current = len(self.layers) - 1
        if replace:
            self.set_selection(None)
        self.rebuild()
        if replace and resized:
            self.fit()

    def add_image_layer(self, path: str, name: str = "絵"):
        img = _load(path)
        if not self.layers:
            self._reset([Layer(name, img)], 0)
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
        self.rebuild()

    def _reset(self, layers: list[Layer], current: int):
        self.layers, self.current = layers, current
        self.sym_center = None   # 新しい絵では軸を真ん中に戻す
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
        self.rebuild()
        self.changed.emit()

    def merge_down(self):
        """選んでいるレイヤーを下のレイヤーに結合する。元に戻すで戻せる"""
        i = self.current
        if i <= 0 or i >= len(self.layers):
            return
        upper, lower = self.layers[i], self.layers[i - 1]
        # 隠した・ロックしたレイヤーへ結合すると、見えている線が消えたり、ロックした絵が変わったりした。
        # 隠した上のレイヤーを結合すると、その絵が黙って捨てられた。どれも結合せずに理由を出す
        for layer, where in ((upper, "選んでいるレイヤー"), (lower, "下のレイヤー")):
            if not layer.visible or layer.locked:
                self.refused.emit(f"{where}「{layer.name}」を{'隠して' if not layer.visible else 'ロックして'}いるので結合できません")
                return False
        self.snapshot_all()
        img = QImage(lower.image)
        p = QPainter(img)
        if upper.visible:
            p.setOpacity(upper.opacity)
            p.drawImage(0, 0, upper.image)
        p.end()
        lower.image = img
        del self.layers[i]
        self.current = i - 1
        self.rebuild()
        self.changed.emit()
        return True

    # ---- レイヤーのコピー・切り取り・貼り付け・複製（普通の作画ソフトと同じ働き。どれも元に戻すで戻せる） ----
    def editable(self, i: int | None = None) -> bool:
        """レイヤー i（既定は選んでいるレイヤー）の絵を変えてよいか。隠した・ロックしたレイヤーは変えずに理由を出す
        （前は「選択範囲の中を消す」「切り取り」「塗る」がロックしたレイヤーの絵を消していた）"""
        if not self.layers:
            return False
        layer = self.layers[self.current if i is None else i]
        if layer.locked or not layer.visible:
            self.refused.emit(f"「{layer.name}」は{'ロックして' if layer.locked else '隠して'}いるので変えられません。"
                              "レイヤーの欄で出すか、ロックを外してください")
            return False
        return True

    def _insert_above(self, layer: Layer):
        self.layers.insert(self.current + 1, layer)
        self.current += 1
        self.rebuild()
        self.changed.emit()

    def duplicate_layer(self) -> bool:
        """選んでいるレイヤーを、すぐ上に同じ絵・濃さで複製して選ぶ"""
        if not self.layers:
            return False
        src = self.layers[self.current]
        self.snapshot_all()
        dup = src.copy()
        dup.name, dup.locked = f"{src.name} のコピー", False
        self._insert_above(dup)
        return True

    copied_layer: Layer | None = None

    def copy_layer(self) -> Layer | None:
        """選んでいるレイヤーを、名前・濃さごと覚える（貼るのは paste_layer）"""
        if not self.layers:
            return None
        self.copied_layer = self.layers[self.current].copy()
        return self.copied_layer

    def cut_layer(self) -> Layer | None:
        """選んでいるレイヤーを覚えてから消す。ロックしたレイヤーは切り取らない"""
        if not self.layers:
            return None
        if self.layers[self.current].locked:
            self.refused.emit(f"「{self.layers[self.current].name}」はロックしているので切り取れません")
            return None
        layer = self.copy_layer()
        self.delete_layer()
        self.changed.emit()
        return layer

    def paste_layer(self) -> bool:
        """覚えたレイヤーを、選んでいるレイヤーのすぐ上に新しいレイヤーとして貼って選ぶ。大きさの違う絵には左上に合わせる"""
        if self.copied_layer is None or not self.layers:
            return False
        w, h = self.size_px()
        src = self.copied_layer
        img = src.image
        if img.size() != QSize(w, h):
            img = blank(w, h)
            p = QPainter(img)
            p.drawImage(0, 0, src.image)
            p.end()
        self.snapshot_all()
        used = {layer.name for layer in self.layers}
        name = src.name if src.name not in used else f"{src.name} のコピー"
        self._insert_above(Layer(name, img.copy(), True, src.opacity, False))
        return True

    def layer_via(self, cut: bool = False) -> bool:
        """選択範囲の中を、同じ位置の新しいレイヤーへ写す（cut なら元から消す）。選択が無いときの写しはレイヤーの複製"""
        if not self.layers:
            return False
        if self.selection is None:
            if cut:
                self.refused.emit("選択範囲がありません。範囲を選んでから使ってください")
                return False
            return self.duplicate_layer()
        if cut and not self.editable():
            return False
        w, h = self.size_px()
        src = self.layers[self.current]
        part = blank(w, h)
        p = QPainter(part)
        p.setClipPath(self.selection_path())
        p.drawImage(0, 0, src.image)
        p.end()
        self.snapshot_all()
        if cut:
            q = QPainter(src.image)
            q.setCompositionMode(QPainter.CompositionMode_Clear)
            q.fillPath(self.selection_path(), Qt.transparent)
            q.end()
        self._insert_above(Layer(f"{src.name} の{'切り取り' if cut else 'コピー'}", part, True, src.opacity))
        return True

    def merged_image(self) -> QImage:
        """見えている絵を重ねた 1 枚の、選択範囲の中だけ（外は透明）。選択が無ければ全体"""
        img = self.flatten()
        if self.selection is None:
            return img
        out = QImage(self.selection.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.translate(-QPointF(self.selection.topLeft()))
        p.setClipPath(self.selection_path())
        p.drawImage(0, 0, img)
        p.end()
        return out

    def clear_layer(self) -> bool:
        """選んでいるレイヤーの絵を全部消して透明にする（レイヤーは残す）"""
        if not self.editable():
            return False
        self.snapshot()
        self.layers[self.current].image.fill(Qt.transparent)
        self.items[self.current].update()
        self.changed.emit()
        return True

    def flip_layer(self, horizontal: bool = True) -> bool:
        """選んでいるレイヤーの絵を左右（horizontal）か上下に反転する。表示の左右反転と違い、絵そのものを変える"""
        if not self.editable():
            return False
        self.snapshot()
        layer = self.layers[self.current]
        layer.image = layer.image.flipped(Qt.Horizontal if horizontal else Qt.Vertical)
        self.items[self.current].layer = layer
        self.items[self.current].sync()
        self.items[self.current].update()
        self.changed.emit()
        return True

    def flatten(self) -> QImage:
        w, h = self.size_px()
        out = blank(w, h)
        p = QPainter(out)
        for i, layer in enumerate(self.layers):
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.drawImage(0, 0, layer.image)
                if self.buffer is not None and i == self.current:
                    p.setOpacity(layer.opacity * self.paint_opacity())
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
        # 大きさの違う絵にしたとき、軸が前の絵の真ん中に残り、線が軸と違う所で折り返された
        if self.sym_center is not None and not QRectF(0, 0, w, h).contains(self.sym_center):
            self.sym_center = None
        # 絵を作る前に選んだ定規は点が無く、大きさの違う絵では点が遠くに残る。どちらも今の絵の初めの所に置き直す
        if self.ruler and (not self.ruler_pts or any(not QRectF(-w, -h, 3 * w, 3 * h).contains(q) for q in self.ruler_pts)):
            self.ruler_pts = []
            self.set_ruler(self.ruler)
        self._update_axis()
        self._update_ruler()
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
        self.layers.insert(self.current + 1, Layer(self._new_name(), blank(w, h)))
        self.current += 1
        self.rebuild()

    def delete_layer(self):
        """選んでいるレイヤーを、絵ごと消す。消したレイヤーの絵は手元の覚えから捨て（元に戻す用の写しだけ残る）、
        読み込んだ元のファイルからは読み直さない。1 枚だけのときは消せないので、絵を消して透明にする
        （前は何も起きず、押しても絵が残った）"""
        if not self.layers:
            return
        self.snapshot_all()
        if len(self.layers) <= 1:
            self.layers[0].image.fill(Qt.transparent)
        else:
            self.layers.pop(self.current)
            self.current = max(0, self.current - 1)
        # 前は消したレイヤーの絵を空にしてから場面を作り直しており、場面の索引が壊れて落ちた。
        # 消したレイヤーは元に戻す用の写しにだけ残り、項目を外せば手放される
        self.rebuild()

    def move_layer(self, step: int):
        j = self.current + step
        if 0 <= j < len(self.layers):
            self.snapshot_all()
            self.layers[self.current], self.layers[j] = self.layers[j], self.layers[self.current]
            self.current = j
            self.rebuild()

    def move_layer_to(self, i: int, j: int):
        """レイヤー i を j の位置へ動かす（ドラッグでの並べ替え）。元に戻すで戻せる"""
        n = len(self.layers)
        if not (0 <= i < n and 0 <= j < n) or i == j:
            return
        self.snapshot_all()
        layer = self.layers.pop(i)
        self.layers.insert(j, layer)
        self.current = j
        self.rebuild()
        self.changed.emit()

    def select(self, i: int):
        if 0 <= i < len(self.layers):
            self.current = i
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

    def snapshot_all(self):
        self._push(("all", [layer.copy() for layer in self.layers], self.current))

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
        if self.tool in SELECT_TOOLS:
            return "選択範囲の中を変える"   # 選ぶ道具はレイヤーを変えない。変えたのは消す・塗る
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
            self.items[i].sync()
            self.changed.emit()
        else:
            _, layers, cur = entry
            other.append(("all", [layer.copy() for layer in self.layers], self.current))
            self.layers, self.current = layers, cur
            self.rebuild()

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
        self.flipped = False
        self.zoomed.emit(1.0)
        self.view_changed.emit()

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
        self.set_angle(self.angle + deg)

    def set_angle(self, deg: float):
        """表示の角度を deg 度にする（-180〜180 にそろえる）。絵そのものは回さない"""
        deg = (deg + 180) % 360 - 180
        step = deg - self.angle
        if abs(step) > 1e-9:
            # 左右反転で見ているときは向きが逆になるので、見た目の向きで回るよう符号を変える
            self.rotate(-step if self.flipped else step)
            self.angle = deg
        self.view_changed.emit()

    def reset_rotation(self):
        self.set_angle(0.0)

    flipped = False

    def flip_view(self, on: bool | None = None):
        """左右反転で見る（絵は変えない）。崩れは反転すると見つけやすい"""
        on = (not self.flipped) if on is None else on
        if on != self.flipped:
            c = self.mapToScene(self.viewport().rect().center())
            self.scale(-1, 1)
            self.flipped = on
            self.centerOn(c)
        self.view_changed.emit()

    def reset_view(self):
        """表示を初めに戻す（回転・左右反転・拡大・位置）。絵は変えない"""
        self.resetTransform()
        self.angle = 0.0
        self.flipped = False
        self.fit()
        self.view_changed.emit()

    # ---- グリッド ----
    grid = False
    grid_step = 32

    def set_grid(self, on: bool, step: int | None = None):
        self.grid = bool(on)
        if step:
            self.grid_step = max(4, int(step))
        self.viewport().update()
        self.view_changed.emit()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.ruler and self.layers:
            self._draw_guides(painter)
        if not self.grid or not self.layers:
            return
        w, h = self.size_px()
        area = rect.intersected(QRectF(0, 0, w, h))
        if area.isEmpty():
            return
        step = self.grid_step
        painter.save()
        painter.setPen(QPen(QColor(61, 123, 255, 90), 0))
        x = int(area.left() // step) * step
        while x <= area.right():
            if x > 0:
                painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            x += step
        y = int(area.top() // step) * step
        while y <= area.bottom():
            if y > 0:
                painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            y += step
        painter.restore()

    # ---- R を押しながらドラッグで回す ----
    # R は「ぼかし」の道具のキーでもある。押して離しただけならぼかしに持ち替え（on_r_tap）、
    # 押したままドラッグしたら表示を回す
    rotating = False
    _rot_from = None
    _rot_used = False
    on_r_tap = None

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ShortcutOverride and e.key() == Qt.Key_R and not e.modifiers():
            e.accept()   # 窓のキー（ぼかし）より先に、絵の上の R を受ける
            return True
        return super().event(e)

    def _angle_at(self, pt) -> float:
        import math
        c = self.viewport().rect().center()
        return math.degrees(math.atan2(pt.y() - c.y(), pt.x() - c.x()))

    def wheelEvent(self, e):
        self.auto_fit = False
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.zoomed.emit(self.zoom())

    # ---- 道具 ----
    def set_tool(self, tool: str):
        if tool == "pen" and getattr(self, "brush", None) is not None and self.brush.name == "消しゴム":
            self.brush = self.brushes["ペン"]   # ペンに持ち替えたのに消しゴムのブラシのままにしない
        if tool != self.tool and self.poly_points:
            self.poly_points = []   # 道具を替えたら置きかけの多角形はやめる
            self.set_selection(self.selection, self.selection_shape)
        if tool != self.tool and self.shape_points:
            self.shape_points = []   # 置きかけの多角形の図形もやめる
            self.sel_path_item.setVisible(False)
            self.set_selection(self.selection, self.selection_shape)
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
        r = (self.size * (2 if self.tool in ("eraser", "blur") and self.brush.name != "消しゴム" or self.tool == "spray" else 1)) / 2
        self.cursor_ring.setRect(pos.x() - r, pos.y() - r, r * 2, r * 2)
        k = 1.0 / max(self.zoom(), 1e-6)   # 内側の輪は画面で 1 画素だけ内に置く
        self.cursor_ring_in.setRect(pos.x() - r + k, pos.y() - r + k, max(0.0, r * 2 - 2 * k), max(0.0, r * 2 - 2 * k))

    def set_brush(self, name: str):
        self.brush = self.brushes[name]
        self.set_tool("eraser" if name == "消しゴム" else "pen")

    def begin_stroke(self):
        """線の描き始め。消しゴムはレイヤーから直接消し、ほかは線用の下書きに描く"""
        self.carry = 0.0
        self.stroke_len = 0.0
        if self.tool not in ("eraser", "blur", "smudge"):
            w, h = self.size_px()
            self.buffer = blank(w, h)
            it = self.items[self.current]
            it.buffer, it.buffer_opacity = self.buffer, self.paint_opacity()

    def end_stroke(self):
        """手を離したら、下書きの線を濃さを掛けてレイヤーへ重ねる"""
        if self.buffer is not None:
            p = QPainter(self.layers[self.current].image)
            if self.selection is not None:
                p.setClipPath(self.selection_path())
            p.setOpacity(self.paint_opacity())
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
        inside = self.selection_path()
        p = QPainter(img)
        p.setClipPath(outside.subtracted(inside))
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, before)
        p.end()
        self.items[self.current].update()

    def stroke(self, a: QPointF, b: QPointF, pressure: float = 1.0):
        """a から b まで今のブラシで描く。線の途中でなければ、その 1 区切りだけで線を描き終える"""
        alone = self.buffer is None and self.tool not in ("eraser", "blur", "smudge")
        if alone:
            self.begin_stroke()
        carry = self.carry
        for i, (a2, b2) in enumerate(self._mirrored(a, b)):
            if i:
                self.carry = carry   # 折り返した線も同じ間隔で点を置く
            if self.tool == "blur":
                self.blur(a2, b2)
            elif self.tool == "smudge":
                self.smudge(a2, b2)
            else:
                self._paint(a2, b2, pressure)
        self.stroke_len += ((b.x() - a.x()) ** 2 + (b.y() - a.y()) ** 2) ** 0.5
        if alone:
            self.end_stroke()

    def axis_center(self) -> QPointF:
        if self.sym_center is not None:
            return QPointF(self.sym_center)
        w, h = self.size_px()
        return QPointF(w / 2, h / 2)

    def sym_maps(self) -> list:
        """対称の写し方。1 つ目は描いたそのまま、残りが軸の反対側（線対称は折り返し、点対称は中心の周りに半回転）"""
        same = [lambda q: QPointF(q)]
        if not self.symmetry or not self.layers:
            return same
        c = self.axis_center()
        cx, cy = c.x(), c.y()
        lr = lambda q: QPointF(2 * cx - q.x(), q.y())         # noqa: E731
        ud = lambda q: QPointF(q.x(), 2 * cy - q.y())         # noqa: E731
        pt = lambda q: QPointF(2 * cx - q.x(), 2 * cy - q.y())   # noqa: E731
        return same + {"lr": [lr], "ud": [ud], "both": [lr, ud, pt], "point": [pt]}[self.symmetry]

    def _mirrored(self, a: QPointF, b: QPointF) -> list:
        """対称のときは、軸の反対側に写した区切りも返す"""
        return [(m(a), m(b)) for m in self.sym_maps()]

    def set_symmetry(self, mode):
        """対称の形を決める。True は左右（前の「左右対称」の印と同じ）、False・"" は切る"""
        mode = "lr" if mode is True else "" if not mode else str(mode)
        if mode and mode not in SYMMETRY:
            raise ValueError(mode)
        self.symmetry = mode
        self._update_axis()
        self.view_changed.emit()

    def set_axis_center(self, pos: QPointF | None):
        """対称の軸を pos へ動かす（絵の外には出さない）。None で絵の真ん中に戻す"""
        if pos is not None and self.layers:
            w, h = self.size_px()
            pos = QPointF(min(max(pos.x(), 0.0), float(w)), min(max(pos.y(), 0.0), float(h)))
        self.sym_center = pos
        self._update_axis()

    def _update_axis(self):
        on = bool(self.symmetry) and bool(self.layers)
        self.mirror_item.setVisible(on)
        self.axis_handle.setVisible(on)
        if not on:
            return
        w, h = self.size_px()
        c = self.axis_center()
        path = QPainterPath()
        if self.symmetry in ("lr", "both", "point"):
            path.moveTo(c.x(), 0)
            path.lineTo(c.x(), h)
        if self.symmetry in ("ud", "both", "point"):
            path.moveTo(0, c.y())
            path.lineTo(w, c.y())
        self.mirror_item.setPath(path)
        self.axis_handle.setPos(c)

    def on_axis_handle(self, view_pos) -> bool:
        """画面の点 view_pos が、軸をつかむ丸の上か"""
        if not self.axis_handle.isVisible():
            return False
        d = self.mapFromScene(self.axis_center()) - view_pos
        return d.x() ** 2 + d.y() ** 2 <= (AXIS_GRIP + 3) ** 2

    def stroke_color(self) -> QColor:
        """今の線の色。虹色は線の長さで色相を回し、行き来は描く色と背景色の間を行き来する（太さの 20 倍の長さで 1 周）"""
        if self.color_mode not in COLOR_MODES[1:]:
            return self.opaque()
        t = self.stroke_len / max(60.0, self.size * 20.0)
        if self.color_mode == COLOR_MODES[1]:
            h, s, v, _ = self.color.getHsvF()
            return QColor.fromHsvF(round((max(h, 0.0) + t) % 1.0, 2), max(s, 0.6), max(v, 0.6))   # 色相は 1% 刻み（点の作り置きを増やしすぎない）
        k = round(1 - abs((t % 2.0) - 1.0), 2)   # 0→1→0 の三角の波
        a, b = self.color, self.bg_color
        return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * k, a.greenF() + (b.greenF() - a.greenF()) * k,
                               a.blueF() + (b.blueF() - a.blueF()) * k)

    def opaque(self) -> QColor:
        """描く色から透明度を除いた色。透明度は paint_opacity でまとめて掛ける（線の点ごとに掛けると重なりで濃くなる）"""
        c = QColor(self.color)
        c.setAlpha(255)
        return c

    def paint_opacity(self) -> float:
        """線・形・塗りを重ねるときの濃さ。ブラシの濃さと、色の欄の透明度を掛けた値"""
        return self.brush_opacity * self.color.alphaF()

    def _paint(self, a: QPointF, b: QPointF, pressure: float):
        erase = self.tool == "eraser"
        target = self.layers[self.current].image if erase else self.buffer
        if self.tool == "spray":
            dirty = self.spray(target, b, pressure)
        else:
            brush = self.brushes["消しゴム"] if erase and self.brush.name != "消しゴム" else self.brush
            size = self.size * (2 if erase and brush is not self.brush else 1)
            color = QColor(0, 0, 0) if erase else self.stroke_color()
            dirty, self.carry = stamp(target, brush, self.dabs, a, b, size, color, pressure, self.carry, erase=erase)
        self.items[self.current].update(dirty)   # 線を引いた四角だけ描き直す

    def spray(self, target: QImage, pos: QPointF, pressure: float = 1.0) -> QRectF:
        """スプレー。太さを半径にした円の中に細かな点を散らす（中ほど多い）。筆圧が強いほど点が多い"""
        import math
        import random
        r = max(2.0, float(self.size))
        n = max(6, int(r * 1.5 * max(0.2, pressure)))
        p = QPainter(target)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.stroke_color())
        dot = max(0.6, r / 30)
        for _ in range(n):
            d = r * random.random() ** 0.8
            ang = random.random() * 2 * math.pi
            p.drawEllipse(QPointF(pos.x() + d * math.cos(ang), pos.y() + d * math.sin(ang)), dot, dot)
        p.end()
        return QRectF(pos.x() - r - 2, pos.y() - r - 2, r * 2 + 4, r * 2 + 4)

    def smudge(self, a: QPointF, b: QPointF):
        """指先。a の所の絵をつまんで b へ引きずり、色を伸ばす（ぼかしと同じく、じかにレイヤーを変える）"""
        img = self.layers[self.current].image
        r = max(2, self.size // 2)
        dist = ((b.x() - a.x()) ** 2 + (b.y() - a.y()) ** 2) ** 0.5
        n = max(1, int(dist / max(1, r / 3)))
        dirty = QRect()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        if self.selection is not None:
            p.setClipPath(self.selection_path())
        prev = a
        for k in range(1, n + 1):
            t = k / n
            cur = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
            part = img.copy(QRect(int(prev.x()) - r, int(prev.y()) - r, r * 2, r * 2))
            dst = QRect(int(cur.x()) - r, int(cur.y()) - r, r * 2, r * 2)
            path = QPainterPath()
            path.addEllipse(QRectF(dst))
            p.save()
            p.setClipPath(path, Qt.IntersectClip)
            p.setOpacity(0.6 * self.brush_opacity)
            p.drawImage(dst.topLeft(), part)
            p.restore()
            dirty = dirty.united(dst)
            prev = cur
        p.end()
        self.items[self.current].update(QRectF(dirty))

    def place_text(self, pos: QPointF, text: str, px: int | None = None):
        """文字の道具。押した所を左上にして、描く色で文字を置く（大きさは太さの 4 倍、最小 8 画素）"""
        if not text or not self.layers:
            return
        from PySide6.QtGui import QFont
        self.snapshot()
        p = QPainter(self.layers[self.current].image)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self.selection is not None:
            p.setClipPath(self.selection_path())
        f = QFont()
        f.setPixelSize(px or max(8, self.size * 4))
        p.setFont(f)
        p.setPen(self.opaque())
        p.setOpacity(self.paint_opacity())
        p.drawText(QRectF(pos.x(), pos.y(), 1e5, 1e5), Qt.AlignLeft | Qt.AlignTop, text)
        p.end()
        self.items[self.current].update()
        self.used_color.emit()
        self.changed.emit()
        self.stroke_done.emit()

    def steadied(self, pos: QPointF) -> QPointF:
        """手ぶれ補正。カーソルに少し遅れてついていく点を返す（強さ n で 1/(n+1) ずつ近づく）"""
        if self.stabilizer <= 0 or self.steady is None:
            self.steady = QPointF(pos)
            return pos
        # 強さ 0〜100。前の 0〜20 の段と同じ効き（100 で前の 20 と同じ遅れ）になるよう 1/5 にして使う
        k = 1.0 / (self.stabilizer / 5 + 1)
        self.steady = QPointF(self.steady.x() + (pos.x() - self.steady.x()) * k, self.steady.y() + (pos.y() - self.steady.y()) * k)
        return QPointF(self.steady)

    # ---- 描く補助: Shift の固定・定規・形の補正 ----
    def constrained(self, a: QPointF, b: QPointF) -> QPointF:
        """図形の道具の終わりの点に、Shift の固定（直線・正多角形は 15 度ごと、四角は正方形、楕円は正円）と、直線への定規を掛ける"""
        from chatdraw import assist
        if self.tool == "line" and self.ruler and not self.shift:
            return QPointF(*assist.ruler_snap(self.ruler, (a.x(), a.y()), self._ruler_tuple(), (b.x(), b.y())))
        if not self.shift:
            return b
        if self.tool in ("line", "regpoly", "gradient", "polyshape"):
            return QPointF(*assist.snap_angle((a.x(), a.y()), (b.x(), b.y())))
        if self.tool in ("rect", "ellipse"):
            return QPointF(*assist.square_end((a.x(), a.y()), (b.x(), b.y())))
        return b

    def _ruler_tuple(self) -> list:
        return [(q.x(), q.y()) for q in self.ruler_pts]

    def set_ruler(self, kind: str):
        """定規を決める。"" で切る。同じ意味の点（中心どうし）の定規に替えたら点を残し、違えばその定規の初めの所に置く"""
        from chatdraw.assist import RULERS
        kind = kind or ""
        if kind and kind not in RULERS:
            raise ValueError(kind)
        group = {"parallel": "dir", "persp2": "vp2"}.get(kind, "center") if kind else ""
        if kind and self.layers and (group != self._ruler_group or not self.ruler_pts):
            w, h = self.size_px()
            if group == "dir":
                self.ruler_pts = [QPointF(w * 0.3, h * 0.5), QPointF(w * 0.7, h * 0.5)]
            elif group == "vp2":
                self.ruler_pts = [QPointF(w * 0.05, h * 0.4), QPointF(w * 0.95, h * 0.4)]
            else:
                self.ruler_pts = [QPointF(w / 2, h / 2)]
        if kind:
            self._ruler_group = group
        self.ruler = kind
        self._update_ruler()
        self.view_changed.emit()

    _ruler_group = ""

    def set_ruler_point(self, i: int, pos: QPointF | None):
        """定規の i 番目の点を動かす（None で初めの所に戻す）"""
        if pos is None:
            self.ruler_pts = []
            self.set_ruler(self.ruler)
            return
        if 0 <= i < len(self.ruler_pts):
            self.ruler_pts[i] = QPointF(pos)
            self._update_ruler()

    def _update_ruler(self):
        on = bool(self.ruler) and bool(self.layers)
        for i, hd in enumerate(self.ruler_handles):
            vis = on and i < len(self.ruler_pts)
            hd.setVisible(vis)
            if vis:
                hd.setPos(self.ruler_pts[i])
        self.viewport().update()

    def on_ruler_handle(self, view_pos) -> int:
        """画面の点 view_pos が定規の点の丸の上なら、その番号。上でなければ -1"""
        for i, hd in enumerate(self.ruler_handles):
            if hd.isVisible():
                d = self.mapFromScene(hd.pos()) - view_pos
                if d.x() ** 2 + d.y() ** 2 <= (AXIS_GRIP + 3) ** 2:
                    return i
        return -1

    def _draw_guides(self, painter):
        """定規の案内の線を、絵の中だけに薄く描く"""
        from chatdraw.assist import ruler_guides
        w, h = self.size_px()
        painter.save()
        painter.setClipRect(QRectF(0, 0, w, h))
        painter.setPen(QPen(QColor(34, 170, 90, 110), 0, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        for g in ruler_guides(self.ruler, self._ruler_tuple(), w, h):
            if g[0] == "circle":
                painter.drawEllipse(QPointF(g[1], g[2]), g[3], g[3])
            else:
                painter.drawLine(QPointF(g[0], g[1]), QPointF(g[2], g[3]))
        painter.restore()

    def assisted(self, pos: QPointF) -> QPointF:
        """なぞる道具の今の所を、定規に沿わせる。パース 2 点は少し動かしてから向きを決める"""
        if not self.ruler or self.stroke_start is None or not self.ruler_pts:
            return pos
        from chatdraw import assist
        a = (self.stroke_start.x(), self.stroke_start.y())
        now = (pos.x(), pos.y())
        if self.ruler == "persp2" and self.ruler_dir is None:
            if (pos - self.stroke_start).manhattanLength() < 6 / max(0.01, self.zoom()):
                return QPointF(self.stroke_start)   # 向きが決まるまでは始めの所から動かさない
            self.ruler_dir = assist.ruler_direction("persp2", a, self._ruler_tuple(), now)
        return QPointF(*assist.ruler_snap(self.ruler, a, self._ruler_tuple(), now, self.ruler_dir))

    def quick_shape(self) -> bool:
        """描いている線を止めたとき、形（直線・円・楕円・四角・三角）に見えれば、その形に描き直す。
        整える前の線は残し、離したあとの元に戻すで、整える前の線に戻せる"""
        if self.last is None or self.buffer is None or self.qs_shape is not None or self.tool != "pen":
            return False
        from chatdraw import assist
        shape = assist.recognize(self.qs_points, min_size=max(12.0, 3 * self.size))
        if shape is None:
            return False
        self.qs_raw = self.buffer.copy()
        self.buffer.fill(Qt.transparent)
        self.carry = 0.0
        pts = [QPointF(*q) for q in assist.shape_points(shape)]
        for a, b in zip(pts, pts[1:]):
            self.stroke(a, b, self.pressure)
        self.qs_shape = shape
        self.items[self.current].update()
        self.shaped.emit(assist.SHAPE_NAMES[shape[0]])
        return True

    def _end_brush(self, pos: QPointF | None):
        """なぞる線を離したとき。手ぶれ補正で遅れた分を離した所まで引き、整えた形は 2 段の元に戻すにして置く"""
        self.qs_timer.stop()
        if self.qs_shape is None and pos is not None and self.stabilizer > 0 and self.last is not None:
            # 手ぶれ補正で、線の終わりが離した所まで届かずに短く切れていた
            end = self.assisted(pos)
            if (end - self.last).manhattanLength() > 0.01:
                self.stroke(self.last, end, self.pressure)
        if self.qs_shape is not None and self.qs_raw is not None and self.undo_stack and self.undo_stack[-1][0] == "one":
            before = self.undo_stack[-1][2]
            shaped, self.buffer = self.buffer, self.qs_raw
            self.items[self.current].buffer = self.buffer
            self.end_stroke()                    # 1 段目: 整える前の線
            self.snapshot()
            self.undo_names[-1] = "形を整える"
            self.layers[self.current].image = before.copy()
            self.items[self.current].sync()
            self.buffer = shaped
            self.items[self.current].buffer = shaped
        self.end_stroke()
        self.qs_shape, self.qs_raw, self.qs_points = None, None, []
        self.stroke_start, self.ruler_dir = None, None

    # ---- 多角形の図形 ----
    def _shape_preview(self, closing: QPointF | None = None):
        path = QPainterPath()
        if self.shape_points:
            path.moveTo(self.shape_points[0])
            for q in self.shape_points[1:]:
                path.lineTo(q)
            if closing is not None:
                path.lineTo(closing)
        self.sel_item.setVisible(False)
        self.sel_path_item.setPath(path)
        self.sel_path_item.setVisible(bool(self.shape_points))

    def finish_shape(self) -> bool:
        """多角形の図形を閉じて描く（ダブルクリック、Enter、始めの角を押す）。角が 3 つ未満なら描かずにやめる"""
        pts, self.shape_points = self.shape_points, []
        self.sel_path_item.setVisible(False)
        self.set_selection(self.selection, self.selection_shape)
        if len(pts) < 3 or not self.layers:
            return False
        self.used_color.emit()
        self.snapshot()
        img = self.layers[self.current].image
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        if self.selection is not None:
            p.setClipPath(self.selection_path())
        p.setOpacity(self.paint_opacity())
        p.setPen(QPen(self.opaque(), self.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(self.opaque() if self.fill_shapes else Qt.NoBrush)
        for m in self.sym_maps():
            p.drawPolygon(QPolygonF([m(q) for q in pts]))
        p.end()
        self.items[self.current].update()
        self.stroke_done.emit()
        return True

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
        sel = self.selection_mask()
        if sel is not None:
            keep = np.frombuffer(sel.constBits(), np.uint8).reshape(h, sel.bytesPerLine())[:, :w] > 127
            mask &= keep
        self.snapshot()
        c = self.opaque()
        c.setAlphaF(self.paint_opacity())
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
            p.setClipPath(self.selection_path())
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
    def set_selection(self, rect: QRect | None, shape: QPainterPath | None = None):
        """選択範囲を決める。shape を渡すと投げなわ・多角形の形にし、rect はその外の四角にする"""
        w, h = self.size_px()
        if shape is not None:
            whole = QPainterPath()
            whole.addRect(QRectF(0, 0, w, h))
            shape = shape.intersected(whole)
            rect = shape.boundingRect().toAlignedRect()
        if rect is not None:
            rect = rect.normalized().intersected(QRect(0, 0, w, h))
            if rect.width() < 2 or rect.height() < 2:
                rect, shape = None, None
        self.selection = rect
        self.selection_shape = shape if rect is not None else None
        self.poly_points = []
        self.sel_item.setVisible(rect is not None and shape is None)
        self.sel_path_item.setVisible(rect is not None and shape is not None)
        if rect is not None and shape is None:
            self.sel_item.setRect(QRectF(rect))
        if rect is not None and shape is not None:
            self.sel_path_item.setPath(shape)

    def selection_path(self) -> QPainterPath:
        """選択範囲の形。四角でも投げなわでも、描く道具はこの形で切り抜く"""
        if self.selection_shape is not None:
            return QPainterPath(self.selection_shape)
        path = QPainterPath()
        if self.selection is not None:
            path.addRect(QRectF(self.selection))
        return path

    @staticmethod
    def _points_shape(pts: list) -> QPainterPath | None:
        if len(pts) < 3:
            return None
        path = QPainterPath()
        path.addPolygon(QPolygonF([QPointF(q) for q in pts]))
        path.closeSubpath()
        return path

    def finish_polygon(self) -> bool:
        """多角形の選択を閉じる（ダブルクリック、Enter、始めの角を押す）。角が 3 つ未満なら閉じずに捨てる"""
        shape = self._points_shape(self.poly_points)
        self.poly_points = []
        if shape is None:
            self.set_selection(self.selection, self.selection_shape)   # 前の選択の見た目に戻す
            return False
        self.set_selection(None, shape)
        self.stroke_done.emit()
        return self.selection is not None

    def _show_points(self, pts: list, closing: QPointF | None = None):
        path = QPainterPath()
        if pts:
            path.moveTo(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            if closing is not None:
                path.lineTo(closing)
        self.sel_item.setVisible(False)
        self.sel_path_item.setPath(path)
        self.sel_path_item.setVisible(True)

    def selection_mask(self) -> QImage | None:
        """四角の選択範囲を、直す所の形（白が直す所）にする。選択が無ければ None"""
        if self.selection is None or self.selection.isEmpty():
            return None
        w, h = self.size_px()
        m = QImage(w, h, QImage.Format_Grayscale8)
        m.fill(0)
        q = QPainter(m)
        q.fillPath(self.selection_path(), QColor("white"))
        q.end()
        return m

    def select_all(self):
        w, h = self.size_px()
        self.set_selection(QRect(0, 0, w, h))

    def clear_selection_area(self):
        """選択範囲の中を消す（Delete）。範囲が無ければ何もしない"""
        if self.selection is None or not self.editable():
            return False
        self.snapshot()
        p = QPainter(self.layers[self.current].image)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillPath(self.selection_path(), Qt.transparent)
        p.end()
        self.items[self.current].update()
        self.changed.emit()
        return True

    def fill_selection(self) -> bool:
        """選択範囲の中を描く色で塗る（濃さも効く）。範囲が無ければ何もしない"""
        if self.selection is None or not self.editable():
            return False
        self.snapshot()
        p = QPainter(self.layers[self.current].image)
        p.setOpacity(self.paint_opacity())
        p.fillPath(self.selection_path(), self.opaque())
        p.end()
        self.items[self.current].update()
        self.used_color.emit()
        self.changed.emit()
        return True

    def selection_image(self) -> QImage | None:
        """選んだレイヤーの、選択範囲の中だけを切り出した絵（外は透明）。範囲が無ければ None"""
        if self.selection is None or not self.layers:
            return None
        out = QImage(self.selection.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.translate(-QPointF(self.selection.topLeft()))
        p.setClipPath(self.selection_path())
        p.drawImage(0, 0, self.layers[self.current].image)
        p.end()
        return out

    def paste_image(self, img: QImage, name: str = "貼り付け", at: QPoint | None = None) -> bool:
        """絵を一番上の新しいレイヤーに置く。選択範囲があればその左上、無ければ左上に置く（元に戻すで戻せる）"""
        if img is None or img.isNull() or not self.layers:
            return False
        w, h = self.size_px()
        self.snapshot_all()
        layer = blank(w, h)
        p = QPainter(layer)
        p.drawImage(at if at is not None else self.selection.topLeft() if self.selection is not None else QPoint(0, 0), img)
        p.end()
        self.layers.append(Layer(name, layer))
        self.current = len(self.layers) - 1
        self.rebuild()
        self.changed.emit()
        return True

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
            self.sel_path_item.setVisible(False)
            self.sel_item.setVisible(True)
            self.sel_item.setRect(QRectF(a, b).normalized())
            return
        if self.tool == "lasso":
            if not self.poly_points:
                self.poly_points = [QPointF(a)]
            self.poly_points.append(QPointF(b))
            self._show_points(self.poly_points)
            return
        self.buffer.fill(Qt.transparent)
        p = QPainter(self.buffer)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.constrained(a, b)
        if self.tool == "gradient":
            g = QLinearGradient(a, b)
            g.setColorAt(0, self.opaque())
            g.setColorAt(1, self.bg_color)
            p.fillRect(self.buffer.rect(), QBrush(g))
        else:
            p.setPen(QPen(self.opaque(), self.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(self.opaque() if self.fill_shapes and self.tool != "line" else Qt.NoBrush)
            # 図形も対称の軸の反対側に描く（前は線の道具だけが対称に効き、直線・四角・楕円は片側だけだった）
            for m in self.sym_maps():
                a2, b2 = m(a), m(b)
                if self.tool == "line":
                    p.drawLine(a2, b2)
                elif self.tool == "regpoly":
                    from chatdraw.assist import regular_polygon
                    p.drawPolygon(QPolygonF([QPointF(*q) for q in regular_polygon((a2.x(), a2.y()), (b2.x(), b2.y()), self.poly_sides)]))
                elif self.tool == "rect":
                    p.drawRect(QRectF(a2, b2).normalized())
                else:
                    p.drawEllipse(QRectF(a2, b2).normalized())
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
        if self.tool == "lasso":
            pts = self.poly_points + [QPointF(b)]
            self.poly_points = []
            shape = self._points_shape(pts)
            # 押しただけ（なぞっていない）は、四角の選択と同じく選択を外す
            if shape is None:
                self.set_selection(None)
            else:
                self.set_selection(None, shape)
            return
        self.end_stroke()

    # ---- マウスとペンタブレット ----
    def _brush_move(self, pos: QPointF):
        if self.qs_shape is not None:
            return   # 形に整えたあとは、離すまで線を足さない
        pos = self.assisted(self.steadied(pos))
        self.stroke(self.last, pos, self.pressure)
        self.last = pos
        if self.quickshape and self.tool == "pen":
            self.qs_points.append((pos.x(), pos.y()))
            self.qs_timer.start(QUICKSHAPE_MS)   # 動かすたびに数え直し、止めて少したったら整える

    def _press(self, pos: QPointF, pressure: float):
        if self.tool == "redpen" and self.layers:
            self.redpen.begin(pos)
            self.marked.emit()
            return True
        if not self.layers:
            return False
        if self.tool == "polygon":
            # 押すたびに角を置く。始めの角の近くを押すと閉じる
            if len(self.poly_points) >= 3 and (pos - self.poly_points[0]).manhattanLength() < 8 / max(0.01, self.zoom()):
                self.finish_polygon()
                return True
            self.poly_points.append(QPointF(pos))
            self._show_points(self.poly_points)
            return True
        if self.tool not in ("eyedropper", "zoom") + SELECT_TOOLS:
            layer = self.layers[self.current]
            if not layer.visible or layer.locked:
                self.refused.emit(f"「{layer.name}」は{'隠して' if not layer.visible else 'ロックして'}いるので描けません。"
                                  "レイヤーの欄で出すか、ロックを外すか、ほかのレイヤーを選んでください")
                return True
        if self.tool == "polyshape":
            if self.shape_points and self.shift:
                pos = self.constrained(self.shape_points[-1], pos)
            if len(self.shape_points) >= 3 and (pos - self.shape_points[0]).manhattanLength() < 8 / max(0.01, self.zoom()):
                self.finish_shape()
                return True
            self.shape_points.append(QPointF(pos))
            self._shape_preview()
            return True
        if self.tool == "eyedropper":
            self.pick(pos)
            return True
        if self.tool == "fill":
            self.fill(pos)
            return True
        if self.tool == "text":
            self.text_wanted.emit(pos)
            return True
        if self.tool == "zoom":
            f = 1 / 1.25 if self.zoom_out else 1.25
            self.auto_fit = False
            self.scale(f, f)
            self.zoomed.emit(self.zoom())
            return True
        if self.tool in DRAG_TOOLS:
            if self.tool not in ("move", "select", "lasso"):
                self.used_color.emit()
            if self.tool not in ("select", "lasso"):
                self.snapshot()
            if self.tool not in ("move", "select", "lasso"):
                w, h = self.size_px()
                self.buffer = blank(w, h)
                it = self.items[self.current]
                it.buffer, it.buffer_opacity = self.buffer, self.paint_opacity()
            self.drag_start = pos
            return True
        if self.tool in BRUSH_TOOLS:
            if self.tool in ("pen", "spray"):
                self.used_color.emit()
            self.snapshot()
            self.begin_stroke()
            self.stroke_start, self.ruler_dir = QPointF(pos), None
            self.qs_points, self.qs_shape, self.qs_raw = [(pos.x(), pos.y())], None, None
            self.steady = QPointF(pos)
            self.last = pos
            self.stroke(pos, pos, pressure)
            return True
        return False

    zoom_out = False

    def mousePressEvent(self, e):
        if self.rotating and e.button() == Qt.LeftButton:
            self._rot_from = (self._angle_at(e.position()), self.angle)
            self._rot_used = True
            return
        if e.button() == Qt.RightButton and self.tool != "zoom":
            self.pan_from, self.panned = e.position().toPoint(), False
            return
        self.shift = bool(e.modifiers() & Qt.ShiftModifier)
        if e.button() == Qt.LeftButton and self.on_ruler_handle(e.position().toPoint()) >= 0:
            self._ruler_drag = self.on_ruler_handle(e.position().toPoint())   # 定規の丸をつかんだら、描かずに定規を動かす
            return
        if e.button() == Qt.LeftButton and self.on_axis_handle(e.position().toPoint()):
            self._axis_drag = True   # 軸の丸をつかんだら、描かずに軸を動かす
            return
        self.zoom_out = bool(e.modifiers() & Qt.ShiftModifier) or e.button() == Qt.RightButton and self.tool == "zoom"
        if self.tool == "zoom" and e.button() == Qt.RightButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        if e.button() == Qt.LeftButton and self._press(self.mapToScene(e.position().toPoint()), 1.0):
            return
        super().mousePressEvent(e)

    def enterEvent(self, e):
        # 絵の上に来たらキー（Space、Alt、[ ]）を受ける。ただし文字の欄（赤ペンの指示など）に書いている間は取らない。
        # 取ると、欄に打った文字がキャンバスに吸われた（指示の欄はキャンバスの上にあるので、マウスが少し動くだけで起きた）
        from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit
        f = QApplication.focusWidget()
        if not (isinstance(f, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) and f.isVisible()):
            self.setFocus()
        super().enterEvent(e)

    def mouseDoubleClickEvent(self, e):
        """赤ペンの番号の丸をダブルクリックすると、その印の指示を書き直す"""
        if self.tool == "polygon" and self.poly_points:
            self.finish_polygon()   # ダブルクリックで多角形を閉じる
            return
        if self.tool == "polyshape" and self.shape_points:
            # ダブルクリックの 1 回目で置いた角と同じ所の角は外してから閉じる
            if len(self.shape_points) >= 2 and (self.shape_points[-1] - self.shape_points[-2]).manhattanLength() < 2:
                self.shape_points.pop()
            self.finish_shape()
            return
        n = self.redpen.number_at(self.mapToScene(e.position().toPoint()), self.zoom())
        if n:
            self.redpen.drawing = None
            self.note_wanted.emit(n)
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        self._wake_cursor()
        if self.rotating and self._rot_from is not None:
            a0, base = self._rot_from
            d = self._angle_at(e.position()) - a0
            self.set_angle(base + d)   # angle は見た目の角度（反転の向きは set_angle が直す）
            return
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
        self.shift = bool(e.modifiers() & Qt.ShiftModifier)
        if self._ruler_drag >= 0:
            self.set_ruler_point(self._ruler_drag, pos)
            return
        if self._axis_drag:
            self.set_axis_center(pos)
            return
        over = not e.buttons() and self.on_axis_handle(e.position().toPoint())
        if over != self._over_axis:   # 丸の上ではつかめると分かる形のカーソルにする
            self._over_axis = over
            self.viewport().setCursor(Qt.SizeAllCursor) if over else self._apply_cursor()
        self._ring(pos)
        self.moved.emit(int(pos.x()), int(pos.y()))
        if self.drag_start is not None:
            self.drag(self.drag_start, pos)
            return
        if self.tool == "polygon" and self.poly_points:
            self._show_points(self.poly_points, pos)   # 次の角までの線を見せる
        if self.tool == "polyshape" and self.shape_points:
            self._shape_preview(self.constrained(self.shape_points[-1], pos))
        if self.redpen.drawing is not None:
            self.redpen.add(pos)
            return
        if self.last is not None:
            self._brush_move(pos)
            return
        if self.tool == "eyedropper" and e.buttons() & Qt.LeftButton:
            self.pick(pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._rot_from is not None and e.button() == Qt.LeftButton:
            self._rot_from = None
            return
        if self._ruler_drag >= 0 and e.button() == Qt.LeftButton:
            self._ruler_drag = -1
            self.view_changed.emit()
            return
        if self._axis_drag and e.button() == Qt.LeftButton:
            self._axis_drag = False
            self.view_changed.emit()
            return
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
            self.shift = bool(e.modifiers() & Qt.ShiftModifier)
            self.end_drag(self.drag_start, self.mapToScene(e.position().toPoint()))
            self.drag_start = None
            self.stroke_done.emit()
            return
        if self.last is not None:
            self._end_brush(self.mapToScene(e.position().toPoint()))
            self.last = None
            self.pressure = 1.0
            self.stroke_done.emit()
            return
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and self.tool in ("fill", "move", "select", "lasso", "line", "rect", "ellipse", "gradient"):
            self.stroke_done.emit()

    def tabletEvent(self, e):
        # ペンタブレットの筆圧で太さと濃さを変える
        pos = self.mapToScene(e.position().toPoint())
        self.pressure = max(0.05, e.pressure())
        self._ring(pos)
        t = e.type()
        # ペンでも軸の丸をつかめるようにする（マウスと同じ働き）
        if t == e.Type.TabletPress and self.on_axis_handle(e.position().toPoint()):
            self._axis_drag = True
        if self._axis_drag:
            self.set_axis_center(pos)
            if t == e.Type.TabletRelease:
                self._axis_drag = False
                self.view_changed.emit()
            e.accept()
            return
        if t in (e.Type.TabletPress, e.Type.TabletMove, e.Type.TabletRelease):
            self.shift = bool(e.modifiers() & Qt.ShiftModifier)
        if t == e.Type.TabletPress:
            self._press(pos, self.pressure)
        elif t == e.Type.TabletMove and self.redpen.drawing is not None:
            self.redpen.add(pos)
        elif t == e.Type.TabletRelease and self.redpen.drawing is not None:
            short = len(self.redpen.drawing) < 3
            self.redpen.end()
            if short:
                self.redpen.undo()   # マウスと同じく、押しただけは印にしない（前はペンでだけ点の印が残った）
            else:
                self.note_wanted.emit(len(self.redpen.marks))
        elif t == e.Type.TabletMove and self.drag_start is not None:
            self.drag(self.drag_start, pos)
        elif t == e.Type.TabletRelease and self.drag_start is not None:
            self.end_drag(self.drag_start, pos)
            self.drag_start = None
            self.stroke_done.emit()   # 前はペンで引いた直線・図形だけタイムラプスの写しが撮られなかった
        elif t == e.Type.TabletMove and self.last is not None:
            self._brush_move(pos)
        elif t == e.Type.TabletRelease and self.last is not None:
            self._end_brush(pos)
            self.last = None
            self.stroke_done.emit()
        elif t == e.Type.TabletRelease:
            self.stroke_done.emit()   # 塗りつぶしなど、押しただけの道具
        e.accept()

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() == Qt.Key_Space:
            self.hold("hand")
        elif e.key() == Qt.Key_Alt:
            self.hold("eyedropper")
        elif e.key() == Qt.Key_R and not e.modifiers():
            self.rotating, self._rot_used = True, False   # R を押している間、ドラッグで表示を回す
            self.viewport().setCursor(Qt.SizeAllCursor)
        elif e.key() == Qt.Key_BracketRight:
            self.resize_brush(1.25)
        elif e.key() == Qt.Key_BracketLeft:
            self.resize_brush(0.8)
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.poly_points:
            self.finish_polygon()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.shape_points:
            self.finish_shape()
        elif e.key() == Qt.Key_Escape and self.shape_points:
            self.shape_points = []   # 置きかけの多角形の図形をやめる
            self.sel_path_item.setVisible(False)
            self.set_selection(self.selection, self.selection_shape)
        elif e.key() == Qt.Key_Escape and self.poly_points:
            self.poly_points = []   # 置きかけの多角形をやめる（前の選択は残す）
            self.set_selection(self.selection, self.selection_shape)
        elif e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.selection is None:
                # 前は押しても何も起きず、壊れたのか分からなかった。何をすれば消せるかを返す
                self.refused.emit("消す範囲がありません。四角・投げなわ・多角形の選択で範囲を選んでから Delete を押してください")
            else:
                self.clear_selection_area()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() == Qt.Key_R and self.rotating:
            self.rotating, self._rot_from = False, None
            self._apply_cursor()
            if not self._rot_used and self.on_r_tap is not None:
                self.on_r_tap()
        elif e.key() in (Qt.Key_Space, Qt.Key_Alt):
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
