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

    def run(self):
        try:
            if self.regions is not None:
                prompts, path = self.studio.fix(self.base, self.regions, self.seeds[0], on_status=self.status.emit,
                                                style=self.style, strength=self.strength, reference=self.reference,
                                                ref_scale=self.ref_scale, check=self.check)
                self._stopped()
                preload(path)
                self.one.emit(" / ".join(prompts), str(path))
            else:
                for seed in self.seeds:
                    extra = dict(reference=self.reference, ref_scale=self.ref_scale) if self.reference is not None else {}
                    prompt, path = self.studio.draw(self.text, seed, on_status=self.status.emit,
                                                    base=self.base, strength=self.strength, size=self.size,
                                                    on_preview=self.preview.emit, style=self.style, meta=self.meta, **extra)
                    self._stopped()
                    preload(path)   # 置くときに画面の糸で絵を読まないよう、ここ（裏の糸）で先に読む
                    self.one.emit(prompt, str(path))
            self.done.emit()
        except Exception as e:  # 描けなかった理由を、次に何をすればよいか分かる日本語で会話に出す
            from chatdraw.engine import explain
            self.failed.emit(f"描けませんでした: {explain(e)}")

    def _stopped(self):
        """止められたあとに返ってきた絵（直しの途中で抜けた物など）は置かずに捨てる。キャンバスは元のまま"""
        if getattr(self.studio.painter, "stop", False):
            from chatdraw.engine import Stopped
            raise Stopped("止めました")


class Task(QObject):
    """時間のかかる処理（拡大など）を裏で回す。fn(on_step) の返りを done で返す"""
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(lambda i, n: self.status.emit(f"描いています（{i}/{n}）")))
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
TOOLS = (("move", "移動", "V"), ("select", "四角の選択", "M"), (None, "", ""),
         ("pen", "ペン", "B"), ("eraser", "消しゴム", "E"), ("blur", "ぼかし", "R"), (None, "", ""),
         ("fill", "塗りつぶし", "G"), ("gradient", "グラデーション", "J"), (None, "", ""),
         ("line", "直線", "N"), ("rect", "四角", "U"), ("ellipse", "楕円", "O"), (None, "", ""),
         ("eyedropper", "スポイト", "I"), ("hand", "手のひら", "H"), ("zoom", "拡大（Shift か右クリックで縮小）", "Z"), (None, "", ""),
         ("redpen", "赤ペン（AI に直す所を囲む）", "T"))

# 欄の帯とメニューに並べる順（よく使う順）
PANEL_ORDER = ("talk", "chat", "view", "history", "library", "progress", "layers", "color", "brushes")

# 欄は動かせて、外に出せて、閉じられる（作画ソフトと同じ）
PANEL = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable


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
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.addWidget(self.model_label)
        self.ai_panel.sections["模型"].body.addLayout(model_row)
        self._lora_row()
        ask_page = QWidget()
        ask_page.setLayout(ask)
        self.ai_tabs = QTabWidget()
        # 中身の縦の流れは AI の欄のタブごとに持つ（描くボタンをタブの外に出し、流しても隠れないようにする）
        ask_scroll = ask_page
        self.ai_tabs.addTab(ask_scroll, "描き方")
        self.ai_tabs.setTabBarAutoHide(True)   # タブが 1 つのときは見出しだけで足りる
        dock = QDockWidget("AI", self)
        dock.setWidget(self.ai_tabs)
        dock.setObjectName("chat")
        dock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # AI の欄の「描く内容」: 頼みを書く欄、模型に渡る言葉の目安、禁止ワード、「描く」と止める、直近の言葉
        tl = self.ai_panel.sections["描く内容"].body
        tl.addWidget(self.entry)
        neg_head = QLabel("禁止ワード")
        neg_head.setObjectName("sectionHead")
        neg_head.setToolTip(self.ai_panel.negative.toolTip())
        tl.addWidget(neg_head)
        tl.addWidget(self.ai_panel.negative)
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
        line.addWidget(self.button, 1)
        line.addWidget(self.stop_button)
        # 書く欄の下のボタン。お気に入り（★、固定）を先に、そのあとに直近に頼んだ言葉を新しい順に並べる。
        # 押すと書く欄に入り、ダブルクリックでそのまま描く。右クリックで固定・外す・消す。書く欄で ↑↓ でも呼び出せる
        # 音声入力。Windows の音声入力（Win+H）を書く欄で開く。話した言葉が書く欄に入る（模型を足さずに済む）
        self.mic_button = QPushButton("🎤")
        self.mic_button.setFixedWidth(40)
        self.mic_button.setToolTip("声で頼む（Windows の音声入力 Win+H を開きます）")
        self.mic_button.clicked.connect(self.voice_input)
        from chatdraw import voice
        # 使えない所（Windows の外）では出さない。押せないボタンを並べると、欄が狭くなるだけだった
        line.addWidget(self.mic_button)
        self.mic_button.setVisible(voice.available())
        self.fav_button = QPushButton("☆")
        self.fav_button.setToolTip("書く欄の言葉をお気に入りに固定する")
        self.fav_button.setFixedWidth(40)
        self.fav_button.clicked.connect(self._toggle_fav)
        self.entry.textChanged.connect(lambda: self.fav_button.setText(
            "★" if (t := self.entry.text().strip()) and t in self.favorite_prompts() else "☆"))
        line.addWidget(self.fav_button)
        self.tips = QHBoxLayout()
        self.tips.setSpacing(4)
        tips_box = QWidget()
        tips_box.setLayout(self.tips)
        from PySide6.QtWidgets import QScrollArea
        tips_scroll = QScrollArea()   # ボタンは横に流す。狭い画面でチャットの欄の幅を広げさせない
        tips_scroll.setWidget(tips_box)
        tips_scroll.setWidgetResizable(True)
        tips_scroll.setFrameShape(QScrollArea.NoFrame)
        tips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 横の流す棒は出さない（棒がボタンの下に出て欄がはみ出して見えた）。ホイールで横に流す
        tips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        from chatdraw.wheelguard import side_wheel
        side_wheel(tips_scroll)
        tips_box.setObjectName("scrollInner")
        self.tips_scroll = tips_scroll
        self.entry.installEventFilter(self)
        self._load_prompts()
        tips_scroll.setFixedHeight(QPushButton("あ").sizeHint().height() + 4)
        tl.addWidget(tips_scroll)
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
        self.history.itemDoubleClicked.connect(lambda it: it.data(Qt.UserRole) and self.layer_from_file(it.data(Qt.UserRole), "AI の絵"))
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

        # 下: 進み
        self.progress = self.activity.bar   # 進みは描いた絵の欄に出す


        # 上: メニュー
        file = self.menuBar().addMenu("ファイル")
        file.addAction(QAction("新規キャンバス", self, shortcut="Ctrl+N", triggered=lambda: self.canvas.new_canvas()))
        file.addAction(QAction("開く…", self, shortcut="Ctrl+O", triggered=self.open_image))
        edit_open = QAction("画像を開いて直す…", self, triggered=self.open_to_edit)
        edit_open.setToolTip("手元の絵を開き、赤ペンで囲んだ所だけを AI に直させます。囲みの外は変えません")
        file.addAction(edit_open)
        file.addAction(QAction("保存", self, shortcut="Ctrl+S", triggered=self.save_project))
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
        trash_act = QAction("ごみ箱…", self, triggered=self.open_trash)
        trash_act.setToolTip("消した絵を見て、元に戻すか本当に消します")
        file.addAction(trash_act)
        file.addSeparator()
        file.addAction(QAction("終了", self, shortcut="Ctrl+Q", triggered=self.close))
        edit = self.menuBar().addMenu("編集")
        edit.addAction(QAction("元に戻す", self, shortcut="Ctrl+Z", triggered=self.canvas.undo))
        edit.addAction(QAction("やり直す", self, shortcut="Ctrl+Y", triggered=self.canvas.redo))

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
        self.fill_shapes.setToolTip("四角と楕円を、線だけでなく中まで塗る")
        self.fill_shapes.toggled.connect(lambda on: setattr(self.canvas, "fill_shapes", on))
        bar.addWidget(self.fill_shapes)
        for key, _label, _s in TOOLS:
            if key:
                self.tool_actions[key].triggered.connect(lambda _=False, k=key: self._tool_changed(k))
                self.tool_actions[key].triggered.connect(lambda _=False, k=key: self.feature_tour(k))
        self._tool_changed("pen")

        # 左上: 色（色相・彩度と明度・16 進・描く色と背景色・見本・最近使った色）
        self.color_panel = ColorPanel(self.canvas)
        self.canvas.used_color.connect(self.color_panel.remember)
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
        bbox = QWidget()
        bbox.setLayout(bform)
        # タブで「ブラシ」（種類を選ぶ）と「設定」（硬さ・流量・間隔・筆圧）を切り替える
        self.brush_tabs = QTabWidget()
        self.brush_tabs.addTab(self.brush_list, "ブラシ")
        self.brush_tabs.addTab(bbox, "設定")
        bdock = QDockWidget("ブラシ", self)
        bdock.setObjectName("brushes")
        bdock.setWidget(self.brush_tabs)
        bdock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, bdock)
        self.brush_list.setCurrentRow(0)
        self.canvas.brush_changed.connect(self.size_box.setValue)
        self.build_status()

        # 右下: レイヤー（縮小図・表示・ロック・名前・並べ替え。chatdraw/layerpanel.py）
        from chatdraw.layerpanel import LayerPanel
        self.layer_panel = LayerPanel(self.canvas)
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
        self.canvas.marked.connect(lambda: self.mode.setCurrentIndex(2))   # 赤ペンで囲んだら、AI の欄を「直す」にする
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
        view.addAction(QAction("全体を表示", self, shortcut="Ctrl+0", triggered=self.canvas.fit))
        view.addAction(QAction("100%", self, shortcut="Ctrl+1", triggered=self.canvas.actual))
        view.addAction(QAction("左に回す", self, shortcut="Ctrl+[", triggered=lambda: self.canvas.rotate_view(-15)))
        view.addAction(QAction("右に回す", self, shortcut="Ctrl+]", triggered=lambda: self.canvas.rotate_view(15)))
        view.addAction(QAction("回転を戻す", self, shortcut="Ctrl+\\", triggered=self.canvas.reset_rotation))
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
        from chatdraw import ratings
        ratings.on_change(self._models_changed)
        setting_menu = self.menuBar().addMenu("設定")
        setting_menu.addAction(QAction("設定…", self, shortcut="Ctrl+,", triggered=self.open_settings))
        setting_menu.addAction(QAction("キーの設定…", self, triggered=self.open_keys))
        sel = self.menuBar().addMenu("選択範囲")
        sel.addAction(QAction("すべてを選択", self, shortcut="Ctrl+A", triggered=self.canvas.select_all))
        sel.addAction(QAction("選択を解除", self, shortcut="Ctrl+D", triggered=lambda: self.canvas.set_selection(None)))
        sel.addAction(QAction("選択範囲の中を消す", self, triggered=self.canvas.clear_selection_area))
        layer_menu = self.menuBar().addMenu("レイヤー")
        layer_menu.addAction(QAction("新しいレイヤー", self, shortcut="Ctrl+Shift+N", triggered=self.canvas.add_layer))
        layer_menu.addAction(QAction("レイヤーを消す", self, triggered=self.canvas.delete_layer))
        layer_menu.addAction(QAction("画像をレイヤーとして読み込む…", self, triggered=self.import_layer))

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
        for d, _area in self.panels.values():
            d.setTitleBarWidget(PanelTitle(d))
            # 欄の境目をドラッグして上下左右に広げ縮めできる。狭めすぎて中身が潰れない大きさだけ決める
            d.setMinimumSize(160, 80)
            d.topLevelChanged.connect(lambda floating, d=d: self._as_window(d, floating))
            d.dockLocationChanged.connect(lambda _area, d=d: d.titleBarWidget().expand())
            d.visibilityChanged.connect(lambda on, d=d: self._appear(d, on))
        self.tools = tools
        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AnimatedDocks)
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
        win.addAction(QAction("すべて別ウィンドウにする", self, triggered=self.float_all))
        win.addAction(QAction("自由配置（欄をドラッグして好きな所に置く）", self, triggered=self.free_layout))
        self.build_ribbon()
        self.build_bottom()
        self.build_layout_menu()
        from chatdraw import themes
        from chatdraw.look import Look
        themes.load_custom(self.layout_store)
        self.look = Look(self)
        self._look(themes.current)
        self._show_model()
        help_menu = self.menuBar().addMenu("ヘルプ")
        help_menu.addAction(QAction(icon("help"), "使い方ツアー", self, shortcut="F1", triggered=self.start_tour))
        help_menu.addAction(QAction("操作方法", self, triggered=lambda: self.open_help("manual")))
        help_menu.addAction(QAction("手順書（入れ方・模型の置き方・困ったとき）", self, triggered=lambda: self.open_help("install")))
        help_menu.addAction(QAction("記録の置き場を開く", self, triggered=self.open_logs))
        help_menu.addAction(QAction("更新を確かめる", self, triggered=lambda: self.check_update(manual=True)))
        from chatdraw import tours
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
        self._ribbon_toggle.addAction(self.ribbon_bar.toggleViewAction())
        self._bars_menu.addAction(self.bottom_bar.toggleViewAction())
        for name, tb in (("下の帯", self.bottom_bar), ("道具の設定の帯", self.options)):
            sub = self._where.addMenu(name)
            for label, area in (("上", Qt.TopToolBarArea), ("下", Qt.BottomToolBarArea)):
                sub.addAction(QAction(label, self, triggered=lambda _=False, tb=tb, area=area: self.place_bar(tb, area)))
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
        """書く欄の下のボタンを作り直す。お気に入り、直近の言葉の順。どちらも無いときだけ頼みの例を出す"""
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
            chip.setToolTip(text + ("\n押すと書く欄に入り、ダブルクリックでもう一度描きます。右クリックで固定・消す" if fav is not None else ""))
            chip.clicked.connect(lambda _=False, t=text: (self.entry.setText(t), self.entry.setFocus()))
            if fav is not None:
                chip.setContextMenuPolicy(Qt.CustomContextMenu)
                chip.customContextMenuRequested.connect(lambda pos, c=chip, t=text, f=fav: self._chip_menu(c, pos, t, f))
                chip.installEventFilter(self)
            self.tips.addWidget(chip)
        self.tips.addStretch()
        self.fav_button.setText("★" if self.entry.text().strip() in favs and self.entry.text().strip() else "☆")
        self._prompt_pos = -1

    def _chip_menu(self, chip, pos, text: str, fav: bool):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("お気に入りから外す" if fav else "お気に入りに固定する", lambda: (self.unpin_prompt(text) if fav else self.pin_prompt(text)))
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
        """お気に入りに固定する。お気に入りは数を限らず、消すまで残す"""
        if not text:
            self.notify("固定する言葉がありません", "info", "書く欄に言葉を書いてから ☆ を押します")
            return
        favs = self.favorite_prompts()
        if text not in favs:
            self._save(self.FAV_KEY, favs + [text])
            self.statusBar().showMessage(f"お気に入りに固定しました: {text}", 4000)

    def select_tool(self, key: str):
        """道具を持ち替える（初めの道具や配置を変えたとき）。利用者が押したときと違い、初めて使うときの案内は出さない"""
        act = self.tool_actions.get(key)
        if act is None:
            return
        act.setChecked(True)
        self.canvas.set_tool(key)
        self._tool_changed(key)

    def voice_input(self):
        """書く欄に移ってから Win+H を送り、Windows の音声入力を開く"""
        from chatdraw import voice
        self.entry.setFocus()
        if voice.start():
            self.statusBar().showMessage("話してください。言葉が書く欄に入ります（止めるときはもう一度 Win+H）", 5000)

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
        if getattr(self, "asking", False):
            self.say("前の答えを待っています。少し待ってからもう一度送ってください")
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
            self.in_background(lambda: assistant.answer(words, turns, text, prompt), answered)

        def answered(got):
            self.asking = False
            self.chat.set_busy(False)
            if isinstance(got, BaseException):
                self.chat.add("ai", f"答えられませんでした: {got}")
                return
            reply, new = got
            self.offer_prompt(self.chat.add("ai", reply), new)

        if commands.needs_model(text, words):
            self.in_background(lambda: commands.by_model(text, words), picked)
        else:
            picked(None)

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
            self.ai_tabs.setCurrentIndex(0)
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
        if self.thread or not text and not (pen.marks and all(pen.texts)):   # 絵の上に全部書いてあれば、チャットは空でよい
            return
        if not text:
            text = " / ".join(f"{i}: {t}" for i, t in enumerate(pen.texts, 1))
        from chatdraw import commands
        words = getattr(getattr(self, "studio", None), "words", None)
        if commands.needs_model(text, words):
            # 言葉の模型に聞くのは裏で行う。画面の糸で聞くと、「赤」「保存」などの操作の言葉を含む頼みで
            # 模型の読み込みと推論の間（数秒〜数十秒）アプリが固まった
            if getattr(self, "asking", False):
                return
            self.asking = True
            self.button.setEnabled(False)

            def got(picked):
                self.asking = False
                self.button.setEnabled(True)
                self._send_after(text, None if isinstance(picked, BaseException) else picked)
            self.in_background(lambda: commands.by_model(text, words), got)
            return
        self._send_after(text, None)   # 模型に聞けないときは言葉の決まりで選ぶ

    def in_background(self, work, done):
        """work を裏の糸で動かし、答えを画面の糸の done に渡す。work が例外を出したら、その例外を渡す"""
        import threading
        key = self._bg_register(done)

        def run():
            try:
                v = work()
            except BaseException as e:   # noqa: BLE001  裏で落ちても画面の糸に必ず返す
                v = e
            self._bg_emit(key, v)
        threading.Thread(target=run, daemon=True).start()

    def _bg_register(self, done) -> int:
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
        if self.canvas.redpen.marks and self.mode.currentIndex() != 2:
            self.mode.setCurrentIndex(2)   # 赤ペンの印があるときの頼みは、印の所を直す頼みとして受ける
        if self.mode.currentIndex() == 2 and not self.canvas.redpen.marks and self.canvas.selection_mask() is None:
            self.notify("直す所がありません", "info", "赤ペンで直す所を囲むか、四角の選択で選んでから頼んでください")
            self.feature_tour("redpen")
            return
        st = self.check_ai()
        if not st["image"]:
            self.say(st["reason"] or "AI が使えません")
            self.progress_popup.tell("描けません", st["reason"] or "AI が使えません")   # 描く前に止まったことも右下に出す
            return
        self.last_text = text
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
        self.thread = QThread()
        self.job_studio = self._fix_studio() if mode == 2 else self.studio
        self.job = Job(self.job_studio, text, seeds, base=base, strength=self.strength.value() / 100,
                       style=self.ai_panel.style_tags(), regions=regions, reference=self.ai_panel.reference(),
                       ref_scale=self.ai_panel.ref_scale.value() / 100, meta=meta,
                       size=fit_size(*self.canvas.size_px()) if base is not None else self.size_pick.currentData())
        self.job.moveToThread(self.thread)
        self.thread.started.connect(self.job.run)
        self.job.status.connect(self.on_status)
        self.job.preview.connect(self.show_preview)
        self.job.one.connect(self.on_one)
        self.job.done.connect(self.finish)
        self.job.failed.connect(self.fail)
        self.gc_guard()
        self.thread.start()

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

    def edit_note(self, n: int):
        """赤ペンの n 番の印の横に、指示を書く欄を出す。Enter で絵の上に残し、Esc でやめる"""
        from PySide6.QtCore import QPoint
        pen = self.canvas.redpen
        if not 1 <= n <= len(pen.marks):
            return
        if getattr(self, "note_edit", None) is None:
            self.note_edit = QLineEdit(self.canvas.viewport())
            self.note_edit.setObjectName("noteEdit")
            self.note_edit.setPlaceholderText("この所をどう直すか（例: 笑顔に）Enter で残す")
            self.note_edit.setMinimumWidth(260)
            self.note_edit.returnPressed.connect(self._note_done)
            self.note_edit.installEventFilter(self)
        self.note_n = n
        at = self.canvas.mapFromScene(pen.marks[n - 1][0]) + QPoint(18, -14)
        self.note_edit.setText(pen.texts[n - 1])
        self.note_edit.move(at)
        self.note_edit.adjustSize()
        self.note_edit.show()
        self.note_edit.setFocus()
        self.feature_tour("redpen_note")

    def _note_done(self):
        pen = self.canvas.redpen
        if 1 <= self.note_n <= len(pen.texts):
            pen.texts[self.note_n - 1] = self.note_edit.text().strip()
            pen.update()
        self.note_edit.hide()
        self.canvas.setFocus()

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if self._entry_keys(obj, e):
            return True
        if obj is getattr(self, "note_edit", None) and e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self.note_edit.hide()
            return True
        return super().eventFilter(obj, e)

    def fix_regions(self, text: str):
        """直す所と指示の並び。赤ペンの印は絵の上に書いた指示か番号ごとの指示、四角の選択は文全体を指示にする"""
        from chatdraw.redpen import merge
        marks = self.canvas.redpen.masks()
        regions = [(gray_to_pil(m), n) for m, n in zip(marks, merge(self.canvas.redpen.texts, text))]
        sel = self.canvas.selection_mask()
        if sel is not None:
            regions.append((gray_to_pil(sel), text))
        return regions

    def on_status(self, msg: str):
        m = re.search(r"（(\d+)/(\d+)）", msg)
        self.activity.status(msg, *(int(m.group(1)), int(m.group(2))) if m else (None, None))

    def on_one(self, prompt: str, path: str):
        """1 枚できるたびに呼ばれる。初めの 1 枚はキャンバスに置き、ほかは履歴に並べて選べるようにする。
        絵を置くのを先にする。前は検品の知らせを先に出していて、そこで落ちると絵が置かれず、途中の絵か何も無いままだった"""
        self.images.append(path)
        self.canvas.show_overlay(None)
        first = not self.batch
        self.batch.append(path)
        bad = getattr(getattr(self, "job_studio", None) or self.studio, "last_flaws", []) if self.job_kind == "fix" else []
        try:
            if self.job_kind == "chibi":
                self.canvas.add_image_layer(path, "ちびキャラ")
            elif self.job_kind == "fix":
                self.canvas.add_image_layer(path, f"AI の直し {len(self.images)}" + ("（崩れあり）" if bad else ""))
                if bad:   # 崩れの見つかった直しは見えなくして重ねる。元の絵を壊さず、見るか消すかは利用者が決める
                    self.canvas.set_visible(self.canvas.current, False)
                    self._refresh_layers()
                else:
                    self.canvas.redpen.clear()   # 崩れが見つからなければ、印は役目を終える
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
        # 頼み・種・設定を PNG にも埋める（.json が離れても、絵だけで続きから直せるように）。PNG を書き直すので
        # 1 枚 0.1 秒ほどかかる。置いたあとに裏の糸で書く（埋めるのは別名に書いてから替えるので、読む側は壊れた絵を見ない）
        from chatdraw import finishers
        self.run_io(lambda: finishers.embed(path, finishers.sidecar(path)), lambda _v: None)   # 描いた絵はライブラリーにも入る（好き・いまいちを付けて好みを育てる）

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
        self._show_model()   # おまかせで選んだ模型を出す
        self.show_final()
        n = len(self.batch)
        fixed = self.job_kind in ("fix", "chibi")
        bad = getattr(getattr(self, "job_studio", None) or self.studio, "last_flaws", []) if self.job_kind == "fix" else []
        result = ("直しを重ねました（崩れあり・隠しています）" if bad else "直しを重ねました") if fixed else \
            f"{n} 枚描きました" if n > 1 else "描けました"
        if bad:   # 崩れがあったときだけ絵の説明に足す（「描けました」は絵を見れば分かる）
            for it in self.batch_items:
                it.setToolTip(f"{result}\n{it.toolTip()}")
        self.activity.end(result, None, record=False)
        self.say(result if fixed else f"{n} 枚描きました。履歴から選べます" if n > 1 else "描きました")
        self.notify(result if fixed else "描けました", "error" if bad else "ok",
                    (f"崩れ {len(bad)} 件。レイヤーを隠して重ねました。見て決めてください" if bad else
                     "新しいレイヤーに重ねました。見て決めてください") if fixed else
                    (f"1 枚目をキャンバスに出しました。ほかの {n - 1} 枚は履歴を押すと出ます" if n > 1
                     else "キャンバスに出しました（元に戻すで前の絵に戻せます）"),
                    on_click=lambda: (self.panels["history"][0].show(), self.activity.tabs.setCurrentIndex(0)))
        self._end("できました")

    def make_chibi(self):
        """今の絵を、ちびキャラ（頭の大きなデフォルメ）に描き直して、新しいレイヤーに重ねる"""
        from PIL import Image
        from chatdraw import postfx
        if self.thread:
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
        out = Path(self.settings.get("output_dir"))
        path = out / f"{time.strftime('%Y%m%d-%H%M%S')}-lineart.png"

        def work():   # 線を取り出して書くのは裏の糸（832×1216 で 0.4 秒ほど固まった）
            out.mkdir(parents=True, exist_ok=True)
            postfx.lineart(src).save(path)

        def done(err):
            if isinstance(err, BaseException):
                self.notify("線画にできませんでした", "error", str(err))
                return
            self.canvas.add_image_layer(str(path), "線画")
            self.activity.add(str(path), "線画")
            self.notify("線画にしました", "ok", "新しいレイヤーに重ねました。元の絵は下に残っています")
        self.statusBar().showMessage("線画にしています…")
        self.in_background(work, done)

    def make_pixel(self, long: int = 128, colors: int = 24):
        """今の絵をドット絵にして、新しいレイヤーに重ねる。小さいドット絵（1 ドット 1 画素）も出力の置き場に残す"""
        from chatdraw import postfx
        self.feature_tour("pixel")
        img = qimage_to_pil(self.canvas.flatten())
        out = Path(self.settings.get("output_dir"))
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
            self.canvas.add_image_layer(str(big), "ドット絵")
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
        self.thread = QThread()
        self.job = job
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
        if self.thread:
            return
        if self.canvas.undo_stack:
            box = QMessageBox(QMessageBox.Question, "絵を 2 倍に拡大",
                              "レイヤーはそのままで 2 倍にします。拡大すると「元に戻す」の履歴は消えるので、先に保存しておくと戻れます。",
                              parent=self)
            save = box.addButton("保存してから拡大", QMessageBox.AcceptRole)
            go = box.addButton("拡大", QMessageBox.DestructiveRole)
            box.addButton("やめる", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is save:
                if not self.save_project(wait=True):
                    return
            elif box.clickedButton() is not go:
                return
        layers = [(l.name, l.visible, l.opacity, qimage_to_pil_rgba(l.image)) for l in self.canvas.layers]
        current = self.canvas.current
        self.feature_tour("upscale")
        self.activity.begin("絵を 2 倍に拡大", "拡大")
        self.activity.status("描いています" + ("" if upscale.ready() else "（初めに拡大の部品 18MB を取ります）"))

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

    def _run_task(self, fn, then):
        self.thread = QThread()
        self.task = Task(fn)
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

    def _history_menu(self, pos, run: bool = True):
        from PySide6.QtWidgets import QMenu
        it = self.history.itemAt(pos)
        path = it.data(Qt.UserRole) if it else None
        if not path:
            return
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
        m.addAction("お気に入りの言葉にする", lambda: self._prompt_from(path, pin=True))
        from chatdraw import ownstyle
        m.addAction("★ お気に入りを外す" if ownstyle.is_favorite(path) else "★ お気に入りにする", lambda: ownstyle.toggle(path))
        m.addAction("学習用に集める", self.collect_favorites)
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
        if not run:
            return m
        m.exec(self.history.mapToGlobal(pos))

    ENTRY_TIP = "描いてほしい絵を日本語か英語で書き、Enter か「描く」で描きます（Shift+Enter で改行）"

    def _entry_tip(self):
        """書く欄のツールチップ。使い方に、模型に渡る言葉の目安と、前に絵の模型に渡した言葉を足す"""
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
            n = len(paths)
            box = QMessageBox(QMessageBox.Question, "絵を消す",
                              ("この絵" if n == 1 else f"{n} 枚の絵") + "をごみ箱へ移します。付属のファイル（頼みと設定）も一緒に移します。\n"
                              "「ファイル」→「ごみ箱…」から戻せます。", parent=self)
            yes = box.addButton("ごみ箱へ移す", QMessageBox.AcceptRole)
            box.addButton("やめる", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return None
        items = self.library.take(paths)
        try:
            key = self.trash.put(paths, items)
        except OSError as e:
            self.library.put_back(items)
            self.notify("消せませんでした", "error", str(e))
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
        import json
        try:
            return json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8")).get("text", "")
        except (OSError, ValueError):
            return ""

    def _prompt_from(self, path: str, pin: bool = False):
        text = self._prompt_text(path)
        if not text:
            self.notify("頼みの言葉が残っていません", "info", "この絵の .json がありません")
            return
        self.entry.setText(text)
        if pin:
            self.pin_prompt(text)

    def copy_image(self, path: str | None = None):
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setImage(QImage(path) if path else self.canvas.flatten())
        self.statusBar().showMessage("絵をコピーしました", 3000)

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
        from PySide6.QtWidgets import QMenu
        c = self.canvas
        m = QMenu(self)
        m.addAction("元に戻す", c.undo).setEnabled(bool(c.undo_stack))
        m.addAction("やり直す", c.redo).setEnabled(bool(c.redo_stack))
        m.addSeparator()
        tools = m.addMenu("道具")
        for key, label in (("hand", "手（画面を動かす）"), ("pen", "ペン"), ("eraser", "消しゴム"), ("eyedropper", "スポイト"),
                           ("select", "四角の選択"), ("redpen", "赤ペン（AI に直す所を示す）")):
            if key in self.tool_actions:
                tools.addAction(label, self.tool_actions[key].trigger)
        m.addSeparator()
        m.addAction("全体を表示", c.fit)
        m.addAction("100%", c.actual)
        m.addAction("回転を戻す", c.reset_rotation)
        m.addSeparator()
        m.addAction("レイヤーを足す", c.add_layer)
        if c.selection is not None:
            m.addAction("選択を外す", lambda: c.set_selection(None))
        m.addAction("絵をコピー", self.copy_image)
        m.addSeparator()
        m.addAction("この絵を AI で描き直す（もう一度描く）", self.draw_again).setEnabled(bool(self.last_text) and not self.thread)
        pin = m.addAction("表示する絵を固定する")
        pin.setCheckable(True)
        pin.setChecked(self.pin_action.isChecked())
        pin.toggled.connect(self.pin_action.setChecked)
        m.addAction("タイムラプスを見る…", self.open_timelapse)
        m.addSeparator()
        self._finish_menu(m.addMenu("綺麗にする"))
        grow = m.addMenu("絵の外へ広げる")
        grow.setToolTipsVisible(True)
        for label, sides in (("左右に広げる", (1, 0, 1, 0)), ("上下に広げる", (0, 1, 0, 1)), ("四方に広げる", (1, 1, 1, 1))):
            act = grow.addAction(label, lambda s=sides: self.outpaint_canvas(*[v * 128 for v in s], background=True))
            act.setToolTip("広げた所だけを AI に描かせます（128 画素ずつ）。元の絵の画素は変えません")
        m.exec(gpos)

    def redo_from(self, path: str):
        """履歴の絵と同じ頼み・種・画風を、AI の欄とチャットに戻す。押せば同じ設定で描ける"""
        import json
        meta_path = Path(path).with_suffix(".json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
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
        self._show_all(True)
        for d, _area in self.panels.values():
            d.setFloating(False)
        self.arrange()
        self.showNormal()
        area = self.screen().availableGeometry()
        self.resize(min(1400, area.width() - 40), min(900, area.height() - 60))
        fit(self)

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
        self.in_background(lambda: {m.repo for m in every if has_image(m)}, done)

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

    def place(self, path: str):
        """描けた絵を置く。新しく描いて、まだ何も描いていないキャンバスなら絵を開く。
        キャンバスを元に描いたときと、描いている途中なら、元の絵を残して新しいレイヤーとして重ねる"""
        if self.mode.currentIndex() == 0:
            # 新しく描いた絵は、いつも同じ形で置く（キャンバスを置き換え、前の状態は元に戻すで戻せる）。
            # 前は、キャンバスの状態で置き換えたり上に重ねたりが変わり、大きさの違う絵が重なった
            self.canvas.replace_with_image(path, f"AI の絵 {len(self.images)}")
        else:
            self.canvas.add_image_layer(path, f"AI の絵 {len(self.images)}")
            self.canvas.fit()   # 描けた絵は全体表示で見せる
        self._placed = path

    def stop(self):
        self.studio.painter.stop = True
        self.statusBar().showMessage("止めています")

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

    def _mode_changed(self, i: int):
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
        self.canvas.show_overlay(None)
        self.say(why)
        if self.activity.started is not None:
            self.activity.end("止めました" if "止め" in why else "描けませんでした")
        # 進みの欄の 1 回分の外で落ちたときも、理由を右下に出す（出さないと何も起きなかったように見えた）
        self.progress_popup.tell("止めました" if "止め" in why else "描けませんでした", why)
        self.notify("止めました" if "止め" in why else "描けませんでした", "info" if "止め" in why else "error",
                    "" if "止め" in why else why)
        self._end(why)

    def pick_color(self):
        c = QColorDialog.getColor(self.canvas.color, self, "色")
        if c.isValid():
            self.color_panel.set_color(c)

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
        self.fill_shapes.setVisible(key in ("rect", "ellipse"))

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
            for name, fn in L.PRESETS.items():
                menu.addAction(QAction(name, self, triggered=lambda _=False, fn=fn: self.feature_tour(
                    "layout", lambda fn=fn: self.apply_layout(fn))))
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
        for key, label, fn in (("undo", "元に戻す", self.canvas.undo), ("redo", "やり直す", self.canvas.redo)):
            bar.addAction(QAction(icon(key), label, self, triggered=fn))
        bar.addSeparator()
        bar.addAction(QAction(icon("fit"), "全体を表示", self, triggered=self.canvas.fit))
        self.zoom_slider = _S(Qt.Horizontal)
        self.zoom_slider.setRange(5, 800)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(180)
        self.zoom_slider.setToolTip("拡大率")
        self.zoom_slider.valueChanged.connect(lambda v: self.canvas.set_zoom(v / 100))
        self.canvas.zoomed.connect(lambda z: (self.zoom_slider.blockSignals(True), self.zoom_slider.setValue(int(z * 100)),
                                              self.zoom_slider.blockSignals(False)))
        bar.addWidget(self.zoom_slider)
        bar.addAction(QAction(icon("rotate"), "右に回す", self, triggered=lambda: self.canvas.rotate_view(15)))
        bar.addAction(QAction("回転を戻す", self, triggered=self.canvas.reset_rotation))
        self.addToolBar(Qt.BottomToolBarArea, bar)
        self.bottom_bar = bar

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
        r = Ribbon()
        r.add_page("ホーム", [
            ("ファイル", [act("new", "新規", lambda: self.canvas.new_canvas(), "新しいキャンバス（Ctrl+N）"),
                         act("open", "開く", self.open_image, "絵を開く（Ctrl+O）"),
                         act("save", "保存", self.save_as, "名前を付けて保存（Ctrl+S）")]),
            ("編集", [act("undo", "戻す", self.canvas.undo, "元に戻す（Ctrl+Z）"),
                     act("redo", "やり直す", self.canvas.redo, "やり直す（Ctrl+Y）")]),
            ("選択", [act("select", "すべて", self.canvas.select_all, "すべてを選択（Ctrl+A）"),
                     act("fit", "解除", lambda: self.canvas.set_selection(None), "選択を解除（Ctrl+D）")]),
        ])
        t = self.tool_actions
        r.add_page("描く", [
            ("道具", [t[k] for k in ("pen", "eraser", "blur", "fill", "gradient")]),
            ("図形", [t[k] for k in ("line", "rect", "ellipse")]),
            ("色", [t["eyedropper"], act("palette", "入れ替え", self.canvas.swap_colors, "描く色と背景色を入れ替える（X）")]),
        ])

        def ai(mode):
            p["chat"][0].show()
            p["chat"][0].raise_()
            self.mode.setCurrentIndex(mode)
            self.ai_panel.sections["描く内容"].set_open(True)
            self.entry.setFocus()
        r.add_page("AI", [
            ("描く", [act("ai", "頼んで描く", lambda: ai(0), "描きたい絵を書いて AI に描かせる"),
                     act("rough", "ラフから", lambda: ai(1), "キャンバスの線に沿って AI に描かせる")]),
            ("模型", [act("models", "絵の模型", lambda: self.ai_menu.exec(self.cursor().pos()), "絵の模型を切り替える"),
                     act("settings", "管理", self.manage_models, "模型の一覧・取得・更新・削除")]),
        ])
        r.add_page("表示", [
            ("キャンバス", [act("fit", "全体", self.canvas.fit, "全体を表示（Ctrl+0）"),
                          act("zoom", "100%", self.canvas.actual, "等倍で表示（Ctrl+1）"),
                          act("rotate", "回す", lambda: self.canvas.rotate_view(15), "右に回す（Ctrl+]）")]),
            ("欄", [self.panel_actions[k] for k in PANEL_ORDER]),
            ("配置", [act("layout", "おすすめ", lambda: self.apply_layout(__import__("chatdraw.layouts", fromlist=["x"]).recommended),
                         "おすすめの配置に戻す"),
                     act("layout", "配置…", lambda: self.layout_menu.exec(self.cursor().pos()), "決まった配置・寄せ・等分・保存")]),
            ("ヘルプ", [act("help", "使い方", self.start_tour, "使い方ツアー（F1）")]),
        ])
        r.setCurrentIndex(1)   # 初めは「描く」を開いておく
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
        return [
            Step(lambda: None, "CharacterDesigner へようこそ", "AI に頼んで描かせ、自分でも描き足せます。主な所を順に案内します。"),
            Step(lambda: p["chat"][0], "AI の欄", "「描く内容」に描きたい絵を、「禁止ワード」に描かない物を書いて「描く」を押します。\n"
                 "作風・模型・詳しい設定は見出しを押すと開きます。", show("chat")),
            Step(lambda: p["talk"][0], "チャット", "AI に使い方を聞いたり、絵の相談をしたりできます。\n"
                 "答えに出た描く内容の案は、吹き出しのボタンで AI の欄に入れられます。「ペンにして」のような操作もします。", show("talk")),
            Step(lambda: self.progress_popup, "進み", "AI が描いている間は、右下に工程と進みが出ます。\n描き終わっても × で閉じるまで消えません。タイトルとデスクトップの通知にも出します。",
                 lambda: self.progress_popup.pop()),
            Step(lambda: self.canvas, "キャンバス", "描いている途中の絵がここに出ます。\nホイールで拡大、Space を押しながらドラッグで動かせます。"),
            Step(lambda: p["view"][0], "表示", "全体の縮小図と参考画像です。縮小図を押すと、その場所を表示します。", show("view")),
            Step(lambda: p["history"][0], "履歴", "描いた絵と、キャンバスの操作の履歴です。\n操作を選ぶと、その時点まで戻れます。", show("history")),
            Step(lambda: self.tools, "道具", "ペン・消しゴム・塗りつぶしなどを選びます。\nアイコンにカーソルを重ねると、名前とキーが出ます。"),
            Step(lambda: p["color"][0], "色・ブラシ・レイヤー", "左には手で描くための欄をまとめています。\nAI の絵はレイヤーとして重なります。", show("color")),
            Step(lambda: self.ribbon, "リボン", "よく使う操作をタブごとに並べています。\n開いているタブをもう一度押すと畳めます。"),
            Step(lambda: self.panel_bar, "欄の帯", "欄を出す・隠すアイコンです。\n帯はドラッグで上下左右へ動かせます。"),
            Step(lambda: self.bottom_bar, "下の帯とステータスバー", "下の帯で拡大と元に戻すを操作します。\nいちばん下には道具・位置・大きさ・AI の状態が出ます。"),
            Step(lambda: self.menuBar(), "配置", "「配置」で、決まった配置・寄せ・3 等分や 5 等分に切り替えます。\n欄の境目はドラッグで広げ縮めできます。"),
            Step(lambda: self.menuBar(), "配置の保存と書き出し", "「今の配置を保存」で名前を付けて残し、「自分の配置」から戻せます。\n「書き出す・読み込む」で配置をファイルにして持ち運べます。"),
            Step(lambda: None, "機能ごとの案内", "機能を初めて使うときにも、その機能の案内が出ます。\n「ヘルプ」から見直したり、出さないようにしたりできます。"),
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
            self.layout_store.setValue("tour_done", 1)
            self.hide_progress_if_idle(0)   # ツアーで見せた進みの欄を、描いていなければ戻す
        self.tour = Tour(self, self.tour_steps(), on_close=closed)
        self.tour.start()

    def maybe_tour(self):
        """初めて起動したときだけ、ツアーを出す"""
        if not int(self.layout_store.value("tour_done", 0)):
            self.start_tour()

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

    def toggle_all(self):
        on = not getattr(self, "_all_hidden", False)
        self._show_all(not on)
        self._all_hidden = on
        if on:
            self.statusBar().showMessage("欄を隠しました。Tab でまた出します", 6000)

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
        self.wait_io()   # 裏で書いている保存を書き終えてから閉じる（書きかけの作業ファイルを残さない）
        self.layout_store.setValue("running", 0)   # 正しく閉じた印（次の起動で戻すかを聞かない）
        # 次に開いたときも同じ並びにする
        self.layout_store.setValue("geometry9", self.saveGeometry())
        self.layout_store.setValue("state9", self.saveState())
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

    def _finish_menu(self, menu):
        """綺麗にする道具の一覧。使えない物は押せない形で並べ、理由をツールチップに出す"""
        from chatdraw import finishers
        menu.setToolTipsVisible(True)
        finishers.use_painter(getattr(self.studio, "painter", None))
        for f in finishers.available():
            act = menu.addAction(f["label"], lambda n=f["name"]: self.finish_with(n, background=True))
            act.setToolTip(f["tip"] if f["ready"] else f["reason"])
            act.setEnabled(f["ready"])

    def finish_with(self, name: str, background: bool = False):
        """仕上げの道具を今の絵に掛け、結果を新しいレイヤーとして重ねる。囲み（赤ペン・選択）があれば囲みの中だけ変える。
        使えないときは止めずに理由を出す。返すのは保存した置き場（出来なければ None）"""
        from chatdraw import finishers
        base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        mask = self._region_mask()
        finishers.use_painter(getattr(self.studio, "painter", None))
        if background:   # 模型を使う道具は数十秒かかる。画面の糸で回すと、その間アプリが固まる
            ok, why = self._finisher_ready(name)
            if not ok:
                self.notify("綺麗にできませんでした", "info", why)
                return None
            self.activity.begin("絵を綺麗にする", "綺麗にする")
            path = self._finished_path(name)
            self._run_task(lambda _step: self._save_out(finishers.run(name, base, mask), path),   # 書くのも裏の糸
                           lambda out: (self._place_finished(name, base, out, path), self._end("綺麗にしました")))
            return None
        try:
            out = finishers.run(name, base, mask)
        except finishers.Unavailable as e:
            self.notify("綺麗にできませんでした", "info", str(e))
            return None
        except Exception as e:  # 道具の中の失敗も、止めずに理由を出す
            from chatdraw.engine import explain
            self.notify("綺麗にできませんでした", "error", explain(e))
            return None
        return self._place_finished(name, base, out)

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
            self.notify("描けませんでした", "info", "絵の模型がまだありません。AI のメニューで模型を取ってください")
            return None
        return painter

    def chara_turnaround(self):
        from chatdraw import charadesign
        painter, ident = self._chara_painter(), getattr(self, "chara_id", "")
        if painter is None or not ident:
            return
        self.activity.begin("三面図を描く", "キャラクターデザイン")
        seed = int(time.time()) % 100000
        self._run_task(lambda _step: charadesign.draw_turnaround(painter, ident, seed, say=self.task.status.emit),
                       lambda out: self._chara_done("三面図を描きました", out))

    def chara_expressions(self, only=("smile", "angry", "sad", "surprised")):
        from chatdraw import charadesign
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
            self.notify("表情差分を描けませんでした", "info", "顔が見つかりませんでした。顔を選択範囲か赤ペンで囲んでください")
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
        return Path(self.settings.get("output_dir")) / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.png"

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
        if out.size == base.size:
            self.canvas.add_image_layer(str(path), "綺麗にした絵")   # 元の絵は下に残す
            self.canvas.fit()
        else:
            self.canvas.replace_with_image(str(path), "綺麗にした絵")   # 拡大した絵（元に戻すで戻せる）
        self.notify("綺麗にしました（新しいレイヤー）", "ok", "見比べて、使うか消すかを決めてください")
        return path

    def outpaint_canvas(self, left: int, top: int, right: int, bottom: int, background: bool = False):
        """絵の外へ広げる。広げた絵でキャンバスを置き換える（元に戻すで戻せる）。使えないときは理由を出して止めない"""
        from chatdraw import finishers
        base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        known = (getattr(self, "edit_meta", None) or {}).get("prompt", "")
        last, words = self.last_text, self.studio.words

        def to_prompt():   # 言葉の模型に聞くので、裏の糸で呼ぶ（画面の糸で読むと数秒〜数十秒固まる）
            return known or words.to_prompt(last) if last else ""
        painter, seed = getattr(self.studio, "painter", None), self.ai_panel.seed.value()
        if background:   # 描くのは模型なので裏の糸で回す（画面の糸で回すと描き終えるまで固まる）
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
        self.canvas.replace_with_image(str(path), "広げた絵")
        self.notify("絵の外へ広げました", "ok", "元の絵の画素はそのままです。広げた所を見て、使うか元に戻すかを決めてください")
        return path

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
            self.run_io(lambda: project.read(path), done)
            return
        else:
            self.canvas.show_image(path)
            self.project_path = None
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
                self.notify("保存できませんでした", "error", str(e))
                return False
            self.project_path, self.dirty = path, False
            self.notify("保存しました", "ok", Path(path).name)
            return True
        self.project_path, self.dirty = path, False
        self.statusBar().showMessage("保存しています…")

        def done(err):
            if isinstance(err, BaseException):
                self.dirty = True
                self.notify("保存できませんでした", "error", str(err))
                return
            self.notify("保存しました", "ok", Path(path).name)
        self.run_io(lambda: project.write(snap, path), done)
        return True

    def run_io(self, work, done):
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
        self._io_queue.put((work, self._bg_register(done)))

    def _bg_done(self, got):
        """裏の糸の答えを画面の糸で受ける。done が落ちても数は戻す（数が残ると、試験と閉じる前の待ちが終わらない）"""
        key, v = got
        done = self._waiting.pop(key, None)
        self.bg_pending -= 1
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
                    lambda err: self.notify("書き出せませんでした", "error", str(err)) if isinstance(err, BaseException)
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
        threading.Thread(target=lambda: self.update_bridge.got.emit(updater.check()), daemon=True).start()

    def _update_found(self, info, manual: bool):
        from chatdraw import updater
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
    from chatdraw.paths import adopt_stray
    try:
        adopt_stray()   # 前の版がずれた置き場（cd）に書いた ★・非表示などを、本来の置き場へ合わせる
    except OSError:
        pass
    app = QApplication(sys.argv)
    dark(app)
    from chatdraw import fit
    fit.install(app)
    w = Window()
    w.show()
    w.ask_models()
    w.ask_words_once()
    w.upgrade_models()
    w.check_ai()
    w.offer_restore()
    # closeEvent を通らずに終わる道（更新を入れて閉じるなど）でも、正しく閉じた印を残す
    app.aboutToQuit.connect(lambda: (w.layout_store.setValue("running", 0), w.layout_store.sync()))
    w.maybe_tour()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(5000, w.check_update)   # 起動の邪魔をしないよう、少し待ってから確かめる
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
