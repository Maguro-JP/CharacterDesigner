"""CharacterDesigner のウィンドウ。チャットで頼むと絵を描いて並べる。

  python chatdraw/app.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chatdraw.paths import HOME as DATA  # noqa: E402


def attach_streams():
    """pythonw.exe で起動すると標準の出力が None になり、模型を取るときの進み表示（tqdm）が書き込めずに落ちた。
    出力が無いときは記録のファイル（DATA/chatdraw.log）へ向ける"""
    for stream in (sys.stdout, sys.stderr):
        # Windows の窓（コンソール）の文字コードは cp1252 などで、日本語を書くと UnicodeEncodeError で落ちた。
        # 書けない文字は置き換えて書き続ける
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if stream is not None and hasattr(stream, "reconfigure") and enc != "utf8":
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        log = open(DATA / "chatdraw.log", "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        import os
        log = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


attach_streams()


def isolate():
    """前の版やほかのアプリが残した環境の設定に引っ張られないようにする。
    Hugging Face の置き場や「取らない」の設定が残っていると、選んだ置き場と違う所を見たり、模型を取れなかったりした"""
    import os
    from chatdraw.paths import HUB
    for k in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
              "HF_DATASETS_OFFLINE", "DIFFUSERS_CACHE"):
        os.environ.pop(k, None)
    os.environ["HF_HUB_CACHE"] = str(HUB)
    # 利用者の Python に入っている物（site-packages）を読まない。版の違う部品が混ざって起動しなかった
    import site
    user = getattr(site, "USER_SITE", None)
    if user:
        import os.path
        mine = os.path.normcase(user)   # Windows は道の大文字小文字を区別しないので、そろえてから比べる
        sys.path[:] = [p for p in sys.path if not os.path.normcase(p).startswith(mine)]


isolate()

# 部品はデータの置き場に入れる（入れたアプリ本体の場所は書き換えない）
for lib in (DATA / "simple" / "lib", DATA / "gen" / "lib", DATA / "llm" / "lib"):
    if lib.exists() and str(lib) not in sys.path:
        sys.path.insert(0, str(lib))

try:
    import PySide6  # noqa: F401
except ImportError:
    # 初めての起動だけ、ウィンドウの部品（PySide6）を入れる。6.12.0 は Python 3.11 で None の参照数を減らしすぎ、
    # 線を数百本引くと落ちた。落ちないことを確かめた 6.9.3 に固定する
    import subprocess
    lib = DATA / "simple" / "lib"
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(lib), "PySide6-Essentials==6.9.3"], check=True,
                   stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sys.path.insert(0, str(lib))

import re  # noqa: E402

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, Signal  # noqa: E402
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QTabWidget, QApplication, QDockWidget, QFileDialog,  # noqa: E402
                               QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QCheckBox, QColorDialog, QComboBox, QFormLayout, QLabel, QProgressBar, QPushButton, QSlider, QSpinBox, QTextEdit, QToolBar, QVBoxLayout, QWidget)

from PIL import Image  # noqa: E402

from chatdraw.activity import ActivityPanel, show_ops  # noqa: E402
from chatdraw import i18n  # noqa: E402
from chatdraw.canvas import Canvas, preload  # noqa: E402
from chatdraw.colorpanel import ColorPanel  # noqa: E402
from chatdraw.icons import icon  # noqa: E402
from chatdraw.engine import Painter, Studio, Words, check  # noqa: E402
from chatdraw.settings import Settings, SettingsDialog  # noqa: E402


class Job(QObject):
    """AI の 1 回分を裏で回す。描く（枚数分）か、直す（regions を渡したとき）"""
    status = Signal(str)
    preview = Signal(object)   # 描いている途中の絵（PIL）
    one = Signal(str, str)     # 1 枚できた（描く言葉、置き場）
    done = Signal()
    failed = Signal(str)

    def __init__(self, studio: Studio, text: str, seeds, base=None, strength: float = 0.6, size=None, style: str = "",
                 regions=None, reference=None, ref_scale: float = 0.6, meta: dict | None = None, check: bool = True):
        super().__init__()
        self.seeds = [seeds] if isinstance(seeds, int) else list(seeds)
        self.studio, self.text, self.style = studio, text, style
        self.base, self.strength, self.size = base, strength, size
        self.regions, self.reference, self.ref_scale, self.meta = regions, reference, ref_scale, meta or {}
        self.check = check
        self.tid = None   # 走っている裏の糸の番号。緊急停止がここへ Stopped を投げ込む
        self._last_preview = 0.0
        fresh_stop(studio)

    PREVIEW_GAP = 0.4   # 途中の絵を画面に渡す間（秒）

    def _preview(self, img):
        """途中の絵は工程ごとに届く。全部を画面の糸に積むと、速い模型では置く処理が溜まって画面とメモリを圧迫したので、間を空けて渡す"""
        now = time.monotonic()
        if now - self._last_preview < self.PREVIEW_GAP:
            return
        self._last_preview = now
        self.preview.emit(img)

    def _say(self, msg: str):
        """工程の知らせ。止める旗が立っていれば、ここで止める（旗を見ない工程の区切りでも止まる）"""
        from chatdraw.engine import check_stop
        check_stop()
        self.status.emit(msg)

    def run(self):
        guarded(self, self._run)

    def _run(self):
        try:
            if self.regions is not None:
                prompts, path = self.studio.fix(self.base, self.regions, self.seeds[0], on_status=self._say,
                                                style=self.style, strength=self.strength, reference=self.reference,
                                                ref_scale=self.ref_scale, check=self.check)
                self._stopped()
                preload(path)
                self.one.emit(" / ".join(prompts), str(path))
            else:
                for seed in self.seeds:
                    extra = dict(reference=self.reference, ref_scale=self.ref_scale) if self.reference is not None else {}
                    # 落ちても止めず、軽い設定・小さい大きさ・別の模型・別の種と段を下げて描く（engine.Studio.draw_anyway）
                    draw = getattr(self.studio, "draw_anyway", None) or self.studio.draw   # 段を下げる形を持たない描き手（試験の偽物など）はそのまま描く
                    prompt, path = draw(self.text, seed, on_status=self._say,
                                                    base=self.base, strength=self.strength, size=self.size,
                                                    on_preview=self._preview, style=self.style, meta=self.meta, **extra)
                    self._stopped()
                    preload(path)   # 置くときに画面の糸で絵を読まないよう、ここ（裏の糸）で先に読む
                    self.one.emit(prompt, str(path))
            self.done.emit()
        except Exception as e:  # 描けなかった理由を、次に何をすればよいか分かる日本語で会話に出す
            from chatdraw.engine import explain
            from chatdraw.engine import Stopped
            self.failed.emit(explain(e))   # 何が起きたかを 1 行で返す（「描けませんでした」の決まり文句は付けない）

    def _stopped(self):
        """止められたあとに返ってきた絵（直しの途中で抜けた物など）は置かずに捨てる。キャンバスは元のまま"""
        from chatdraw.engine import STOP, Stopped
        if STOP.is_set() or getattr(self.studio.painter, "stop", False) is True:
            raise Stopped("止めました")


def fresh_stop(studio=None):
    """裏の 1 回分を始める前に、止める旗を戻す（戻すのはここだけ）"""
    from chatdraw.engine import STOP
    STOP.clear()
    painter = getattr(studio, "painter", None)
    if painter is not None and "stop" in vars(painter):
        painter.stop = False   # 試験の偽の模型など、自分の旗を持つ物


def guarded(obj, body):
    """裏の 1 回分を、1 つずつ・止められる形で走らせる。前の回が止めたあとの後片付け中なら終わるのを待つ。
    緊急停止が投げ込む Stopped は、どこで届いても failed で返す"""
    import threading
    from chatdraw.engine import WORK, Stopped
    try:
        if not WORK.acquire(blocking=False):
            obj.status.emit("前の処理の後片付けを待っています")
            WORK.acquire()
        try:
            obj.tid = threading.get_ident()
            body()
        finally:
            obj.tid = None
            WORK.release()
    except Stopped:
        obj.failed.emit("止めました")
    except BaseException as e:   # noqa: BLE001  落ちても画面に必ず返す
        obj.failed.emit(f"できませんでした: {e}")


class Task(QObject):
    """時間のかかる処理（拡大など）を裏で回す。fn(on_step) の返りを done で返す"""
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.tid = None
        fresh_stop()

    def _step(self, i, n):
        from chatdraw.engine import check_stop
        check_stop()
        self.status.emit(f"描いています（{i}/{n}）")

    def run(self):
        guarded(self, self._run)

    def _run(self):
        try:
            self.done.emit(self.fn(self._step))
        except Exception as e:
            from chatdraw.engine import explain
            self.failed.emit(f"できませんでした: {explain(e)}")


def pid_alive(pid: int) -> bool:
    """その番号のプロセスがまだ動いているか。Windows の os.kill は相手を止めてしまうので使わない"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def crashed_before(store) -> bool:
    """前の起動が正しく閉じずに終わったか。印には起動したプロセスの番号を残す。

    前は印が 0/1 だけで、固まって止められると 1 が残り、正しく 1 回閉じるまで起動のたびに落ちた扱いになった。
    番号が今も動いている（2 つ目の起動）なら落ちた扱いにしない。昔の印の 1 は落ちた扱い
    """
    try:
        prev = int(store.value("running", 0) or 0)
    except (TypeError, ValueError):
        return True
    if prev == 0:
        return False
    return prev == 1 or prev != os.getpid() and not pid_alive(prev)


class Bridge(QObject):
    """裏の糸（threading）から画面へ結果を渡す"""
    got = Signal(object)


def gray_to_pil(img):
    """直す所の形（QImage の灰色）を PIL の L にする"""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_Grayscale8)
    return Image.frombuffer("L", (img.width(), img.height()), bytes(img.constBits()), "raw", "L", img.bytesPerLine(), 1)


def fit_size(w: int, h: int, area: int = 832 * 1216) -> tuple[int, int]:
    """キャンバスと同じ縦横比で、模型の得意な画素数（約 100 万）に合う大きさ。64 の倍数にする。
    決まった大きさで描くと、ラフと縦横比がずれて、重ねたときに下のラフがはみ出した"""
    k = (area / max(1, w * h)) ** 0.5
    return max(64, round(w * k / 64) * 64), max(64, round(h * k / 64) * 64)


def qimage_from_pil(im):
    from PySide6.QtGui import QImage
    im = im.convert("RGBA")
    return QImage(im.tobytes(), im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()


def qimage_to_pil_rgba(img):
    """レイヤー（QImage）を、透明度を保ったまま PIL にする"""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()), "raw", "RGBA",
                            img.bytesPerLine(), 1).copy()


def qimage_to_pil(img):
    """キャンバスの絵（QImage）を描く模型に渡せる形（PIL）にする"""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()), "raw", "RGBA",
                            img.bytesPerLine(), 1).convert("RGB")


class Navigator(QLabel):
    """キャンバス全体の縮小図。今見えている所を四角で示し、押した所を真ん中に出す。四角は引いて動かせる。
    描くたびに作り直すと重いので、絵は変わってから少し待って作る（四角はすぐ描き直す）"""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(120)
        self.setToolTip("赤い四角が今見えている所です。押すか四角を引くと、表示する場所が動きます")
        self._grab = None   # 四角を引いているとき、押した所と四角の中心のずれ
        from PySide6.QtCore import QTimer
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.redraw)
        canvas.changed.connect(self.timer.start)
        canvas.history_changed.connect(self.timer.start)
        canvas.horizontalScrollBar().valueChanged.connect(self.update)
        canvas.verticalScrollBar().valueChanged.connect(self.update)
        canvas.zoomed.connect(self.update)

    def redraw(self):
        if not self.isVisible() or not self.canvas.layers:
            return
        img = self.canvas.flatten().scaled(max(1, self.width() - 8), max(1, self.height() - 8), Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation)
        self.setPixmap(QPixmap.fromImage(img))

    def showEvent(self, e):
        super().showEvent(e)
        self.redraw()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.timer.start()

    def _frame(self):
        """縮小図の置き場（左上と倍率）。絵がまだ無ければ None"""
        pm = self.pixmap()
        w, h = self.canvas.size_px()
        if pm is None or pm.isNull() or not w or not h:
            return None
        return (self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2, pm.width() / w, pm.height() / h

    def view_rect(self):
        """今キャンバスに見えている所を、縮小図の上の四角で返す"""
        from PySide6.QtCore import QRectF
        f = self._frame()
        if f is None:
            return None
        x0, y0, sx, sy = f
        r = self.canvas.mapToScene(self.canvas.viewport().rect()).boundingRect() & self.canvas.scene().sceneRect()
        return QRectF(x0 + r.x() * sx, y0 + r.y() * sy, r.width() * sx, r.height() * sy)

    def paintEvent(self, e):
        super().paintEvent(e)
        r = self.view_rect()
        if r is None or r.isEmpty():
            return
        from PySide6.QtGui import QPainter, QPen, QColor
        p = QPainter(self)
        p.setPen(QPen(QColor(230, 40, 40), 2))
        p.drawRect(r.adjusted(1, 1, -1, -1))
        p.end()

    def _center_at(self, pos):
        f = self._frame()
        if f is None:
            return
        x0, y0, sx, sy = f
        w, h = self.canvas.size_px()
        self.canvas.centerOn(min(max((pos.x() - x0) / sx, 0), w), min(max((pos.y() - y0) / sy, 0), h))
        self.update()

    def mousePressEvent(self, e):
        r = self.view_rect()
        pos = e.position()
        if r is not None and r.contains(pos):
            self._grab = pos - r.center()   # 四角の中を押したら、押した所がずれないように引く
        else:
            self._grab = pos - pos
            self._center_at(pos)

    def mouseMoveEvent(self, e):
        if self._grab is not None and e.buttons() & Qt.LeftButton:
            self._center_at(e.position() - self._grab)

    def mouseReleaseEvent(self, e):
        self._grab = None


class Reference(QLabel):
    """参考画像。押すか画像を落とすと読み込み、欄の大きさに合わせて縮めて見せる"""

    def __init__(self):
        super().__init__("押すか画像をここへ落とすと\n参考画像を置けます")
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("cardMeta")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.image: QPixmap | None = None

    def load(self, path: str):
        pm = QPixmap(path)
        if not pm.isNull():
            self.image = pm
            self.path = path
            self.setToolTip(Path(path).name)
            self._fit()

    def _fit(self):
        if self.image is not None:
            self.setPixmap(self.image.scaled(self.width() - 8, self.height() - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(self, "参考画像", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.load(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.load(urls[0].toLocalFile())


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
        place = QPushButton("⋯")
        place.setToolTip("置き場所（左・右・下・上・別ウィンドウ）")
        place.setFixedSize(22, 20)
        place.setFlat(True)
        place.clicked.connect(lambda: self.place_menu().exec(place.mapToGlobal(place.rect().bottomLeft())))
        row.addWidget(place)
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

    def place_menu(self):
        """欄の置き場所を選ぶメニュー。どの欄も左右・下・上と別ウィンドウに置ける"""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        mw = self.dock.parent()
        for label, area in (("左に置く", Qt.LeftDockWidgetArea), ("右に置く", Qt.RightDockWidgetArea),
                            ("下に置く", Qt.BottomDockWidgetArea), ("上に置く", Qt.TopDockWidgetArea)):
            menu.addAction(label, lambda area=area: mw.move_panel(self.dock, area))
        menu.addSeparator()
        menu.addAction("別ウィンドウにする", lambda: self.dock.setFloating(True))
        return menu

    def toggle(self):
        """畳む・広げる。中身を薄くしてから畳み、広げたら中身を濃くしていく（どこが畳まれたかを目で追える）。
        高さそのものは動かさない。中身の最小の高さより低くできず、動きの途中で止まった"""
        from chatdraw.motion import fade_in, fade_out
        if not self.collapsed and self.dock.isFloating():
            return   # 別ウィンドウは畳まない（見出しだけの細い窓になり、どこにあるか分からなくなった）。窓の最小化を使う
        self.collapsed = not self.collapsed
        body = self.dock.widget()
        head = self.height() + 4
        if self.collapsed:
            def done():
                if not self.collapsed:
                    return   # 畳む途中で広げた
                self.dock.setMinimumHeight(0)   # 欄の最小の高さが中身の分（例: 256）に上がっていて、畳めなかった
                self.dock.setMaximumHeight(head)
            if body is not None:
                fade_out(body, then=done)
            else:
                done()
        else:
            self.dock.setMaximumHeight(16777215)
            self.dock.setMinimumHeight(80)
            if body is not None:
                fade_in(body)
        self.collapse_button.setText("▔" if self.collapsed else "▁")

    def expand(self):
        """畳んでいれば広げる。置き場所を変えた・別ウィンドウにした・タブにした欄が、見出しだけの細い帯のまま
        残ると、同じ所の欄（タブの相手）まで高さを奪われ、欄が消えたように見えた"""
        if self.collapsed:
            self.toggle()

    def float_(self):
        self.dock.setFloating(not self.dock.isFloating())

    def mouseDoubleClickEvent(self, e):
        self.toggle()


# 左端の道具。None は区切り
TOOLS = (("move", "移動", "V"), ("select", "四角の選択", "M"), ("lasso", "投げなわの選択（なぞって囲む）", "L"),
         ("polygon", "多角形の選択（押して角を置き、ダブルクリックか Enter で閉じる）", "Shift+L"), (None, "", ""),
         ("pen", "ペン", "B"), ("eraser", "消しゴム", "E"), ("blur", "ぼかし", "R"),
         ("spray", "スプレー", "K"), ("smudge", "指先（色を伸ばす）", "W"), (None, "", ""),
         ("fill", "塗りつぶし", "G"), ("gradient", "グラデーション", "J"), (None, "", ""),
         ("line", "直線", "N"), ("rect", "四角", "U"), ("ellipse", "楕円", "O"),
         ("polyshape", "多角形", "Shift+U"), ("regpoly", "正多角形", "Shift+O"), ("text", "文字", "Y"), (None, "", ""),
         ("eyedropper", "スポイト", "I"), ("hand", "手のひら", "H"), ("zoom", "拡大（Shift か右クリックで縮小）", "Z"), (None, "", ""),
         ("redpen", "赤ペン（AI に直す所を囲む）", "T"))

# 図形の道具の説明（ツールチップ）。Shift の働きは押してみないと分からないので、ここに書く
SHAPE_TIPS = {
    "line": "直線（N）。押した所から離した所まで引きます。Shift で 15 度ごとの向きにそろえます。定規を出していれば定規に沿います",
    "rect": "四角（U）。ドラッグした範囲に描きます。Shift で正方形にします",
    "ellipse": "楕円（O）。ドラッグした範囲に描きます。Shift で正円にします",
    "polyshape": "多角形（Shift+U）。押すたびに角を置き、ダブルクリックか Enter か始めの角を押すと閉じて描きます。Shift で辺を 15 度ごとの向きにそろえます。Esc でやめます",
    "regpoly": "正多角形（Shift+O）。真ん中から角へドラッグします。辺の数は上の帯で変えます。Shift で向きを 15 度ごとにそろえます",
}

# 欄の帯とメニューに並べる順（よく使う順）
PANEL_ORDER = ("talk", "chat", "view", "history", "library", "progress", "layers", "color", "brushes")

# 欄は動かせて、外に出せて、閉じられる（作画ソフトと同じ）
PANEL = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable


class NoteEdit(QLineEdit):
    """赤ペンの指示を書く欄。キャンバスの上に置くので、打ったキーを欄の外へ逃がさない。
    1 文字のショートカット（B、E、T など）、Space の手のひら、Delete、Ctrl+Z、Tab に文字を取られ、書けなかった"""

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ShortcutOverride:
            if not (e.key() == Qt.Key_Escape and e.modifiers() & Qt.ShiftModifier):   # 非常停止（Shift+Esc）だけは効かせる
                e.accept()   # 受けると、帯やメニューのショートカットより先に、この欄にキーが来る
                return True
        if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            return True   # Tab で欄を離れない
        return super().event(e)

    def keyPressEvent(self, e):
        super().keyPressEvent(e)
        e.accept()   # 欄が使わなかったキーも、親のキャンバス（Space で手のひら、Delete で消す）へ渡さない


class Window(QMainWindow):
    """作画ソフトの並び: 左に頼みの欄、真ん中に絵、右に描いた絵の一覧、下に進み"""

    def __init__(self, studio: Studio | None = None):
        super().__init__()
        from chatdraw import wheelguard
        wheelguard.install()   # 欄のスクロールで種や強さが変わらないようにする
        self.settings = Settings()
        self.layout_store = QSettings("CharacterDesigner", "chatdraw")   # 配置・テーマ・AI プリセット・ツアーの済み
        self.last_text = ""
        self.studio = studio or self._studio_from_settings()
        self.setWindowTitle("CharacterDesigner")
        self.resize(1400, 900)
        self.images: list[str] = []
        self.thread: QThread | None = None
        self.bg_pending = 0   # 裏の糸で回している、画面に答えを返す前の処理の数

        self.canvas = Canvas()
        self.canvas.set_cursor_style(self.settings.get("cursor"))
        self.canvas.new_canvas()
        self.setCentralWidget(self.canvas)
        self.canvas.menu_wanted.connect(self.canvas_menu)
        self.canvas.hide_cursor_after = 1500 if self.settings.get("cursor_hide") == "止まったら隠す" else 0

        # 左: 頼み（チャット）
        # チャットは相談と操作の場、描く内容は AI の欄に書く（1 行の欄に描く頼み・操作・質問が混ざり、会話として読めなかった）
        from chatdraw.chatpanel import ChatPanel, EnterEdit
        self.chat = ChatPanel()
        self.chat.sent.connect(self.chat_send)
        self.chat.open_image = self.open_chat_image
        self.entry = EnterEdit("描きたい絵を書く（例: 赤いマフラーの女の子 全身）", lines=3)
        self.entry.setToolTip("描いてほしい絵を日本語か英語で書き、Enter か「描く」で描きます（Shift+Enter で改行）")
        self.entry.returnPressed.connect(self.send)
        self.button = QPushButton(icon("ai", "#ffffff"), " 描く")
        self.button.setToolTip("AI で描く（Enter）")
        self.button.setObjectName("primary")
        self.button.clicked.connect(self.send)
        self.stop_button = QPushButton("■")
        self.stop_button.setToolTip("止める")
        self.stop_button.setFixedWidth(40)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.entry.setMinimumWidth(120)
        row = QHBoxLayout()
        row.addWidget(self.button, 1)
        row.addWidget(self.stop_button)
        # 描き方: 新しく描くか、キャンバスの絵（下描き・ラフ）を元に描き直すか
        self.mode = QComboBox()
        self.mode.addItems(["新規", "ラフから", "直す"])
        self.mode.setToolTip("新規: 白紙から描く\nラフから: キャンバスの線の形に沿って描く")
        self.size_pick = QComboBox()
        self.size_pick.setToolTip("描く絵の大きさ")
        for label, wh in (("縦 832×1216", (832, 1216)), ("横 1216×832", (1216, 832)), ("正方形 1024", (1024, 1024))):
            self.size_pick.addItem(label, wh)
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(30, 100)
        self.strength.setValue(int(self.settings.get("rough_follow") * 100))
        self.strength_label = QLabel(f"{self.strength.value()}%")
        self.strength.setToolTip("ラフに沿う強さ。大きいほどラフの線の形どおりに描く")
        self.strength.valueChanged.connect(lambda v: self.strength_label.setText(f"{v}%"))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed(0)
        for hidden in (self.mode, self.size_pick):   # 選ぶのは AI の欄のボタン。こちらは値の入れ物
            hidden.setParent(self)
            hidden.hide()
        follow = QHBoxLayout()
        follow.addWidget(self.strength, 1)
        follow.addWidget(self.strength_label)
        # AI の欄は描き方の設定（描き方・大きさ・ラフに沿う強さ・絵の模型）だけ。頼みを書くのはチャットの欄
        from chatdraw.aipanel import AiPanel
        ask = QVBoxLayout()
        ask.setContentsMargins(0, 0, 0, 0)
        self.ai_panel = AiPanel(self)
        ask.addWidget(self.ai_panel)
        follow.setContentsMargins(0, 0, 0, 0)
        self.ai_panel.sections["詳しい設定"].body.addWidget(QLabel("ラフに沿う強さ"))
        self.ai_panel.sections["詳しい設定"].body.addLayout(follow)
        self.model_label = QPushButton()
        self.model_label.setObjectName("modelButton")
        self.model_label.setToolTip("絵の模型。押すと切り替えられます")
        self.model_label.clicked.connect(lambda: self.ai_menu.exec(self.model_label.mapToGlobal(self.model_label.rect().bottomLeft())))
        ask_page = QWidget()
        ask_page.setLayout(ask)
        # 外の入れ物（描き方）は ai_pages。ai_tabs は AI の欄のタブを出し入れする TabDocks が使う
        self.ai_pages = QTabWidget()
        # 中身の縦の流れは AI の欄のタブごとに持つ（描くボタンをタブの外に出し、流しても隠れないようにする）
        ask_scroll = ask_page
        self.ai_pages.addTab(ask_scroll, "描き方")
        self.ai_pages.setTabBarAutoHide(True)   # タブが 1 つのときは見出しだけで足りる
        dock = QDockWidget("AI", self)
        dock.setWidget(self.ai_pages)
        dock.setObjectName("chat")
        dock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # AI の欄の「描く内容」: 頼みを書く欄、模型に渡る言葉の目安、禁止ワード、「描く」と止める、直近の言葉
        tl = self.ai_panel.sections["描く内容"].body
        neg_head = QLabel("禁止ワード")
        neg_head.setObjectName("sectionHead")
        neg_head.setToolTip(self.ai_panel.negative.toolTip())
        self.ai_panel.negative.textChanged.connect(lambda _t: self._apply_avoid())
        self.entry.textChanged.connect(self.ai_panel.preview_timer.start)
        # 模型に渡る言葉の目安は欄に常に出さず、書く欄にカーソルを合わせたときだけ出す。
        # 目安の札（aipanel の preview）は隠した入れ物に入れ、出し入れされても画面には出ない
        self._preview_hold = QWidget(self)
        self._preview_hold.hide()
        self.ai_panel.preview.setParent(self._preview_hold)
        self.last_model_prompt = ""
        self.ai_panel.preview_timer.timeout.connect(self._entry_tip)
        self.ai_panel.update_preview()
        self._entry_tip()
        line = self.ai_panel.draw_bar   # 描くボタンはタブの外。どのタブからも押せる
        # 作成枚数は描くボタンのすぐ左に置く（前は指示のタブの中の模型の下にあり、見つからなかった）。
        # 詳しい設定の 1・2・4 枚のボタンと同じ値
        self.ai_panel.count_spin.setToolTip("作成枚数。一度に描く枚数です（直すときは 1 枚）")
        self.ai_panel.count_spin.setAccessibleName("作成枚数")
        line.addWidget(self.ai_panel.count_spin)
        line.addWidget(self.button, 1)
        line.addWidget(self.stop_button)
        # 書く欄の下のボタン。登録した言葉（★）を先に、そのあとに直近に頼んだ言葉を新しい順に並べる。
        # 押すと書く欄に入り、ダブルクリックでそのまま描く。右クリックで登録・外す・消す。書く欄で ↑↓ でも呼び出せる
        # 音声入力。押して話すと、話した言葉を描くワードの欄に入れる（chatdraw/voice.py。手元の模型 faster-whisper を先に使う）。
        # 使えない環境でもボタンは出し、何を入れれば使えるかをツールチップと押したときの知らせに出す
        from chatdraw import voice
        self.mic_button = voice.mic_button(self.entry, parent=self)
        line.addWidget(self.mic_button)
        self.fav_button = QPushButton("☆")
        self.fav_button.setToolTip("書く欄の言葉を描くワードに登録する（もう一度押すと外す）")
        self.fav_button.setFixedWidth(40)
        self.fav_button.clicked.connect(self._toggle_fav)
        self.entry.textChanged.connect(lambda: self.fav_button.setText(
            "★" if (t := self.entry.text().strip()) and t in self.favorite_prompts() else "☆"))
        line.addWidget(self.fav_button)
        from chatdraw.flowlayout import FlowLayout
        from PySide6.QtWidgets import QSizePolicy
        # 登録・履歴のボタンは欄の横幅で折り返して並べる（横 1 行だと欄からはみ出し、奥のボタンが見えなかった）
        self.tips = FlowLayout()
        tips_box = QWidget()
        tips_box.setLayout(self.tips)
        tips_box.setObjectName("scrollInner")
        self.tips_scroll = tips_box
        self.entry.installEventFilter(self)
        self._load_prompts()
        # 単語のお気に入りの段（描くワードの登録の中、文のまとまりの下）と、読めなかった語の段（chatdraw/wordpanel.py）
        from chatdraw import wordpanel
        self.word_row = wordpanel.WordRow(self.entry, on_change=self._words_changed)
        self.lost_row = wordpanel.LostRow(self.entry, on_change=self._words_changed)
        self.entry.setContextMenuPolicy(Qt.CustomContextMenu)
        self.entry.customContextMenuRequested.connect(
            lambda pos: wordpanel.entry_menu(self.entry, self._words_changed).exec(self.entry.mapToGlobal(pos)))
        # 禁止ワードの登録。描くワードの登録と同じく、押すと禁止ワードの欄に入る。設定に残すので更新でも消えない
        self.neg_fav_button = QPushButton("☆")
        self.neg_fav_button.setFixedWidth(40)
        self.neg_fav_button.setToolTip("禁止ワードの欄の言葉を登録する（もう一度押すと外す）")
        self.neg_fav_button.clicked.connect(self._toggle_neg_fav)
        self.ai_panel.negative.textChanged.connect(lambda _t: self.neg_fav_button.setText(
            "★" if (t := self.ai_panel.negative.text().strip()) and t in self.negative_presets() else "☆"))
        self.neg_tips = FlowLayout()
        neg_box = QWidget()
        neg_box.setLayout(self.neg_tips)
        neg_box.setObjectName("scrollInner")
        self.neg_tips_box = neg_box
        self._load_negatives()
        # 指示のタブの並び: 模型、描くワード、描くワードの登録、禁止ワード、禁止ワードの登録
        model_head = QLabel("模型")
        model_head.setObjectName("sectionHead")
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.addWidget(self.model_label)
        word_head = QLabel("描くワード")
        word_head.setObjectName("sectionHead")
        word_head.setToolTip("描きたい絵を言葉で書きます。下のボタンは登録した言葉と、前に頼んだ言葉です")
        neg_row = QHBoxLayout()
        neg_row.setContentsMargins(0, 0, 0, 0)
        neg_row.addWidget(self.ai_panel.negative, 1)
        neg_row.addWidget(self.neg_fav_button)
        for wdg in (model_head, word_head, neg_head, self.ai_panel.negative):
            wdg.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        tl.addWidget(model_head)
        tl.addLayout(model_row)
        self._lora_row()
        tl.addWidget(word_head)
        tl.addWidget(self.entry)
        tl.addWidget(self.lost_row)
        tl.addWidget(tips_box)
        tl.addWidget(self.word_row)
        tl.addWidget(neg_head)
        tl.addLayout(neg_row)
        tl.addWidget(neg_box)
        # 真ん中の下: チャット。吹き出しの会話と、複数行の書く欄
        talk = QDockWidget("チャット", self)
        talk.setWidget(self.chat)
        talk.setObjectName("talk")
        talk.setFeatures(PANEL)
        self.addDockWidget(Qt.BottomDockWidgetArea, talk)

        # 右: 描いた絵。AI の今の工程・進み・時間と、描いた絵の履歴
        self.activity = ActivityPanel()
        self.history = self.activity.list
        # ダブルクリックは今の絵に重ねる（今の絵を閉じない）。右クリックで開く・同じ設定で描き直す
        # 押すとその絵をキャンバスに出す（元に戻すで戻せる）。ダブルクリックは今の絵に重ねる
        self.history.itemClicked.connect(lambda it: it.data(Qt.UserRole) and self.show_history_image(it.data(Qt.UserRole)))
        # ダブルクリックはその絵を見せるだけ（レイヤーに足すと勝手に増えた）。重ねるのは右クリックの「今の絵に重ねる」
        self.history.itemDoubleClicked.connect(lambda it: it.data(Qt.UserRole) and self.show_history_image(it.data(Qt.UserRole)))
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._history_menu)
        # 履歴で選んだ絵を Delete キーで消す（確かめてからごみ箱へ）。キャンバスの Delete（選んだ所を消す）とぶつからないよう履歴の中だけで効かせる
        hist_del = QAction("消す（ごみ箱へ）", self.history, shortcut="Delete", shortcutContext=Qt.WidgetWithChildrenShortcut)
        hist_del.triggered.connect(lambda: self.delete_images([it.data(Qt.UserRole) for it in self.history.selectedItems()]))
        self.history.addAction(hist_del)
        hist = QDockWidget("履歴", self)
        hist.setWidget(self.activity)
        hist.setObjectName("history")
        hist.setFeatures(PANEL)
        self.addDockWidget(Qt.RightDockWidgetArea, hist)
        # 真ん中の上: 進み（工程・帯・時間）
        prog = QDockWidget("進み", self)
        prog.setWidget(self.activity.progress_view)
        self.activity.changed.connect(self.show_progress)
        prog.setObjectName("progress")
        prog.setFeatures(PANEL)
        self.addDockWidget(Qt.TopDockWidgetArea, prog)
        # 緊急停止。いつでも見える所（上の帯と進みの欄）に置き、押したら必ず止める。帯は閉じられない（隠すと止められなくなる）
        self.emergency_stop = QAction("■ 緊急停止", self)
        self.emergency_stop.setObjectName("emergencyStop")
        self.emergency_stop.setShortcut("Shift+Esc")
        self.emergency_stop.setShortcutContext(Qt.ApplicationShortcut)
        self.emergency_stop.setToolTip("動いている AI の処理を今すぐ止めます（Shift+Esc）。キャンバスは元のままです")
        self.emergency_stop.triggered.connect(self.stop)
        sbar = QToolBar("緊急停止", self)
        sbar.setObjectName("stopbar")
        sbar.addAction(self.emergency_stop)
        sbar.toggleViewAction().setEnabled(False)
        self.addToolBar(Qt.TopToolBarArea, sbar)
        self.stop_bar = sbar
        self.activity.stop_tool.setDefaultAction(self.emergency_stop)

        # 下: 進み
        self.progress = self.activity.bar   # 進みは描いた絵の欄に出す


        # 上: メニュー。メニュー・リボン・帯・欄の右クリックで同じ働きの物は、同じ QAction を使う
        # （別々に作ると、片方だけキーや働きが変わり、名前が同じで違う動きになった。リボンの「保存」は PNG の書き出しだった）
        self.build_shared_actions()
        S = self.shared
        file = self.menuBar().addMenu("ファイル")
        file.addAction(S["new"])
        file.addAction(S["open"])
        edit_open = QAction("画像を開いて直す…", self, triggered=self.open_to_edit)
        edit_open.setToolTip("手元の絵を開き、赤ペンで囲んだ所だけを AI に直させます。囲みの外は変えません")
        file.addAction(edit_open)
        file.addAction(S["save"])
        file.addAction(QAction("名前を付けて保存…", self, shortcut="Ctrl+Shift+S", triggered=lambda: self.save_project(ask=True)))
        out = file.addMenu("書き出す")
        out.addAction(QAction("PNG（重ねた 1 枚）…", self, shortcut="Ctrl+E", triggered=self.save_as))
        out.addAction(QAction("PSD（レイヤーごと）…", self, triggered=self.export_psd))
        # 置き場はボタンを並べず、1 つの下の段にまとめる（開くたびに作り直し、保存先を変えたらすぐ合うようにする）
        from chatdraw import folders
        self.folder_menu = file.addMenu("ディレクトリを開く")
        self.folder_menu.aboutToShow.connect(lambda: folders.fill_menu(self.folder_menu, self.settings, self))
        folders.fill_menu(self.folder_menu, self.settings, self)
        file.addSeparator()
        file.addAction(S["trash"])
        file.addSeparator()
        file.addAction(QAction("終了", self, shortcut="Ctrl+Q", triggered=self.close))
        edit = self.menuBar().addMenu("編集")
        edit.setToolTipsVisible(True)
        edit.addAction(S["undo"])
        edit.addAction(S["redo"])
        edit.addAction(S["redpen_clear"])
        edit.addAction(S["inspect"])
        edit.addSeparator()
        edit.addAction(S["cut"])
        edit.addAction(S["copy"])
        edit.addAction(S["copy_merged"])
        edit.addAction(S["paste"])
        edit.addAction(S["paste_in_place"])
        edit.addSeparator()
        edit.addAction(S["layer_cut"])
        edit.addAction(S["layer_copy"])
        edit.addAction(S["layer_paste"])

        # 左端: 道具
        tools = QToolBar("道具", self)
        tools.setObjectName("tools")
        tools.setIconSize(QSize(22, 22))
        tools.setMovable(True)
        self.addToolBar(Qt.LeftToolBarArea, tools)
        group = QActionGroup(self)
        self.tool_actions = {}
        # 作画ソフトでよく使う並びと同じキー（V 移動、M 選択、B ペン、E 消しゴム、G 塗り、I スポイト、H 手のひら、Z 拡大）
        for key, label, short in TOOLS:
            if key is None:
                tools.addSeparator()
                continue
            act = QAction(icon(key), label, self, checkable=True, shortcut=short,
                          triggered=lambda _=False, k=key: self.canvas.set_tool(k))
            act.setToolTip(f"{label}（{short}）")
            group.addAction(act)
            tools.addAction(act)
            self.tool_actions[key] = act
        self.tool_actions["pen"].setChecked(True)
        for k, tip in SHAPE_TIPS.items():
            self.tool_actions[k].setToolTip(tip)
        # 絵の上の R は、押して離すとぼかし、押したままドラッグすると表示を回す（canvas.on_r_tap）
        self.canvas.on_r_tap = self.tool_actions["blur"].trigger
        self.tool_actions["blur"].setToolTip("ぼかし（R）。絵の上で R を押したままドラッグすると表示を回します")
        self.extra_key_actions = []
        for text, short, fn in (("描く色と背景の色を入れ替える", "X", self.canvas.swap_colors),
                                ("色を黒と白に戻す", "D", self.canvas.reset_colors)):
            act = QAction(text, self, shortcut=short, triggered=fn)
            self.addAction(act)
            self.extra_key_actions.append(act)

        # 上: 選んだ道具の設定（太さ・濃さ・形の塗り）。作画ソフトと同じく、絵のすぐ上に置いて手元で変える
        bar = QToolBar("道具の設定", self)
        bar.setObjectName("options")
        bar.setMovable(True)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.options = bar
        self.tool_name = QLabel("ペン")
        self.tool_name.setObjectName("toolName")
        bar.addWidget(self.tool_name)
        bar.addSeparator()
        bar.addWidget(QLabel(" 太さ "))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(1, 300)
        self.size_slider.setFixedWidth(160)
        self.size_slider.setValue(self.canvas.size)
        bar.addWidget(self.size_slider)
        self.size_box = QSpinBox()
        self.size_box.setRange(1, 300)
        self.size_box.setValue(self.canvas.size)
        self.size_box.setSuffix(" px")
        bar.addWidget(self.size_box)
        self.size_box.valueChanged.connect(lambda v: (setattr(self.canvas, "size", v), self.size_slider.setValue(v)))
        self.size_slider.valueChanged.connect(self.size_box.setValue)
        bar.addSeparator()
        bar.addWidget(QLabel(" 濃さ "))
        self.flow = QSlider(Qt.Horizontal)
        self.flow.setRange(1, 100)
        self.flow.setValue(100)
        self.flow.setFixedWidth(120)
        self.flow_label = QLabel("100%")
        self.flow.valueChanged.connect(lambda v: (setattr(self.canvas, "brush_opacity", v / 100), self.flow_label.setText(f"{v}%")))
        bar.addWidget(self.flow)
        bar.addWidget(self.flow_label)
        bar.addSeparator()
        self.fill_shapes = QCheckBox("塗り")
        self.fill_shapes.setToolTip("四角・楕円・多角形・正多角形を、線だけでなく中まで塗る")
        self.fill_shapes.toggled.connect(lambda on: setattr(self.canvas, "fill_shapes", on))
        # 帯に置いた部品は、部品ではなく帯の項目を隠さないと消えない（前は「塗り」がペンでも出たままだった）
        self.fill_shapes_act = bar.addWidget(self.fill_shapes)
        self.poly_sides = QSpinBox()
        self.poly_sides.setRange(3, 24)
        self.poly_sides.setValue(self.canvas.poly_sides)
        self.poly_sides.setSuffix(" 角")
        self.poly_sides.setToolTip("正多角形の角（辺）の数")
        self.poly_sides.valueChanged.connect(lambda v: setattr(self.canvas, "poly_sides", v))
        self.poly_sides_act = bar.addWidget(self.poly_sides)
        for key, _label, _s in TOOLS:
            if key:
                self.tool_actions[key].triggered.connect(lambda _=False, k=key: self._tool_changed(k))
                self.tool_actions[key].triggered.connect(lambda _=False, k=key: self.feature_tour(k))
        self._tool_changed("pen")

        # 左上: 色（色相・彩度と明度・16 進・描く色と背景色・見本・最近使った色）
        self.color_panel = ColorPanel(self.canvas)
        self.canvas.used_color.connect(self.color_panel.remember)
        self.color_panel.eyedropper_wanted.connect(lambda: self.tool_actions["eyedropper"].trigger())
        self.canvas.text_wanted.connect(self.ask_text)
        odock = QDockWidget("カラー", self)
        odock.setObjectName("color")
        odock.setWidget(self.color_panel)
        odock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, odock)

        # 左上: ブラシ。種類を選び、硬さ・流量・間隔・筆圧の効き方を変える
        self.brush_list = QListWidget()
        for b in self.canvas.brushes.values():
            self.brush_list.addItem(b.name)
        self.brush_list.currentTextChanged.connect(self._brush_selected)
        self.hardness = QSlider(Qt.Horizontal)
        self.hardness.setRange(0, 100)
        self.flow_s = QSlider(Qt.Horizontal)
        self.flow_s.setRange(1, 100)
        self.spacing = QSlider(Qt.Horizontal)
        self.spacing.setRange(2, 100)
        self.size_pressure = QCheckBox("筆圧→太さ")
        self.opacity_pressure = QCheckBox("筆圧→濃さ")
        self.size_pressure.setToolTip("ペンタブレットの筆圧で線の太さを変える")
        self.opacity_pressure.setToolTip("ペンタブレットの筆圧で線の濃さを変える")
        self.hardness.valueChanged.connect(lambda v: setattr(self.canvas.brush, "hardness", v / 100))
        self.flow_s.valueChanged.connect(lambda v: setattr(self.canvas.brush, "flow", v / 100))
        self.spacing.valueChanged.connect(lambda v: setattr(self.canvas.brush, "spacing", v / 100))
        self.size_pressure.toggled.connect(lambda on: setattr(self.canvas.brush, "size_pressure", on))
        self.opacity_pressure.toggled.connect(lambda on: setattr(self.canvas.brush, "opacity_pressure", on))
        bform = QFormLayout()
        self.hardness.setToolTip("縁のくっきりさ")
        self.flow_s.setToolTip("1 回に置く絵の具の量")
        self.spacing.setToolTip("筆の跡の間隔")
        bform.addRow("硬さ", self.hardness)
        bform.addRow("流量", self.flow_s)
        bform.addRow("間隔", self.spacing)
        bform.addRow(self.size_pressure)
        bform.addRow(self.opacity_pressure)
        # 手ぶれ補正と左右対称は、ペン・消しゴム・ぼかし・スプレー・指先のなぞる道具すべてに効く
        self.stabilizer = QSpinBox()
        from chatdraw.canvas import STABILIZER_MAX
        self.stabilizer.setRange(0, STABILIZER_MAX)
        self.stabilizer.setSingleStep(5)
        self.stabilizer.setToolTip(f"手ぶれ補正の強さ（0〜{STABILIZER_MAX}）。大きいほど線がカーソルに遅れてついてきて、なめらかになる（0 で切る）")
        self.stabilizer.valueChanged.connect(lambda v: setattr(self.canvas, "stabilizer", v))
        bform.addRow("手ぶれ補正", self.stabilizer)
        # 対称: 線対称（左右・上下・上下左右）と点対称。表示のメニューの「対称定規」と同じ設定
        from chatdraw.canvas import SYMMETRY
        self.symmetry = QComboBox()
        self.symmetry.addItem("なし", "")
        for key, label in SYMMETRY.items():
            self.symmetry.addItem(label, key)
        self.symmetry.setToolTip("描いた線と図形を、軸の反対側にも同時に描きます。軸の丸をドラッグすると軸を動かせます")
        self.symmetry.currentIndexChanged.connect(lambda _i: self.canvas.set_symmetry(self.symmetry.currentData()))
        bform.addRow("対称", self.symmetry)
        # 定規: なぞる線と直線を、平行線・同心円・放射・パースの向きに沿わせる。表示のメニューの「定規」と同じ設定
        from chatdraw.assist import RULERS
        self.ruler = QComboBox()
        self.ruler.addItem("なし", "")
        for key, label in RULERS.items():
            self.ruler.addItem(label, key)
        self.ruler.setToolTip("なぞる線と直線を定規に沿わせます。緑の丸をドラッグすると、中心・消失点・平行線の向きを動かせます")
        self.ruler.currentIndexChanged.connect(lambda _i: self.canvas.set_ruler(self.ruler.currentData()))
        bform.addRow("定規", self.ruler)
        self.quickshape = QCheckBox("描いて止めると形を整える")
        self.quickshape.setToolTip("ペンで描き終えて少し止めると、直線・円・楕円・四角・三角に整えます。元に戻すで整える前の線に戻ります")
        self.quickshape.toggled.connect(lambda on: setattr(self.canvas, "quickshape", on))
        bform.addRow(self.quickshape)
        bbox = QWidget()
        bbox.setLayout(bform)
        # タブで「ブラシ」（種類を選ぶ）と「設定」（硬さ・流量・間隔・筆圧）を切り替える
        self.brush_tabs = QTabWidget()
        self.brush_tabs.addTab(self.brush_list, "ブラシ")
        self.brush_tabs.addTab(bbox, "設定")
        # 見本の線。ブラシ・太さ・色・濃さ・硬さ・間隔・筆圧・色の出方を変えるたびに描き直す
        from chatdraw.brushpreview import BrushPreview
        self.brush_preview = BrushPreview(self.canvas)
        for sig in (self.size_box.valueChanged, self.flow.valueChanged, self.hardness.valueChanged, self.flow_s.valueChanged,
                    self.spacing.valueChanged, self.size_pressure.toggled, self.opacity_pressure.toggled,
                    self.color_panel.color_changed, self.canvas.color_picked, self.brush_list.currentTextChanged,
                    self.canvas.brush_changed, self.color_panel.mode_changed):
            sig.connect(lambda *_a: self.brush_preview.update())
        bwrap = QWidget()
        bl = QVBoxLayout(bwrap)
        bl.setContentsMargins(6, 4, 6, 4)
        bl.setSpacing(4)
        bl.addWidget(self.brush_preview)
        bl.addWidget(self.brush_tabs, 1)
        bdock = QDockWidget("ブラシ", self)
        bdock.setObjectName("brushes")
        bdock.setWidget(bwrap)
        bdock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, bdock)
        self.brush_list.setCurrentRow(0)
        self.canvas.brush_changed.connect(self.size_box.setValue)
        self.build_status()

        # 右下: レイヤー（縮小図・表示・ロック・名前・並べ替え。chatdraw/layerpanel.py）
        from chatdraw.layerpanel import LayerPanel
        self.layer_panel = LayerPanel(self.canvas)
        self.layer_panel.shared = self.shared   # 右クリックにメニューと同じ操作（同じキー）を出す
        self.layer_list, self.layer_opacity = self.layer_panel.list, self.layer_panel.opacity
        self.canvas.refused.connect(lambda why: self.statusBar().showMessage(why, 6000))
        lbox = self.layer_panel
        self.navigator = Navigator(self.canvas)
        self.layer_tabs = QTabWidget()
        self.layer_tabs.addTab(lbox, "レイヤー")
        self.layer_tabs.setTabBarAutoHide(True)
        # 右の上: 表示（全体の縮小図と参考画像）
        self.reference = Reference()
        self.view_tabs = QTabWidget()
        self.view_tabs.addTab(self.navigator, "全体")
        self.view_tabs.addTab(self.reference, "参考画像")
        vdock = QDockWidget("表示", self)
        vdock.setWidget(self.view_tabs)
        vdock.setObjectName("view")
        vdock.setFeatures(PANEL)
        self.addDockWidget(Qt.RightDockWidgetArea, vdock)
        self.view_dock = vdock
        ldock = QDockWidget("レイヤー", self)
        ldock.setWidget(self.layer_tabs)
        ldock.setObjectName("layers")
        ldock.setFeatures(PANEL)
        self.addDockWidget(Qt.RightDockWidgetArea, ldock)
        self.canvas.marked.connect(lambda: self.mode.setCurrentIndex(2))
        self.canvas.redpen.on_change = self._redpen_changed   # 赤ペンで囲んだら、AI の欄を「直す」にする
        self.canvas.note_wanted.connect(self.edit_note)
        # 自動保存: 変わってから 2 分ごとに書く
        self.dirty = False
        self.canvas.history_changed.connect(lambda: setattr(self, "dirty", True))
        from PySide6.QtCore import QTimer
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(120_000)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()
        # 裏の糸が動いている間は、Python の後片付け（gc）を画面の糸だけで回す（gc_guard）
        self.gc_timer = QTimer(self)
        self.gc_timer.setInterval(500)
        self.gc_timer.timeout.connect(self.gc_guard)
        self.gc_timer.start()
        # 操作の履歴（履歴の欄の「操作」のタブ）
        self.canvas.history_changed.connect(lambda: show_ops(self.activity.ops, self.canvas))
        self.activity.ops.currentRowChanged.connect(lambda r: r >= 0 and self.canvas.go_to(r))
        show_ops(self.activity.ops, self.canvas)

        view = self.menuBar().addMenu("表示")
        view.setToolTipsVisible(True)
        for k in ("fit", "actual", "zoom_in", "zoom_out", "zoom_ask", None, "rotate_left", "rotate_right", "rotate_dial",
                  "rotate_reset", "flip_view", "view_reset", None, "grid", "op_history"):
            view.addAction(S[k]) if k else view.addSeparator()
        self.build_symmetry_menu(view.addMenu("対称定規"))
        self.build_ruler_menu(view.addMenu("定規"))
        # 図形の道具。おすすめの配置の道具の帯には出さない（初めはシンプルにする）ので、メニューからも選べるようにする
        shapes = view.addMenu("図形")
        shapes.setToolTipsVisible(True)
        for k in ("line", "rect", "ellipse", "polyshape", "regpoly"):
            shapes.addAction(self.tool_actions[k])
        view.addSeparator()
        from chatdraw.timelapse import Recorder
        self.recorder = Recorder()
        self.recorder.enabled = self.settings.get("timelapse") == "記録する"
        self.canvas.stroke_done.connect(self._record)
        self.tl_action = QAction("タイムラプスを記録する", self, checkable=True, checked=self.recorder.enabled)
        self.tl_action.setToolTip("線を引くたび、AI が描く工程ごとに写しを撮り、描いた過程を残します")
        self.tl_action.toggled.connect(self._set_timelapse)
        # タイムラプスの 4 つは 1 つの小さなメニューにまとめる（表示のメニューが長く、絵の見え方の項目が埋もれた）
        tl = view.addMenu("タイムラプス")
        tl.setToolTipsVisible(True)
        tl.addAction(self.tl_action)
        tl.addAction(QAction("タイムラプスを見る…", self, shortcut="Ctrl+Shift+T", triggered=self.open_timelapse))
        tl.addAction(QAction("タイムラプスを消す", self, triggered=self.recorder.clear))
        tl.addAction(QAction("GIF・動画を開く…", self, triggered=self.open_player))
        view.addSeparator()
        self.pin_action = QAction("表示する絵を固定する", self, checkable=True)
        self.pin_action.setToolTip("固定すると、AI が新しく描いた絵はキャンバスに出さず履歴に入れます。外すと最新の絵を出します")
        self.pin_action.toggled.connect(self._set_pinned)
        view.addAction(self.pin_action)
        from chatdraw import themes
        self.theme_menu = view.addMenu("テーマ")
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        from PySide6.QtWidgets import QMenu
        self.ai_menu = QMenu("AI", self)   # 窓を親にして作る（文字だけで足すと、作り直しの知らせの前に消えていた）
        self.menuBar().addMenu(self.ai_menu)
        # 開くたびに手元の模型を数え直してから作る。開いている間に変わった分は、閉じたあとに作り直す
        self.ai_menu.aboutToShow.connect(self._open_ai_menu)
        self.ai_menu.aboutToHide.connect(self._ai_menu_hidden)
        self._have_images: set[str] | None = None   # 手元にある絵の模型。裏の糸で数え、メニューを開くたびには数えない
        self._fill_ai_menu()
        self.rescan_models()
        self.chara_menu = QMenu("キャラクターデザイン", self)
        self.menuBar().addMenu(self.chara_menu)
        self.chara_menu.aboutToShow.connect(self._fill_chara_menu)
        self._fill_chara_menu()
        self.logo_menu = QMenu("ロゴ・スタンプ", self)   # キャラクターとは別の物（ロゴ・マーク、スタンプ）を作る。chatdraw/logo.py
        self.menuBar().addMenu(self.logo_menu)
        self.logo_menu.aboutToShow.connect(self._fill_logo_menu)
        self._fill_logo_menu()
        from chatdraw import ratings
        ratings.on_change(self._models_changed)
        setting_menu = self.menuBar().addMenu("設定")
        setting_menu.addAction(QAction("設定…", self, shortcut="Ctrl+,", triggered=self.open_settings))
        setting_menu.addAction(QAction("キーの設定…", self, triggered=self.open_keys))
        setting_menu.addAction(QAction("作風の登録…", self, triggered=self.open_favorites,
                                       toolTip="好きな作家・作品の言葉を名前で残し、描くときに足します"))
        setting_menu.addAction(QAction("参考画像を探す…", self, triggered=self.ask_reference_search))
        setting_menu.addAction(QAction("単語辞書…", self, triggered=self.open_word_dict,
                                       toolTip="頼みの語がどのタグになったか、描いて使えた語と訳、学びの様子を見ます"))
        setting_menu.addAction(QAction("予約の一覧", self, triggered=lambda: self.say(self.scheduler.summary())))
        setting_menu.addAction(QAction("確かめの窓をまた出す", self, triggered=self.reset_confirms,
                                       toolTip="「次から聞かない」を選んだ確かめの窓を、また出すようにします"))
        setting_menu.addAction(QAction("予約を全部消す", self, triggered=lambda: (self.scheduler.clear(), self.say("予約を全部消しました"))))
        sel = self.menuBar().addMenu("選択範囲")
        sel.addAction(S["select_all"])
        sel.addAction(S["deselect"])
        sel.addSeparator()
        sel.addAction(self.tool_actions["select"])
        sel.addAction(self.tool_actions["lasso"])
        sel.addAction(self.tool_actions["polygon"])
        sel.addSeparator()
        sel.addAction(S["sel_clear"])
        sel.addAction(S["sel_fill"])
        sel.addAction(S["copy"])
        sel.addAction(S["cut"])
        sel.addAction(QAction("選択範囲を AI で直す", self, triggered=self.fix_marked,
                              toolTip="選択範囲の中だけを、指示の欄の言葉で AI が直します"))
        layer_menu = self.menuBar().addMenu("レイヤー")
        layer_menu.setToolTipsVisible(True)
        layer_menu.addAction(S["add_layer"])
        layer_menu.addAction(S["dup_layer"])
        layer_menu.addAction(S["delete_layer"])
        layer_menu.addAction(S["clear_layer"])
        layer_menu.addSeparator()
        for k in ("layer_cut", "layer_copy", "layer_paste", "via_copy", "via_cut"):
            layer_menu.addAction(S[k])
        layer_menu.addSeparator()
        layer_menu.addAction(S["flip_layer_h"])
        layer_menu.addAction(S["flip_layer_v"])
        layer_menu.addSeparator()
        layer_menu.addAction(QAction("画像をレイヤーとして読み込む…", self, triggered=self.import_layer))
        layer_menu.addAction(QAction("レイヤーを PNG で保存…", self, triggered=self.save_layer_png))
        layer_menu.addAction(QAction("全部のレイヤーを PNG で書き出す…", self, triggered=self.export_layers_png))
        layer_menu.addSeparator()
        layer_menu.addAction(S["merge_down"])
        layer_menu.addAction(QAction("見えているレイヤーを結合", self, shortcut="Ctrl+Shift+E", triggered=self.canvas.merge_visible))
        layer_menu.addAction(QAction("結合して元の画像に上書き保存…", self, triggered=self.merge_and_overwrite))

        # ウィンドウ: 欄ごとの表示と、並べ方（整列・別ウィンドウ・自由配置）
        # ライブラリー: 作品・資料・好み。試験（描く仕組みを渡したとき）は、その出力の置き場の中に作って本物を汚さない
        from chatdraw.library import Library
        from chatdraw.librarypanel import LibraryPanel
        self.library = Library(None if studio is None else Path(self.studio.out) / ".library")
        from chatdraw.paths import HOME
        from chatdraw.trash import Trash
        self.trash = Trash(HOME / "trash" if studio is None else Path(self.studio.out) / ".trash")
        self.library_panel = LibraryPanel(self)
        # チャットの会話は閉じても残す（ライブラリーと同じく、試験では出力の置き場の中に作る）
        self.chat.decorate = self.offer_prompt
        self.chat.set_store((DATA if studio is None else Path(self.studio.out)) / "chat.json")
        libdock = QDockWidget("ライブラリー", self)
        libdock.setWidget(self.library_panel)
        libdock.setObjectName("library")
        libdock.setFeatures(PANEL)
        self.addDockWidget(Qt.RightDockWidgetArea, libdock)
        self.panels = {"color": (odock, Qt.LeftDockWidgetArea), "brushes": (bdock, Qt.LeftDockWidgetArea),
                       "library": (libdock, Qt.RightDockWidgetArea),
                       "chat": (dock, Qt.RightDockWidgetArea),
                       "history": (hist, Qt.RightDockWidgetArea), "layers": (ldock, Qt.LeftDockWidgetArea),
                       "view": (self.view_dock, Qt.RightDockWidgetArea), "talk": (talk, Qt.BottomDockWidgetArea),
                       "progress": (prog, Qt.TopDockWidgetArea)}
        from PySide6.QtWidgets import QScrollArea
        for key in self.panels:
            # 中身が欄より大きいときは欄の中で流す。中身の大きさで欄が縮まず、ウィンドウが画面（ノートの高さ 720 など）からはみ出した
            d = self.panels[key][0]
            inner = d.widget()
            box = QScrollArea()
            box.setWidget(inner)
            box.setWidgetResizable(True)
            box.setFrameShape(QScrollArea.NoFrame)
            # 縦も横も、収まらないときだけ流す棒を出す
            box.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            box.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            box.setMinimumSize(0, 0)
            inner.setObjectName(inner.objectName() or "scrollInner")
            d.setWidget(box)
        for key, (d, _area) in self.panels.items():
            d.setTitleBarWidget(PanelTitle(d))
            # 欄の中で、自分のメニューを持たない所を右クリックしても、使えるメニューを出す（押しても何も出ない所を作らない）
            d.setContextMenuPolicy(Qt.CustomContextMenu)
            d.customContextMenuRequested.connect(lambda pos, d=d, k=key: self.area_menu(k).exec(d.mapToGlobal(pos)))
            # 欄の境目をドラッグして上下左右に広げ縮めできる。狭めすぎて中身が潰れない大きさだけ決める
            d.setMinimumSize(160, 80)
            d.topLevelChanged.connect(lambda floating, d=d: self._as_window(d, floating))
            d.dockLocationChanged.connect(lambda _area, d=d: d.titleBarWidget().expand())
            d.visibilityChanged.connect(lambda on, d=d: self._appear(d, on))
        self.tools = tools
        self.setDockNestingEnabled(True)
        # GroupedDragging: タブにまとめた欄を、まとめたまま動かせる（1 枚ずつはタブを引いて外へ出す）
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AnimatedDocks
                            | QMainWindow.GroupedDragging)
        # 欄どうしを重ねるとタブになる（欄の見出しを別の欄の上へドラッグ）。タブは上に出す
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        self.tabifiedDockWidgetActivated.connect(lambda d: isinstance(d.titleBarWidget(), PanelTitle) and d.titleBarWidget().expand())
        # 欄の帯: 欄ごとのアイコン。押すと欄を出す・隠す。初めは右の端に置き、上下左右のどこへでも動かせる
        bar = QToolBar("欄の帯", self)
        bar.setObjectName("panelbar")
        bar.setIconSize(QSize(22, 22))
        self.addToolBar(Qt.RightToolBarArea, bar)
        self.panel_bar = bar
        from chatdraw.popup import ProgressPopup
        self.progress_popup = ProgressPopup(self)   # 進みは右下のポップアップに出す（上の欄は「ウィンドウ」から出せる）
        win = self.menuBar().addMenu("ウィンドウ")
        keys = {"brushes": "F3", "color": "F5", "chat": "F6", "history": "F7", "layers": "F8", "view": "F9", "talk": "F10",
                "progress": "F11", "library": "F12"}
        icons = {"color": "palette", "brushes": "brush", "chat": "ai", "history": "history", "layers": "layers", "view": "view",
                 "talk": "chat", "progress": "progress", "library": "library"}
        self.panel_actions = {}
        for k in PANEL_ORDER:
            d = self.panels[k][0]
            # Qt の toggleViewAction は、タブの裏に隠れた欄も「出ている」と数え、押すと隠した。
            # ライブラリーは履歴・表示とタブで重なっているので、F12 や欄の帯で押しても前に出ず、開けなくなっていた。
            # 裏に隠れている欄は前に出し、前に出ている欄だけを隠す
            act = QAction(d.windowTitle(), self, checkable=True)   # チェックが付いていれば表示中
            act.setChecked(not d.isHidden())
            act.setShortcut(keys[k])
            act.setIcon(icon(icons[k]))
            act.setToolTip(f"{d.windowTitle()}（{keys[k]}）")
            act.triggered.connect(lambda _on, k=k: self.toggle_panel(k))
            d.visibilityChanged.connect(lambda _on, d=d, act=act: act.setChecked(not d.isHidden()))
            self.panel_actions[k] = act
            win.addAction(act)
            bar.addAction(act)
        tact = tools.toggleViewAction()
        tact.setShortcut("F4")
        win.addAction(tact)
        win.addAction(bar.toggleViewAction())
        win.addAction(self.options.toggleViewAction())
        self._bars_menu = win
        self._ribbon_toggle = win
        # 帯は上下左右のどこにでも置ける（帯の端をドラッグしても動く）
        panel_where = win.addMenu("欄の位置")
        for k in PANEL_ORDER:
            d = self.panels[k][0]
            sub = panel_where.addMenu(d.windowTitle())
            for label, area in (("左", Qt.LeftDockWidgetArea), ("右", Qt.RightDockWidgetArea), ("下", Qt.BottomDockWidgetArea),
                                ("上", Qt.TopDockWidgetArea)):
                sub.addAction(QAction(label, self, triggered=lambda _=False, d=d, area=area: self.move_panel(d, area)))
        where = win.addMenu("帯の位置")
        self._where = where
        for name, tb in (("道具の帯", tools), ("欄の帯", bar)):
            sub = where.addMenu(name)
            for label, area in (("左", Qt.LeftToolBarArea), ("右", Qt.RightToolBarArea), ("上", Qt.TopToolBarArea),
                                ("下", Qt.BottomToolBarArea)):
                sub.addAction(QAction(label, self, triggered=lambda _=False, tb=tb, area=area: self.place_bar(tb, area)))
        win.addSeparator()
        win.addAction(QAction("すべての欄を畳む", self, triggered=lambda: self._collapse_all(True)))
        win.addAction(QAction("すべての欄を広げる", self, triggered=lambda: self._collapse_all(False)))
        win.addAction(QAction("メインウィンドウを最小化", self, shortcut="Ctrl+M", triggered=self.showMinimized))
        win.addSeparator()
        win.addAction(QAction("すべての欄を表示", self, triggered=lambda: self._show_all(True)))
        # Tab は出す・隠すを入れ替える。隠すだけだと、もう一度押しても戻らず、帯も消えて操作できなくなった
        win.addAction(QAction("欄を隠す・出す（絵だけを見る）", self, shortcut="Tab", triggered=self.toggle_all))
        win.addSeparator()
        # 初めの並びに戻すのはここの 1 か所（前は「設定」にも同じ働きの項目があった）
        win.addAction(QAction("並びを初めの形に戻す", self, triggered=self.reset_layout))
        win.addAction(QAction("リボンの並びを変える…", self, triggered=self.edit_ribbon_order))
        win.addAction(QAction("すべて別ウィンドウにする", self, triggered=self.float_all))
        win.addAction(QAction("自由配置（欄をドラッグして好きな所に置く）", self, triggered=self.free_layout))
        self.build_ribbon()
        self.build_bottom()
        self.build_quick_bar()
        win.addAction(self.quick_bar.toggleViewAction())
        win.addSeparator()
        self.edit_menus_action = QAction("メニューを編集…", self, triggered=lambda: self.edit_menus().exec())
        self.edit_menus_action.setToolTip("メニューの項目を隠す・出す・並べ替える")
        self.edit_bars_action = QAction("帯を編集…", self, triggered=lambda: self.edit_bars().exec())
        self.edit_bars_action.setToolTip("帯に操作を足す・外す、区切りを入れる、並べ替える")
        self.lock_bars_action = QAction("帯を固定する", self, checkable=True)
        self.lock_bars_action.setToolTip("帯とリボンのタブをドラッグで動かせなくします")
        self.lock_bars_action.toggled.connect(lambda on: self.bars_editor.set_locked(on))
        for a in (self.edit_menus_action, self.edit_bars_action, self.lock_bars_action):
            win.addAction(a)
        self.build_layout_menu()
        from chatdraw import themes
        from chatdraw.look import Look
        themes.load_custom(self.layout_store)
        self.look = Look(self)
        self._look(themes.current)
        self._show_model()
        help_menu = self.menuBar().addMenu("ヘルプ")
        help_menu.addAction(S["tour"])
        help_menu.addAction(QAction("操作方法", self, triggered=lambda: self.open_help("manual")))
        help_menu.addAction(QAction("落ちた記録を開く", self, triggered=self.open_crashlog))
        help_menu.addAction(QAction("手順書（入れ方・模型の置き方・困ったとき）", self, triggered=lambda: self.open_help("install")))
        help_menu.addAction(QAction("記録の置き場を開く", self, triggered=self.open_logs))
        help_menu.addAction(QAction("更新を確かめる", self, triggered=lambda: self.check_update(manual=True)))
        from chatdraw import tours
        self.new_tours_menu = help_menu.addMenu("新しいツアー")   # まだ見ていない新しい案内。数を名前に出す
        help_menu.aboutToShow.connect(self._fill_new_tours)   # 開くたびに数を合わせる
        self._fill_new_tours()
        each = help_menu.addMenu("機能ごとの案内")
        for key, (name, _steps) in tours.catalog(self).items():
            each.addAction(QAction(name, self, triggered=lambda _=False, k=key: tours.show(self, k, force=True)))
        each.addSeparator()   # 案内の出し方も「機能ごとの案内」の中にまとめる
        auto = QAction("機能を初めて使うときに案内を出す", self, checkable=True)
        auto.setChecked(tours.enabled(self))
        auto.toggled.connect(lambda on: self.layout_store.setValue("feature_tours", int(on)))
        each.addAction(auto)
        each.addAction(QAction("機能の案内をもう一度出す", self, triggered=lambda: (tours.reset(self),
                                                                                       self.notify("次に使うときに、また案内します", "ok"))))
        from chatdraw import i18n
        lang = self.settings.get("language")
        i18n.translate_menus(self.menuBar(), lang)   # 英語を選んだときだけ換える（表に無い言葉は日本語のまま）
        # ボタン・欄・ツールチップ・ダイアログ・右クリックのメニューは、出すたびに引き換える（前はメニューだけが英語になった）
        from PySide6.QtWidgets import QApplication
        i18n.install(QApplication.instance(), lang)
        from chatdraw.scheduler import Scheduler
        self.scheduler = Scheduler(self.settings.store, self)   # チャットの「10 分後に」「毎晩」の予約。開いている間だけ動く
        self.scheduler.fire.connect(self._scheduled)
        QTimer.singleShot(5000, self.scheduler.tick)   # 閉じていた間に過ぎた予約は、開いて落ち着いてから 1 回だけ行う
        self._ribbon_toggle.addAction(self.ribbon_bar.toggleViewAction())
        self._bars_menu.addAction(self.bottom_bar.toggleViewAction())
        for name, tb in (("下の帯", self.bottom_bar), ("道具の設定の帯", self.options)):
            sub = self._where.addMenu(name)
            for label, area in (("上", Qt.TopToolBarArea), ("下", Qt.BottomToolBarArea)):
                sub.addAction(QAction(label, self, triggered=lambda _=False, tb=tb, area=area: self.place_bar(tb, area)))
        # AI の欄のタブの順と、外へ出したタブの欄。欄の位置を戻す（restoreState）より先に欄を作る
        from chatdraw.tabdock import TabDocks
        self.ai_tabs = TabDocks(self, self.ai_panel, self.layout_store)
        self.ai_tabs.restore()
        state = self.layout_store.value("state9")   # 欄の並びを変えたら名前を変え、古い並びを読まない
        if state is not None:
            self.restoreGeometry(self.layout_store.value("geometry9"))
            if not self.restoreState(state):
                self.arrange()
            for d, _area in self.panels.values():
                if d.isFloating():
                    self._as_window(d, True)   # 戻した並びで外に出ている欄も、ふつうの窓の枠にする
        else:
            self.arrange()
        for old in ("state8", "geometry"):   # 前の版の並び。読むと欄が画面の外や縦長のまま戻った
            self.layout_store.remove(old)
        from chatdraw import keys
        keys.apply(self, self.layout_store)
        self.setup_customizing()
        # 起動したときの道具。初めは手（絵を動かして見る）。描くときにペンを選ぶ。設定でペンにもできる
        self.select_tool("pen" if self.settings.get("first_tool") == "ペン" else "hand")

    PROMPT_KEY, FAV_KEY, PROMPT_MAX = "prompts/history", "prompts/favorites", 20
    EXAMPLES = ("赤いマフラーの女の子", "鎧の騎士 全身", "猫耳の少女 笑顔", "夕暮れの街", "レイヤーを足して")

    def _list(self, key: str) -> list[str]:
        saved = self.settings.store.value(key, []) or []
        return [str(t) for t in ([saved] if isinstance(saved, str) else list(saved))]

    def recent_prompts(self) -> list[str]:
        return self._list(self.PROMPT_KEY)

    def favorite_prompts(self) -> list[str]:
        return self._list(self.FAV_KEY)

    def _load_prompts(self):
        """書く欄の下のボタンを作り直す。登録した言葉、直近の言葉の順。どちらも無いときだけ頼みの例を出す"""
        while self.tips.count():
            it = self.tips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        favs = self.favorite_prompts()
        recent = [t for t in self.recent_prompts() if t not in favs]
        self.chip_texts = favs + recent   # ↑↓ で呼び出す順
        rows = [(t, True) for t in favs] + [(t, False) for t in recent] or [(t, None) for t in self.EXAMPLES]
        for text, fav in rows:
            chip = QPushButton(("★ " if fav else "") + (text if len(text) <= 24 else text[:23] + "…"))
            chip.setObjectName("suggest")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setProperty("prompt", text)
            chip.setToolTip(text + ("\n押すと書く欄に入り、ダブルクリックでもう一度描きます。右クリックで登録・外す・消す" if fav is not None else ""))
            chip.clicked.connect(lambda _=False, t=text: (self.entry.setText(t), self.entry.setFocus()))
            if fav is not None:
                chip.setContextMenuPolicy(Qt.CustomContextMenu)
                chip.customContextMenuRequested.connect(lambda pos, c=chip, t=text, f=fav: self._chip_menu(c, pos, t, f))
                chip.installEventFilter(self)
            self.tips.addWidget(chip)
        self.fav_button.setText("★" if self.entry.text().strip() in favs and self.entry.text().strip() else "☆")
        self._prompt_pos = -1

    def _chip_menu(self, chip, pos, text: str, fav: bool):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("登録から外す" if fav else "描くワードに登録する", lambda: (self.unpin_prompt(text) if fav else self.pin_prompt(text)))
        m.addAction("この言葉ですぐ描く", lambda: (self.entry.setText(text), self.send()))
        m.addAction("一覧から消す", lambda: self.forget_prompt(text))
        m.exec(chip.mapToGlobal(pos))

    def _save(self, key: str, items: list[str], limit: int | None = None):
        self.settings.store.setValue(key, items[:limit] if limit else items)
        self._load_prompts()

    def _remember_prompt(self, text: str):
        """頼んだ言葉を、新しい順に残す（同じ言葉は 1 つにまとめて先頭へ）"""
        self._save(self.PROMPT_KEY, [text] + [t for t in self.recent_prompts() if t != text], self.PROMPT_MAX)

    def pin_prompt(self, text: str):
        """描くワードに登録する。登録は数を限らず、外すまで残す"""
        if not text:
            self.notify("登録する言葉がありません", "info", "書く欄に言葉を書いてから ☆ を押します")
            return
        favs = self.favorite_prompts()
        if text not in favs:
            self._save(self.FAV_KEY, favs + [text])
            self.statusBar().showMessage(f"描くワードに登録しました: {text}", 4000)

    def select_tool(self, key: str):
        """道具を持ち替える（初めの道具や配置を変えたとき）。利用者が押したときと違い、初めて使うときの案内は出さない"""
        act = self.tool_actions.get(key)
        if act is None:
            return
        act.setChecked(True)
        self.canvas.set_tool(key)
        self._tool_changed(key)

    def voice_input(self):
        """描くワードの欄のマイクを押すのと同じ"""
        self.mic_button.press()

    def _toggle_fav(self):
        text = self.entry.text().strip() or self.last_text
        if text and text in self.favorite_prompts():
            self.unpin_prompt(text)
        else:
            self.pin_prompt(text)
        self.fav_button.setText("★" if text in self.favorite_prompts() else "☆")

    def unpin_prompt(self, text: str):
        self._save(self.FAV_KEY, [t for t in self.favorite_prompts() if t != text])

    def forget_prompt(self, text: str):
        self.settings.store.setValue(self.FAV_KEY, [t for t in self.favorite_prompts() if t != text])
        self._save(self.PROMPT_KEY, [t for t in self.recent_prompts() if t != text])

    def _entry_keys(self, obj, e) -> bool:
        """書く欄で ↑ を押すと前に頼んだ言葉、↓ で新しい方へ戻る"""
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "entry", None) and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Up, Qt.Key_Down) \
                and "\n" not in self.entry.text():   # 複数行のときは、↑↓ で行を動かす
            texts = getattr(self, "chip_texts", [])
            if texts:
                self._prompt_pos = min(self._prompt_pos + 1, len(texts) - 1) if e.key() == Qt.Key_Up else self._prompt_pos - 1
                if self._prompt_pos < 0:
                    self._prompt_pos = -1
                    self.entry.clear()
                else:
                    self.entry.setText(texts[self._prompt_pos])
                return True
        if e.type() == QEvent.MouseButtonDblClick and isinstance(obj, QPushButton) and obj.property("prompt"):
            self.entry.setText(obj.property("prompt"))   # ボタンをダブルクリックで、その言葉ですぐ描く
            self.send()
            return True
        return False

    NEG_KEY = "prompts/negatives"

    def negative_presets(self) -> list[str]:
        return self._list(self.NEG_KEY)

    def _load_negatives(self):
        """禁止ワードの欄の下のボタン（登録した禁止ワード）を作り直す"""
        while self.neg_tips.count():
            it = self.neg_tips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for text in self.negative_presets():
            chip = QPushButton("★ " + (text if len(text) <= 24 else text[:23] + "…"))
            chip.setObjectName("suggest")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setProperty("negative", text)
            chip.setToolTip(text + "\n押すと禁止ワードの欄に足します。右クリックで外す・この言葉だけにする")
            chip.clicked.connect(lambda _=False, t=text: self._use_negative(t))
            chip.setContextMenuPolicy(Qt.CustomContextMenu)
            chip.customContextMenuRequested.connect(lambda pos, c=chip, t=text: self._neg_chip_menu(c, pos, t))
            self.neg_tips.addWidget(chip)
        self.neg_tips_box.setVisible(bool(self.negative_presets()))
        t = self.ai_panel.negative.text().strip()
        self.neg_fav_button.setText("★" if t and t in self.negative_presets() else "☆")

    def _use_negative(self, text: str):
        """登録した禁止ワードを欄に足す。もう入っている言葉は重ねない"""
        cur = self.ai_panel.negative.text().strip()
        if not cur:
            self.ai_panel.negative.setText(text)
        elif text not in cur:
            self.ai_panel.negative.setText(cur + "、" + text)
        self.ai_panel.negative.setFocus()

    def _neg_chip_menu(self, chip, pos, text: str):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("禁止ワードの欄に足す", lambda: self._use_negative(text))
        m.addAction("この言葉だけにする", lambda: self.ai_panel.negative.setText(text))
        m.addAction("登録から外す", lambda: self.unpin_negative(text))
        m.exec(chip.mapToGlobal(pos))

    def pin_negative(self, text: str):
        """禁止ワードを登録する。数を限らず、外すまで残す"""
        if not text:
            self.notify("登録する禁止ワードがありません", "info", "禁止ワードの欄に言葉を書いてから ☆ を押します")
            return
        presets = self.negative_presets()
        if text not in presets:
            self.settings.store.setValue(self.NEG_KEY, presets + [text])
            self.statusBar().showMessage(f"禁止ワードを登録しました: {text}", 4000)
        self._load_negatives()

    def unpin_negative(self, text: str):
        self.settings.store.setValue(self.NEG_KEY, [t for t in self.negative_presets() if t != text])
        self._load_negatives()

    def _toggle_neg_fav(self):
        text = self.ai_panel.negative.text().strip()
        if text and text in self.negative_presets():
            self.unpin_negative(text)
        else:
            self.pin_negative(text)

    def _apply_avoid(self):
        """AI の欄の禁止ワードを絵の模型に渡す。描く・直す・ちびキャラ・広げる・綺麗にするのどの経路も painter.avoid を読む。
        描くときだけ渡すと、書き換えたあとに描かずに広げた・ちびキャラにしたときに前の禁止ワードのままだった"""
        painter = getattr(getattr(self, "studio", None), "painter", None)
        if painter is None:
            return
        avoid = list(self.ai_panel.taste()["avoid"])
        avoid += [a for a in self.ai_panel.avoid_words() if a not in avoid]   # 模型の決まりと「〜なし」には engine が足す
        painter.avoid = ", ".join(avoid)

    def draw_again(self):
        """前と同じ頼みを、別の種で描き直す"""
        if not self.last_text:
            self.notify("まだ描いていません", "info", "チャットに描きたい絵を書いて「描く」を押します")
            return
        self.entry.setText(self.last_text)
        self.send()

    def _fill_theme_menu(self):
        """決まったテーマ、自分のテーマ、テーマを作る・消す"""
        from chatdraw import themes
        m = self.theme_menu
        m.clear()
        group = QActionGroup(m)
        for name in themes.all_names():
            if name == next(iter(themes.CUSTOM), None):
                m.addSeparator()
            a = QAction(name, m, checkable=True, triggered=lambda _=False, n=name: self.set_theme(n))
            a.setChecked(name == themes.current["name"])
            group.addAction(a)
            m.addAction(a)
        m.addSeparator()
        m.addAction(QAction("テーマを作る…", m, triggered=self.edit_theme))
        if themes.CUSTOM:
            gone = m.addMenu("自分のテーマを消す")
            for name in themes.CUSTOM:
                gone.addAction(QAction(name, gone, triggered=lambda _=False, n=name: self.remove_theme(n)))

    def _look(self, t: dict):
        self.canvas.setBackgroundBrush(QColor(t["canvas"]))
        self.look.apply(t)

    def set_theme(self, name: str):
        """テーマ（色・模様・演出）を替えて覚える。アイコン・絵の周り・欄の色がそろって替わる"""
        from chatdraw import look, themes

        def change():
            t = themes.apply(QApplication.instance(), name)
            self._look(t)
            self.layout_store.setValue("theme", t["name"])
        look.crossfade(self, change)
        self.feature_tour("theme")
        return themes.current

    def preview_theme(self, t: dict):
        """テーマを作る窓で替えている途中の色を、保存せずに当てる"""
        from chatdraw import themes
        self._look(themes.apply(QApplication.instance(), t))

    def edit_theme(self):
        from chatdraw.themeedit import ThemeEditor
        self.feature_tour("theme_edit", lambda: ThemeEditor(self).exec())

    def remove_theme(self, name: str):
        from chatdraw import themes
        if QMessageBox.question(self, "自分のテーマを消す", f"「{name}」を消します。よろしいですか") != QMessageBox.Yes:
            return
        if themes.current["name"] == name:
            self.set_theme(themes.DEFAULT)
        themes.remove_custom(self.layout_store, name)

    def say(self, text: str, who: str = "CharacterDesigner"):
        """チャットに吹き出しを出す。描く途中の知らせは、言葉の模型に渡す会話には入れない"""
        return self.chat.add("user" if who == "あなた" else "ai", text, remember=False)

    def chat_send(self, text: str):
        """チャットに書かれた一言に答える。操作ならして、「〜を描いて」なら描く内容に入れて描き、
        それ以外は言葉の模型に裏で聞く（画面の糸で聞くと、読み込みと推論の間アプリが固まる）"""
        from chatdraw import assistant, commands
        self.chat.add("user", text)
        self.watch_chat_result()   # 絵が変わったら、終わったときに縮小した絵を返す
        if getattr(self, "asking", False):
            self.say("前の答えを待っています。少し待ってからもう一度送ってください")
            return
        if self.chat_plan(text):   # 文の頼み（繰り返し・予約・書き出し・加工の並び・参考画像・お気に入り）は段取りにして行う
            return
        words = getattr(getattr(self, "studio", None), "words", None)
        self.asking = True
        self.chat.set_busy(True)

        def picked(p):
            p = None if isinstance(p, BaseException) else p
            reply = commands.handle(self, text, picked=p)
            if reply:
                self.asking = False
                self.chat.set_busy(False)
                self.chat.add("ai", reply)
                self.feature_tour("ai_commands")
                return
            body = assistant.draw_request(text)
            if body:
                body = self.favorites().apply(body)[0]   # 「お気に入りの水彩で描いて」は、残した言葉を足して描く
                self.asking = False
                self.chat.set_busy(False)
                self.chat.add("ai", f"AI の欄の描く内容に「{body}」と入れて描きます")
                self.entry.setText(body)
                self.send()
                return
            if self.thread is not None and getattr(words, "ready", lambda: False)():
                self.asking = False   # 描いている間は言葉の模型を描く側が使う。同時に使うと落ちることがある
                self.chat.set_busy(False)
                self.chat.add("ai", "描いている間は答えられません。描き終わってからもう一度送ってください")
                return
            turns, prompt = list(self.chat.turns[:-1]), self.entry.text().strip()
            self.in_background(lambda: assistant.answer(words, turns, text, prompt), answered, "言葉の模型の答え待ち")

        def answered(got):
            self.asking = False
            self.chat.set_busy(False)
            if isinstance(got, BaseException):
                self.chat.add("ai", f"答えられませんでした: {got}")
                return
            reply, new = got
            self.offer_prompt(self.chat.add("ai", reply), new)

        if commands.needs_model(text, words):
            self.in_background(lambda: commands.by_model(text, words), picked, "言葉の模型の答え待ち")
        else:
            picked(None)

    # ---- チャットの文の頼み（chatdraw/chatplan.py） ----
    _FIND_REF = re.compile(r"参考(画像|資料|の絵)を?.{0,4}(探|検索|見つけ)|find\s+reference", re.I)
    _FAV_ADD = re.compile(r"お気に入り(の作風)?(に|へ|として)\s*(保存|登録|足|追加|残)")

    def chat_plan(self, text: str) -> bool:
        """チャットの文を段取りに読んで行う。普通の 1 回の頼み・操作・質問なら False（今までの流れに任せる）"""
        from chatdraw import chatplan, finishers
        if self._FIND_REF.search(text):
            q = self._FIND_REF.sub(" ", text)
            q = re.sub(r"(を|の|して|ください|[、。])", " ", q).strip()
            self.find_reference(q or self.entry.text().strip())
            return True
        if self._FAV_ADD.search(text):
            m = re.search(r"「([^」]+)」\s*[:：=＝は]?\s*(.+)?", text)
            if not m:
                self.chat.add("ai", "「名前」と言葉を書いてください。例: お気に入りに保存「水彩」: watercolor, soft colors")
                return True
            words = (m.group(2) or "").strip(" 、。") or self.entry.text().strip()
            words = self._FAV_ADD.sub(" ", words).strip(" 、。して")
            self.favorites().put(m.group(1), words)
            self.chat.add("ai", f"登録した作風「{m.group(1)}」に「{words}」を残しました。「{m.group(1)}で描いて」で使えます")
            return True
        try:
            # 一覧の見出しだけを使う。available() は使えるかを確かめるので 1 秒余りかかり、画面の糸で呼ぶとチャットが固まった
            entries = [{"name": n, "label": f.label} for n, f in finishers.REGISTRY.items()]
        except Exception:   # noqa: BLE001  仕上げの一覧が読めなくても、ほかの段取りは読む
            entries = []
        from chatdraw import aipanel
        prompts = self.shortcut_store().prompts()
        asked = chatplan.clarify(text, entries, [n for n, *_ in aipanel.STYLES], prompts)
        if asked is not None:
            self.offer_choices(*asked)
            return True
        called = chatplan.find_prompts(text, prompts)
        if len(called) == 1:
            p = called[0]
            self.chat.add("ai", f"登録した指示「{p['name']}」（{p['text']}）で直します")
            self.run_shortcut(p["id"])
            return True
        plan = chatplan.parse(text, entries)
        if not plan.special:
            return False
        if plan.scheduled:
            later = re.sub(r"\s+", " ", chatplan._SCHEDULE_WORDS.sub(" ", text)).strip()
            self.scheduler.add(later, plan.after_min, plan.daily)
            self.chat.add("ai", f"予約しました: {chatplan.describe(plan)}。アプリを開いている間に行います（設定 → 予約の一覧で見る・消す）")
            return True
        self.run_plan(plan)
        return True

    def offer_choices(self, question: str, choices):
        """曖昧な頼みに、候補をボタンで出す。押すと、その文をチャットに送ったのと同じに行う"""
        b = self.chat.add("ai", question)
        for label, send in choices:
            b.add_button(label, f"「{send}」と頼みます", lambda _c=False, t=send: self.chat_send(t))
        self.chat._fit(b)
        return b

    def watch_chat_result(self):
        """チャットの頼みで絵が変わったら、処理が終わったときに縮小した絵をチャットに返す。
        終わりは画面の糸の時計で見る（描く・加工は裏で動き、終わりの知らせの形が処理ごとに違うため）"""
        from PySide6.QtCore import QTimer
        if getattr(self, "_chat_watch", None) is not None:
            return   # 前の頼みを見ている途中。その前の絵と比べる
        self._chat_watch = self._canvas_key()
        QTimer.singleShot(400, self._chat_watch_tick)

    def _canvas_key(self) -> str:
        import hashlib
        img = self.canvas.flatten()
        return f"{img.width()}x{img.height()}:" + hashlib.blake2b(bytes(img.constBits()), digest_size=16).hexdigest()

    def _chat_watch_tick(self):
        from PySide6.QtCore import QTimer
        if not self._plan_idle() or getattr(self, "_plan_queue", []):
            QTimer.singleShot(400, self._chat_watch_tick)
            return
        before, self._chat_watch = self._chat_watch, None
        if before is None or self._canvas_key() == before:
            return
        folder = Path(self.settings.get("output_dir")) / "chat"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.png"
            qimage_to_pil(self.canvas.flatten()).save(path)
        except OSError as e:
            self.chat.add("ai", f"結果の絵を残せませんでした: {e}", remember=False)
            return
        self.chat.add_image("できました。絵を押すと元の大きさで開きます", str(path))

    def open_chat_image(self, path: str):
        """チャットの結果の絵を元の大きさで見る。キャンバスに開くこともできる"""
        return self.chat.view_image(path, ("キャンバスに開く", "この絵をキャンバスに開きます（元に戻すで戻せます）", self.edit_image))

    def _scheduled(self, text: str):
        self.chat.add("ai", f"予約の時刻になりました: {text}")
        self.chat_send(text)

    def run_plan(self, plan):
        """段取りを 1 つずつ、前の作業が終わってから行う。描く・加工は裏で動くので、空いたのを見てから次を始める"""
        from chatdraw import chatplan
        body = plan.body
        if body:
            fav = self.favorites().apply(body)
            body = fav[0]
        acts = {"upscale": self.upscale_canvas, "transparent": self.make_transparent, "chibi": self.make_chibi,
                "lineart": self.make_lineart, "pixel": self.make_pixel}
        queue = []
        for step in plan.steps:
            if step in ("draw", "fix"):
                for _ in range(plan.repeat):
                    queue.append(lambda st=step: self._plan_draw(body, fix=st == "fix"))
            elif step.startswith("finisher:"):
                queue.append(lambda n=step.split(":", 1)[1]: self.finish_with(n, background=True))
            elif step in acts:
                queue.append(acts[step])
        if plan.export is not None:
            queue.append(lambda: self.export_to(plan.export))
        if plan.keep_best and plan.repeat > 1:
            # どれが良いかは利用者が決める（AI が自分で出来を判定しない）。描いた絵は全部履歴に残し、選んでもらう
            queue.append(lambda: self.chat.add("ai", f"{plan.repeat} 枚描きました。履歴の欄で見比べて、残す絵を選んでください"
                                                     "（気に入った絵は「この絵が好き」で覚えます）"))
        self.chat.add("ai", f"段取り: {chatplan.describe(plan)}")
        self._plan_queue = getattr(self, "_plan_queue", []) + queue
        self._plan_pump()

    def _plan_idle(self) -> bool:
        return self.thread is None and not getattr(self, "bg_pending", 0) and not getattr(self, "asking", False)

    def _plan_pump(self):
        from PySide6.QtCore import QTimer
        q = getattr(self, "_plan_queue", [])
        if not q:
            return
        if self._plan_idle():
            q.pop(0)()
        if q:
            QTimer.singleShot(1000, self._plan_pump)   # 前の作業が終わるのを、画面を止めずに待つ

    def _plan_draw(self, body: str, fix: bool = False):
        if fix:
            self.mode.setCurrentIndex(2)
        self.entry.setText(body or self.last_text)
        if not self.entry.text().strip():
            self.chat.add("ai", "何を描くかが分かりませんでした。描く内容を書いてください")
            self._plan_queue = []
            return
        self.send()

    def export_to(self, folder: str = "") -> Path | None:
        """今の絵を 1 枚の PNG にしてフォルダーへ書き出す。空なら設定の保存先"""
        to = Path(folder).expanduser() if folder else Path(self.settings.get("output_dir"))
        try:
            to.mkdir(parents=True, exist_ok=True)
            path = to / f"{time.strftime('%Y%m%d-%H%M%S')}.png"
            qimage_to_pil(self.canvas.flatten()).save(path)
        except OSError as e:
            self.chat.add("ai", f"書き出せませんでした: {e}")
            return None
        self.chat.add("ai", f"書き出しました: {path}")
        return path

    def favorites(self):
        from chatdraw.refs import Favorites
        if getattr(self, "_favorites", None) is None:
            self._favorites = Favorites(self.settings.store)
        return self._favorites

    def open_favorites(self):
        from chatdraw.refs import FavoritesDialog

        def use(d):
            cur = self.entry.text().strip()
            self.entry.setText(f"{cur}, {d['words']}" if cur else d["words"])
        FavoritesDialog(self.favorites(), self, on_use=use).exec()

    def ask_reference_search(self):
        from PySide6.QtWidgets import QInputDialog
        q, ok = QInputDialog.getText(self, "参考画像を探す", "探す言葉（例: 海 少女 麦わら帽子）", text=self.entry.text().strip())
        if ok and q.strip():
            self.find_reference(q.strip())

    def find_reference(self, query: str):
        """ライブラリーと保存先のフォルダーから参考画像をタグで探し、いちばん合う物を参考画像に置く"""
        from chatdraw import refs
        folders = [self.settings.get("output_dir")] + [str(p) for p in (self.settings.store.value("reference_dirs", []) or [])]
        items = self.library.works() + self.library.docs() if hasattr(self, "library") else []

        def done(got):
            if isinstance(got, BaseException) or not got:
                self.chat.add("ai", f"「{query}」に合う参考画像は見つかりませんでした（ライブラリーと保存先のディレクトリを探しました）")
                return
            self.reference.load(got[0][1])
            self.ai_panel.use_ref.setChecked(True)
            lines = "\n".join(p for _s, p in got[:5])
            self.chat.add("ai", f"「{query}」で {len(got)} 枚見つけました。いちばん合う絵を参考画像に置きました:\n{lines}")
        self.in_background(lambda: refs.find_images(query, items, folders), done, "参考画像を探す")

    def offer_prompt(self, bubble, new: str | None, restored: bool = False):
        """答えの吹き出しに、描く内容の案を AI の欄へ入れるボタンを付ける。読み戻した会話の案にも付ける"""
        if not new:
            return
        if not restored:
            bubble.set_text(bubble.text + f"\n\n描く内容の案: {new}")
        bubble.proposal = new

        def fill():
            self.entry.setText(new)
            dock = self.panels["chat"][0] if hasattr(self, "panels") else None
            if dock is not None:
                dock.show()
                dock.raise_()
            self.ai_panel.sections["描く内容"].set_open(True)
            self.ai_pages.setCurrentIndex(0)
        bubble.add_button("AI の欄に入れる", "この案を AI の欄の「描く内容」に入れます（描きはしません）", fill)
        bubble.add_button("入れて描く", "この案を「描く内容」に入れて、すぐ描きます", lambda: (fill(), self.send()))
        self.chat._fit(bubble)
        if not restored:
            self.chat.save()

    def _show_model(self):
        from chatdraw.models import image_model
        from chatdraw.setup import AUTO
        key = self.settings.get("image_model")
        if key == AUTO:   # おまかせで選んだ模型を出す（選ぶ前は、今読んでいる模型）
            chosen = getattr(getattr(self, "studio", None), "chosen", None)
            painter = getattr(getattr(self, "studio", None), "painter", None)
            name = chosen[0] if chosen else image_model(painter.model).name if getattr(painter, "model", "") else ""
            self.model_label.setText("絵の模型: おまかせ" + (f"（{name}）" if name else ""))
            self.model_label.setToolTip(f"おまかせで選んだ理由: {chosen[1]}" if chosen else "描くときに、手元の模型から頼みに合う物を選びます")
        else:
            self.model_label.setText(f"絵の模型: {image_model(key).name}")

    def _fit_features(self):
        """選んだ模型の世代で使えない機能（ラフから、直す、参考画像）のボタンを止め、理由を出す"""
        from chatdraw.models import family as fam, image_model
        painter = getattr(getattr(self, "studio", None), "painter", None)
        model = getattr(painter, "model", "") or ""
        if not model or not hasattr(self, "ai_panel"):
            return
        f = fam(image_model(model).family)
        why = f"{f.name} の模型では使えません。SDXL の模型に替えると使えます"
        panel = self.ai_panel
        buttons = panel.mode_buttons[1]   # mode_buttons は（並び、ボタンの一覧）の 2 つ組
        widgets = [(buttons[1], f.sketch), (buttons[2], f.inpaint)]
        if hasattr(panel, "use_ref"):
            widgets.append((panel.use_ref, f.reference))
        for b, ok in widgets:
            if b.property("tip0") is None:
                b.setProperty("tip0", b.toolTip())   # 元の説明は残しておき、使えるときに戻す
            b.setEnabled(ok)
            b.setToolTip(b.property("tip0") if ok else why)
        if not f.sketch and self.mode.currentIndex() == 1 or not f.inpaint and self.mode.currentIndex() == 2:
            self.mode.setCurrentIndex(0)

    def check_ai(self) -> dict:
        """AI が使えるかを確かめて、下の欄に出す。描く前と起動のときに毎回呼ぶ"""
        self._show_model()
        self._fit_features()
        st = check(getattr(self.studio, "painter", None), getattr(self.studio, "words", None)) if isinstance(self.studio, Studio) else \
            {"torch": True, "image": True, "words": True, "reason": ""}
        if st["image"]:
            self.ai_label.setText("AI: 使えます" + ("" if st["words"] else "（言葉の模型なし。日本語は語の表で英語に直します）"))
            self.ai_label.setStyleSheet("color:#8fd18f")
        else:
            self.ai_label.setText("AI: 使えません")
            self.ai_label.setStyleSheet("color:#ff7a5c")
            self.ai_label.setToolTip(st["reason"])
        return st

    def send(self):
        text = self.entry.text().strip()
        pen = self.canvas.redpen
        if self.thread and text:   # 描いている間の頼みは受けない。黙って捨てると、押しても何も起きないように見えた
            self.progress_popup.pop()
            self.statusBar().showMessage("描いている途中です。終わってから頼んでください（止めるときは「止める」）", 6000)
            return
        shown = pen.shown()   # 隠した印は直さないので、指示の有無も見ない（隠した印の空の指示で、押しても何も起きなかった）
        if not self.thread and not text and shown and not all(pen.texts[i - 1] for i in shown):
            self.inspect_marks_then_fix()   # 指示の空の囲みは、その中を検品し、見つけた崩れを指示にして 1 回だけ直す
            return
        if self.thread or not text and not (shown and all(pen.texts[i - 1] for i in shown)):   # 絵の上に全部書いてあれば、チャットは空でよい
            return
        if not text:
            text = " / ".join(f"{i}: {pen.texts[i - 1]}" for i in shown)
        from chatdraw import commands
        words = getattr(getattr(self, "studio", None), "words", None)
        if commands.needs_model(text, words):
            # 言葉の模型に聞くのは裏で行う。画面の糸で聞くと、「赤」「保存」などの操作の言葉を含む頼みで
            # 模型の読み込みと推論の間（数秒〜数十秒）アプリが固まった
            if getattr(self, "asking", False):
                return
            self.asking = True
            self.button.setEnabled(False)

            token = self._ask_token = getattr(self, "_ask_token", 0) + 1

            def got(picked):
                if token != self._ask_token:
                    return   # 止めた回の答え
                self.asking = False
                self.button.setEnabled(True)
                self._send_after(text, None if isinstance(picked, BaseException) else picked)
            self.in_background(lambda: commands.by_model(text, words), got, "言葉の模型の答え待ち")
            return
        self._send_after(text, None)   # 模型に聞けないときは言葉の決まりで選ぶ

    def in_background(self, work, done, name: str = "裏の処理"):
        """work を裏の糸で動かし、答えを画面の糸の done に渡す。work が例外を出したら、その例外を渡す"""
        import threading
        key = self._bg_register(done, name)

        def run():
            try:
                v = work()
            except BaseException as e:   # noqa: BLE001  裏で落ちても画面の糸に必ず返す
                v = e
            self._bg_emit(key, v)
        threading.Thread(target=run, daemon=True).start()

    def _bg_register(self, done, name: str = "裏の処理") -> int:
        """答えの受け手を画面の糸で覚え、番号を返す。裏の糸には番号だけを渡す。
        前は呼ぶたびに Bridge（QObject）を作って裏の糸に渡していた。裏の糸がその最後の参照を手放すと、
        Python の側の後片付けが裏の糸で走り、画面の糸で落ちた（Shiboken の runDeletionInMainThread で Segmentation fault）"""
        if getattr(self, "_bridge", None) is None:
            self._bridge = Bridge(self)   # 窓と同じだけ生きる 1 つだけの橋。裏の糸で消えることはない
            self._bridge.got.connect(self._bg_done, Qt.QueuedConnection)
            self._waiting: dict[int, object] = {}
            self._next_key = 0
        self._next_key += 1
        self._waiting[self._next_key] = done
        self.activity.bg_begin(self._next_key, name)   # 進みの欄に、裏で動いている物を出す
        self.bg_pending = getattr(self, "bg_pending", 0) + 1
        self.gc_guard()
        return self._next_key

    def gc_guard(self):
        """裏の糸が動いている間は自動の gc を止め、画面の糸で若い世代だけを片付ける。
        裏の糸で gc が走ると、消えた画面の部品の Python 側の後片付けが裏の糸で起き、画面の糸が落ちた
        （Shiboken の runDeletionInMainThread で Segmentation fault。線画を裏で書いている間に再現した）。
        裏の糸が全部終われば、自動の gc に戻す"""
        import gc
        if self.thread is not None or getattr(self, "bg_pending", 0):
            if gc.isenabled():
                gc.disable()
            gc.collect(0)
        elif not gc.isenabled():
            gc.enable()

    def _bg_emit(self, key: int, v):
        try:
            self._bridge.got.emit((key, v))
        except RuntimeError:
            pass   # 窓を閉じたあと

    def _send_after(self, text: str, picked):
        from chatdraw import commands
        reply = commands.handle(self, text, picked=picked)   # 操作の頼み（道具・色・欄・配置など）はその場で行い、絵は描かない
        if reply:
            self.entry.clear()
            self.say(text, "あなた")
            self.say(reply)
            self.feature_tour("ai_commands")
            return
        self._draw_now(text)

    def _draw_now(self, text: str):
        """頼みを描く（新規・ラフから・直す）。チャットの頼みと、右クリックの指示のショートカットの同じ入口"""
        if self.canvas.redpen.marks and self.mode.currentIndex() != 2:
            self.mode.setCurrentIndex(2)   # 赤ペンの印があるときの頼みは、印の所を直す頼みとして受ける
        if self.mode.currentIndex() == 2 and not self.canvas.redpen.marks and self.canvas.selection_mask() is None:
            self.mode.setCurrentIndex(0)   # 直す所が無いときは、止めずに新しく描く頼みとして受ける（直すのままで止まっていた）
        st = self.check_ai()
        if not st["image"]:
            self.say(st["reason"] or "AI が使えません")
            self.progress_popup.tell("描けません", st["reason"] or "AI が使えません")   # 描く前に止まったことも右下に出す
            return
        text = self._keep_original(text)
        if text is None or not self._ok_batch():
            return
        self.last_text = text
        if self.mode.currentIndex() != 2:   # 赤ペン・選択範囲の直しの指示は、描くワードの履歴に入れない（その絵の 1 か所だけの言葉）
            self._remember_prompt(text)
        self.say(f"描きます: {text}")
        self.button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.feature_tour("draw")
        self.activity.begin(text, self.mode.currentText())
        self.activity.status("AI が使えるかを確かめました")
        m = re.search(r"([124１２４一二四])\s*枚", text)
        if m:   # 「4 枚描いて」のように枚数を書いたら、その枚数で描く
            self.ai_panel.set_count({"１": 1, "一": 1, "２": 2, "二": 2, "４": 4, "四": 4}.get(m.group(1)) or int(m.group(1)))
        if self.ai_panel.reference() is not None and hasattr(self.studio.painter, "reference_ready") \
                and not self.studio.painter.reference_ready():
            from chatdraw.engine import REFERENCE_GB
            gb = REFERENCE_GB.get(getattr(self.studio.painter, "family", "sdxl"), 3)
            if QMessageBox.question(self, "参考画像に寄せる", f"参考画像を読む部品（約 {gb}GB）を初めに取ります。取りますか。") \
                    != QMessageBox.Yes:
                self.ai_panel.use_ref.setChecked(False)   # 取らないなら、参考画像なしで描く
        self.offer_two_stage_parts()
        mode = self.mode.currentIndex()
        base = qimage_to_pil(self.canvas.flatten()) if mode in (1, 2) else None
        regions = self.fix_regions(text) if mode == 2 else None
        seeds = self.ai_panel.seeds()[:1 if mode == 2 else None]
        self.ai_panel.seed.setValue(seeds[0])   # 使った種を見せる（固定すれば同じ絵を描き直せる）
        self.batch, self.batch_items = [], []
        self.job_kind = "fix" if mode == 2 else "draw"
        meta = dict(mode=self.mode.currentText(), preset=self.ai_panel.preset, style_name=self.ai_panel.style,
                    size=list(self.size_pick.currentData()), strength=self.strength.value())
        self._apply_avoid()
        self.job_studio = self._fix_studio() if mode == 2 else self.studio
        self.before_heavy(self.job_studio.painter)
        self.thread = QThread()
        self.job = Job(self.job_studio, text, seeds, base=base, strength=self.strength.value() / 100,
                       style=self.ai_panel.style_tags(), regions=regions, reference=self.ai_panel.reference(),
                       ref_scale=self.ai_panel.ref_scale.value() / 100, meta=meta,
                       size=fit_size(*self.canvas.size_px()) if base is not None else self.size_pick.currentData())
        self._worker = self.job
        self.job.moveToThread(self.thread)
        self.thread.started.connect(self.job.run)
        self.job.status.connect(self.on_status)
        self.job.preview.connect(self.show_preview)
        self.job.one.connect(self.on_one)
        self.job.done.connect(self.finish)
        self.job.failed.connect(self.fail)
        self.gc_guard()
        self.thread.start()

    def _keep_original(self, text: str) -> str | None:
        """直しの頼みが、描いたときの描くワードや赤ペンの指示と食い違えば、確かめてから進める。
        黙って進めると元の指示が無視された。返すのは描く頼み（やめたら None）"""
        if self.mode.currentIndex() != 2:
            return text
        from chatdraw import confirm, intent
        pen = self.canvas.redpen
        given = set(intent.terms(text))
        old = [getattr(self, "origin_prompt", "") or ""] + [t for t in pen.texts if t and not set(intent.terms(t)) <= given]
        found = intent.conflicts(old, text)
        if not found:
            return text
        lines = "\n".join(f"・元「{a}」 → 今「{b}」" for a, b in found)
        picked = confirm.ask(self, "intent", "元の頼みと食い違います",
                             "今の頼みは、元の頼み（描くワード・赤ペンの指示）と食い違います。\n" + lines,
                             [("keep", "元のまま"), ("new", "新しい頼みにする")],
                             detail="「元のまま」は食い違った所を外して直します。「新しい頼みにする」は今の頼みのとおりに直します。")
        if picked == "cancel":
            self.statusBar().showMessage("直しをやめました。元の絵のままです", 6000)
            return None
        if picked == "keep":
            rest = intent.drop(text, [b for _a, b in found])
            if not rest:
                self.notify("元の頼みのままにしました", "info", "食い違った所を外すと、直す所が残りませんでした")
                return None
            return rest
        gone = {a for a, _b in found}
        kept = [t for t in intent.terms(getattr(self, "origin_prompt", "") or "") if t not in gone]
        self.origin_prompt = "、".join(kept + [b for _a, b in found])   # 次の直しは、新しい頼みを元として見る
        return text

    def _ok_batch(self) -> bool:
        """まとめて描く（枚数が多い）ときは、時間がかかることを先に確かめる"""
        from chatdraw import confirm
        n = self.ai_panel.count_spin.value()
        if self.mode.currentIndex() == 2 or n < confirm.BATCH_COUNT:
            return True
        return confirm.ask(self, "batch", "まとめて描く", f"{n} 枚をまとめて描きます。1 枚より時間がかかります（描いている間も止められます）。",
                           [("go", f"{n} 枚描く")]) == "go"

    def offer_two_stage_parts(self):
        """2 段で描ける模型がそろっていて、部品（約 2.9GB）だけが無いときに、取るかを聞く。
        取らないと、おまかせでは黙って 1 つの模型で描き、崩れにくい描き方が使われないままになる"""
        if self.studio.way == "one" or self.mode.currentIndex() != 0 or getattr(self, "_two_parts_asked", False):
            return
        from chatdraw import twostage
        try:
            if twostage.pick(self.have_image_models(), self.studio.painter.model) is None or twostage.parts_ready():
                return
        except Exception:
            return
        self._two_parts_asked = True   # 断られたら、この起動の間は聞き直さない
        if QMessageBox.question(self, "構図と仕上げを分けて描く",
                                f"手足や姿勢が崩れにくい描き方（構図と仕上げを分ける）に使う部品（約 {twostage.PARTS_GB}GB）を取りますか。"
                                "取らないときは、1 つの模型で描きます。") == QMessageBox.Yes:
            self.studio.fetch_two_parts = True   # 取るのは描く裏の処理で行う（画面を止めない）

    def save_layer_png(self, path: str | None = None) -> str:
        """選んでいるレイヤーだけを、透明を残したまま PNG で保存する"""
        c = self.canvas
        if not c.layers:
            return ""
        layer = c.layers[c.current]
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "レイヤーを PNG で保存", str(Path(self.settings.get("output_dir")) / f"{layer.name}.png"), "PNG (*.png)")
            if not path:
                return ""
        if not layer.image.save(path, "PNG"):
            self.notify("レイヤーを保存できませんでした", "error", f"{path}\n保存先に書き込めるか、ディスクに空きがあるかを確かめて、別の場所を選び直してください")
            return ""
        self.statusBar().showMessage(f"{layer.name} を保存しました: {path}", 6000)
        return path

    def export_layers_png(self, folder: str | None = None) -> list[str]:
        """全部のレイヤーを 1 枚ずつ PNG で書き出す。名前は下からの番号と名前（並びが分かり、同じ名前でも上書きしない）"""
        import re
        c = self.canvas
        if not c.layers:
            return []
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, "レイヤーを書き出すディレクトリ", str(self.settings.get("output_dir")))
            if not folder:
                return []
        out = []
        for i, layer in enumerate(c.layers, 1):
            safe = re.sub(r'[\\/:*?"<>|]', "_", layer.name).strip() or "layer"
            path = str(Path(folder) / f"{i:02d}-{safe}.png")
            if layer.image.save(path, "PNG"):
                out.append(path)
        self.statusBar().showMessage(f"{len(out)} 枚のレイヤーを書き出しました: {folder}", 6000)
        return out

    def fix_marked(self):
        """赤ペンで囲んだ所を直す。AI の欄を「直す」にして「描く」と同じ send() を呼ぶ"""
        self.mode.setCurrentIndex(2)
        self.send()

    # ---- 手で呼ぶ検品（chatdraw/qcmanual.py）。検品は印と指示を置くだけで、直すのは利用者が押したときだけ ----
    def _picture(self):
        """今の絵を平らにした絵。白一色などの何も描いていない絵なら None"""
        img = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        return img if any(lo != hi for lo, hi in img.getextrema()) else None

    def _busy_inspect(self) -> bool:
        if self.thread or getattr(self, "inspecting", False):
            self.statusBar().showMessage("描いているか検品している途中です。終わってから押してください", 6000)
            return True
        return False

    def add_flaw_mark(self, box, note: str) -> int:
        """崩れの枠を囲む赤ペンの印を足し、指示の欄に崩れの中身を書く。足した印の番号を返す"""
        import math
        from PySide6.QtCore import QPointF
        pen = self.canvas.redpen
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = max(12.0, (x1 - x0) * 0.6), max(12.0, (y1 - y0) * 0.6)
        pts = [QPointF(cx + rx * math.cos(t * math.pi / 16), cy + ry * math.sin(t * math.pi / 16)) for t in range(33)]
        pen.begin(pts[0])
        for q in pts[1:]:
            pen.add(q)
        pen.end()
        n = len(pen.marks)
        pen.set_text(n, note)
        return n

    def inspect_now(self):
        """今の絵（AI が描いていない絵も）を検品し、崩れた所を赤ペンで囲む。直しはしない"""
        if self._busy_inspect():
            return
        img = self._picture()
        if img is None:
            self.notify("検品する絵がありません", "info", "絵を描くか開いてから押します")
            return
        from chatdraw import qcmanual
        self.inspecting = True
        self.statusBar().showMessage("検品しています（手・足・顔）", 6000)

        def done(res):
            self.inspecting = False
            self.statusBar().clearMessage()
            if isinstance(res, BaseException):
                self.notify("検品で止まりました", "error", str(res))
                return
            found, rest, lost = qcmanual.flaws(res), qcmanual.unplaced(res), qcmanual.missed(res)
            for box, note in found:
                self.add_flaw_mark(box, note)
            if found:
                self.mode.setCurrentIndex(2)   # 「描く」を「囲んだ所を直す」にして、そのまま押せるようにする
                if hasattr(self, "layer_panel"):
                    self._refresh_layers()
            tail = "。".join(([f"場所の分からない崩れ: {'、'.join(rest)}"] if rest else [])
                             + ([f"検品できなかった所: {'、'.join(lost)}"] if lost else []))
            if found:
                self.notify(f"検品: 崩れ {len(found)} か所を赤ペンで囲みました", "info",
                            "印の指示を見て「囲んだ所を直す」で直せます" + (f"。{tail}" if tail else ""))
            elif rest:
                self.notify(f"検品: 崩れ {len(rest)} 件（場所は分かりません）", "info", tail)
            else:
                self.notify("検品: 崩れは見つかりませんでした" + ("（検品できなかった所があります）" if lost else ""),
                            "ok" if not lost else "info", tail)
        self.in_background(lambda: qcmanual.inspect(img), done, "検品")

    def inspect_marks_then_fix(self):
        """指示の空の囲みの中だけを検品し、見つけた崩れを指示にして 1 回だけ直す。崩れが無ければ何もしない。
        直したあとは検品し直さない（描く・検品・直しを繋げて回すと止まらなかった）"""
        if self._busy_inspect():
            return
        img = self._picture()
        pen = self.canvas.redpen
        if img is None:
            self.notify("検品する絵がありません", "info", "絵を描くか開いてから押します")
            return
        masks = pen.masks()
        jobs = []
        for i in pen.shown():
            if pen.texts[i - 1]:
                continue
            box = gray_to_pil(masks[i - 1]).resize(img.size).getbbox()
            if box:
                jobs.append((i, box, img.crop(box)))
        if not jobs:
            return
        from chatdraw import qcmanual
        self.inspecting = True
        self.statusBar().showMessage(f"囲みの中を検品しています（{len(jobs)} か所）", 6000)
        marks = list(pen.marks)

        def done(got):
            self.inspecting = False
            self.statusBar().clearMessage()
            if isinstance(got, BaseException):
                self.notify("検品で止まりました", "error", str(got))
                return
            if list(pen.marks) != marks:   # 検品の間に印を消した・足した。古い番号に指示を書かない
                self.notify("検品の間に赤ペンの印が変わったので、直しませんでした", "info")
                return
            clean, lost = [], []
            for i, (x0, y0, _x1, _y1), res in got:
                notes = [t for _b, t in qcmanual.flaws(res, (x0, y0))] + qcmanual.unplaced(res)
                lost += [f"印 {i} の{w}" for w in qcmanual.missed(res)]
                if notes:
                    pen.set_text(i, "、".join(notes))
                else:
                    clean.append(i)
            more = f"検品できなかった所: {'、'.join(lost)}" if lost else ""
            if len(clean) == len(got):
                self.notify("囲みの中に崩れは見つからなかったので、直しませんでした", "info", more)
                return
            for i in clean:   # 崩れの無い囲みは隠して直さない（レイヤーの欄で出し直せる）
                pen.set_hidden(i, True)
            if hasattr(self, "layer_panel"):
                self._refresh_layers()
            self.notify(f"囲みの中の崩れを指示にして直します（{len(got) - len(clean)} か所）", "info",
                        "。".join(x for x in ([f"崩れの無い印 {'・'.join(map(str, clean))} は隠しました"] if clean else []) + [more] if x))
            self.send()   # 指示が全部そろったので、普段の直しを 1 回だけ通す
        self.in_background(lambda: [(i, box, qcmanual.inspect(crop)) for i, box, crop in jobs], done, "囲みの中の検品")

    def edit_note(self, n: int):
        """赤ペンの n 番の印の横に、指示を書く欄を出す。Enter で絵の上に残し、Esc でやめる"""
        from PySide6.QtCore import QPoint
        pen = self.canvas.redpen
        if not 1 <= n <= len(pen.marks):
            return
        if getattr(self, "note_edit", None) is None:
            # 指示の欄の横にマイクを置き、声でも指示を入れられるようにする（chatdraw/voice.py。描くワードの欄と同じ仕組み）
            from chatdraw import voice
            self.note_box = QWidget(self.canvas.viewport())
            self.note_box.setObjectName("noteBox")
            row = QHBoxLayout(self.note_box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)
            self.note_edit = NoteEdit(self.note_box)   # 打った文字をキャンバスとショートカットに取られない欄
            self.note_edit.setObjectName("noteEdit")
            self.note_edit.setPlaceholderText("この所をどう直すか（例: 笑顔に）Enter で残す")
            self.note_edit.setMinimumWidth(260)
            self.note_edit.returnPressed.connect(self._note_done)
            self.note_edit.installEventFilter(self)
            self.note_mic = voice.mic_button(self.note_edit, parent=self.note_box)
            row.addWidget(self.note_edit, 1)
            row.addWidget(self.note_mic)
        self.note_n = n
        at = self.canvas.mapFromScene(pen.marks[n - 1][0]) + QPoint(18, -14)
        self.note_edit.setText(pen.texts[n - 1])
        self.note_box.move(at)
        self.note_box.adjustSize()
        self.note_box.show()
        self.note_edit.setFocus()
        self.feature_tour("redpen_note")

    def _note_done(self):
        pen = self.canvas.redpen
        if 1 <= self.note_n <= len(pen.texts):
            pen.set_text(self.note_n, self.note_edit.text())
            if hasattr(self, "layer_panel"):   # 指示はレイヤーの欄の「赤ペン n」の行にも出す
                self._refresh_layers()
        self.note_box.hide()
        self.canvas.setFocus()

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if self._entry_keys(obj, e):
            return True
        if obj is getattr(self, "note_edit", None) and e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self.note_box.hide()
            return True
        return super().eventFilter(obj, e)

    def fix_regions(self, text: str):
        """直す所と指示の並び。赤ペンの印は絵の上に書いた指示か番号ごとの指示、四角の選択は文全体を指示にする"""
        from chatdraw.redpen import merge
        marks = self.canvas.redpen.masks()
        shown = self.canvas.redpen.shown()   # 欄で隠した印は直さない
        regions = [(gray_to_pil(m), n) for i, (m, n) in enumerate(zip(marks, merge(self.canvas.redpen.texts, text)), 1) if i in shown]
        sel = self.canvas.selection_mask()
        if sel is not None:
            regions.append((gray_to_pil(sel), text))
        return regions

    def on_status(self, msg: str):
        if self._stale():
            return
        m = re.search(r"（(\d+)/(\d+)）", msg)
        self.activity.status(msg, *(int(m.group(1)), int(m.group(2))) if m else (None, None))

    def on_one(self, prompt: str, path: str):
        """1 枚できるたびに呼ばれる。初めの 1 枚はキャンバスに置き、ほかは履歴に並べて選べるようにする。
        絵を置くのを先にする。前は検品の知らせを先に出していて、そこで落ちると絵が置かれず、途中の絵か何も無いままだった"""
        if self._stale():
            return
        self.canvas.show_overlay(None)
        if self.job_kind == "fix":
            self._on_fixed(path)
            return
        self.images.append(path)
        first = not self.batch
        self.batch.append(path)
        bad = []
        try:
            if self.job_kind == "chibi":
                self.put_result(path, "ちびキャラ")
            elif first and self.pin_action.isChecked() and self.mode.currentIndex() == 0:
                self.say("表示する絵を固定しているので、新しい絵は履歴に入れました（押すと出ます）")
            elif first:
                self.activity.status("キャンバスに置いています")
                self.place(path)
        except (OSError, ValueError) as e:
            self.say(f"絵をキャンバスに置けませんでした（{e}）。履歴から押すと出せます")
        self.batch_items.append(self.activity.add(path, prompt))
        if first and not self.pin_action.isChecked():
            self.history.setCurrentRow(0)   # 選んでいた古い絵ではなく、出した新しい絵を選んだ形にする
        for f in bad:
            self.say(f"崩れ: {f}")
        if prompt:
            # 絵の模型に渡した言葉は会話に毎回出さず、書く欄にカーソルを合わせたときだけ出す（頼みとずれた絵が出たときに見られる）
            self.last_model_prompt = prompt
            self._entry_tip()
        if getattr(self.studio, "last_lost", None) and self.job_kind == "draw":
            self.say("模型に伝わらなかった言葉: " + "、".join(self.studio.last_lost))
        check = getattr(self.studio, "last_check", None)
        if check is not None and self.job_kind == "draw":
            from chatdraw.handcheck import summary
            try:
                self.say(summary(check))   # 検品の結果は、絵ごとに先に出す（崩れを見落としたまま使わないように）
            except (KeyError, TypeError) as e:
                self.say(f"検品の結果を読めませんでした（{e}）。目で確かめてください")
        self._record()
        self.library_panel.add(self.library.add_work(path))
        # 頼み・種・設定は描いたときに PNG に埋めてある。埋まっていない絵（前の版で描き、隣に .json だけがある物）だけ、
        # 裏の糸で埋める（PNG を書き直すので 1 枚 0.1 秒ほどかかる。別名に書いてから替えるので、読む側は壊れた絵を見ない）
        from chatdraw import finishers
        self.run_io(lambda: finishers.embedded(path) or finishers.embed(path, finishers.sidecar(path)), lambda _v: None, "ライブラリーへ保存")

    def _on_fixed(self, path: str):
        """赤ペン・選択範囲の直しの結果は、一番上の新しいレイヤーにだけ置いて選ぶ。描いた絵の履歴・ライブラリーには載せない
        （レイヤーを消せば何も残らない）。崩れが見つかっても隠さずに見せ、崩れは会話に書いて判断を利用者に渡す"""
        self.batch.append(path)
        bad = getattr(getattr(self, "job_studio", None) or self.studio, "last_flaws", [])
        n = getattr(self, "_fix_count", 0) + 1
        self._fix_count = n
        try:
            self._put_fix(path, f"赤ペンの直し {n}" + ("（崩れあり）" if bad else ""))
        except (OSError, ValueError) as e:
            self.say(f"直しをレイヤーに置けませんでした（{e}）")
        finally:
            if self.settings.get("result_place") != "別ファイル":   # 別ファイルで開くときは、開く側がこの絵を読む
                Path(path).unlink(missing_ok=True)   # 置いたあとは保存先にも残さない（絵はレイヤーの中にある）
        # 直しが済んだら印は消す（残ると、いつまでも絵の上に赤い線が残った）。消した印は元に戻すで戻せる
        for _ in range(len(self.canvas.redpen.marks)):
            self.canvas.redpen.undo()
        self._refresh_layers()
        for f in bad:
            self.say(f"崩れ: {f}")

    def show_final(self):
        """描き終えたら、1 枚目の絵をキャンバスに出して履歴で選ぶ。途中の絵（重ねた下描き）は必ず消す。
        途中の絵の知らせが絵の知らせより後に届くと、仕上がった絵の上に途中の絵が残り、出来た絵が見えなかった"""
        self.canvas.show_overlay(None)
        if not self.batch or self.job_kind != "draw" or self.pin_action.isChecked():
            return
        path = self.batch[0]
        if getattr(self, "_placed", None) != path:
            self.place(path)
        for row in range(self.history.count()):
            if self.history.item(row).data(Qt.UserRole) == path:
                self.history.setCurrentRow(row)
                break

    def finish(self):
        if self._stale():
            return
        self._show_model()   # おまかせで選んだ模型を出す
        self.show_final()
        n = len(self.batch)
        fixed = self.job_kind in ("fix", "chibi")
        bad = getattr(getattr(self, "job_studio", None) or self.studio, "last_flaws", []) if self.job_kind == "fix" else []
        result = ("直しを重ねました（崩れあり）" if bad else "直しを重ねました") if fixed else \
            f"{n} 枚描きました" if n > 1 else "描けました"
        if bad:   # 崩れがあったときだけ絵の説明に足す（「描けました」は絵を見れば分かる）
            for it in self.batch_items:
                it.setToolTip(f"{result}\n{it.toolTip()}")
        self.activity.end(result, None, record=False)
        self.say(result if fixed else f"{n} 枚描きました。履歴から選べます" if n > 1 else "描きました")
        self.notify(result if fixed else "描けました", "error" if bad else "ok",
                    (f"崩れ {len(bad)} 件。一番上のレイヤーに置きました。見て決めてください" if bad else
                     "新しいレイヤーに重ねました。見て決めてください") if fixed else
                    (f"1 枚目をキャンバスに出しました。ほかの {n - 1} 枚は履歴を押すと出ます" if n > 1
                     else "キャンバスに出しました（元に戻すで前の絵に戻せます）"),
                    on_click=lambda: (self.panels["history"][0].show(), self.activity.tabs.setCurrentIndex(0)))
        self._end("できました")

    def make_chibi(self):
        """今の絵を、ちびキャラ（頭の大きなデフォルメ）に描き直して、新しいレイヤーに重ねる"""
        from PIL import Image
        from chatdraw import postfx
        if self.busy("ちびキャラ"):
            return
        st = self.check_ai()
        if not st["image"]:
            self.notify("AI が使えません", "error", st["reason"])
            return
        self.feature_tour("chibi")
        base = qimage_to_pil(self.canvas.flatten())
        full = Image.new("L", base.size, 255)
        self._start_job("ちびキャラにする", "chibi", Job(self.studio, postfx.CHIBI_NOTE, self.ai_panel.seeds()[:1], base=base,
                                                       strength=0.7, style=postfx.CHIBI_TAGS,
                                                       regions=[(full, postfx.CHIBI_NOTE)], check=False))

    def make_lineart(self):
        """今の絵から線だけを取り出した線画を、新しいレイヤーに重ねる（元の絵は残す）"""
        from chatdraw import postfx
        self.feature_tour("lineart")
        src = qimage_to_pil(self.canvas.flatten())
        out = Path(self.settings.get("output_dir")) / time.strftime("%Y-%m-%d")
        path = out / f"{time.strftime('%Y%m%d-%H%M%S')}-lineart.png"

        def work():   # 線を取り出して書くのは裏の糸（832×1216 で 0.4 秒ほど固まった）
            out.mkdir(parents=True, exist_ok=True)
            postfx.lineart(src).save(path)

        def done(err):
            if isinstance(err, BaseException):
                self.notify("線画にできませんでした", "error", str(err))
                return
            self.put_result(str(path), "線画")
            self.activity.add(str(path), "線画")
            self.notify("線画にしました", "ok", "新しいレイヤーに重ねました。元の絵は下に残っています")
        self.statusBar().showMessage("線画にしています…")
        self.in_background(work, done)

    def make_pixel(self, long: int = 128, colors: int = 24):
        """今の絵をドット絵にして、新しいレイヤーに重ねる。小さいドット絵（1 ドット 1 画素）も出力の置き場に残す"""
        from chatdraw import postfx
        self.feature_tour("pixel")
        img = qimage_to_pil(self.canvas.flatten())
        out = Path(self.settings.get("output_dir")) / time.strftime("%Y-%m-%d")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        small = out / f"{stamp}-pixel.png"
        big = out / f"{stamp}-pixel-view.png"

        def work():   # 減色と書き出しは裏の糸（832×1216 で 1.7 秒固まった）
            dots = postfx.pixel_art(img, long=long, colors=colors)
            out.mkdir(parents=True, exist_ok=True)
            dots.save(small)
            postfx.enlarge(dots, img.size).save(big)
            return dots.size

        def done(got):
            if isinstance(got, BaseException):
                self.notify("ドット絵にできませんでした", "error", str(got))
                return
            dw, dh = got
            self.put_result(str(big), "ドット絵")
            self.activity.add(str(small), f"ドット絵 {dw}×{dh}・{colors} 色")
            self.notify("ドット絵にしました", "ok", f"{dw}×{dh} ドット・{colors} 色。元の大きさの絵は履歴にあります")
        self.statusBar().showMessage("ドット絵にしています…")
        self.in_background(work, done)

    def _start_job(self, label: str, kind: str, job):
        self.say(label, "あなた")
        self.button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.activity.begin(label, kind)
        self.batch, self.batch_items, self.job_kind = [], [], kind
        self.before_heavy(getattr(getattr(job, "studio", None), "painter", None))
        self.thread = QThread()
        self.job = self._worker = job
        job.moveToThread(self.thread)
        self.thread.started.connect(job.run)
        job.status.connect(self.on_status)
        job.preview.connect(self.show_preview)
        job.one.connect(self.on_one)
        job.done.connect(self.finish)
        job.failed.connect(self.fail)
        self.gc_guard()
        self.thread.start()

    def upscale_canvas(self):
        """今の絵を、レイヤーを分けたまま 2 倍の大きさにする（元に戻すの履歴は消えるので、先に保存を勧める）"""
        from chatdraw import upscale
        if self.busy("2 倍に拡大"):
            return
        from chatdraw import confirm
        cw, ch = self.canvas.size_px()
        if cw * ch * 4 > confirm.BIG_UPSCALE_PX and confirm.ask(
                self, "upscale_big", "大きな絵の拡大", f"拡大すると {cw * 2}×{ch * 2} になります。時間がかかり、メモリも多く使います。",
                [("go", "拡大する")]) != "go":
            return
        if self.canvas.undo_stack:
            picked = confirm.ask(self, "upscale", "絵を 2 倍に拡大",
                                 "レイヤーはそのままで 2 倍にします。拡大すると「元に戻す」の履歴は消えるので、先に保存しておくと戻れます。",
                                 [("save", "保存してから拡大"), ("go", "拡大")])
            if picked == "save":
                if not self.save_project(wait=True):
                    return
            elif picked != "go":
                return
        layers = [(l.name, l.visible, l.opacity, qimage_to_pil_rgba(l.image)) for l in self.canvas.layers]
        current = self.canvas.current
        self.feature_tour("upscale")
        self.activity.begin("絵を 2 倍に拡大", "拡大")
        self.activity.status("描いています" + ("" if upscale.ready() else "（初めに拡大の部品 2.4MB を取ります）"))

        def work(on_step):
            from PIL import Image
            out = []
            for i, (name, visible, opacity, img) in enumerate(layers, 1):
                size = (img.width * 2, img.height * 2)
                if img.getchannel("A").getbbox() is None:   # 何も描いていないレイヤーは、模型に通さず広げるだけ
                    big = Image.new("RGBA", size, (0, 0, 0, 0))
                else:
                    big = upscale.upscale(img, 2, on_step=lambda a, n, i=i: on_step((i - 1) * 100 + a * 100 // n, len(layers) * 100))
                out.append((name, visible, opacity, big))
            return out, current
        self._run_task(work, self._upscaled)

    def _upscaled(self, result):
        from chatdraw.canvas import Layer
        made, current = result
        from PySide6.QtGui import QImage
        layers = [Layer(name, qimage_from_pil(big).convertToFormat(QImage.Format_ARGB32_Premultiplied), visible, opacity)
                  for name, visible, opacity, big in made]
        self.canvas._reset(layers, current)
        self.dirty = True
        self.activity.end("拡大しました", None, record=False)
        w, h = self.canvas.size_px()
        self.notify("拡大しました", "ok", f"{w}×{h}・レイヤー {len(layers)} 枚のまま")
        self._end("拡大しました")

    def busy(self, what: str) -> bool:
        """裏で描いている間なら、押した物を始めずに理由を出して True。
        描いている糸を新しい糸で上書きすると、動いている QThread が消されてアプリごと落ちた（綺麗にする・広げる・三面図）"""
        if self.thread is None:
            return False
        self.notify(f"{what}は、今の絵を描き終えてから押してください", "info", "描いている間は、ほかの AI の作業を始めません。止めるなら「止める」を押します")
        return True

    def before_heavy(self, keep=None):
        """AI の重い作業を始める前に、落ちても失わないよう作業を自動保存し、使わない絵の模型をメモリから降ろす。
        描いている途中にアプリごと落ちる報告があった。落ちる前に保存しておけば、次の起動で戻すかを聞ける（offer_restore）。
        今の模型と直しの模型（_fix_cache）が両方メモリに残ると、2 つの模型の分だけメモリを使い、足りなくなった"""
        try:
            self.autosave()
        except Exception:   # noqa: BLE001  保存できなくても描くのは止めない
            pass
        for st in (getattr(self, "studio", None), getattr(self, "_fix_cache", None)):
            p = getattr(st, "painter", None)
            if p is None or p is keep or getattr(p, "model", None) == getattr(keep, "model", object()):
                continue
            loaded = getattr(p, "loaded", None)
            if callable(loaded) and loaded():
                p.unload()

    def _run_task(self, fn, then):
        if self.busy("この作業"):   # 呼び手が見落としても、動いている糸を上書きしない
            return False
        try:
            self.autosave()   # 落ちても失わないように（before_heavy と同じ理由）
        except Exception:   # noqa: BLE001
            pass
        self.thread = QThread()
        self.task = self._worker = Task(fn)
        self.stop_button.setEnabled(True)
        self.task.moveToThread(self.thread)
        self.thread.started.connect(self.task.run)
        self.task.status.connect(self.on_status)
        # lambda をそのままつなぐと、終わりの処理が裏の糸で走って画面を触る。Window の関数を通して画面の糸に戻す
        self._task_then = then
        self.task.done.connect(self._task_done)
        self.task.failed.connect(self.fail)
        self.button.setEnabled(False)
        self.gc_guard()
        self.thread.start()

    def _task_done(self, result):
        if self._stale():
            return
        then, self._task_then = getattr(self, "_task_then", None), None
        if then is not None:
            then(result)

    def _lora_row(self):
        """AI の欄の「模型」に、自分の作風の LoRA を選ぶ欄と強さを足す。初めは「なし」"""
        from PySide6.QtWidgets import QComboBox, QSlider
        from chatdraw import ownstyle
        self.lora_pick = QComboBox()
        self.lora_pick.setToolTip("自分の作風の LoRA を絵の模型に重ねます。置き場は " + str(ownstyle.lora_dir()))
        self.lora_pick.addItem("LoRA なし", "")
        for p in ownstyle.loras():
            self.lora_pick.addItem(p.stem, str(p))
        self.lora_pick.setCurrentIndex(max(0, self.lora_pick.findData(str(self.layout_store.value("lora", "") or ""))))
        self.lora_strength = QSlider(Qt.Horizontal)
        self.lora_strength.setRange(0, 150)
        self.lora_strength.setValue(int(self.layout_store.value("lora_scale", 80)))
        self.lora_strength.setToolTip("LoRA の強さ。大きいほど自分の作風に寄せる")
        self.lora_pick.currentIndexChanged.connect(lambda _i: self._lora_changed())
        self.lora_strength.valueChanged.connect(lambda _v: self._lora_changed())
        body = self.ai_panel.sections["模型"].body
        body.addWidget(self.lora_pick)
        body.addWidget(self.lora_strength)
        Window._lora_shown(self)   # 試験は名前空間で呼ぶので、窓の側の関数を直接呼ぶ

    def _lora_shown(self):
        """LoRA を置いていなければ選ぶ欄を出さず、「なし」のときは強さを出さない（動かしても何も変わらない部品を並べない）。
        選んだ値と設定の鍵（lora、lora_scale）はそのまま残す"""
        self.lora_pick.setVisible(self.lora_pick.count() > 1)
        self.lora_strength.setVisible(bool(self.lora_pick.currentData()))

    def _lora_changed(self):
        Window._lora_shown(self)   # 試験は名前空間で呼ぶので、窓の側の関数を直接呼ぶ
        path, scale = self.lora_pick.currentData() or "", self.lora_strength.value()
        self.layout_store.setValue("lora", path)
        self.layout_store.setValue("lora_scale", scale)
        painter = getattr(getattr(self, "studio", None), "painter", None)
        if painter is not None:
            painter.lora, painter.lora_scale = path, scale / 100

    def collect_favorites(self):
        """★ の絵を学習用のデータ（絵と説明の .txt）に書き出し、置き場を知らせる"""
        from chatdraw import ownstyle
        if not ownstyle.favorites():
            self.statusBar().showMessage("★ の絵がありません。履歴かライブラリーの絵を右クリックして ★ を付けてください", 8000)
            return None
        res = ownstyle.collect()
        self.statusBar().showMessage(f"学習用に {len(res['images'])} 枚を集めました: {res['dir']}"
                                     + (f"（見つからない絵 {len(res['missing'])} 枚）" if res["missing"] else ""), 12000)
        return res

    def judge(self, path: str, verdict: str) -> bool:
        """履歴の右クリック → 判定。記録の無い絵（前の版で描いた絵）は知らせる"""
        from chatdraw import wordlearn
        ok = wordlearn.set_verdict(path, verdict)
        self.statusBar().showMessage((f"判定を付けました: {wordlearn.VERDICTS.get(verdict, '消しました')}" if ok else
                                      "この絵は学びの記録がありません（前の版で描いた絵です）"), 4000)
        return ok

    def _history_menu(self, pos, run: bool = True):
        from PySide6.QtWidgets import QMenu
        it = self.history.itemAt(pos)
        path = it.data(Qt.UserRole) if it else None
        if not path:   # 絵の無い所でも、使えるメニューを出す
            m = self.area_menu("history")
            if not run:
                return m
            m.exec(self.history.mapToGlobal(pos))
            return None
        m = QMenu(self)
        m.addAction("この絵を出す", lambda: self.show_history_image(path))
        m.addAction("この絵を出して固定する", lambda: (self.show_history_image(path), self.pin_action.setChecked(True)))
        if self.pin_action.isChecked():
            m.addAction("固定を外す（最新の絵を出す）", lambda: self.pin_action.setChecked(False))
        m.addAction("今の絵に重ねる", lambda: self.layer_from_file(path, "AI の絵"))
        m.addAction("編集する（囲んで直す）", lambda: self.edit_image(path))
        m.addSeparator()
        m.addAction("この設定で描き直す", lambda: self.redo_from(path))
        m.addAction("頼みの言葉を書く欄に入れる", lambda: self._prompt_from(path))
        m.addAction("頼みの言葉を描くワードに登録する", lambda: self._prompt_from(path, pin=True))
        from chatdraw import ownstyle
        m.addAction("★ お気に入りを外す" if ownstyle.is_favorite(path) else "★ お気に入りにする", lambda: ownstyle.toggle(path))
        m.addAction("学習用に集める", self.collect_favorites)
        # 判定（良い・悪い・直した）は学びの記録に付ける（chatdraw/wordlearn.py）。検品より弱く数え、「良い」はタグを強めない
        from chatdraw import wordlearn
        judge = QMenu("判定", m)   # 親をはっきり持たせる（文字だけで足すと、返したメニューから引いたときに消えていた）
        m.addMenu(judge)
        judge.setToolTipsVisible(True)
        now = wordlearn.verdict_of(path)
        for key, label in list(wordlearn.VERDICTS.items()) + [("", "判定を消す")]:
            act = judge.addAction(("● " if key and key == now else "") + label, lambda k=key: self.judge(path, k))
            act.setToolTip("この絵の判定を学びの記録に付けます。次から描くときの通りやすさに弱く数えます")
        m.addSeparator()
        m.addAction("絵をコピー", lambda: self.copy_image(path))
        m.addAction("保存した場所を開く", lambda: self.open_folder(path))
        m.addAction("3D に進む…", lambda: self.open_3d(path)).setToolTip("この絵から 3D のキャラデザに進む（最初の一歩: 厚みのある板の模型）")
        from chatdraw import share
        sns = m.addMenu("SNS に送る")
        for name in share.SERVICES:
            act = sns.addAction(f"{name} に送る", lambda n=name: share.post(self, n, path, self._prompt_text(path)))
            act.setEnabled(share.enabled(self.settings, name))
        if not any(share.enabled(self.settings, n) for n in share.SERVICES):
            sns.setToolTip("設定の「SNS 連携」で選ぶと使えます")
            sns.setEnabled(False)
        m.addSeparator()
        m.addAction("消す（ごみ箱へ）…", lambda: self.delete_images([path]))
        self.common_menu(m.addMenu("そのほか"))
        if not run:
            return m
        m.exec(self.history.mapToGlobal(pos))

    ENTRY_TIP = "描いてほしい絵を日本語か英語で書き、Enter か「描く」で描きます（Shift+Enter で改行）"

    def _words_changed(self):
        """単語のお気に入り・読めなかった語の直しのあと。目安と段を作り直す"""
        self.word_row.reload()
        self.ai_panel.update_preview()
        self._entry_tip()

    def open_word_dict(self):
        """設定 → 単語辞書…（描くワードの段の「辞書…」と同じ窓）"""
        return self.word_row.open_dialog()

    def _entry_tip(self):
        """書く欄のツールチップ。使い方に、模型に渡る言葉の目安と、前に絵の模型に渡した言葉を足す"""
        if hasattr(self, "lost_row"):   # 読めなかった語は、カーソルを合わせなくても見える段に出す（黙って落とさない）
            from chatdraw.engine import has_japanese
            from chatdraw.jaterms import leftover
            text = self.entry.text().strip()
            self.lost_row.update_words(leftover(text) if text and has_japanese(text) else [])
        lines = [self.ENTRY_TIP]
        guess = self.ai_panel.preview.text().strip()
        if guess:
            lines += ["", guess]
        if getattr(self, "last_model_prompt", ""):
            lines += ["", "前に絵の模型に渡した言葉: " + self.last_model_prompt]
        # 長い英語の言葉で横に広がり画面からはみ出さないよう、折り返す形（リッチテキスト）で出す
        import html
        self.entry.setToolTip("<qt>" + "<br>".join(html.escape(t) for t in lines) + "</qt>")

    # ---- 消す・ごみ箱 ----
    def delete_images(self, paths: list[str], ask: bool = True) -> str | None:
        """絵と付属のファイルをアプリのごみ箱へ移し、履歴とライブラリーから外す。消す前に確かめる。
        すぐには消さない（ごみ箱から戻せる）。移した 1 回分の名前を返す"""
        paths = [str(p) for p in paths if p]
        if not paths:
            return None
        if ask:
            from chatdraw import confirm
            n = len(paths)
            if confirm.ask(self, "delete_images", "絵を消す",
                           ("この絵" if n == 1 else f"{n} 枚の絵") + "をごみ箱へ移します。付属のファイル（頼みと設定）も一緒に移します。\n"
                           "「ファイル」→「ごみ箱…」から戻せます。", [("yes", "ごみ箱へ移す")]) != "yes":
                return None
        items = self.library.take(paths)
        try:
            key = self.trash.put(paths, items)
        except OSError as e:
            self.library.put_back(items)
            self.notify("消せませんでした", "error", f"{e}\nほかのアプリでその絵を開いていれば閉じてから、もう一度消してください")
            return None
        gone = set(paths)
        for row in reversed(range(self.history.count())):
            if self.history.item(row).data(Qt.UserRole) in gone:
                self.history.takeItem(row)
        self.images = [p for p in self.images if p not in gone]
        self.library_panel.refresh()
        self._trash_changed()
        self.notify("ごみ箱へ移しました", "ok", "押すと戻します", on_click=lambda: self.restore_trash(key))
        return key

    def restore_trash(self, key: str) -> bool:
        """ごみ箱から元の場所へ戻し、履歴とライブラリーにも戻す"""
        m = self.trash.restore(key)
        if m is None:
            return False
        if m.get("library"):
            self.library.put_back(m["library"])
            self.library_panel.refresh()
        for p in m["images"]:
            if Path(p).exists() and not any(it.get("kind") == "doc" and it["path"] == p for it in m.get("library", [])):
                self.activity.add(p, "")
                if p not in self.images:
                    self.images.append(p)
        self.statusBar().showMessage("ごみ箱から戻しました", 4000)
        self._trash_changed()
        return True

    def _trash_changed(self):
        """ごみ箱の画面を開いたままなら並べ直す"""
        dlg = getattr(self, "_trash_dialog", None)
        if dlg is not None and dlg.isVisible() and not getattr(dlg, "_filling", False):
            dlg._filling = True
            try:
                dlg.fill()
            finally:
                dlg._filling = False

    def open_trash(self):
        from chatdraw.trash import open_dialog
        open_dialog(self)

    def _prompt_text(self, path: str) -> str:
        from chatdraw import finishers
        return str(finishers.sidecar(path).get("text", ""))

    def _prompt_from(self, path: str, pin: bool = False):
        text = self._prompt_text(path)
        if not text:
            self.notify("頼みの言葉が残っていません", "info", "この絵の .json がありません")
            return
        self.entry.setText(text)
        if pin:
            self.pin_prompt(text)

    def _need_selection(self) -> bool:
        if self.canvas.selection is None:
            self.notify("選択範囲がありません", "info", "四角・投げなわ・多角形の選択で範囲を選んでから使ってください")
            return False
        return True

    def selection_clear(self):
        if self._need_selection():
            self.canvas.clear_selection_area()
            self.statusBar().showMessage("選択範囲の中を消しました（Ctrl+Z で戻せます）", 3000)

    def selection_fill(self):
        if self._need_selection() and self.canvas.fill_selection():
            self.statusBar().showMessage("選択範囲を塗りました（Ctrl+Z で戻せます）", 3000)

    def selection_copy(self) -> bool:
        """選択があればその中を、無ければ見えている絵全体をコピーする"""
        from PySide6.QtWidgets import QApplication
        img = self.canvas.selection_image()
        if img is None:
            self.copy_image()
            self._copied_at = None
            return True
        QApplication.clipboard().setImage(img)
        self._copied_at = self.canvas.selection.topLeft()   # 「同じ位置に貼り付け」で使う
        self.statusBar().showMessage("選択範囲をコピーしました", 3000)
        return True

    def selection_cut(self):
        if not self._need_selection():
            return
        from PySide6.QtWidgets import QApplication
        if not self.canvas.editable():
            return   # ロックした・隠したレイヤーは切り取らない（前はロックしたレイヤーの絵が消えた）
        QApplication.clipboard().setImage(self.canvas.selection_image())
        self._copied_at = self.canvas.selection.topLeft()
        self.canvas.clear_selection_area()
        self.statusBar().showMessage("選択範囲を切り取りました（Ctrl+Z で戻せます）", 3000)

    def paste_clipboard(self):
        """コピーした絵を一番上の新しいレイヤーに貼る（利用者が気づけるよう、貼ったレイヤーを選んだ状態にする）"""
        from PySide6.QtWidgets import QApplication
        img = QApplication.clipboard().image()
        if img.isNull():
            self.notify("貼り付ける絵がありません", "info", "絵をコピーしてから貼り付けてください")
            return
        if not self.canvas.layers:
            self.canvas.new_canvas(img.width(), img.height())
        if self.canvas.paste_image(img):
            self.statusBar().showMessage("一番上の新しいレイヤーに貼りました（Ctrl+Z で戻せます）", 3000)

    def layer_copy(self):
        from PySide6.QtWidgets import QApplication
        layer = self.canvas.copy_layer()
        if layer is not None:
            QApplication.clipboard().setImage(layer.image)   # ほかのアプリにも絵として貼れるようにする
            self._copied_at = None
            self.statusBar().showMessage(f"レイヤー「{layer.name}」をコピーしました", 3000)

    def layer_cut(self):
        from PySide6.QtWidgets import QApplication
        layer = self.canvas.cut_layer()
        if layer is not None:
            QApplication.clipboard().setImage(layer.image)
            self.statusBar().showMessage(f"レイヤー「{layer.name}」を切り取りました（Ctrl+Z で戻せます）", 3000)

    def layer_paste(self):
        if self.canvas.copied_layer is None:
            self.notify("貼り付けるレイヤーがありません", "info", "「レイヤーをコピー」か「レイヤーを切り取り」をしてから貼り付けてください")
            return
        if self.canvas.paste_layer():
            self.statusBar().showMessage("レイヤーを貼り付けました（Ctrl+Z で戻せます）", 3000)

    def copy_merged(self):
        from PySide6.QtWidgets import QApplication
        if not self.canvas.layers:
            return
        QApplication.clipboard().setImage(self.canvas.merged_image())
        sel = self.canvas.selection
        self._copied_at = sel.topLeft() if sel is not None else None
        self.statusBar().showMessage("見えている絵を結合してコピーしました", 3000)

    def paste_in_place(self):
        """コピーした所と同じ位置に貼る。位置の分からない絵（ほかのアプリでコピーした絵）は左上に貼る"""
        from PySide6.QtWidgets import QApplication
        img = QApplication.clipboard().image()
        if img.isNull():
            self.notify("貼り付ける絵がありません", "info", "絵をコピーしてから貼り付けてください")
            return
        if not self.canvas.layers:
            self.canvas.new_canvas(img.width(), img.height())
        from PySide6.QtCore import QPoint
        at = getattr(self, "_copied_at", None)
        if self.canvas.paste_image(img, "貼り付け", at if at is not None else QPoint(0, 0)):
            self.statusBar().showMessage("同じ位置の新しいレイヤーに貼りました（Ctrl+Z で戻せます）", 3000)

    def build_symmetry_menu(self, menu):
        """表示のメニューの「対称定規」。ブラシの設定の「対称」と同じ設定を、どの道具からでも切り替えられるようにする"""
        from PySide6.QtGui import QActionGroup
        from chatdraw.canvas import SYMMETRY
        group = QActionGroup(menu)
        self.symmetry_actions = {}
        for key, label in (("", "なし"),) + tuple(SYMMETRY.items()):
            a = QAction(label, menu, checkable=True)
            a.setToolTip("描いた線と図形を、軸の反対側にも同時に描きます" if key else "対称を切ります")
            a.triggered.connect(lambda _=False, k=key: self.symmetry.setCurrentIndex(self.symmetry.findData(k)))
            group.addAction(a)
            menu.addAction(a)
            self.symmetry_actions[key] = a
        self.symmetry_actions[""].setChecked(True)
        menu.addSeparator()
        menu.addAction(QAction("軸を真ん中に戻す", menu, triggered=lambda: self.canvas.set_axis_center(None),
                               toolTip="対称の軸を絵の真ん中に戻します"))
        self.canvas.view_changed.connect(lambda: self.symmetry_actions[self.canvas.symmetry].setChecked(True))

    def build_ruler_menu(self, menu):
        """表示のメニューの「定規」と「形を整える」。ブラシの設定の「定規」「描いて止めると形を整える」と同じ設定"""
        from PySide6.QtGui import QActionGroup
        from chatdraw.assist import RULERS
        menu.setToolTipsVisible(True)
        group = QActionGroup(menu)
        self.ruler_actions = {}
        for key, label in (("", "なし"),) + tuple(RULERS.items()):
            a = QAction(label, menu, checkable=True)
            a.setToolTip("なぞる線と直線を、この定規に沿わせます" if key else "定規を切ります")
            a.triggered.connect(lambda _=False, k=key: self.ruler.setCurrentIndex(self.ruler.findData(k)))
            group.addAction(a)
            menu.addAction(a)
            self.ruler_actions[key] = a
        self.ruler_actions[""].setChecked(True)
        menu.addSeparator()
        menu.addAction(QAction("定規の点を初めの所に戻す", menu, triggered=lambda: self.canvas.set_ruler_point(0, None),
                               toolTip="定規の中心・消失点・平行線の向きを、初めの所に戻します"))
        self.quickshape_action = QAction("描いて止めると形を整える", menu, checkable=True,
                                         toolTip="ペンで描き終えて少し止めると、直線・円・楕円・四角・三角に整えます")
        self.quickshape_action.toggled.connect(self.quickshape.setChecked)
        self.quickshape.toggled.connect(self.quickshape_action.setChecked)
        menu.addAction(self.quickshape_action)
        self.canvas.view_changed.connect(lambda: self.ruler_actions[self.canvas.ruler].setChecked(True))
        self.canvas.shaped.connect(lambda name: self.statusBar().showMessage(f"{name}に整えました（元に戻すで整える前の線に戻ります）", 4000))

    def copy_image(self, path: str | None = None):
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setImage(QImage(path) if path else self.canvas.flatten())
        self.statusBar().showMessage("絵をコピーしました", 3000)

    def open_crashlog(self):
        """落ちたときの記録（crash.log）を開く。無ければ無いと知らせる"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from chatdraw import crashlog
        p = crashlog.path()
        if not p.exists():
            self.notify("落ちた記録はありません", "info", str(p))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def open_folder(self, path: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def show_history_image(self, path: str):
        """履歴で選んだ絵をキャンバスに出す。出した絵は「固定」すると、新しく描いても入れ替わらない"""
        try:
            self.canvas.replace_with_image(path, "AI の絵")
        except ValueError as e:
            self.notify("絵を出せません", "error", f"{e}（消したか、動かした絵です）")
            return
        self._record()

    def layer_from_file(self, path: str, name: str) -> bool:
        """絵をレイヤーとして重ねる。読めない絵（消した・動かした）は知らせて止める"""
        try:
            self.canvas.add_image_layer(path, name)
        except ValueError as e:
            self.notify("絵を重ねられません", "error", f"{e}（消したか、動かした絵です）")
            return False
        return True

    def _set_pinned(self, on: bool):
        """固定を外したら、いちばん新しい絵を出す（固定の間に描いた絵が出ないままにしない）"""
        self.statusBar().showMessage("表示する絵を固定しました。新しい絵は履歴に入ります" if on else "固定を外しました。最新の絵を出します", 4000)
        if not on and self.images:
            self.show_history_image(self.images[-1])
            self.history.setCurrentRow(0)

    def _record(self):
        if self.recorder.enabled:   # 先に Qt で縮めてから渡す（元の大きさで PIL に移すと 30 ミリ秒ほどかかった）
            from chatdraw.timelapse import MAX_SIDE
            img = self.canvas.flatten()
            if max(img.width(), img.height()) > MAX_SIDE:
                img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.recorder.add(qimage_to_pil(img))

    def _set_timelapse(self, on: bool):
        self.recorder.enabled = on
        self.settings.set("timelapse", "記録する" if on else "記録しない")

    def open_timelapse(self):
        from chatdraw.timelapse import TimelapseDialog
        TimelapseDialog(self.recorder, self, Path(self.settings.get("output_dir"))).show()

    def open_player(self):
        from chatdraw.timelapse import open_player
        open_player(self, Path(self.settings.get("output_dir")))

    def open_3d(self, path: str):
        from chatdraw.to3d import To3DDialog
        To3DDialog(path, self).show()

    def canvas_menu(self, gpos):
        """絵の上の右クリック（右ボタンを動かさずに離したとき）。よく使う操作をまとめる"""
        self.build_canvas_menu(gpos).exec(gpos)

    def build_canvas_menu(self, gpos=None):
        """右クリックのメニューを作って返す（試験はこれを開かずに押す）"""
        from PySide6.QtWidgets import QMenu
        from chatdraw import shortcuts
        c = self.canvas
        m = QMenu(self)
        m.setToolTipsVisible(True)
        # よく使う物を上に、1 回で押せる所に置く（赤ペンを「道具」の奥に入れていたら見つからなかった）
        if "redpen" in self.tool_actions:
            m.addAction("赤ペンで直す所を囲む（T）", self.tool_actions["redpen"].trigger).setToolTip(
                "囲んで指示を書き、「描く」を押すと囲んだ所だけを AI が直します")
        if c.redpen.marks or c.selection is not None:
            # 「描く」を直すにして押すのと同じ道を通す（右クリックから仕上げと同じ手数で直せるように）
            m.addAction("囲んだ所を直す", self.fix_marked).setEnabled(not self.thread)
        m.addAction(self.shared["inspect"])
        if c.redpen.marks:
            m.addAction("赤ペンの印を消す", c.redpen.clear)
        # 番号の丸の上で右クリックしたら、その印だけを直す・消す
        n = c.redpen.number_at(c.mapToScene(c.viewport().mapFromGlobal(gpos)), c.zoom()) if gpos is not None else 0
        if n:
            m.addAction(f"印 {n} の指示を書き直す", lambda: self.edit_note(n))
            m.addAction(f"印 {n} を消す", lambda: c.redpen.remove(n)).setToolTip("元に戻すで戻せます")
            m.addSeparator()
        from chatdraw import fixmenu
        fixmenu.add_to_menu(self, m, n)   # 修正依頼と、模型を使わない整える・揃える・消す（chatdraw/fixmenu.py の 1 か所）
        # 言葉で指示する。登録した指示は shortcuts.fill_menu が小さなメニューに入れずに上へ並べ、1 回で呼べる
        m.addAction("言葉で指示…", self.open_text_instruction).setToolTip(
            "言葉を書いて、今の絵（囲みがあれば囲みの中）を直す・加工する・描くことができます。書いた言葉は登録できます")
        m.addSeparator()
        m.addAction("元に戻す（Ctrl+Z）", c.undo).setEnabled(bool(c.undo_stack) or (c.tool == "redpen" and bool(c.redpen.marks)))
        m.addAction("やり直す（Ctrl+Y）", c.redo).setEnabled(bool(c.redo_stack) or (c.tool == "redpen" and bool(c.redpen.undone)))
        m.addSeparator()
        shortcuts.fill_menu(self, m, self.shortcut_store())   # ★・よく使う物を上に、残りは処理の種類ごと
        m.addSeparator()
        # 道具・表示・選択は左端の帯やメニューと同じ操作を足す（名前もキーも、今の道具の印もそろう）
        tools = m.addMenu("道具")
        for key in ("pen", "eraser", "eyedropper", "select", "lasso", "polygon", "hand", "redpen"):
            if key in self.tool_actions:
                tools.addAction(self.tool_actions[key])
        shapes = tools.addMenu("図形")
        for key in ("line", "rect", "ellipse", "polyshape", "regpoly"):
            shapes.addAction(self.tool_actions[key])
        view = m.addMenu("表示")
        for k in ("fit", "actual", "rotate_left", "rotate_right", "rotate_reset", "flip_view", "view_reset", "grid"):
            view.addAction(self.shared[k])
        m.addAction(self.shared["add_layer"])
        if c.selection is not None:
            sm = m.addMenu("選択範囲")
            for k in ("sel_clear", "sel_fill", "copy", "cut"):
                sm.addAction(self.shared[k])
            sm.addAction(self.shared["deselect"])
        else:
            m.addAction("絵をコピー", self.copy_image)
        m.addAction(self.shared["paste"])
        m.addSeparator()
        m.addAction("この絵を AI で描き直す（もう一度描く）", self.draw_again).setEnabled(bool(self.last_text) and not self.thread)
        pin = m.addAction("表示する絵を固定する")
        pin.setCheckable(True)
        pin.setChecked(self.pin_action.isChecked())
        pin.toggled.connect(self.pin_action.setChecked)
        m.addAction("タイムラプスを見る…", self.open_timelapse)
        m.addSeparator()
        m.addAction(self.shared["new"])
        m.addAction("画像を開く…", self.open_image).setToolTip("作業ファイルか絵を開きます")
        return m

    # ---- どこで右クリックしても出るメニュー ----
    AREA_NAMES = {"color": "色", "brushes": "ブラシ", "library": "ライブラリー", "chat": "AI", "history": "履歴",
                  "layers": "レイヤー", "view": "表示", "talk": "チャット", "progress": "進み"}

    def common_menu(self, m):
        """どの欄の右クリックにも出す操作。新しく描く・開く・ショートカット"""
        from chatdraw import shortcuts
        m.setToolTipsVisible(True)
        m.addAction("新しく描く（書く欄へ）", self.start_new_drawing).setToolTip("書く欄に移ります。描いてほしい絵を書いて Enter で描きます")
        m.addAction(self.shared["new"])
        m.addAction("画像を開く…", self.open_image).setToolTip("作業ファイルか絵を開きます")
        m.addAction("画像を開いて直す…", self.open_to_edit).setToolTip("手元の絵を開き、赤ペンで囲んで直せる形にします")
        if "redpen" in getattr(self, "tool_actions", {}):
            m.addAction("赤ペンで直す所を囲む（T）", self.tool_actions["redpen"].trigger).setToolTip("絵の上で囲んで指示を書き、「描く」で囲んだ所だけを直します")
        shortcuts.fill_menu(self, m.addMenu("ショートカット"), self.shortcut_store())
        return m

    def area_menu(self, key: str):
        """欄 key の空いた所の右クリックのメニュー。その欄の操作と、どこでも使える操作を出す"""
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        if key == "history":
            m.addAction("ごみ箱…", self.open_trash).setToolTip("消した絵を戻す・本当に消す")
        elif key == "layers":
            m.addAction("レイヤーを足す", self.canvas.add_layer)
        elif key == "talk":
            m.addAction("書く欄へ", self.entry.setFocus)
        elif key == "library":
            from chatdraw import folders
            m.addAction("ディレクトリを開く", lambda: folders.open_folder(self.library.root)).setToolTip("ライブラリーの絵と資料の置き場を開きます")
        if m.actions():
            m.addSeparator()
        self.common_menu(m)
        if key in self.AREA_NAMES and hasattr(self, "panels") and key in self.panels:
            m.addSeparator()
            d = self.panels[key][0]
            m.addAction(f"「{self.AREA_NAMES[key]}」の欄を隠す", d.hide).setToolTip("表示メニューからまた出せます")
        return m

    def start_new_drawing(self):
        self.mode.setCurrentIndex(0)
        self.entry.setFocus()

    # ---- 右クリックのショートカット（chatdraw/shortcuts.py） ----
    def shortcut_store(self):
        from chatdraw import shortcuts
        if getattr(self, "_shortcut_store", None) is None:
            self._shortcut_store = shortcuts.Store(self.layout_store)   # 利用者の設定（更新で消さない）
        return self._shortcut_store

    def run_shortcut(self, sid: str):
        """ショートカットを押したとき。使えなければ理由を出して止めない。使った回数を数えて並びに使う"""
        from chatdraw import shortcuts
        store = self.shortcut_store()
        s = next((s for s in shortcuts.all_items(self, store) if s.id == sid), None)
        if s is None:
            self.notify("そのショートカットはありません", "info", "消したか、名前が変わりました")
            return None
        if not s.ready:
            self.notify(f"{s.label}は使えません", "info", s.reason)
            return None
        if self.thread:
            self.statusBar().showMessage("ほかの処理の途中です。終わってから押してください", 6000)
            return None
        store.count(sid)
        return s.run()

    def fix_with_text(self, text: str):
        """指示の言葉で今の絵を直す。囲み（赤ペン・選択）があれば囲みの中、無ければ絵全体を直す。
        描く処理は「直す」で頼んだときと同じ道（_draw_now）を通す"""
        from PySide6.QtCore import QRect
        if self.thread:
            self.statusBar().showMessage("描いている途中です。終わってから頼んでください", 6000)
            return
        whole = not self.canvas.redpen.marks and self.canvas.selection_mask() is None
        if whole:   # 囲みが無ければ、絵全体を選んだ形で頼み、頼み終えたら選択を戻す
            w, h = self.canvas.size_px()
            self.canvas.set_selection(QRect(0, 0, w, h))
        self.mode.setCurrentIndex(2)
        self.entry.setText(text)
        try:
            self._draw_now(text)
        finally:
            if whole:
                self.canvas.set_selection(None)
        self.entry.clear()

    def add_prompt_shortcut(self, text: str | None = None, name: str | None = None) -> str:
        """書く欄の言葉（空なら尋ねる）を、右クリックから選べる指示として登録する。返すのは id（やめたら空）"""
        from PySide6.QtWidgets import QInputDialog
        if not isinstance(text, str):   # メニューから呼ぶと checked の真偽が来る
            text = self.entry.text().strip()
            if not text:
                text, ok = QInputDialog.getText(self, "指示を登録", "直しの頼みの言葉（例: 目を大きく、背景を夕焼けに）")
                if not ok:
                    return ""
        text = (text or "").strip()
        if not text:
            return ""
        if name is None:
            name, ok = QInputDialog.getText(self, "指示を登録", "右クリックに出す名前", text=text[:20])
            if not ok:
                return ""
        sid = self.shortcut_store().add(name, text)
        self.notify("指示を登録しました", "ok", "絵の上の右クリックの「指示で直す」から選べます")
        return sid

    def open_pick_shortcuts(self):
        """右クリックに出す加工を選ぶ窓"""
        from chatdraw import shortcuts
        dlg = shortcuts.picker(self, self.shortcut_store())
        dlg.show()
        self._pick_dialog = dlg
        return dlg

    def open_text_instruction(self):
        """言葉で指示する窓。書いた言葉で今の絵（囲みがあれば囲みの中）を直す・加工する・描く。名前を付けて登録もできる"""
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
        from chatdraw import voice
        from chatdraw.chatpanel import EnterEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("言葉で指示")
        lay = QVBoxLayout(dlg)
        where = "囲んだ所" if (self.canvas.redpen.marks or self.canvas.selection is not None) else "絵全体"
        dlg.where = QLabel(f"直す所: {where}")
        dlg.where.setToolTip("赤ペンか四角の選択で囲んでから開くと、囲んだ所だけを直します")
        lay.addWidget(dlg.where)
        row = QHBoxLayout()
        dlg.edit = EnterEdit("例: 目を大きく / 線画にして / 夕焼けの海辺を描いて", lines=2)
        dlg.edit.setToolTip("Enter で行います（Shift+Enter で改行）。日本語でも英語でも書けます")
        dlg.mic = voice.mic_button(dlg.edit, parent=dlg)
        row.addWidget(dlg.edit, 1)
        row.addWidget(dlg.mic)
        lay.addLayout(row)
        buttons = QHBoxLayout()
        dlg.run = QPushButton("行う")
        dlg.run.setObjectName("primary")
        dlg.run.setToolTip("書いた言葉で、今の絵を直す・加工する・描きます。結果は一番上の新しいレイヤーに置きます（Enter）")
        dlg.save = QPushButton("登録…")
        dlg.save.setToolTip("書いた言葉に名前を付けて、右クリックから 1 回で呼べるようにします")
        close = QPushButton("閉じる")
        for b in (dlg.run, dlg.save, close):
            buttons.addWidget(b)
        lay.addLayout(buttons)

        def run():
            text = dlg.edit.text().strip()
            if not text:
                dlg.edit.setFocus()
                return
            dlg.accept()
            self.text_instruction(text)

        def save():
            text = dlg.edit.text().strip()
            if text:
                dlg.saved = self.add_prompt_shortcut(text)
        dlg.edit.returnPressed.connect(run)
        dlg.run.clicked.connect(run)
        dlg.save.clicked.connect(save)
        close.clicked.connect(dlg.reject)
        dlg.resize(460, 160)
        dlg.show()
        dlg.edit.setFocus()
        self._text_dialog = dlg
        return dlg

    def text_instruction(self, text: str):
        """言葉の指示を行う。加工の名前があれば加工、「〜を描いて」なら新しく描く、それ以外は今の絵を直す。
        どれも AI の欄・右クリックと同じ関数を通す（日本語は描く処理の中の言葉の直しを通り、そのまま絵の模型に渡らない）"""
        from chatdraw import chatplan, finishers
        from chatdraw.assistant import draw_request
        text = (text or "").strip()
        if not text:
            return
        if self.thread:
            self.statusBar().showMessage("描いている途中です。終わってから頼んでください", 6000)
            return
        entries = [{"name": n, "label": f.label} for n, f in finishers.REGISTRY.items()]
        plan = chatplan.parse(text, entries)
        if any(st not in ("draw", "fix") for st in plan.steps) or plan.repeat > 1 or plan.export is not None:
            self.run_plan(plan)
            return
        if draw_request(text) is not None:
            self.mode.setCurrentIndex(0)
            self.entry.setText(plan.body or text)
            self.send()
            return
        self.fix_with_text(text)

    def open_shortcuts(self):
        from chatdraw import shortcuts
        dlg = shortcuts.dialog(self, self.shortcut_store())
        dlg.show()
        self._shortcut_dialog = dlg
        return dlg

    def make_transparent(self):
        """透過。人物を切り抜いた透明の地の絵を、一番上の新しいレイヤーに置く（元の絵は残す）。
        切り抜きはアニメの切り抜きの模型（tools/gen/layers.anime_cut、isnet-anime）で行う。部品が無いときは、
        四隅から続く地の色を透明にする方法に替えて、替えたことを知らせる"""
        import tempfile
        src = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        src.save(tmp)
        out = self._finished_path("transparent")

        def work():
            how = "人物を切り抜きました"
            try:
                from chatdraw import paths
                paths.use_tools_gen()
                import layers as gen_layers
                cut = gen_layers.anime_cut(tmp)
            except ImportError:
                from chatdraw import logo
                cut = logo.remove_background(src)
                how = "切り抜きの部品が無いので、四隅から続く地の色を透明にしました"
            finally:
                Path(tmp).unlink(missing_ok=True)
            out.parent.mkdir(parents=True, exist_ok=True)
            cut.save(out)
            return out, how

        def done(got):
            if isinstance(got, BaseException):
                self.notify("透過できませんでした", "error", str(got))
                return
            path, how = got
            self.put_result(str(path), "透過")
            self.dirty = True
            self.notify(how, "ok", "元の絵は下のレイヤーに残しています。下のレイヤーを隠すと透過の絵だけになります")
        self.statusBar().showMessage("透過しています（初めは切り抜きの模型を取ります）…")
        self.in_background(work, done, "透過")

    def remove_background(self):
        """四隅から続く背景の色を透明にした絵で、キャンバスを置き換える（元に戻すで戻せる）。囲みがあれば囲みの中だけ消す"""
        from chatdraw import postfx
        from PIL import ImageChops
        src = qimage_to_pil(self.canvas.flatten()).convert("RGBA")
        mask = self._region_mask()
        path = self._finished_path("nobg")

        def work():   # 塗りつぶしと書き出しは裏の糸
            out = postfx.paper_to_alpha(src)
            if mask is not None:   # 囲みの外は元の不透明さのまま
                from chatdraw.finishers import binary
                keep = ImageChops.invert(binary(mask, src.size))
                out.putalpha(ImageChops.lighter(out.getchannel("A"), ImageChops.multiply(keep, src.getchannel("A"))))
            path.parent.mkdir(parents=True, exist_ok=True)
            out.save(path)
            return path

        def done(got):
            if isinstance(got, BaseException):
                self.notify("背景を消せませんでした", "error", str(got))
                return
            self.canvas.replace_with_image(str(got), "背景を消した絵")
            self.dirty = True
            self.notify("背景を消しました", "ok", "元に戻すで戻せます")
        self.statusBar().showMessage("背景を消しています…")
        self.in_background(work, done)

    def redo_from(self, path: str):
        """履歴の絵と同じ頼み・種・画風を、AI の欄とチャットに戻す。押せば同じ設定で描ける"""
        from chatdraw import finishers
        meta = finishers.sidecar(path)   # PNG に埋めた頼み。前の版の絵は隣の .json
        if not meta:
            self.notify("設定が残っていません", "info", "この絵には描いたときの設定が残っていません")
            return
        self.entry.setText(meta.get("text", ""))
        self.ai_panel.seed.setValue(int(meta.get("seed", 0)))
        self.ai_panel.seed_lock.setChecked(True)
        self.ai_panel.set_style(meta.get("style_name", "おまかせ"))
        self.ai_panel.set_count(1)
        if meta.get("mode") in ("新規", "ラフから"):
            self.mode.setCurrentText(meta["mode"])
        self.entry.setFocus()
        self.notify("同じ設定にしました", "ok", f"種 {meta.get('seed')} を固定しました。「描く」で同じ絵を描きます")

    def _studio_from_settings(self) -> Studio:
        """設定の模型で描く仕組みを作る。前と同じ絵の模型なら、読んだ物をそのまま使う（7GB を読み直さない）"""
        from chatdraw.models import IMAGES
        from chatdraw.setup import AUTO
        g = self.settings.get
        image, words = g("image_model"), g("words_model")
        from chatdraw.ratings import is_blocked
        if is_blocked(image):   # ブロックした模型は、設定に残っていても使わない
            image = AUTO
        if image == AUTO:
            from chatdraw.choose import choose_image
            first = choose_image("", "", have=self.have_image_models())[0] or IMAGES[0]
            image, steps, guidance = first.repo, first.steps, first.guidance
        else:
            steps, guidance = g("steps"), g("guidance")
        old = getattr(self, "studio", None)
        if old is not None and getattr(old.painter, "model", None) != image and not getattr(self, "thread", None) \
                and callable(getattr(old.painter, "unload", None)):
            old.painter.unload()   # 模型を替えたら、前の模型を降ろしてから次を読む（2 つを同時にメモリに置かない）
        painter = old.painter if old is not None and getattr(old.painter, "model", None) == image else Painter(image)
        painter.steps, painter.guidance = steps, guidance
        painter.lora = str(self.layout_store.value("lora", "") or "")
        painter.lora_scale = int(self.layout_store.value("lora_scale", 80)) / 100
        studio = Studio(Words(None if words == AUTO else Path(words)), painter, Path(g("output_dir")))
        studio.image_auto, studio.words_auto = g("image_model") == AUTO, words == AUTO
        studio.way = {"1つの模型で描く": "one", "構図と仕上げを分けて描く": "two"}.get(g("draw_way"), "auto")
        return studio

    def open_help(self, key: str):
        from chatdraw.helpview import HelpDialog
        HelpDialog(key, self).show()

    def open_logs(self):
        """記録（chatdraw.log、setup.log）の置き場を開く。困ったときに中を見たり、渡したりするため"""
        from chatdraw.folders import open_folder
        open_folder(DATA)

    def open_keys(self):
        from chatdraw.keys import KeyDialog
        if KeyDialog(self, self.layout_store).exec():
            self.statusBar().showMessage("キーの設定を保存しました", 4000)

    def reset_layout(self):
        """欄と帯を初めの並びに戻し、ウィンドウを画面に収める（並びが崩れて操作できなくなったときの戻り道）"""
        from chatdraw.fit import fit
        self._all_hidden = False
        if getattr(self, "ai_tabs", None) is not None:
            self.ai_tabs.reset()   # 外へ出した AI の欄のタブも戻し、タブの順も初めの形にする
        self._show_all(True)
        for d, _area in self.panels.values():
            d.setFloating(False)
        self.arrange()
        self.showNormal()
        area = self.screen().availableGeometry()
        self.resize(min(1400, area.width() - 40), min(900, area.height() - 60))
        fit(self)

    def reset_confirms(self):
        from chatdraw import confirm
        n = confirm.forget(self)
        self.notify("確かめの窓をまた出します" if n else "聞かないにした窓はありません", "ok")

    def open_settings(self):
        """設定ウィンドウを開き、保存されたら描く仕組みに当てる。絵の模型を替えたときだけ読み直す"""
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            g = self.settings.get
            self.studio = self._studio_from_settings()
            self.strength.setValue(int(g("rough_follow") * 100))
            self.check_ai()
            self.canvas.set_cursor_style(g("cursor"))
            self.statusBar().showMessage("設定を保存しました")

    def ask_models(self, force: bool = False):
        """初めての起動か、絵の模型が足りなければ、候補を見せて選んでもらう。force なら入れ替えと更新の画面を開く"""
        from chatdraw.setup import SetupDialog, missing
        first = not int(self.settings.store.value("setup_done", 0))
        if not (force or first or missing()["image"]):
            return
        if SetupDialog(self.settings, self, first=not force).exec():
            self.studio = self._studio_from_settings()   # 選んだ模型で描き直す
            self.check_ai()

    def upgrade_models(self):
        """使っている言葉の模型を、完全に上回る新しい模型があれば裏で取って乗り換える。古いファイルは消さない"""
        from chatdraw.models import SUPERSEDED, WORDS, offered_words
        from chatdraw.setup import Fetcher, has_words, words_path
        # 言葉の模型は利用者に選ばせず、確かめていちばん点の高い物を使う。利用者が自分で置いた模型（一覧に無い物）はそのまま
        from chatdraw.manager import words_chosen
        if words_chosen(self.settings):   # 利用者が選んだ物（「使わない」を含む）は勝手に替えない
            return
        now = self.settings.get("words_model")
        best = offered_words()
        new = best[0] if best else None
        known = {m.file for m in WORDS} | set(SUPERSEDED)
        if new is None or Path(now).name == new.file or (now not in ("", "auto") and Path(now).name not in known):
            return

        def switch(err: str = ""):
            if err:
                self.statusBar().showMessage(f"{new.name} に乗り換えられませんでした", 6000)
                return
            self.settings.set("words_model", str(words_path(new)))
            self.studio = self._studio_from_settings()
            self.notify(f"言葉の模型を {new.name} に乗り換えました", "ok")
        if has_words(new):
            switch()
            return
        import threading
        self.upgrader = Fetcher()
        self.upgrader.finished.connect(switch, Qt.QueuedConnection)
        self.watch_fetch(self.upgrader, "言葉の模型")
        self.statusBar().showMessage(f"新しい言葉の模型 {new.name} を裏で取っています", 6000)
        threading.Thread(target=self.upgrader.run, args=(None, new), daemon=True).start()

    def ask_words_once(self, pick=None):
        """言葉の模型を一度だけ選んでもらう。選んだ物（「使わない」を含む）は覚え、次の起動からは聞かない。
        変えるのは模型の管理から。pick は試験で窓の代わりに答えを返す関数（items を受けて 1 つ返す。None はやめた）"""
        from chatdraw.manager import choose_words, words_chosen
        from chatdraw.models import offered_words
        from chatdraw.setup import has_words, words_path
        if words_chosen(self.settings):
            return
        offered = offered_words()
        if not offered:
            return   # 選べる物が無いうちは聞かない（聞いても「使わない」しか無い）
        labels = [f"{m.name}（{m.gb:.1f}GB{'・取得済み' if has_words(m) else ''}）" for m in offered] + ["使わない"]
        now = Path(self.settings.get("words_model") or "").name
        first = next((i for i, m in enumerate(offered) if m.file == now), 0)
        if pick is None:
            from PySide6.QtWidgets import QInputDialog
            got, ok = QInputDialog.getItem(self, "言葉の模型", "日本語の頼みとチャットに使う模型を選んでください。\n"
                                           "選んだ物を覚え、次からは聞きません。あとで「模型の管理」から変えられます。",
                                           labels, first, False)
            got = got if ok else None
        else:
            got = pick(labels)
        if got is None or got == "使わない":
            choose_words(self.settings, "")
            self.statusBar().showMessage("言葉の模型を使いません。使うときは「模型の管理」から選びます", 6000)
        else:
            m = offered[labels.index(got)]
            choose_words(self.settings, str(words_path(m)))
            if not has_words(m):
                import threading
                from chatdraw.setup import Fetcher
                self.words_fetcher = Fetcher()
                self.words_fetcher.finished.connect(lambda _err="": (setattr(self, "studio", self._studio_from_settings()),
                                                                   self.check_ai()), Qt.QueuedConnection)
                self.watch_fetch(self.words_fetcher, "言葉の模型")
                threading.Thread(target=self.words_fetcher.run, args=(None, m), daemon=True).start()
        self.studio = self._studio_from_settings()

    # ---- AI のメニュー: 模型の切り替え ----
    def rescan_models(self):
        """手元にある絵の模型を裏の糸で数え直す。模型 1 つごとに置き場を見に行くので、100 余りの模型で
        画面の糸が 50 ミリ秒以上（Windows の大きな置き場ではもっと）止まり、メニューを開くたびに引っかかった"""
        if getattr(self, "_scanning", False):
            self._rescan_again = True
            return
        self._scanning, self._rescan_again = True, False
        from chatdraw.models import all_images
        from chatdraw.setup import has_image
        every = all_images()

        def done(have):
            self._scanning = False
            if isinstance(have, BaseException):
                return
            changed = have != self._have_images
            self._have_images = have
            if changed:
                self._refresh_ai_menu()
            if self._rescan_again:
                self.rescan_models()
        self.in_background(lambda: {m.repo for m in every if has_image(m)}, done, "模型を調べる")

    def installed_images(self, models) -> set[str]:
        """models のうち手元にある物。まだ一度も数えていなければ（起動の初めだけ）その場で数える"""
        if getattr(self, "_have_images", None) is None:
            from chatdraw.models import all_images
            from chatdraw.setup import has_image
            self._have_images = {m.repo for m in all_images() if has_image(m)}
        return {m.repo for m in models if m.repo in self._have_images}

    def have_image_models(self) -> list:
        """手元にある絵の模型（裏で数えて覚えた物を使う）"""
        from chatdraw.models import all_images
        every = all_images()
        have = self.installed_images(every)
        return [m for m in every if m.repo in have]

    def _fill_ai_menu(self):
        """模型の一覧を作り直す。開くときと、取った・消した・点・★・非表示が変わったとき（ratings.changed）に呼ぶ"""
        from chatdraw.models import catalog_images, manual_images, pick
        from chatdraw.ratings import is_blocked, is_favorite, rating_text, set_favorite
        from chatdraw.setup import AUTO
        menu = self.ai_menu
        menu.clear()
        now_image = self.settings.get("image_model")
        # 出すのは、推奨に届いた模型と手元にある模型（手元の物と ★ が先）。非表示にした物は出さない
        catalog = catalog_images()
        have = self.installed_images(catalog)
        listed = pick(catalog, "推奨（確かめ済み）", have=have)
        images = listed + [m for m in manual_images() if not is_blocked(m.repo)]
        menu.addSection("絵の模型")
        group = QActionGroup(menu)
        auto = QAction("おまかせ", menu, checkable=True)
        auto.setToolTip("描くときに、手元の模型から頼みに合い点の高い物を選びます")
        entries = [(AUTO, auto)]
        for m in images:
            label = ("★ " if is_favorite(m.repo) else "") + m.name + (f"　{rating_text(m)}" if m in listed else "")
            ok = m.repo in have or m not in listed
            entries.append((m.repo, QAction(label if ok else f"{label}（未取得）", menu, checkable=True)))
        for key, act in entries:
            act.setChecked(key == now_image)
            act.triggered.connect(lambda _=False, k=key: self.switch_model("絵の模型", k))
            group.addAction(act)
            menu.addAction(act)
        stars = menu.addMenu("★ お気に入り")
        stars.setToolTipsVisible(True)
        for m in listed:
            a = QAction(m.name, menu, checkable=True)   # 親はメニュー（作り直すと一緒に消える）
            stars.addAction(a)
            a.setChecked(is_favorite(m.repo))
            a.setToolTip("★ を付けた模型は一覧の先頭に出て、おまかせでも選ばれやすくなります")
            a.toggled.connect(lambda on, r=m.repo: set_favorite(r, on))
        menu.addSeparator()
        fix_menu = menu.addMenu("直しに使う模型")
        fix_menu.setToolTipsVisible(True)
        fix_menu.aboutToShow.connect(lambda: self._fill_fix_menu(fix_menu))
        self._fill_fix_menu(fix_menu)
        menu.addAction(QAction("模型の管理…", self, triggered=self.manage_models))

    def _open_ai_menu(self):
        """AI のメニューを開くとき。取った・消した直後でも古い一覧を出さないよう、手元の模型をその場で数え直す"""
        self._have_images = None
        self._ai_menu_stale = False
        self._fill_ai_menu()

    def _refresh_ai_menu(self):
        """模型の一覧を作り直す。開いているメニューの中身は押している最中に消さず、閉じたあとに作り直す"""
        if self.ai_menu.isVisible():
            self._ai_menu_stale = True
        else:
            self._fill_ai_menu()

    def _ai_menu_hidden(self):
        if getattr(self, "_ai_menu_stale", False):
            self._ai_menu_stale = False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._fill_ai_menu)

    def _models_changed(self):
        """模型の一覧が変わったら（取得・削除・ブロック・非表示・評価・★）、AI のメニューと模型の表示を作り直す"""
        self._refresh_ai_menu()
        self._show_model()
        self.rescan_models()   # 取った・消したあとの手元の模型は裏で数え直し、変わっていればメニューを作り直す

    def manage_models(self):
        if self.tour_first("manager", self.manage_models):
            return
        from chatdraw.manager import ModelManager
        ModelManager(self.settings, self).exec()
        self._have_images = None   # 取った・消した物があるかもしれないので、数え直すまで覚えを使わない
        self.studio = self._studio_from_settings()
        self.check_ai()
        self._fill_ai_menu()
        self.rescan_models()

    def switch_model(self, kind: str, key: str):
        self.feature_tour("model")
        """メニューで選んだ模型に替える。取っていなければ取ってから替える。消すことはしない"""
        from chatdraw.models import IMAGES, WORDS
        from chatdraw.setup import AUTO, SetupDialog, has_image, has_words, words_path
        if kind == "絵の模型":
            from chatdraw.models import all_images
            m = next((m for m in all_images() if m.repo == key), None)
            need = m is not None and not has_image(m) or key == AUTO and not any(has_image(x) for x in all_images())
        else:
            m = next((m for m in WORDS if m.file == key), None)
            need = m is not None and not has_words(m) or key == AUTO and not any(has_words(x) for x in WORDS)
            if m is None and key not in (AUTO, ""):
                from chatdraw.paths import find_gguf
                from chatdraw.manager import choose_words
                choose_words(self.settings, str(find_gguf(key) or key))   # 利用者が自分で置いた模型
                self.studio = self._studio_from_settings()
                self.check_ai()
                return
        if need:
            dlg = SetupDialog(self.settings, self, first=False)
            dlg.select(**({"image": key} if kind == "絵の模型" else {"words": key}))
            dlg.start(update=False)
            if not dlg.exec():
                return
            self._have_images = None   # 取ったばかりの模型を、おまかせの選びに入れる
        elif kind == "絵の模型":
            self.settings.set("image_model", key)
            if m is not None:
                self.settings.set("steps", m.steps)
                self.settings.set("guidance", m.guidance)
        else:
            from chatdraw.manager import choose_words
            choose_words(self.settings, key if key in (AUTO, "") else str(words_path(m)))
        self.studio = self._studio_from_settings()
        self.check_ai()
        self._fill_ai_menu()
        self.rescan_models()
        self.notify(f"{kind}を替えました", "ok")

    def show_preview(self, img):
        """AI が描いている途中の絵を、工程ごとにキャンバスの上に重ねて見せ、タイムラプスにも残す。
        描き終えたあとに遅れて届いた途中の絵は捨てる（仕上がった絵を隠さない）"""
        if self.thread is None:
            return
        self.canvas.show_overlay(qimage_from_pil(img))
        self.recorder.add(img)

    def put_result(self, path: str, name: str, replace: bool = False) -> bool:
        """AI の結果を置く。設定「AI の結果の置き場」が「別ファイル」なら新しい作業ファイル（別のウィンドウ）で開き、
        今のキャンバスには触らない。既定の「上のレイヤー」なら一番上の新しいレイヤーに置いて選ぶ。キャンバスに置いたら True"""
        if self.settings.get("result_place") == "別ファイル":
            self.open_in_new_file(path)
            return False
        self.canvas.place_result(path, name, replace=replace)
        return True

    def _put_fix(self, path: str, name: str) -> bool:
        """囲んだ所の直しは、直した所だけのレイヤーにして置く。絵全体の写しを重ねると、
        囲みの外まで同じ絵のレイヤーが積み重なり、邪魔で見分けにくかった"""
        import os
        import tempfile
        from PySide6.QtGui import QImage, QPainter
        if self.settings.get("result_place") == "別ファイル":
            return self.put_result(path, name)
        masks = list(self.canvas.redpen.masks())
        sel = self.canvas.selection_mask()
        if sel is not None:
            masks.append(sel)
        img = QImage(path)
        if not masks or img.isNull() or img.hasAlphaChannel():
            # Studio.fix は直した所だけを不透明にして返す。印で上書きすると、隠した印の所（直していない所）まで出た
            return self.put_result(path, name)
        img = img.convertToFormat(QImage.Format_ARGB32)
        alpha = QImage(img.size(), QImage.Format_Grayscale8)
        alpha.fill(0)
        q = QPainter(alpha)
        q.setCompositionMode(QPainter.CompositionMode_Lighten)
        for m in masks:   # 印ごとの直す所を重ねる（白が直す所）
            q.drawImage(0, 0, m.scaled(img.size()))
        q.end()
        img.setAlphaChannel(alpha)
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            img.save(tmp)
            return self.put_result(tmp, name)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def open_in_new_file(self, path: str):
        """絵を新しい作業ファイルとして、別のウィンドウで開く。今の作業ファイルはそのまま残る"""
        from PySide6.QtCore import QProcess
        args = ["--open", str(path)] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve()), "--open", str(path)]
        if not QProcess.startDetached(sys.executable, args):
            self.notify("別ファイルで開けませんでした", "error", str(path))

    def place(self, path: str):
        """描けた絵を置く。新しく描いて、まだ何も描いていないキャンバスなら絵を開く。
        キャンバスを元に描いたときと、描いている途中なら、元の絵を残して新しいレイヤーとして重ねる"""
        if self.mode.currentIndex() == 0:
            # 新しく描いた絵は、いつも同じ形で置く（キャンバスを置き換え、前の状態は元に戻すで戻せる）。
            # 前は、キャンバスの状態で置き換えたり上に重ねたりが変わり、大きさの違う絵が重なった
            self.put_result(path, f"AI の絵 {len(self.images)}", replace=True)
            self.origin_prompt = getattr(self, "last_text", "")   # 直しのときに、元の頼みと食い違いを見る
        else:
            self.put_result(path, f"AI の絵 {len(self.images)}")
            self.canvas.fit()   # 結果は全体表示で見せる
        self._placed = path

    def stop(self):
        """緊急停止。押したら必ず止まる。
        1. 止める旗を立てる（工程の区切りで止まる）
        2. 旗を見ない重い工程（模型の読み込み、言葉の模型の答え待ち、検品、仕上げ）の裏の糸へ Stopped を投げ込む
        3. 裏の糸の終わりを待たずに、画面をすぐ待機に戻す。止めた回の答えは捨てる（キャンバスは元のまま）
        4. 裏の糸が終わったら、メモリを返す（_reap）"""
        from chatdraw import engine
        t0 = time.time()
        engine.STOP.set()
        for st in (self.studio, getattr(self, "job_studio", None)):
            painter = getattr(st, "painter", None)
            if painter is not None:
                try:
                    painter.stop = True
                except AttributeError:
                    pass
        if getattr(self, "asking", False):   # 言葉の模型に頼みの種類を聞いている途中
            self.asking = False
            self._ask_token = getattr(self, "_ask_token", 0) + 1   # 返ってきた答えは捨てる
            self.button.setEnabled(True)
        worker, obj = self.thread, getattr(self, "_worker", None)
        if worker is None:
            self.statusBar().showMessage("止めました" if getattr(self, "asking", None) is False else "動いている処理はありません", 3000)
            self.activity.idle_check()
            return
        engine.kill_thread(getattr(obj, "tid", None))
        if obj is not None:
            obj.failed.connect(worker.quit)
            obj.done.connect(worker.quit)
        self._zombies = getattr(self, "_zombies", [])
        self._zombies.append((worker, obj, t0))
        worker.finished.connect(self._reap)
        if not worker.isRunning():
            worker.quit()
        self.thread, self._worker = None, None
        self.canvas.show_overlay(None)
        if self.activity.started is not None:
            self.activity.end("止めました")
        self.stop_button.setEnabled(False)
        self.button.setEnabled(True)
        self.progress_popup.tell("止めました", "キャンバスは元のままです")
        self.notify("止めました", "info", "")
        self.hide_progress_if_idle()
        self.last_stop_ui = time.time() - t0
        self.statusBar().showMessage(f"止めました（{self.last_stop_ui:.2f} 秒）", 4000)

    def finish_threads_before_close(self, wait_ms: int = 5000) -> bool:
        """描いている途中に閉じたら、止めて裏の糸の終わりを待つ。動いている QThread を消すと、Qt がアプリごと落とす
        （QThread: Destroyed while thread is still running）。待っても終わらなければ窓だけ隠し、終わってから閉じ直す。閉じてよければ True"""
        if self.thread is not None:
            self.stop()
        left = [w for w, _o, _t in getattr(self, "_zombies", []) if w.isRunning()]
        for w in left:
            w.wait(wait_ms)
        left = [w for w in left if w.isRunning()]
        if not left:
            return True
        self.closing_checked = True   # 保存を聞くのは 1 回だけ
        self.hide()
        for w in left:
            w.finished.connect(self.close, Qt.QueuedConnection)
        return False

    def _stale(self) -> bool:
        """止めた回の裏の処理から遅れて届いた知らせか。止めた回の絵はキャンバスに置かない"""
        src = self.sender()
        return src is not None and isinstance(src, (Job, Task)) and src is not getattr(self, "_worker", None)

    def _reap(self):
        """止めた回の裏の糸が終わった。糸を片付け、描きかけの物を捨ててメモリを返す"""
        import gc
        left = []
        for worker, obj, t0 in getattr(self, "_zombies", []):
            if worker.isRunning():
                left.append((worker, obj, t0))
                continue
            self.last_stop_secs = time.time() - t0
            worker.deleteLater()
            if obj is not None:
                obj.deleteLater()
        self._zombies = left
        gc.collect()
        torch = sys.modules.get("torch")
        if torch is not None:
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:   # noqa: BLE001  返せなくても止めたことは変わらない
                pass
        self.gc_guard()
        if getattr(self, "_unload_after", False) and not left:
            self._unload_after = False
            self.studio.painter.unload()

    def drawing(self) -> bool:
        return self.thread is not None

    def unload_model(self, repo: str | None = None) -> str:
        """読んだ絵の模型をメモリから降ろす。描いている途中なら止めて、終わってから降ろす"""
        painter = self.studio.painter
        if repo is not None and painter.model != repo:
            return "その模型は読んでいません"
        if self.drawing():
            self._unload_after = True
            self.stop()
            return "止めてから、メモリから降ろします"
        painter.unload()
        return "メモリから降ろしました。次に描くときに読み直します"

    def _redpen_changed(self):
        """赤ペンの印が増えた・消えたとき。印が無くなったら「直す」をやめて新しく描くに戻す。
        印が無いのに「直す」のままだと、次の頼みまで直しとして扱われた。
        道具はここでは替えない。印を付けたあと・直したあとに勝手にペンへ戻ると、続けて囲めなかった"""
        if hasattr(self, "layer_panel"):
            self._refresh_layers()
        c = self.canvas
        if c.redpen.marks or c.selection is not None:
            return
        if self.mode.currentIndex() == 2:
            self.mode.setCurrentIndex(0)

    def _mode_changed(self, i: int):
        # 直すとき（赤ペン）は描くボタンの文字を替え、押せば囲んだ所を直すと分かるようにする
        if hasattr(self, "button"):
            self.button.setText(" 囲んだ所を直す" if i == 2 else " 描く")
            self.button.setToolTip("赤ペンで囲んだ所だけを、書いた指示どおりに直します（Enter）。囲みの外は変えません" if i == 2
                                   else "AI で描く（Enter）")
        if i == 1 and hasattr(self, "layout_store"):
            self.feature_tour("rough")
        if i == 2 and hasattr(self, "layout_store"):
            self.feature_tour("redpen")
        self.size_pick.setEnabled(i == 0)          # 元に描くときはキャンバスの大きさで描く
        self.strength.setEnabled(i in (1, 2))
        self.strength_label.setEnabled(i in (1, 2))
        if i == 2 and self.strength.value() > 60:
            self.strength.setValue(45)   # 直すときは元の絵を土台に少しだけ変える（微調整）。足りなければもう一度直す
        self.strength.setToolTip("直す強さ。小さいほど元の絵のまま少しだけ直す" if i == 2 else
                                 "ラフに沿う強さ。大きいほどラフの線の形どおりに描く")

    def fail(self, why: str):
        if self._stale():
            return
        self.canvas.show_overlay(None)
        why = (why or "うまくいきませんでした").strip().splitlines()[0]   # 何が起きたかを 1 行で出す（「描けませんでした」の決まり文句は出さない）
        stop = "止め" in why
        self.say(why)
        if self.activity.started is not None:
            self.activity.end("止めました" if stop else why)
        # 進みの欄の 1 回分の外で落ちたときも、理由を右下に出す（出さないと何も起きなかったように見えた）
        self.progress_popup.tell("止めました" if stop else why, "" if stop else why)
        self.notify("止めました" if stop else why, "info" if stop else "error", "")
        self._end(why)

    def pick_color(self):
        c = QColorDialog.getColor(self.canvas.color, self, "色")
        if c.isValid():
            self.color_panel.set_color(c)

    def ask_text(self, pos):
        """文字の道具で押した所に置く文字を聞く。空なら何もしない"""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "文字", "置く文字（描く色・太さの 4 倍の大きさで置きます）")
        if ok and text:
            self.canvas.place_text(pos, text)

    def _brush_selected(self, name: str):
        if name not in self.canvas.brushes:
            return
        self.canvas.set_brush(name)
        b = self.canvas.brush
        for w, v in ((self.hardness, b.hardness), (self.flow_s, b.flow), (self.spacing, b.spacing)):
            w.blockSignals(True)
            w.setValue(int(v * 100))
            w.blockSignals(False)
        for w, v in ((self.size_pressure, b.size_pressure), (self.opacity_pressure, b.opacity_pressure)):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        key = "eraser" if name == "消しゴム" else "pen"
        if key in getattr(self, "tool_actions", {}):
            self.tool_actions[key].setChecked(True)

    def _tool_changed(self, key: str):
        """上の道具の設定の見出しを、選んだ道具の名前にする"""
        label = next(lb for k, lb, _s in TOOLS if k == key)
        self.tool_name.setText(label)
        if hasattr(self, "st_tool"):
            self.st_tool.setText(label)
        if hasattr(self, "fill_shapes_act"):
            self.fill_shapes_act.setVisible(key in ("rect", "ellipse", "polyshape", "regpoly"))
        if hasattr(self, "poly_sides_act"):
            self.poly_sides_act.setVisible(key == "regpoly")
        if hasattr(self, "brush_preview"):
            self.brush_preview.update()

    def arrange(self):
        """初期の配置。左に道具・色・ブラシ、右に AI・描いた絵と進み・レイヤー、真ん中を広く絵に使う"""
        brushes, opt, chat = self.panels["brushes"][0], self.panels["color"][0], self.panels["chat"][0]
        hist, layers = self.panels["history"][0], self.panels["layers"][0]
        for d, _area in self.panels.values():
            d.setFloating(False)
            d.show()
        self.addToolBar(Qt.LeftToolBarArea, self.tools)
        self.tools.show()
        self.addToolBar(Qt.TopToolBarArea, self.ribbon_bar)
        self.ribbon_bar.show()
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.options)
        self.options.show()
        if hasattr(self, "quick_bar"):
            self.addToolBar(Qt.TopToolBarArea, self.quick_bar)
            self.quick_bar.show()
        self.addToolBar(Qt.RightToolBarArea, self.panel_bar)
        self.panel_bar.show()
        self.addToolBar(Qt.BottomToolBarArea, self.bottom_bar)
        self.bottom_bar.show()
        from PySide6.QtCore import QTimer
        from chatdraw.layouts import recommended, settle
        recommended(self)
        QTimer.singleShot(0, lambda: settle(self))

    def apply_layout(self, fn, *args):
        """配置を当て、絵を新しい大きさに合わせる"""
        self._all_hidden = False   # Tab で隠したあとに配置を選んだとき、次の Tab で出したばかりの欄が隠れないように
        fn(self, *args)
        from PySide6.QtCore import QTimer
        from chatdraw.layouts import settle
        QTimer.singleShot(0, lambda: settle(self))
        QTimer.singleShot(0, self.canvas.fit)

    def build_layout_menu(self):
        """「配置」メニュー。決まった配置・寄せ・等分・自分の配置の保存と読み出し・書き出しと読み込み"""
        from PySide6.QtWidgets import QInputDialog
        from chatdraw import layouts as L
        menu = self.menuBar().addMenu("配置")
        self.layout_menu = menu

        def fill():
            menu.clear()
            for name in L.PRESETS:
                menu.addAction(self.shared[f"layout:{name}"])   # リボンの「おすすめ」と同じ操作
            menu.addSeparator()
            for label, where in (("左に寄せる", "left"), ("右に寄せる", "right"), ("真ん中に寄せる（絵を中央に）", "center")):
                menu.addAction(QAction(label, self, triggered=lambda _=False, w=where: self.apply_layout(L.align, w)))
            for n in (3, 5):
                menu.addAction(QAction(f"{n} 等分にする", self, triggered=lambda _=False, n=n: self.apply_layout(L.split, n)))
            menu.addSeparator()
            mine = L.saved_names(self.layout_store)
            if mine:
                sub = menu.addMenu("自分の配置")
                for name in mine:
                    sub.addAction(QAction(name, self, triggered=lambda _=False, n=name: (
                        L.load(self, self.layout_store, n), self.notify(f"「{n}」の配置にしました", "ok"))))
                rm = menu.addMenu("自分の配置を消す")
                for name in mine:
                    rm.addAction(QAction(name, self, triggered=lambda _=False, n=name: (
                        L.remove(self.layout_store, n), self.notify(f"「{n}」を消しました", "info"))))

            def save():
                name, ok = QInputDialog.getText(self, "今の配置を保存", "配置の名前")
                if ok and name.strip():
                    L.save(self, self.layout_store, name.strip())
                    self.notify(f"「{name.strip()}」として保存しました", "ok")
            menu.addAction(QAction("今の配置を保存…", self, triggered=lambda: self.feature_tour("layout_save", save)))
            menu.addSeparator()

            def export():
                path, _ = QFileDialog.getSaveFileName(self, "配置を書き出す", "layout.cdlayout.json", "配置 (*.json)")
                if path:
                    L.export(self, path)
                    self.notify("配置を書き出しました", "ok", Path(path).name)

            def import_():
                path, _ = QFileDialog.getOpenFileName(self, "配置を読み込む", "", "配置 (*.json)")
                if path:
                    name = L.import_(self, path)
                    self.notify(f"「{name}」の配置にしました" if name else "読み込めませんでした", "ok" if name else "error")
            menu.addAction(QAction("配置を書き出す…", self, triggered=lambda: self.feature_tour("layout_export", export)))
            menu.addAction(QAction("配置を読み込む…", self, triggered=lambda: self.feature_tour("layout_export", import_)))
        menu.aboutToShow.connect(fill)
        fill()

    def build_status(self):
        """下のステータスバー。左に知らせ、右に道具・座標・キャンバスの大きさ・レイヤー・AI の状態・拡大率を並べる。
        拡大率は押すと全体表示に戻る"""
        sb = self.statusBar()
        sb.setSizeGripEnabled(True)

        def cell(tip, w=0):
            lb = QLabel()
            lb.setObjectName("statusCell")
            lb.setToolTip(tip)
            if w:
                lb.setMinimumWidth(w)
            sb.addPermanentWidget(lb)
            return lb
        self.st_tool = cell("今の道具", 70)
        self.st_pos = cell("カーソルの位置（画素）", 90)
        self.st_size = cell("キャンバスの大きさ", 90)
        self.st_layer = cell("描いているレイヤー", 90)
        self.ai_label = cell("AI の状態")
        self.zoom_label = QPushButton("100%")
        self.zoom_label.setObjectName("statusButton")
        self.zoom_label.setToolTip("拡大率。押すと全体を表示します")
        self.zoom_label.clicked.connect(self.canvas.fit)
        sb.addPermanentWidget(self.zoom_label)
        self.canvas.zoomed.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        self.canvas.moved.connect(lambda x, y: self.st_pos.setText(f"{x}, {y}"))
        self.canvas.changed.connect(self._status_doc)
        self._status_doc()
        self.st_tool.setText(self.tool_name.text())

    def _status_doc(self):
        w, h = self.canvas.size_px()
        self.st_size.setText(f"{w}×{h}")
        if self.canvas.layers:
            self.st_layer.setText(self.canvas.layers[self.canvas.current].name)

    def build_bottom(self):
        """下の帯。表示と元に戻すの操作を、手の届く下に並べる。「ウィンドウ」から隠せ、上にも移せる"""
        from PySide6.QtWidgets import QSlider as _S
        bar = QToolBar("下の帯", self)
        bar.setObjectName("bottombar")
        bar.setIconSize(QSize(18, 18))
        S = self.shared
        bar.addAction(S["undo"])
        bar.addAction(S["redo"])
        bar.addSeparator()
        bar.addAction(S["fit"])
        self.zoom_slider = _S(Qt.Horizontal)
        self.zoom_slider.setRange(5, 800)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(180)
        self.zoom_slider.setToolTip("拡大率")
        self.zoom_slider.valueChanged.connect(lambda v: self.canvas.set_zoom(v / 100))
        self.canvas.zoomed.connect(lambda z: (self.zoom_slider.blockSignals(True), self.zoom_slider.setValue(int(z * 100)),
                                              self.zoom_slider.blockSignals(False)))
        from PySide6.QtWidgets import QWidgetAction
        zoom = QWidgetAction(self)   # 帯の編集で外して戻せるよう、操作として持つ
        zoom.setText("拡大率")
        zoom.setDefaultWidget(self.zoom_slider)
        S["zoom_slider"] = zoom
        bar.addAction(zoom)
        # 拡大率は数字でも見て入れられる（つまみだけだと今が何 % か分からなかった）
        from PySide6.QtWidgets import QSpinBox
        self.zoom_box = QSpinBox()
        self.zoom_box.setRange(5, 3200)
        self.zoom_box.setSuffix(" %")
        self.zoom_box.setValue(100)
        self.zoom_box.setToolTip("拡大率。数字を入れて Enter で変わります")
        self.zoom_box.setKeyboardTracking(False)
        self.zoom_box.valueChanged.connect(lambda v: abs(self.canvas.zoom() * 100 - v) >= 0.5 and self.canvas.set_zoom(v / 100))
        self.canvas.zoomed.connect(lambda z: (self.zoom_box.blockSignals(True), self.zoom_box.setValue(round(z * 100)),
                                              self.zoom_box.blockSignals(False)))
        zbox = QWidgetAction(self)
        zbox.setText("拡大率の数字")
        zbox.setDefaultWidget(self.zoom_box)
        S["zoom_box"] = zbox
        bar.addAction(zbox)
        bar.addAction(S["rotate_left"])
        bar.addAction(S["rotate_right"])
        # 角度のつまみ（-180〜180 度）。R を押しながら絵の上をドラッグしても回せる
        self.angle_slider = _S(Qt.Horizontal)
        self.angle_slider.setRange(-180, 180)
        self.angle_slider.setFixedWidth(120)
        self.angle_slider.setToolTip("表示の角度（0 度）。R を押しながら絵の上をドラッグしても回せます")
        self.angle_slider.valueChanged.connect(lambda v: self.canvas.set_angle(float(v)))

        def sync_angle():
            v = round(self.canvas.angle)
            self.angle_slider.blockSignals(True)
            self.angle_slider.setValue(v)
            self.angle_slider.blockSignals(False)
            self.angle_slider.setToolTip(f"表示の角度（{v} 度）。R を押しながら絵の上をドラッグしても回せます")
        self.canvas.view_changed.connect(sync_angle)
        ang = QWidgetAction(self)
        ang.setText("角度")
        ang.setDefaultWidget(self.angle_slider)
        S["angle_slider"] = ang
        bar.addAction(ang)
        bar.addAction(S["rotate_reset"])
        bar.addAction(S["flip_view"])
        bar.addAction(S["view_reset"])
        self.addToolBar(Qt.BottomToolBarArea, bar)
        self.bottom_bar = bar

    def build_shared_actions(self):
        """メニュー・リボン・帯・右クリックで共に使う操作。1 つの QAction を、出す所ごとに足す"""
        c = self.canvas
        rows = (("new", "new", "新規キャンバス", lambda: c.new_canvas(), "Ctrl+N", "白い新しいキャンバスにします（元に戻すで戻せます）"),
                ("open", "open", "開く…", self.open_image, "Ctrl+O", "作業ファイルか絵を開きます"),
                ("save", "save", "保存", self.save_project, "Ctrl+S", "作業ファイルに保存します"),
                ("trash", "trash", "ごみ箱…", self.open_trash, "", "消した絵を見て、元に戻すか本当に消します"),
                ("undo", "undo", "元に戻す", c.undo, "Ctrl+Z", ""),
                ("redo", "redo", "やり直す", c.redo, "Ctrl+Y", ""),
                ("redpen_clear", "", "赤ペンの印を全部消す", c.redpen.clear, "Ctrl+Shift+Backspace", ""),
                ("inspect", "", "検品する", self.inspect_now, "",
                 "今の絵の手・足・顔を検品し、崩れた所を赤ペンで囲みます。直しはしません（直すのは「囲んだ所を直す」）"),
                ("select_all", "select", "すべてを選択", c.select_all, "Ctrl+A", ""),
                ("deselect", "", "選択を解除", lambda: c.set_selection(None), "Ctrl+D", ""),
                ("sel_clear", "eraser", "選択範囲の中を消す", self.selection_clear, "", "選んだレイヤーの、選択範囲の中を消します（絵の上で Delete でも消せます。元に戻すで戻せます）"),
                ("sel_fill", "fill", "選択範囲を塗る", self.selection_fill, "Alt+Backspace", "選択範囲の中を描く色で塗ります"),
                ("copy", "", "コピー", self.selection_copy, "Ctrl+C", "選択範囲の中をコピーします。選択が無いときは見えている絵全体をコピーします"),
                ("cut", "", "切り取り", self.selection_cut, "Ctrl+X", "選択範囲の中をコピーして消します"),
                ("paste", "", "貼り付け", self.paste_clipboard, "Ctrl+V", "コピーした絵を一番上の新しいレイヤーに貼ります"),
                ("fit", "fit", "全体を表示", c.fit, "Ctrl+0", ""),
                ("actual", "zoom", "100%", c.actual, "Ctrl+1", "等倍で表示"),
                ("rotate_left", "", "左に回す", lambda: c.rotate_view(-15), "Ctrl+[", ""),
                ("rotate_right", "rotate", "右に回す", lambda: c.rotate_view(15), "Ctrl+]", ""),
                ("rotate_reset", "", "回転を戻す", c.reset_rotation, "Ctrl+\\", "表示の角度を 0 度に戻します"),
                ("view_reset", "fit", "表示をリセット", c.reset_view, "Ctrl+Alt+0",
                 "回転・左右反転・拡大・位置を初めに戻し、絵の全体を出します（絵は変えません）"),
                ("rotate_dial", "rotate", "角度を指定…", self.ask_angle, "",
                 "表示の角度を数字で決めます（R を押しながらドラッグでも回せます）"),
                ("zoom_in", "zoom", "拡大", lambda: c.set_zoom(c.zoom() * 1.25), "Ctrl+=", ""),
                ("zoom_out", "", "縮小", lambda: c.set_zoom(c.zoom() / 1.25), "Ctrl+-", ""),
                ("zoom_ask", "", "拡大率を指定…", self.ask_zoom, "", "拡大率を % の数字で決めます"),
                ("flip_view", "", "左右反転で表示", lambda: c.flip_view(), "Shift+H",
                 "絵を左右反転して見ます（絵は変えません）。崩れを見つけやすくなります"),
                ("grid", "", "グリッド", lambda: c.set_grid(not c.grid), "Ctrl+'", "絵の上に方眼を出します（保存する絵には入りません）"),
                ("op_history", "history", "操作の履歴…", self.show_op_history, "Ctrl+Alt+Z",
                 "元に戻すの履歴を出します。選ぶとその操作のあとまで戻ります"),
                ("add_layer", "layers", "新しいレイヤー", c.add_layer, "Ctrl+Shift+N", ""),
                ("delete_layer", "", "レイヤーを消す", c.delete_layer, "", "選んでいるレイヤーを消します（元に戻すで戻せます）"),
                ("dup_layer", "", "レイヤーを複製", c.duplicate_layer, "", "選んでいるレイヤーを、すぐ上に同じ絵で複製します"),
                ("layer_copy", "", "レイヤーをコピー", self.layer_copy, "Ctrl+Alt+C", "選んでいるレイヤーを、名前と不透明度ごとコピーします"),
                ("layer_cut", "", "レイヤーを切り取り", self.layer_cut, "Ctrl+Alt+X", "選んでいるレイヤーをコピーしてから消します"),
                ("layer_paste", "", "レイヤーを貼り付け", self.layer_paste, "Ctrl+Alt+V",
                 "コピーしたレイヤーを、選んでいるレイヤーのすぐ上に新しいレイヤーとして貼ります"),
                ("paste_in_place", "", "同じ位置に貼り付け", self.paste_in_place, "Ctrl+Shift+V",
                 "コピーした絵を、コピーした所と同じ位置の新しいレイヤーに貼ります"),
                ("copy_merged", "", "結合してコピー", self.copy_merged, "Ctrl+Shift+C",
                 "見えているレイヤーを重ねた絵の、選択範囲の中をコピーします（選択が無いときは全体）"),
                ("via_copy", "", "選択範囲をコピーして新しいレイヤーへ", lambda: c.layer_via(False), "Ctrl+J",
                 "選択範囲の中を同じ位置の新しいレイヤーに写します。選択が無いときはレイヤーを複製します"),
                ("via_cut", "", "選択範囲を切り取って新しいレイヤーへ", lambda: c.layer_via(True), "Ctrl+Shift+J",
                 "選択範囲の中を元のレイヤーから切り取り、同じ位置の新しいレイヤーに移します"),
                ("merge_down", "", "下のレイヤーと結合", c.merge_down, "", "選んでいるレイヤーを、すぐ下のレイヤーに結合します"),
                ("clear_layer", "", "レイヤーの中を消す", c.clear_layer, "", "選んでいるレイヤーの絵を全部消します（レイヤーは残ります）"),
                ("flip_layer_h", "", "レイヤーを左右反転", lambda: c.flip_layer(True), "", "選んでいるレイヤーの絵そのものを左右に反転します"),
                ("flip_layer_v", "", "レイヤーを上下反転", lambda: c.flip_layer(False), "", "選んでいるレイヤーの絵そのものを上下に反転します"),
                ("tour", "help", "使い方ツアー", self.start_tour, "F1", ""),
                ("draw", "ai", "描く", self.send, "", "書いた内容で AI に描かせます"))
        self.shared: dict[str, QAction] = {}
        for key, ic, label, fn, short, tip in rows:
            a = QAction(label, self)
            if ic:
                a.setIcon(icon(ic))
            if short:
                a.setShortcut(short)
            a.triggered.connect(lambda _=False, fn=fn: fn())
            a.setToolTip((tip or label) + (f"（{short}）" if short else ""))
            self.shared[key] = a
        for k in ("flip_view", "grid"):
            self.shared[k].setCheckable(True)
        c.view_changed.connect(lambda: (self.shared["flip_view"].setChecked(c.flipped), self.shared["grid"].setChecked(c.grid)))
        self.shared["stop"] = self.emergency_stop
        from chatdraw import layouts as L
        for name, fn in L.PRESETS.items():
            a = QAction(name, self, triggered=lambda _=False, fn=fn: self.feature_tour("layout", lambda fn=fn: self.apply_layout(fn)))
            a.setToolTip(f"「{name}」の配置にします")
            if name == "おすすめ":
                a.setIcon(icon("layout"))
            self.shared[f"layout:{name}"] = a

    def build_quick_bar(self):
        """よく使う帯。元に戻す・やり直す・赤ペン・描く・止める を、絵のすぐ上の手の届く所に小さく並べる"""
        bar = QToolBar("よく使う帯", self)
        bar.setObjectName("quickbar")
        bar.setIconSize(QSize(18, 18))
        S = self.shared
        for k in ("undo", "redo"):
            bar.addAction(S[k])
        bar.addSeparator()
        if "redpen" in self.tool_actions:
            bar.addAction(self.tool_actions["redpen"])
        bar.addAction(S["draw"])
        bar.addAction(S["stop"])
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.quick_bar = bar

    def all_actions(self) -> dict[str, QAction]:
        """帯に置ける操作の一覧。帯の並びはこの名前で覚える"""
        out = dict(self.shared)
        out.update({f"tool:{k}": a for k, a in self.tool_actions.items()})
        out.update({f"panel:{k}": a for k, a in self.panel_actions.items()})
        return out

    def setup_customizing(self):
        """メニューと帯の並べ替え・出し入れ・固定を、覚えた形で当てる（版を上げても利用者の形を残す）"""
        from chatdraw import menuedit
        self.bars_editor = menuedit.Bars(self, self.layout_store, {
            "よく使う帯": self.quick_bar, "道具の帯": self.tools, "欄の帯": self.panel_bar, "下の帯": self.bottom_bar},
            self.all_actions())
        self.menus_editor = menuedit.Menus(self, self.layout_store)

    def edit_menus(self):
        from chatdraw.menuedit import MenuEditor
        return MenuEditor(self, self.menus_editor)

    def edit_bars(self):
        from chatdraw.menuedit import BarEditor
        return BarEditor(self, self.bars_editor)

    def createPopupMenu(self):
        """帯やメニューの帯の右クリック。出し入れの一覧に、帯とメニューの編集と固定を足す"""
        m = super().createPopupMenu() or __import__("PySide6.QtWidgets", fromlist=["QMenu"]).QMenu(self)
        m.addSeparator()
        m.addAction(self.edit_bars_action)
        m.addAction(self.edit_menus_action)
        m.addAction(self.lock_bars_action)
        return m

    def notify(self, text: str, kind: str = "info", detail: str = "", on_click=None):
        """右下に短い知らせを出す（数秒で消える。作業は止めない）"""
        from chatdraw.notice import Notice
        return Notice(self, text, kind, detail=detail, on_click=on_click)

    def build_ribbon(self):
        """上部のリボン。メニューと同じ操作を、タブごとに大きなアイコンで並べる"""
        from chatdraw.ribbon import Ribbon

        def act(key, label, fn, tip=""):
            a = QAction(icon(key), label, self, triggered=fn)
            a.setToolTip(tip or label)
            return a
        p = self.panels
        S = self.shared
        r = Ribbon()
        r.add_page("ホーム", [
            ("ファイル", [S["new"], S["open"], S["save"]]),
            ("編集", [S["undo"], S["redo"]]),
            ("選択", [S["select_all"], S["deselect"]]),
        ])
        t = self.tool_actions
        r.add_page("描く", [
            ("道具", [t[k] for k in ("pen", "eraser", "blur", "fill", "gradient")]),
            ("図形", [t[k] for k in ("line", "rect", "ellipse", "polyshape", "regpoly")]),
            ("色", [t["eyedropper"], act("palette", "入れ替え", self.canvas.swap_colors, "描く色と背景色を入れ替える（X）")]),
        ])

        def ai(mode):
            p["chat"][0].show()
            p["chat"][0].raise_()
            self.mode.setCurrentIndex(mode)
            self.ai_panel.sections["描く内容"].set_open(True)
            self.entry.setFocus()
        r.add_page("AI", [
            ("描く", [S["draw"], act("ai", "頼んで描く", lambda: ai(0), "描きたい絵を書いて AI に描かせる"),
                     act("rough", "ラフから", lambda: ai(1), "キャンバスの線に沿って AI に描かせる")]),
            ("模型", [act("models", "絵の模型", lambda: self.ai_menu.exec(self.cursor().pos()), "絵の模型を切り替える"),
                     act("settings", "管理", self.manage_models, "模型の一覧・取得・更新・削除")]),
        ])
        r.add_page("表示", [
            ("キャンバス", [S["fit"], S["actual"], S["zoom_ask"]]),
            ("回転・反転", [S["rotate_left"], S["rotate_right"], S["rotate_dial"], S["flip_view"], S["view_reset"]]),
            ("補助", [S["grid"], S["op_history"]]),
            ("欄", [self.panel_actions[k] for k in PANEL_ORDER]),
            ("配置", [S["layout:おすすめ"],
                     act("layout", "配置…", lambda: self.layout_menu.exec(self.cursor().pos()), "決まった配置・寄せ・等分・保存")]),
            ("ヘルプ", [S["tour"]]),
        ])
        # タブはドラッグで並べ替えられ、並びを覚える（「帯を固定する」で動かなくなる）
        r.tabBar().setMovable(True)
        order = self.layout_store.value("ribbon/order")
        if order:
            names = str(order).split("\t")
            for i, name in enumerate(names):
                j = next((k for k in range(r.count()) if i18n.ja(r.tabText(k)) == name), -1)
                if j >= 0 and j != i and i < r.count():
                    r.tabBar().moveTab(j, i)
        r.tabBar().tabMoved.connect(lambda *_: self.layout_store.setValue(
            "ribbon/order", "\t".join(i18n.ja(r.tabText(k)) for k in range(r.count()))))   # 英語の画面でも日本語の名前で残す
        r.setCurrentIndex(next((k for k in range(r.count()) if r.tabText(k) == "描く"), 0))   # 初めは「描く」を開いておく
        # タブを右クリックすると、並びを変える窓を出す（ドラッグのほかに、上へ・下へでも並べ替えられる）
        r.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        r.tabBar().customContextMenuRequested.connect(
            lambda pos: self._ribbon_menu().exec(r.tabBar().mapToGlobal(pos)))
        bar = QToolBar("リボン", self)
        bar.setObjectName("ribbonbar")
        bar.setMovable(False)
        bar.addWidget(r)
        self.insertToolBar(self.options, bar)     # リボンを道具の設定の帯の前に入れ、
        self.insertToolBarBreak(self.options)     # 道具の設定の帯はリボンの下の段に置く
        self.ribbon, self.ribbon_bar = r, bar

    def move_panel(self, dock: QDockWidget, area):
        """欄を左・右・下・上のどこかへ移す。移した先で中身をふわっと出す"""
        from chatdraw.motion import fade_in
        self.feature_tour("panel_place")
        dock.titleBarWidget().expand()
        dock.setFloating(False)
        self.addDockWidget(area, dock)
        dock.show()
        if dock.widget() is not None:
            fade_in(dock.widget())

    def place_bar(self, bar: QToolBar, area):
        self.feature_tour("bars")
        self.addToolBar(area, bar)
        bar.show()

    def tour_steps(self):
        from chatdraw.tour import Step
        p = self.panels

        def show(key):
            return lambda: (p[key][0].show(), p[key][0].raise_())
        # はじめのツアーは 5 枚まで。前は 15 枚が続き、閉じたあとに機能ごとの案内が続けて出て長かった。
        # 欄と帯の案内は「ヘルプ」の「機能ごとの案内」（chatdraw/tours.py の tour_panels・tour_bars）に分けた
        return [
            Step(lambda: None, "CharacterDesigner へようこそ", "AI に頼んで描かせ、自分でも描き足せます。主な所を 5 枚で案内します。"),
            Step(lambda: p["chat"][0], "AI の欄", "「描く内容」に描きたい絵を、「禁止ワード」に描かない物を書いて「描く」を押します。\n"
                 "作風・模型・詳しい設定は見出しを押すと開きます。", show("chat")),
            Step(lambda: self.canvas, "キャンバス", "描いている途中の絵がここに出ます。\nホイールで拡大、Space を押しながらドラッグで動かせます。"),
            Step(lambda: self.tools, "道具", "ペン・消しゴム・塗りつぶしなどを選びます。\nアイコンにカーソルを重ねると、名前とキーが出ます。"),
            Step(lambda: self.menuBar(), "ほかの案内", "欄・帯・配置の案内は「ヘルプ」の「機能ごとの案内」にあります。\n"
                 "新しい案内が増えると、「ヘルプ」に印が付きます。"),
        ]

    def feature_tour(self, key: str, then=None) -> bool:
        """機能を初めて使うときの案内（chatdraw/tours.py）。出したら閉じたあとに then を呼ぶ"""
        from chatdraw import tours
        return tours.show(self, key, then)

    def tour_first(self, key: str, then) -> bool:
        """初めてなら案内を出して True（閉じたあとに then）。出さなければ then を呼ばずに False"""
        from chatdraw import tours
        return tours.first(self, key, then)

    def start_tour(self):
        from chatdraw.tour import Tour
        def closed():
            from chatdraw import tours
            tours.hold(self)   # 閉じた直後に機能ごとの案内を続けて出さない（連鎖して長くなった）
            self.layout_store.setValue("tour_done", 1)
            self.hide_progress_if_idle(0)   # ツアーで見せた進みの欄を、描いていなければ戻す
        self.tour = Tour(self, self.tour_steps(), on_close=closed)
        self.tour.start()

    def maybe_tour(self):
        """初めて起動したときだけ、ツアーを出す。2 回目からは、まだ見ていない新しいツアーを 1 回だけ控えめに知らせる"""
        if not int(self.layout_store.value("tour_done", 0)):
            from chatdraw import tours
            tours.mark_noticed(self)   # 初めての人には、はじめのツアーの終わりで「ヘルプ」に案内がある
            self.start_tour()
            return
        self.notice_new_tours()

    def notice_new_tours(self):
        from chatdraw import tours
        fresh = tours.unnoticed(self)
        if fresh:
            tours.mark_noticed(self)
            self.notify(f"新しいツアーが {len(fresh)} つあります", "info", "「ヘルプ」の「新しいツアー」から見られます",
                        on_click=lambda: self.new_tours_menu.popup(self.mapToGlobal(self.rect().center())))

    def _fill_new_tours(self):
        """「ヘルプ」の「新しいツアー（n）」を、まだ見ていない新しい案内で作り直す"""
        from chatdraw import tours
        m = self.new_tours_menu
        m.clear()
        cat = tours.catalog(self)
        fresh = tours.unseen_new(self)
        m.setTitle(f"新しいツアー（{len(fresh)}）" if fresh else "新しいツアー")
        for key in tours.NEW:
            a = m.addAction(("● " if key in fresh else "") + cat[key][0])
            a.setToolTip("まだ見ていない案内" if key in fresh else "見た案内（もう一度見られます）")
            a.triggered.connect(lambda _=False, k=key: (tours.show(self, k, force=True), self._fill_new_tours()))

    def panel_in_front(self, key: str) -> bool:
        """欄が出ていて、タブの裏に隠れていないか"""
        d = self.panels[key][0]
        if d.isHidden():
            return False
        if d.isFloating():
            return d.isVisible()
        return d.isVisible() and not d.visibleRegion().isEmpty()

    def toggle_panel(self, key: str):
        """欄の帯・ウィンドウのメニュー・F キーで押したとき。隠れていれば出して前に出し、前に出ていれば隠す"""
        d = self.panels[key][0]
        if self.panel_in_front(key):
            d.hide()
        else:
            was_hidden = d.isHidden()
            d.show()
            d.raise_()
            title = d.titleBarWidget()
            if getattr(title, "collapsed", False):
                title.toggle()   # 畳んだままだと出しても中身が見えない
            if was_hidden:
                self.feature_tour(key)
        self.panel_actions[key].setChecked(not d.isHidden())

    def _appear(self, d: QDockWidget, on: bool):
        """隠していた欄を出したときだけ、中身をふわっと出す（タブの切り替えでは動かさない）"""
        from chatdraw.motion import fade_in
        if on and getattr(d, "_was_hidden", False) and d.widget() is not None:
            fade_in(d.widget())
        d._was_hidden = not on and d.isHidden()

    def _as_window(self, d: QDockWidget, floating: bool):
        """別ウィンドウにした欄を、ふつうのウィンドウの枠にする。上下左右と四隅の端をつかんで大きさを変えられ、最大化もできる"""
        title = d.titleBarWidget()
        if isinstance(title, PanelTitle):
            title.expand()
        if floating:
            d.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
            d.show()
            self.keep_on_screen(d)

    def keep_on_screen(self, d: QDockWidget):
        """別ウィンドウの欄を画面の中に収める。保存した配置を別の画面の大きさで読んだときや、
        すべて別ウィンドウにして並べたときに、画面の外に出て見えなくなった"""
        screen = (self.screen() or QApplication.primaryScreen())
        if screen is None:
            return
        area = screen.availableGeometry()
        g = d.frameGeometry()
        w, h = min(max(g.width(), 200), area.width()), min(max(g.height(), 160), area.height())
        x = min(max(g.x(), area.left()), area.right() - w + 1)
        y = min(max(g.y(), area.top()), area.bottom() - h + 1)
        if (w, h) != (g.width(), g.height()):
            d.resize(w, h)
        if (x, y) != (g.x(), g.y()):
            d.move(x, y)

    def _collapse_all(self, on: bool):
        for d, _area in self.panels.values():
            title = d.titleBarWidget()
            if isinstance(title, PanelTitle) and title.collapsed != on:
                title.toggle()

    def _ribbon_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("リボンの並びを変える…", self.edit_ribbon_order)
        return m

    def edit_ribbon_order(self):
        from chatdraw.ribbon import OrderDialog
        self.ribbon_order_dialog = OrderDialog(self.ribbon, self)
        self.ribbon_order_dialog.exec()

    def ask_angle(self):
        from PySide6.QtWidgets import QInputDialog
        v, ok = QInputDialog.getInt(self, "表示の角度", "角度（度。右回りが +）", round(self.canvas.angle), -180, 180, 1)
        if ok:
            self.canvas.set_angle(float(v))

    def ask_zoom(self):
        from PySide6.QtWidgets import QInputDialog
        v, ok = QInputDialog.getInt(self, "拡大率", "拡大率（%）", round(self.canvas.zoom() * 100), 5, 3200, 5)
        if ok:
            self.canvas.set_zoom(v / 100)

    def show_op_history(self):
        """操作の履歴（履歴の欄の「操作」のタブ）を出す"""
        dock = self.panels["history"][0]
        dock.show()
        dock.raise_()
        tabs = self.activity.tabs
        tabs.setCurrentIndex(tabs.indexOf(self.activity.ops))

    def toggle_all(self):
        # 文字の欄（チャット、描く内容、赤ペンの指示、名前の書き換え）で打った Tab は、欄を隠さずに次の欄へ移る。
        # 前は文字を打っている途中の Tab で欄が全部消え、打っていた欄も見えなくなった
        from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)) or (
                isinstance(fw, QComboBox) and fw.isEditable()):
            nxt = fw.nextInFocusChain()
            while nxt is not None and nxt is not fw and not (
                    nxt.isVisible() and nxt.isEnabled() and nxt.focusPolicy() & Qt.TabFocus):
                nxt = nxt.nextInFocusChain()
            if nxt is not None and nxt is not fw:
                nxt.setFocus(Qt.TabFocusReason)
            return
        on = not getattr(self, "_all_hidden", False)
        if on:
            # 隠す前に見えていた欄と帯だけを覚え、次の Tab でそれだけを出す（前は閉じていた欄まで全部出た）
            self._shown_before = [w for w in self._all_bars() if w.isVisible()]
            for w in self._shown_before:
                w.setVisible(False)
        else:
            for w in getattr(self, "_shown_before", None) or self._all_bars():
                w.setVisible(True)
            self._shown_before = []
        self._all_hidden = on
        if on:
            self.statusBar().showMessage("欄を隠しました。Tab でまた出します", 6000)

    def _all_bars(self):
        return [d for d, _area in self.panels.values()] + [self.tools, self.options, self.panel_bar,
                                                           self.bottom_bar, self.ribbon_bar]

    def _show_all(self, on: bool):
        for d, _area in self.panels.values():
            d.setVisible(on)
        self.tools.setVisible(on)
        self.options.setVisible(on)
        self.panel_bar.setVisible(on)
        self.bottom_bar.setVisible(on)
        self.ribbon_bar.setVisible(on)

    def float_all(self):
        """欄をすべて別のウィンドウにして、少しずつずらして並べる"""
        x, y = self.geometry().right() - 380, self.geometry().top() + 40
        for i, (d, _area) in enumerate(self.panels.values()):
            d.show()
            d.setFloating(True)
            self._as_window(d, True)   # 前の並びで既に外に出ていると topLevelChanged が来ず、窓の枠にならなかった
            d.resize(360, 520)
            d.move(x - i * 40, y + i * 40)
            self.keep_on_screen(d)

    def free_layout(self):
        """欄の見出しをドラッグすると、左右上下のどこにでも置け、重ねるとタブになる"""
        for d, _area in self.panels.values():
            d.show()
            d.setFeatures(PANEL)
        self.tools.setMovable(True)
        self.statusBar().showMessage("欄をドラッグして配置できます", 4000)

    def closeEvent(self, e):
        if getattr(self, "dirty", False) and self.isVisible() and not getattr(self, "closing_checked", False):
            box = QMessageBox(QMessageBox.Question, "閉じる前に", "作業ファイルに保存していない変更があります。保存しますか。", parent=self)
            save = box.addButton("保存", QMessageBox.AcceptRole)
            drop = box.addButton("保存しない", QMessageBox.DestructiveRole)
            box.addButton("やめる", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is save and not self.save_project(wait=True) or box.clickedButton() not in (save, drop):
                e.ignore()
                return
        if not self.finish_threads_before_close():
            e.ignore()
            return
        self.wait_io()   # 裏で書いている保存を書き終えてから閉じる（書きかけの作業ファイルを残さない）
        self.layout_store.setValue("running", 0)   # 正しく閉じた印（次の起動で戻すかを聞かない）
        # 次に開いたときも同じ並びにする
        self.layout_store.setValue("geometry9", self.saveGeometry())
        self.layout_store.setValue("state9", self.saveState())
        if getattr(self, "ai_tabs", None) is not None:
            self.ai_tabs.save()
        super().closeEvent(e)

    def _refresh_layers(self):
        self.layer_panel.refresh()

    def import_layer(self):
        path, _ = QFileDialog.getOpenFileName(self, "画像をレイヤーとして読み込む", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.layer_from_file(path, Path(path).stem)

    def open_image(self):
        if self.tour_first("open", self.open_image):
            return
        path, _ = QFileDialog.getOpenFileName(self, "開く", "", "作業ファイルと画像 (*.cdproj *.png *.jpg *.jpeg *.webp)")
        if path:
            self.open_path(path)

    # ---- 既存の絵をあとから直す ----
    def open_to_edit(self):
        path, _ = QFileDialog.getOpenFileName(self, "直す絵を開く", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.edit_image(path)

    def edit_image(self, path: str):
        """手元の絵・ライブラリー・履歴の絵をキャンバスに開き、赤ペンで囲んで直せる形にする。
        キャンバスは置き換える（前の状態は元に戻すで戻せる）。前に描いた絵の .json があれば、頼み・種・模型を戻して続きから直す"""
        from chatdraw import finishers
        if not Path(path).is_file():
            self.notify("開けませんでした", "error", f"絵が見つかりません: {path}")
            return
        self.canvas.replace_with_image(path, Path(path).stem)
        self.project_path = None
        self.source_path = str(path)   # 「結合して元の画像に上書き保存」で書き戻す先
        self.mode.setCurrentIndex(2)   # 直す
        if "redpen" in self.tool_actions:
            self.tool_actions["redpen"].trigger()
        meta = finishers.sidecar(path)
        if meta.get("text"):
            self.entry.setText(meta["text"])
            self.last_text = meta["text"]
        try:
            if "seed" in meta:
                self.ai_panel.seed.setValue(int(meta["seed"]))
        except (TypeError, ValueError):
            pass
        if meta.get("style_name"):
            self.ai_panel.set_style(meta["style_name"])
        if meta.get("model"):
            self.fix_model = meta["model"]   # 描いた模型で続きを直す（取得していなければ今の模型で直す）
        self.edit_meta = meta
        self.notify("直す形で開きました", "ok",
                    "赤ペンで直す所を囲み、指示を書いて「描く」を押してください。囲みの外は変えません"
                    + ("（前の頼みと種を戻しました）" if meta else ""))

    def _fix_studio(self):
        """直しに使う模型を選んでいれば、その模型で直す Studio を作る。おまかせか、使えない模型なら今の Studio"""
        from chatdraw import finishers
        from chatdraw.models import all_images
        key = getattr(self, "fix_model", finishers.AUTO)
        if not key or key == finishers.AUTO or key == getattr(self.studio.painter, "model", None):
            return self.studio
        every = all_images()
        have = list(self.installed_images(every))
        m = next((m for m in finishers.inpaint_models(every, have) if m.repo == key), None)
        if m is None:
            self.say("直しに選んだ模型が使えないので、今の模型で直します")
            return self.studio
        old = getattr(self, "_fix_cache", None)
        if old is not None and old.painter.model == m.repo:
            return old   # 同じ模型を 2 度読まない
        painter = Painter(m.repo, m.steps, guidance=m.guidance)
        painter.avoid = getattr(self.studio.painter, "avoid", "")
        self._fix_cache = Studio(self.studio.words, painter, Path(self.settings.get("output_dir")))
        return self._fix_cache

    def _fill_fix_menu(self, menu):
        from chatdraw import finishers
        from chatdraw.models import all_images
        menu.clear()
        now = getattr(self, "fix_model", finishers.AUTO)
        group = QActionGroup(menu)
        auto = QAction(finishers.AUTO, menu, checkable=True)
        auto.setToolTip("囲んだ所を、今の絵の模型で直します")
        entries = [(finishers.AUTO, auto)]
        every = all_images()
        for m in finishers.inpaint_models(every, list(self.installed_images(every))):
            act = QAction(m.name, menu, checkable=True)
            act.setToolTip("囲んだ所を、この模型で直します（取得済みで、範囲の直しができる模型だけを出しています）")
            entries.append((m.repo, act))
        for key, act in entries:
            act.setChecked(key == now)
            act.triggered.connect(lambda _=False, k=key: setattr(self, "fix_model", k))
            group.addAction(act)
            menu.addAction(act)

    def finish_with(self, name: str, background: bool = False):
        """仕上げの道具を今の絵に掛け、結果を新しいレイヤーとして重ねる。囲み（赤ペン・選択）があれば囲みの中だけ変える。
        使えないときは止めずに理由を出す。返すのは保存した置き場（出来なければ None）"""
        from chatdraw import finishers
        base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        mask = self._region_mask()
        finishers.use_painter(getattr(self.studio, "painter", None))
        if background:   # 模型を使う道具は数十秒かかる。画面の糸で回すと、その間アプリが固まる
            return self.finish_chain([name], finishers.REGISTRY[name].label, base=base, mask=mask)
        try:
            out = finishers.run(name, base, mask)
        except finishers.Unavailable as e:
            self.notify("綺麗にできませんでした", "info", str(e))
            return None
        except Exception as e:  # 道具の中の失敗も、止めずに理由を出す
            from chatdraw.engine import explain
            self.notify("綺麗にできませんでした", "error", explain(e))
            return None
        if finishers.LAST_QC.get("rejected"):
            self.notify("加工で絵が崩れたので、掛けませんでした", "info", finishers.qc_note())
            return None
        note = finishers.qc_note()   # 元に戻した所（目の色・髪の色・崩れた区画）を知らせる。黙って戻さない
        path = self._place_finished(name, base, out)
        if note and path is not None:
            self.notify("加工の検品の結果", "info", note + "見比べて、使うか消すかを決めてください")
        return path

    def finish_chain(self, steps, label: str = "", base=None, mask=None):
        """加工を順に裏の糸で掛ける（1 つだけの加工も、まとめて綺麗にするも、自分の組み合わせも同じ道）。
        大きな絵は区画ごとに進みを出し、区画の区切りで「止める」が効く。工程ごとに崩れを検品し、崩れた所は元に戻して知らせる。
        結果は今の絵の一番上の新しいレイヤーに置く。返すのは None（置くのは終わってから）"""
        from chatdraw import finishers
        from chatdraw.engine import check_stop
        steps = list(steps or [])
        label = label or (finishers.REGISTRY[steps[0]].label if steps and steps[0] in finishers.REGISTRY else "加工")
        unknown = [n for n in steps if n not in finishers.REGISTRY]
        if not steps or unknown:
            self.notify(f"{label}を掛けられませんでした", "info", "組み合わせの中の加工が見つかりません。組み合わせを作り直してください")
            return None
        if self.busy(label):
            return None
        if base is None:
            base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
            mask = self._region_mask()
        finishers.use_painter(getattr(self.studio, "painter", None))
        fetch = []
        for n in steps:
            ok, why = self._finisher_ready(n)
            if not ok:
                if not finishers.fetchable(n):
                    self.notify("綺麗にできませんでした" if len(steps) == 1 else f"{label}を掛けられませんでした", "info", why)
                    return None
                fetch.append(n)
        name = steps[0] if len(steps) == 1 else "chain"
        self.activity.begin(label, "加工")
        path = self._finished_path(name)

        def say(text):   # 区画の区切りごとに呼ばれる。止めるの旗を見てから進みを出す
            check_stop()
            self.task.status.emit(text)

        def work(_step):   # 足りない部品は押したときに取り、取れたら続けて掛ける。書くのも裏の糸
            if fetch:
                finishers.fetch_parts(sorted({m for n in fetch for m in finishers.lacking(n)}),
                                      say=lambda msg, _pct: self.task.status.emit(msg))
                for n in fetch:
                    if not finishers.REGISTRY[n].ready():
                        raise finishers.Unavailable(finishers.REGISTRY[n].why_not())
            out = finishers.run_chain(steps, base, mask, say)
            if all(q.get("rejected") for q in finishers.LAST_CHAIN):
                return None   # どの工程も崩れたので採らない（置かない）
            return self._save_out(out, path)
        self._run_task(work, lambda out: self._chain_done(name, label, base, out, path))
        return None

    def _chain_done(self, name, label, base, out, path):
        from chatdraw import finishers
        note = finishers.chain_note()
        if out is None:
            self._end(f"{label}は掛けませんでした")
            self.notify("加工で絵が崩れたので、掛けませんでした", "info", note + "元の絵のままです")
            return
        self._place_finished(name, base, out, path)
        self._end(f"{label}を掛けました")
        if note:
            self.notify("加工の検品の結果", "info", note + "見比べて、使うか消すかを決めてください")

    def add_chain_shortcut(self, steps=None, name: str | None = None) -> str:
        """加工の組み合わせを、右クリックの「自分の組み合わせ」に登録する。steps が無ければ選ぶ窓を出す。返すのは id（やめたら空）"""
        from chatdraw import finishers, shortcuts
        if not isinstance(steps, (list, tuple)):   # メニューから呼ぶと checked の真偽が来る
            dlg = shortcuts.chain_picker(self)
            self._chain_picker = dlg
            if not dlg.exec():
                return ""
            steps, name = dlg.picked, dlg.name.text()
        steps = [n for n in steps if n in finishers.REGISTRY]
        if not steps:
            return ""
        sid = self.shortcut_store().add_chain(name or shortcuts.chain_text(steps)[:24], steps)
        self.notify("組み合わせを登録しました", "ok", "絵の上の右クリックの「自分の組み合わせ」から選べます")
        return sid

    def _region_mask(self):
        """赤ペンの囲みと選択範囲を合わせた囲み（PIL の L）。どちらも無ければ None"""
        from PIL import ImageChops
        masks = [gray_to_pil(m) for m in self.canvas.redpen.masks()]
        sel = self.canvas.selection_mask()
        if sel is not None:
            masks.append(gray_to_pil(sel))
        mask = None
        for m in masks:
            mask = m.convert("L") if mask is None else ImageChops.lighter(mask, m.convert("L"))
        return mask

    # ---- キャラクターデザイン（設定資料集・三面図・表情差分。chatdraw/charadesign.py） ----

    def _fill_chara_menu(self):
        from chatdraw import charadesign
        m = self.chara_menu
        m.clear()
        m.setToolTipsVisible(True)
        m.addAction("描いた人物を設定資料に保存…", self.chara_save).setToolTip(
            "今の絵を色の手本にして、頼んだ言葉と色見本と一緒に設定資料に残します。三面図と表情差分はこの資料から描きます")
        try:
            saved = charadesign.characters()
        except OSError:
            saved = []
        now = getattr(self, "chara_id", "") or (saved[0]["id"] if saved else "")
        self.chara_id = now
        if saved:
            pick = m.addMenu("使う人物")
            for c in saved[:20]:
                act = pick.addAction(c["name"], lambda i=c["id"]: setattr(self, "chara_id", i))
                act.setCheckable(True)
                act.setChecked(c["id"] == now)
        busy = getattr(self, "thread", None) is not None
        for label, fn, tip in (
                ("三面図を描く", self.chara_turnaround, "正面・横・後ろを同じ種で 1 枚ずつ描き、設定資料に置きます"),
                ("表情差分を描く", lambda: self.chara_expressions(),
                 "今の絵の顔の中だけを、笑顔・怒り・悲しみ・驚きに描き直します。顔の外は変えません。顔を囲むと、その囲みを使います"),
                ("設定資料を開く", self.chara_sheet, "設定資料のページ（絵を埋め込んだ 1 つのファイル）を書き、置き場を開きます")):
            act = m.addAction(label, fn)
            act.setToolTip(tip)
            act.setEnabled(bool(now) and not busy)

    def chara_save(self, name: str | None = None):
        """今の絵を設定資料に保存する。返すのは保存した id（やめたときは空）"""
        from chatdraw import charadesign
        if not isinstance(name, str):   # メニューから呼ぶと checked の真偽が来る
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "設定資料に保存", "人物の名前")
            if not ok:
                return ""
        name = (name or "").strip() or "名前のない人物"
        text = self.last_text or ""
        look = text
        try:
            words = getattr(self.studio, "words", None)
            look = words.to_prompt(text, tags=True) if (words is not None and text) else text
        except Exception:   # 言葉の模型が使えないときは頼みの言葉のまま残す
            look = text
        image = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        try:
            c = charadesign.save_character(name, look, image, notes=text)
        except (charadesign.NotReady, OSError) as e:
            self.notify("設定資料に保存できませんでした", "error", str(e))
            return ""
        self.chara_id = c["id"]
        self.notify("設定資料に保存しました", "ok", f"{name}（色見本 {len(c['palette'])} 色）")
        return c["id"]

    def _chara_painter(self):
        painter = getattr(self.studio, "painter", None)
        if painter is None or not getattr(painter, "ready", lambda: False)():
            self.notify("絵の模型がまだありません", "info", "AI のメニューで模型を取ってください")
            return None
        return painter

    def chara_turnaround(self):
        from chatdraw import charadesign
        if self.busy("三面図"):
            return
        painter, ident = self._chara_painter(), getattr(self, "chara_id", "")
        if painter is None or not ident:
            return
        self.activity.begin("三面図を描く", "キャラクターデザイン")
        seed = int(time.time()) % 100000
        self._run_task(lambda _step: charadesign.draw_turnaround(painter, ident, seed, say=self.task.status.emit),
                       lambda out: self._chara_done("三面図を描きました", out))

    def chara_expressions(self, only=("smile", "angry", "sad", "surprised")):
        from chatdraw import charadesign
        if self.busy("表情差分"):
            return
        painter, ident = self._chara_painter(), getattr(self, "chara_id", "")
        if painter is None or not ident:
            return
        base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        mask = self._region_mask()
        if mask is None:   # 囲みが無ければ、検品の顔の枠を使う
            try:
                from chatdraw import handcheck
                boxes = [f["box"] for f in handcheck.check(base, fetch=False).get("faces", [])]
            except Exception:
                boxes = []
            mask = charadesign.face_mask(base, boxes) if boxes else None
        if mask is None:
            self.notify("顔が見つかりませんでした", "info", "顔を選択範囲か赤ペンで囲んでください")
            return
        self.activity.begin("表情差分を描く", "キャラクターデザイン")
        seed = int(time.time()) % 100000
        self._run_task(lambda _step: charadesign.draw_expressions(painter, ident, base, mask, seed, list(only),
                                                                  say=self.task.status.emit),
                       lambda out: self._chara_done("表情差分を描きました", out))

    def _chara_done(self, msg: str, out: dict):
        self.activity.end(msg, None, record=False)
        self.notify(msg, "ok", f"{len(out)} 枚を設定資料に置きました。「設定資料を開く」で並べて見られます")
        self._end(msg)

    # ---- ロゴ・スタンプ（chatdraw/logo.py）。項目は logo.menu_items が返し、メニューバーと右クリックで同じ物を使う ----

    def _fill_logo_menu(self, m=None):
        from chatdraw import logo
        m = m if m is not None else self.logo_menu
        m.clear()
        m.setToolTipsVisible(True)
        busy = getattr(self, "thread", None) is not None
        for label, fn, tip in logo.menu_items(self):
            act = m.addAction(label, fn)
            act.setToolTip(tip)
            act.setEnabled(not busy)
        return m

    def _logo_folder(self, kind: str) -> Path:
        return Path(self.settings.get("output_dir")) / time.strftime("%Y-%m-%d") / kind / time.strftime("%Y%m%d-%H%M%S")

    def logo_make(self, name=None, mood: str = "", colors: str = ""):
        """頼み（名前、雰囲気、色）からロゴのマークを AI に描かせ、整えた版を書き出す"""
        from chatdraw import logo
        if not isinstance(name, str):
            from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit
            d = QDialog(self)
            d.setWindowTitle("ロゴ・マークを作る")
            form = QFormLayout(d)
            fields = []
            for label, tip in (("名前", "ロゴに重ねる文字。文字は AI に描かせず、フォントで書きます"),
                               ("雰囲気", "例: かわいい、和風、猫"), ("色", "例: 青と白")):
                e = QLineEdit()
                e.setToolTip(tip)
                form.addRow(label, e)
                fields.append(e)
            box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            box.accepted.connect(d.accept)
            box.rejected.connect(d.reject)
            form.addRow(box)
            if d.exec() != QDialog.Accepted:
                return
            name, mood, colors = (e.text().strip() for e in fields)
        painter = self._chara_painter()
        if painter is None:
            return
        words = getattr(self.studio, "words", None)
        folder, seed = self._logo_folder("logo"), int(time.time()) % 100000
        self.activity.begin("ロゴ・マークを描く", "ロゴ・スタンプ")

        def work(_step):
            mark = logo.draw_logo(painter, name, mood, colors, seed, words=words, say=self.task.status.emit)
            return logo.export_logo(mark, folder, text=name)
        self._run_task(work, lambda out: self._logo_done("ロゴを書き出しました", out))

    def logo_from_canvas(self, text=None):
        from chatdraw import logo
        if not isinstance(text, str):
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, "今の絵をロゴに整える", "横長の版に重ねる文字（空なら文字なし）")
            if not ok:
                return
        image, folder = qimage_to_pil(self.canvas.flatten()), self._logo_folder("logo")
        self.activity.begin("ロゴに整える", "ロゴ・スタンプ")
        self._run_task(lambda _step: logo.export_logo(logo.remove_background(image), folder, text=text),
                       lambda out: self._logo_done("ロゴを書き出しました", out))

    def _pick_spec(self, spec):
        from chatdraw import logo
        if isinstance(spec, str) and spec in logo.SPECS:
            return spec
        from PySide6.QtWidgets import QInputDialog
        keys = ("line", "telegram")
        names = [logo.SPECS[k]["name"] for k in keys]
        got, ok = QInputDialog.getItem(self, "スタンプ", "形", names, 0, False)
        return keys[names.index(got)] if ok else None

    def stamp_from_canvas(self, spec=None):
        from chatdraw import logo
        spec = self._pick_spec(spec)
        if spec is None:
            return
        image, folder = qimage_to_pil(self.canvas.flatten()), self._logo_folder("stamp")
        self.activity.begin("スタンプにする", "ロゴ・スタンプ")
        self._run_task(lambda _step: logo.export_stamps([image], folder, spec),
                       lambda out: self._logo_done("スタンプを書き出しました", out))

    def stamp_from_expressions(self, spec=None):
        from chatdraw import logo
        ident = getattr(self, "chara_id", "")
        files = logo.expressions(ident) if ident else []
        if not files:
            self.notify("スタンプにできませんでした", "info",
                        "表情差分がまだありません。キャラクターデザインのメニューで「表情差分を描く」を先に押してください")
            return
        spec = self._pick_spec(spec)
        if spec is None:
            return
        folder = self._logo_folder("stamp")
        self.activity.begin("表情差分をスタンプにする", "ロゴ・スタンプ")
        self._run_task(lambda _step: logo.export_stamps(files, folder, spec, stem=ident),
                       lambda out: self._logo_done("スタンプを書き出しました", out))

    def _logo_done(self, msg: str, out: list):
        self.activity.end(msg, None, record=False)
        self.logo_out = out
        where = str(Path(out[0]).parent) if out else ""
        self.notify(msg, "ok", f"{len(out)} 個のファイルを {where} に置きました")

    def chara_sheet(self):
        from chatdraw import charadesign
        ident = getattr(self, "chara_id", "")
        if not ident:
            return None
        try:
            path = charadesign.write_sheet(ident)
        except (charadesign.NotReady, OSError, SystemExit) as e:
            self.notify("設定資料を開けませんでした", "error", str(e))
            return None
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self.notify("設定資料を書きました", "ok", str(path))
        return path

    def _finisher_ready(self, name: str):
        from chatdraw import finishers
        for f in finishers.available():
            if f.get("name") == name:
                return bool(f.get("ready")), f.get("reason", "")
        return False, "その道具はありません"

    def _finished_path(self, name: str) -> Path:
        # 日付ごとのフォルダに分ける（1 つのフォルダに絵が溜まり続け、探せなくなった）。前に保存した絵は動かさない
        day = Path(self.settings.get("output_dir")) / time.strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        return day / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.png"

    @staticmethod
    def _save_out(out, path: Path, meta: dict | None = None):
        """出来た絵を書く（裏の糸で呼んでよい）。返すのは out のまま"""
        from chatdraw.canvas import preload
        path.parent.mkdir(parents=True, exist_ok=True)
        out.save(path)
        if meta is not None:
            from chatdraw import finishers
            finishers.embed(path, meta)
        preload(path)
        return out

    def _place_finished(self, name: str, base, out, path: Path | None = None):
        """仕上げた絵を保存し、同じ大きさなら新しいレイヤー、拡大なら置き換えで置く。path を渡したら書き済み"""
        if path is None:
            path = self._finished_path(name)
            self._save_out(out, path)
        from chatdraw import finishers
        f = finishers.REGISTRY.get(name)
        if f is not None and f.extra.get("effect") and out.size == base.size:
            # エフェクトは変わった画素だけのレイヤーに置く。元の絵の画素は変えず、表示の切り替え・不透明度・消すで扱える
            layer = finishers.effect_layer(base, out)
            layer.save(path)
            from chatdraw.canvas import preload
            preload(path)
            self.canvas.place_result(str(path), f"エフェクト: {f.label}")   # エフェクトはいつも今の絵の一番上のレイヤー
            s = finishers.LAST_STRENGTH.get("strength")
            self.notify("エフェクトを新しいレイヤーに置きました", "ok",
                        (f"この絵に合わせた強さ {s}。" if s else "") + "レイヤーの欄で表示・不透明度を変えたり、消したりできます")
            return path
        if f is not None and f.group == "style" and out.size == base.size:
            from chatdraw import restyle
            self.put_result(str(path), f"画風: {f.label}")   # 一番上の新しいレイヤーに置いて選ぶ。元の絵は下に残す
            self.notify(f"{f.label}に描き替えました（新しいレイヤー）", "ok", restyle.note() + "見比べて、使うか消すかを決めてください")
            return path
        if out.size == base.size:
            self.put_result(str(path), "綺麗にした絵")   # 元の絵は下に残す
            self.canvas.fit()   # 結果は全体表示で見せる
        else:
            self.put_result(str(path), "綺麗にした絵（拡大）", replace=True)   # 拡大した絵（元に戻すで戻せる）
        self.notify("綺麗にしました（新しいレイヤー）", "ok", "見比べて、使うか消すかを決めてください")
        return path

    def outpaint_canvas(self, left: int, top: int, right: int, bottom: int, background: bool = False):
        """絵の外へ広げる。広げた絵でキャンバスを置き換える（元に戻すで戻せる）。使えないときは理由を出して止めない"""
        from chatdraw import finishers
        base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        known = (getattr(self, "edit_meta", None) or {}).get("prompt", "")
        last, words = self.last_text, self.studio.words

        def to_prompt():   # 言葉の模型に聞くので、裏の糸で呼ぶ（画面の糸で読むと数秒〜数十秒固まる）
            # 括弧が無いと「(known or 訳) if last else ""」と読まれ、開いて直す絵（頼みが無く、言葉だけ残る）で言葉を捨てた
            return known or (words.to_prompt(last) if last else "")
        painter, seed = getattr(self.studio, "painter", None), self.ai_panel.seed.value()
        if background:   # 描くのは模型なので裏の糸で回す（画面の糸で回すと描き終えるまで固まる）
            if self.busy("絵の外へ広げる"):
                return None
            if painter is None:
                self.notify("広げられませんでした", "info", "絵の模型がまだ読めていません。AI の欄で模型を選んでください")
                return None
            self.activity.begin("絵の外へ広げる", "広げる")
            path = self._finished_path("outpaint")
            meta = dict(getattr(self, "edit_meta", None) or {}, text=last, mode="広げる", grow=[left, top, right, bottom])

            def work(_step):
                prompt = to_prompt()
                out = finishers.outpaint(base, left, top, right, bottom, painter=painter, prompt=prompt, seed=seed)
                return self._save_out(out, path, dict(meta, prompt=prompt)), prompt
            self._run_task(work, lambda got: (self._place_outpaint(got[0], got[1], left, top, right, bottom, path),
                                              self._end("絵の外へ広げました")))
            return None
        prompt = to_prompt()
        try:
            out = finishers.outpaint(base, left, top, right, bottom, painter=painter, prompt=prompt, seed=seed)
        except finishers.Unavailable as e:
            self.notify("広げられませんでした", "info", str(e))
            return None
        except Exception as e:  # 道具の中の失敗も、止めずに理由を出す
            from chatdraw.engine import explain
            self.notify("広げられませんでした", "error", explain(e))
            return None
        return self._place_outpaint(out, prompt, left, top, right, bottom)

    def _place_outpaint(self, out, prompt, left, top, right, bottom, path: Path | None = None):
        if path is None:
            path = self._finished_path("outpaint")
            self._save_out(out, path, dict(getattr(self, "edit_meta", None) or {}, text=self.last_text, prompt=prompt,
                                           mode="広げる", grow=[left, top, right, bottom]))
        self.put_result(str(path), "広げた絵", replace=True)
        self.notify("絵の外へ広げました", "ok", "元の絵の画素はそのままです。広げた所を見て、使うか元に戻すかを決めてください")
        return path

    def merge_and_overwrite(self):
        """見えているレイヤーを結合し、開いた元の画像に上書きで保存する。上書きの前に元の画像の控えを取る"""
        import shutil
        import time
        from PySide6.QtWidgets import QMessageBox
        from chatdraw.paths import HOME
        src = getattr(self, "source_path", None)
        if not src or not Path(src).is_file():
            self.notify("上書きする元の画像がありません", "info", "画像を開いてから使います。作業ファイルは「保存」で保存します")
            return
        from chatdraw import confirm
        if confirm.ask(self, "overwrite", "元の画像に上書き", f"見えているレイヤーを結合して、\n{src}\nに上書きします。\n"
                       "元の画像の控えをアプリのデータの backup に残します。", [("yes", "上書きする")]) != "yes":
            return
        backup = HOME / "backup" / f"{Path(src).stem}-{time.strftime('%Y%m%d-%H%M%S')}{Path(src).suffix}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup)
        self.canvas.merge_visible(Path(src).stem)
        if not self.canvas.flatten().save(src):
            self.notify("上書きできませんでした", "error", f"控えは {backup} にあります")
            return
        self.dirty = False
        self.statusBar().showMessage(f"上書きしました。元の画像の控え: {backup}", 8000)

    def open_path(self, path: str, restore: bool = False):
        from chatdraw import project
        if path.endswith(project.SUFFIX):
            # 読んで PNG を戻すのは裏の糸。置くのは画面の糸（レイヤーが多いと 0.1 秒を超えた）
            def done(got):
                if isinstance(got, BaseException):
                    self.notify("開けませんでした", "error", str(got))
                    return
                project.apply(self.canvas, got)
                # 自動保存から戻したときは、自動保存の場所に上書き保存しない
                self.project_path, self.dirty = (None, True) if restore else (path, False)
            self.run_io(lambda: project.read(path), done, "読み込み")
            return
        else:
            self.canvas.show_image(path)
            self.project_path = None
            self.source_path = str(path)
        self.dirty = False

    def save_project(self, ask: bool = False, wait: bool = False) -> bool:
        """作業ファイル（レイヤー・赤ペンの印ごと）に保存する。初めてか ask なら置き場を聞く。
        書くのは裏の糸（PNG に縮めるのに 1 枚 0.1〜0.3 秒かかり、その間描けなかった）。wait なら書き終えるまで待つ
        （閉じる前・拡大の前など、保存できたかで次を決めるとき）。書き始めたか書けたら True"""
        from chatdraw import project
        path = getattr(self, "project_path", None)
        if ask or not path:
            if self.tour_first("project", lambda: self.save_project(ask)):
                return False
            path, _ = QFileDialog.getSaveFileName(self, "作業ファイルを保存", "drawing" + project.SUFFIX,
                                                  f"作業ファイル (*{project.SUFFIX})")
            if not path:
                return False
            if not path.endswith(project.SUFFIX):
                path += project.SUFFIX
        snap = project.snapshot(self.canvas)
        if wait:
            try:
                project.write(snap, path)
            except OSError as e:
                self.notify("保存できませんでした", "error", f"{e}\n保存先に書き込めるか、ディスクに空きがあるかを確かめてください")
                return False
            self.project_path, self.dirty = path, False
            self.notify("保存しました", "ok", Path(path).name)
            return True
        self.project_path, self.dirty = path, False
        self.statusBar().showMessage("保存しています…")

        def done(err):
            if isinstance(err, BaseException):
                self.dirty = True
                self.notify("保存できませんでした", "error", f"{err}\n保存先に書き込めるか、ディスクに空きがあるかを確かめてください")
                return
            self.notify("保存しました", "ok", Path(path).name)
        self.run_io(lambda: project.write(snap, path), done, "保存")
        return True

    def run_io(self, work, done, name: str = "保存・読み込み"):
        """保存・読み込みなどの書き物を裏の糸で回す。同じ置き場に重ねて書かないよう、1 本の列に並べて順に書く"""
        import queue
        import threading
        if getattr(self, "_io_queue", None) is None:
            self._io_queue = queue.Queue()

            def loop(q):
                while True:
                    fn, key = q.get()
                    try:
                        v = fn()
                    except BaseException as e:   # noqa: BLE001  裏で落ちても画面の糸に必ず返す
                        v = e
                    fn = None   # 次を待つ間、終わった仕事を持ち続けない
                    self._bg_emit(key, v)
                    q.task_done()
            threading.Thread(target=loop, args=(self._io_queue,), daemon=True).start()
        self._io_queue.put((work, self._bg_register(done, name)))

    def _bg_done(self, got):
        """裏の糸の答えを画面の糸で受ける。done が落ちても数は戻す（数が残ると、試験と閉じる前の待ちが終わらない）"""
        key, v = got
        done = self._waiting.pop(key, None)
        self.bg_pending -= 1
        self.activity.bg_end(key)
        if done is not None:
            done(v)

    def wait_io(self, sec: float = 30.0):
        """裏で書いている物を書き終えるまで待つ（閉じる前に、途中のファイルを残さない）"""
        q = getattr(self, "_io_queue", None)
        end = time.time() + sec
        while q is not None and q.unfinished_tasks and time.time() < end:
            time.sleep(0.01)

    def export_psd(self):
        from chatdraw import project
        dst, _ = QFileDialog.getSaveFileName(self, "PSD で書き出す", "drawing.psd", "PSD (*.psd)")
        if not dst:
            return
        snap, n = project.psd_snapshot(self.canvas), len(self.canvas.layers)
        self.statusBar().showMessage("PSD を書き出しています…")
        self.run_io(lambda: project.write_psd(snap, dst),
                    lambda err: self.notify("書き出せませんでした", "error", f"{err}\n書き出す先に書き込めるかを確かめてください") if isinstance(err, BaseException)
                    else self.notify("書き出しました", "ok", f"{Path(dst).name}（レイヤー {n} 枚）"))

    def autosave(self):
        """変わっていれば、決まった置き場に作業ファイルを書く。落ちたときに次の起動で戻せるように"""
        from chatdraw import project
        if not getattr(self, "dirty", False) or not self.canvas.layers:
            return
        if getattr(self, "_autosaving", False):
            return   # 前の自動保存がまだ書き終わっていない
        path = project.autosave_path()
        snap = project.snapshot(self.canvas)   # 写すのは画面の糸、書くのは裏の糸（前は 2 分ごとに 1 秒近く固まった）
        self._autosaving = True

        def work():
            path.parent.mkdir(parents=True, exist_ok=True)
            project.write(snap, path)

        def done(err):
            self._autosaving = False
            if not isinstance(err, BaseException):   # 自動保存が書けなくても、描く邪魔はしない
                self.autosaved = True
        self.run_io(work, done)

    def check_update(self, manual: bool = False):
        """新しい版があるかを裏で確かめる。自分で頼んだとき以外は 1 日に 1 回だけ"""
        import datetime
        import threading
        from chatdraw import updater
        today = datetime.date.today().isoformat()
        if not manual and self.layout_store.value("update_checked", "") == today:
            return
        self.layout_store.setValue("update_checked", today)
        self.update_bridge = Bridge()
        self.update_bridge.got.connect(lambda info: self._update_found(info, manual))

        def run():
            try:
                info = updater.check(quiet=False)
            except Exception as e:   # noqa: BLE001  確かめられなかったことを画面の糸に返す
                info = {"error": str(e) or type(e).__name__}
            self.update_bridge.got.emit(info)
        threading.Thread(target=run, daemon=True).start()

    def _update_found(self, info, manual: bool):
        from chatdraw import updater
        if info and info.get("error"):
            if manual:   # 自分で押したときだけ知らせる（起動時の確かめは黙る）
                self.notify("更新を確かめられませんでした", "error", "ネットに届きませんでした: " + info["error"][:120])
            return
        if not info:
            if manual:
                self.notify("今の版が最新です", "ok", f"版 {updater.current()}")
            return
        self.update_info = info
        self.notify(f"新しい版 {info['version']} があります", "info", "押すと取って、入れるかを聞きます",
                    on_click=self.get_update)

    def get_update(self):
        """新しい Setup.exe を取り、入れるかを聞く。入れるときはアプリを閉じてから Setup.exe を開く"""
        from chatdraw import updater
        info = getattr(self, "update_info", None)
        if not info or not info.get("setup"):
            self.notify("取れる Setup.exe がありません", "info", info.get("page", "") if info else "")
            return
        if self.thread:
            return
        self.activity.begin(f"版 {info['version']} を取る", "更新")
        self._run_task(lambda on_step: str(updater.download(info["setup"], lambda got, total: on_step(got >> 20, total >> 20))),
                       self._update_ready)

    def _update_ready(self, path: str):
        import os
        import subprocess
        import sys as _sys
        self.activity.end("取りました", None, record=False)
        self._end("取りました")
        box = QMessageBox(QMessageBox.Question, "更新を入れる",
                          "新しい版を取りました。アプリを閉じて入れますか。描いている絵は先に保存します。", parent=self)
        go = box.addButton("閉じて入れる", QMessageBox.AcceptRole)
        box.addButton("あとで", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            self.notify("あとで入れられます", "info", path)
            return
        if getattr(self, "dirty", False) and not self.save_project(wait=True):
            return
        if _sys.platform == "win32":
            os.startfile(path)   # noqa: S606  利用者が「閉じて入れる」を選んだときだけ開く
        else:
            subprocess.Popen([path])
        self.dirty = False
        self.close()

    def offer_restore(self):
        """前に閉じずに終わっていて、自動保存が残っていれば、戻すかを聞く（自動保存は消さない）"""
        from chatdraw import project
        crashed = crashed_before(self.layout_store)
        self.layout_store.setValue("running", os.getpid())
        path = project.autosave_path()
        if not crashed or not path.exists():
            return False
        box = QMessageBox(QMessageBox.Question, "前の絵を戻す",
                          "前回は正しく閉じられませんでした。自動保存した絵を開きますか。", parent=self)
        yes = box.addButton("開く", QMessageBox.AcceptRole)
        box.addButton("開かない", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.open_path(str(path), restore=True)
            return True
        return False

    def save_as(self) -> bool:
        """保存できたら True"""
        if not self.canvas.layers:
            return False
        if self.tour_first("save", self.save_as):
            return False
        dst, _ = QFileDialog.getSaveFileName(self, "名前を付けて保存", "drawing.png", "PNG (*.png)")
        if not dst:
            return False
        ok = self.canvas.flatten().save(dst)
        self.notify("保存しました" if ok else "保存できませんでした", "ok" if ok else "error", Path(dst).name)
        return bool(ok)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "progress_popup"):
            self.progress_popup.place()
        if not getattr(self, "_settle_queued", False):   # 大きさが変わったら、収まらなくなった欄の高さを配り直す
            self._settle_queued = True
            from PySide6.QtCore import QTimer

            def again():
                self._settle_queued = False
                from chatdraw.layouts import settle
                settle(self)
            QTimer.singleShot(0, again)

    def hide_progress_if_idle(self, ms: int = 4000):
        """進みの欄は自分では隠さない。描き終わると消えて、結果も今の状態も分からなかった。閉じるのは利用者だけ"""

    def watch_fetch(self, fetcher, what: str = "模型"):
        """模型を取る進みを、描く進みと同じ右下のポップアップに出す。模型の管理を閉じたあとも、取り終わるまで進みが見える"""
        # 取り始めは新しい 1 回分。前の 1 回分を × で閉じたままだと、取る進みが一度も出なかった
        self.progress_popup._new_run()
        fetcher.progress.connect(lambda msg, pct: self.progress_popup.tell(f"{what}を取っています", msg, pct), Qt.QueuedConnection)
        fetcher.finished.connect(lambda err: self.progress_popup.tell("取れませんでした" if err else "取りました",
                                                                      err or f"{what}を取り終わりました"), Qt.QueuedConnection)

    def show_progress(self, text: str, pct: int):
        """進みをウィンドウの外にも出す。タイトル（タスクバーに出る）、通知の領域のアイコン、終わったときの知らせ"""
        base = "CharacterDesigner"
        if pct == -2:
            self.setWindowTitle(base)
        else:
            self.setWindowTitle(f"{pct}% {text} - {base}" if pct >= 0 else f"{text} - {base}")
        tray = self._tray()
        if tray is not None:
            tray.setToolTip(text if pct < 0 else f"{text}（{pct}%）")
        if pct == -2:
            self.tell_outside("CharacterDesigner", text)

    def _tray(self):
        from PySide6.QtWidgets import QSystemTrayIcon
        if getattr(self, "tray", None) is None:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return None
            self.tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull() else icon("ai"), self)
            self.tray.activated.connect(lambda *_: (self.showNormal() if self.isMinimized() else None, self.raise_(),
                                                    self.activateWindow()))
            self.tray.show()
        return self.tray

    def tell_outside(self, title: str, text: str):
        """ほかのウィンドウを見ている間に終わったら、デスクトップの通知とタスクバーの点滅で知らせる（設定の「知らせ」）"""
        if self.settings.get("notify") == "画面の中だけ" or (self.isActiveWindow() and not self.isMinimized()):
            return
        QApplication.alert(self, 0)
        tray = self._tray()
        if tray is not None:
            tray.showMessage(title, text, tray.icon(), 8000)

    def _end(self, msg: str):
        self.statusBar().showMessage(msg, 4000)
        # 加工などで始めた進みの表示も終える。終えないと「確認中」のまま止まって見えた
        act = getattr(self, "activity", None)
        if act is not None and getattr(act, "started", None):
            act.end(msg, None, record=False)
        self.stop_button.setEnabled(False)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self.button.setEnabled(True)
        self.hide_progress_if_idle()
        if getattr(self, "_unload_after", False):
            self._unload_after = False
            self.studio.painter.unload()


from chatdraw.themes import qss as _qss
THEME = _qss()   # 既定のテーマ（chatdraw/themes.py）



def dark(app: QApplication, name: str | None = None):
    """テーマの色を当てる。name が無ければ前に選んだテーマ（初めはナイト: 暗い灰色の地に赤とオレンジの差し色）"""
    from chatdraw import themes
    store = QSettings("CharacterDesigner", "chatdraw")
    themes.load_custom(store)
    if name is None:
        name = store.value("theme", themes.DEFAULT)
    return themes.apply(app, name)


def main():
    from chatdraw import crashlog
    from chatdraw.paths import adopt_stray
    crashlog.install()
    try:
        adopt_stray()   # 前の版がずれた置き場（cd）に書いた ★・非表示などを、本来の置き場へ合わせる
    except OSError:
        pass
    app = QApplication(sys.argv)
    dark(app)
    from chatdraw import fit
    fit.install(app)
    from chatdraw import logo
    if logo.icon_png() is not None:   # 選ばれたアイコンがあるときだけ替える。無い間は今のまま
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(logo.icon_png())))
    w = Window()
    w.show()
    w.ask_models()
    w.ask_words_once()
    w.upgrade_models()
    w.check_ai()
    opened = sys.argv[sys.argv.index("--open") + 1] if "--open" in sys.argv[:-1] else None
    if opened:
        w.open_path(opened)   # AI の結果を別ファイルで開くとき。自動保存から戻すかは聞かない
    else:
        w.offer_restore()
    # closeEvent を通らずに終わる道（更新を入れて閉じるなど）でも、正しく閉じた印を残す
    app.aboutToQuit.connect(lambda: (w.layout_store.setValue("running", 0), w.layout_store.sync()))
    # 前の回が落ちていたら、記録の場所を知らせる（次に直すときの手がかりにする）
    try:
        prev = int(w.layout_store.value("crashlog_size", 0) or 0)
    except (TypeError, ValueError):
        prev = 0
    if crashlog.last_crash(prev):
        w.notify("前に落ちたときの記録があります", "error", f"記録: {crashlog.path()}（ヘルプの「落ちた記録を開く」で開けます）")
    try:
        w.layout_store.setValue("crashlog_size", crashlog.path().stat().st_size)
    except OSError:
        pass
    w.maybe_tour()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(5000, w.check_update)   # 起動の邪魔をしないよう、少し待ってから確かめる
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
