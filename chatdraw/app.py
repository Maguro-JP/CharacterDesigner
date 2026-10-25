"""CharacterDesigner のウィンドウ。チャットで頼むと絵を描いて並べる。

  python chatdraw/app.py
"""
from __future__ import annotations

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
from chatdraw.canvas import Canvas  # noqa: E402
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
                self.one.emit(" / ".join(prompts), str(path))
            else:
                for seed in self.seeds:
                    extra = dict(reference=self.reference, ref_scale=self.ref_scale) if self.reference is not None else {}
                    prompt, path = self.studio.draw(self.text, seed, on_status=self.status.emit,
                                                    base=self.base, strength=self.strength, size=self.size,
                                                    on_preview=self.preview.emit, style=self.style, meta=self.meta, **extra)
                    self.one.emit(prompt, str(path))
            self.done.emit()
        except Exception as e:  # 描けなかった理由をそのまま会話に出す
            self.failed.emit(f"描けませんでした: {e}")


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
            self.failed.emit(f"できませんでした: {e}")


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
    """キャンバス全体の縮小図。押した所を真ん中に出す。描くたびに作り直すと重いので、変わってから少し待って作る"""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(120)
        self.setToolTip("押した所を真ん中に表示します")
        from PySide6.QtCore import QTimer
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.redraw)
        canvas.changed.connect(self.timer.start)
        canvas.history_changed.connect(self.timer.start)

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

    def mousePressEvent(self, e):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return
        w, h = self.canvas.size_px()
        x0, y0 = (self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2
        px, py = (e.position().x() - x0) / pm.width(), (e.position().y() - y0) / pm.height()
        self.canvas.centerOn(min(max(px, 0), 1) * w, min(max(py, 0), 1) * h)


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
        self.collapsed = not self.collapsed
        body = self.dock.widget()
        head = self.height() + 4
        if self.collapsed:
            def done():
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
        self.settings = Settings()
        self.layout_store = QSettings("CharacterDesigner", "chatdraw")   # 配置・テーマ・AI プリセット・ツアーの済み
        self.last_text = ""
        self.studio = studio or self._studio_from_settings()
        self.setWindowTitle("CharacterDesigner")
        self.resize(1400, 900)
        self.images: list[str] = []
        self.thread: QThread | None = None

        self.canvas = Canvas()
        self.canvas.set_cursor_style(self.settings.get("cursor"))
        self.canvas.new_canvas()
        self.setCentralWidget(self.canvas)

        # 左: 頼み（チャット）
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("描きたい絵か、してほしい操作を書く（例: 猫耳の少女 / ペンにして）")
        self.entry.setToolTip("描いてほしい絵を日本語か英語で書き、Enter か「描く」で描きます。\n「赤にして」「レイヤーを足して」のような操作も AI がします")
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
        self.entry.setMinimumHeight(34)
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
        follow.setContentsMargins(8, 0, 8, 0)
        ask.addLayout(follow)
        self.model_label = QPushButton()
        self.model_label.setObjectName("modelButton")
        self.model_label.setToolTip("絵の模型。押すと切り替えられます")
        self.model_label.clicked.connect(lambda: self.ai_menu.exec(self.model_label.mapToGlobal(self.model_label.rect().bottomLeft())))
        model_row = QHBoxLayout()
        model_row.setContentsMargins(8, 0, 8, 8)
        model_row.addWidget(self.model_label)
        ask.addLayout(model_row)
        ask.addStretch()
        ask_page = QWidget()
        ask_page.setLayout(ask)
        self.ai_tabs = QTabWidget()
        # AI の欄は項目が多いので、縦に流れる形にする。入りきらない画面（ノートの 1280×720 など）でウィンドウが画面より大きくならない
        from PySide6.QtWidgets import QScrollArea
        ask_scroll = QScrollArea()
        ask_scroll.setWidget(ask_page)
        ask_scroll.setWidgetResizable(True)
        ask_scroll.setFrameShape(QScrollArea.NoFrame)
        ask_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ask_page.setObjectName("scrollInner")
        self.ai_tabs.addTab(ask_scroll, "描き方")
        self.ai_tabs.setTabBarAutoHide(True)   # タブが 1 つのときは見出しだけで足りる
        dock = QDockWidget("AI", self)
        dock.setWidget(self.ai_tabs)
        dock.setObjectName("chat")
        dock.setFeatures(PANEL)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # 真ん中の下: チャット。会話の流れと、頼みを書く欄と「描く」
        talk_box = QWidget()
        tl = QVBoxLayout(talk_box)
        tl.setContentsMargins(8, 4, 8, 8)
        tl.addWidget(self.chat, 1)
        line = QHBoxLayout()
        line.addWidget(self.entry, 1)
        line.addWidget(self.button)
        line.addWidget(self.stop_button)
        self.button.setMinimumWidth(110)
        tl.addLayout(line)
        # 書く欄の下のボタン。お気に入り（★、固定）を先に、そのあとに直近に頼んだ言葉を新しい順に並べる。
        # 押すと書く欄に入り、ダブルクリックでそのまま描く。右クリックで固定・外す・消す。書く欄で ↑↓ でも呼び出せる
        self.fav_button = QPushButton("☆")
        self.fav_button.setToolTip("書く欄の言葉をお気に入りに固定する")
        self.fav_button.setFixedWidth(40)
        self.fav_button.clicked.connect(self._toggle_fav)
        self.entry.textChanged.connect(lambda t: self.fav_button.setText("★" if t.strip() and t.strip() in self.favorite_prompts() else "☆"))
        line.addWidget(self.fav_button)
        self.tips = QHBoxLayout()
        self.tips.setSpacing(4)
        tips_box = QWidget()
        tips_box.setLayout(self.tips)
        tips_scroll = QScrollArea()   # ボタンは横に流す。狭い画面でチャットの欄の幅を広げさせない
        tips_scroll.setWidget(tips_box)
        tips_scroll.setWidgetResizable(True)
        tips_scroll.setFrameShape(QScrollArea.NoFrame)
        tips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tips_box.setObjectName("scrollInner")
        self.tips_scroll = tips_scroll
        self.entry.installEventFilter(self)
        self._load_prompts()
        tips_scroll.setFixedHeight(QPushButton("あ").sizeHint().height() + 14)
        tl.addWidget(tips_scroll)
        talk = QDockWidget("チャット", self)
        talk.setWidget(talk_box)
        talk.setObjectName("talk")
        talk.setFeatures(PANEL)
        self.addDockWidget(Qt.BottomDockWidgetArea, talk)

        # 右: 描いた絵。AI の今の工程・進み・時間と、描いた絵の履歴
        self.activity = ActivityPanel()
        self.history = self.activity.list
        # ダブルクリックは今の絵に重ねる（今の絵を閉じない）。右クリックで開く・同じ設定で描き直す
        self.history.itemDoubleClicked.connect(lambda it: it.data(Qt.UserRole) and self.canvas.add_image_layer(it.data(Qt.UserRole), "AI の絵"))
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._history_menu)
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
        file.addAction(QAction("保存", self, shortcut="Ctrl+S", triggered=self.save_project))
        file.addAction(QAction("名前を付けて保存…", self, shortcut="Ctrl+Shift+S", triggered=lambda: self.save_project(ask=True)))
        out = file.addMenu("書き出す")
        out.addAction(QAction("PNG（重ねた 1 枚）…", self, shortcut="Ctrl+E", triggered=self.save_as))
        out.addAction(QAction("PSD（レイヤーごと）…", self, triggered=self.export_psd))
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
        self.layer_opacity.setToolTip("レイヤーの不透明度")
        row2.addWidget(self.layer_opacity)
        lay.addLayout(row2)
        lay.addLayout(buttons)
        lbox = QWidget()
        lbox.setLayout(lay)
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
        self.canvas.changed.connect(self._refresh_layers)
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
        self._refresh_layers()
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
        from chatdraw import themes
        self.theme_menu = view.addMenu("テーマ")
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        self.ai_menu = self.menuBar().addMenu("AI")
        self.ai_menu.aboutToShow.connect(self._fill_ai_menu)
        self._fill_ai_menu()
        setting_menu = self.menuBar().addMenu("設定")
        setting_menu.addAction(QAction("設定…", self, shortcut="Ctrl+,", triggered=self.open_settings))
        setting_menu.addAction(QAction("キーの設定…", self, triggered=self.open_keys))
        setting_menu.addAction(QAction("並びを初めの形に戻す", self, triggered=self.reset_layout))
        setting_menu.addAction(QAction("模型の管理（入れ替え・更新）…", self, triggered=lambda: self.ask_models(force=True)))
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
        self.library_panel = LibraryPanel(self)
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
            d.visibilityChanged.connect(lambda on, d=d: self._appear(d, on))
        self.tools = tools
        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AnimatedDocks)
        # 欄どうしを重ねるとタブになる（欄の見出しを別の欄の上へドラッグ）。タブは上に出す
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
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
        for k in PANEL_ORDER:
            d = self.panels[k][0]
            act = d.toggleViewAction()   # チェックが付いていれば表示中
            act.setShortcut(keys[k])
            act.setIcon(icon(icons[k]))
            act.setToolTip(f"{d.windowTitle()}（{keys[k]}）")
            act.triggered.connect(lambda on, k=k: on and self.feature_tour(k))
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
        win.addAction(QAction("整列（初期の配置に戻す）", self, triggered=self.arrange))
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
        help_menu.addSeparator()
        auto = QAction("機能を初めて使うときに案内を出す", self, checkable=True)
        auto.setChecked(tours.enabled(self))
        auto.toggled.connect(lambda on: self.layout_store.setValue("feature_tours", int(on)))
        help_menu.addAction(auto)
        help_menu.addAction(QAction("機能の案内をもう一度出す", self, triggered=lambda: (tours.reset(self),
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
        if obj is getattr(self, "entry", None) and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Up, Qt.Key_Down):
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
        self.chat.append(f"<b>{who}</b>: {text}")

    def _show_model(self):
        from chatdraw.models import image_model
        from chatdraw.setup import AUTO
        key = self.settings.get("image_model")
        self.model_label.setText("絵の模型: おまかせ" if key == AUTO else f"絵の模型: {image_model(key).name}")

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
            self.ai_label.setText("AI: 使えます" + ("" if st["words"] else "（言葉の模型なし。日本語はそのまま渡します）"))
            self.ai_label.setStyleSheet("color:#8fd18f")
        else:
            self.ai_label.setText("AI: 使えません")
            self.ai_label.setStyleSheet("color:#ff7a5c")
            self.ai_label.setToolTip(st["reason"])
        return st

    def send(self):
        text = self.entry.text().strip()
        pen = self.canvas.redpen
        if self.thread or not text and not (pen.marks and all(pen.texts)):   # 絵の上に全部書いてあれば、チャットは空でよい
            return
        if not text:
            text = " / ".join(f"{i}: {t}" for i, t in enumerate(pen.texts, 1))
        from chatdraw import commands
        reply = commands.handle(self, text)   # 操作の頼み（道具・色・欄・配置など）はその場で行い、絵は描かない
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
            return
        self.entry.clear()
        self.last_text = text
        self._remember_prompt(text)
        self.say(text, "あなた")
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
        self.studio.painter.avoid = ", ".join(self.ai_panel.taste()["avoid"])
        self.thread = QThread()
        self.job = Job(self.studio, text, seeds, base=base, strength=self.strength.value() / 100,
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
        self.thread.start()

    def offer_two_stage_parts(self):
        """2 段で描ける模型がそろっていて、部品（約 2.9GB）だけが無いときに、取るかを聞く。
        取らないと、おまかせでは黙って 1 つの模型で描き、崩れにくい描き方が使われないままになる"""
        if self.studio.way == "one" or self.mode.currentIndex() != 0 or getattr(self, "_two_parts_asked", False):
            return
        from chatdraw import twostage
        from chatdraw.choose import installed_images
        try:
            if twostage.pick(installed_images(), self.studio.painter.model) is None or twostage.parts_ready():
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
        """1 枚できるたびに呼ばれる。初めの 1 枚はキャンバスに置き、ほかは履歴に並べて選べるようにする"""
        self.images.append(path)
        self.canvas.show_overlay(None)
        if prompt and prompt != self.last_text:
            self.say(f"絵の模型に渡した言葉: {prompt}")   # 頼みとずれた絵が出たとき、どこでずれたかを見られるように
        if self.job_kind == "chibi":
            self.canvas.add_image_layer(path, "ちびキャラ")
        elif self.job_kind == "fix":
            bad = getattr(self.studio, "last_flaws", [])
            self.canvas.add_image_layer(path, f"AI の直し {len(self.images)}" + ("（崩れあり）" if bad else ""))
            if bad:   # 崩れの見つかった直しは見えなくして重ねる。元の絵を壊さず、見るか消すかは利用者が決める
                self.canvas.set_visible(self.canvas.current, False)
                self._refresh_layers()
                for f in bad:
                    self.say(f"崩れ: {f}")
            else:
                self.canvas.redpen.clear()   # 崩れが見つからなければ、印は役目を終える
        elif not self.batch:
            self.activity.status("キャンバスに置いています")
            self.place(path)
        self.batch.append(path)
        self.batch_items.append(self.activity.add(path, prompt))
        self.library_panel.add(self.library.add_work(path))   # 描いた絵はライブラリーにも入る（好き・いまいちを付けて好みを育てる）

    def finish(self):
        n = len(self.batch)
        fixed = self.job_kind in ("fix", "chibi")
        bad = getattr(self.studio, "last_flaws", []) if self.job_kind == "fix" else []
        result = ("直しを重ねました（崩れあり・隠しています）" if bad else "直しを重ねました") if fixed else \
            f"{n} 枚描きました" if n > 1 else "描けました"
        for it in self.batch_items:
            it.setToolTip(f"{result}\n{it.toolTip()}")
        self.activity.end(result, None, record=False)
        self.say(result if fixed else f"{n} 枚描きました。履歴から選べます" if n > 1 else "描きました")
        self.notify(result if fixed else "描けました", "error" if bad else "ok",
                    (f"崩れ {len(bad)} 件。レイヤーを隠して重ねました。見て決めてください" if bad else
                     "新しいレイヤーに重ねました。見て決めてください") if fixed else
                    (f"1 枚目を重ねました。ほかの {n - 1} 枚は履歴をダブルクリックで重ねられます" if n > 1
                     else "レイヤーとして重ねました。押すと履歴を開きます"),
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
        img = postfx.lineart(qimage_to_pil(self.canvas.flatten()))
        out = Path(self.settings.get("output_dir"))
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{time.strftime('%Y%m%d-%H%M%S')}-lineart.png"
        img.save(path)
        self.canvas.add_image_layer(str(path), "線画")
        self.activity.add(str(path), "線画")
        self.notify("線画にしました", "ok", "新しいレイヤーに重ねました。元の絵は下に残っています")

    def make_pixel(self, long: int = 128, colors: int = 24):
        """今の絵をドット絵にして、新しいレイヤーに重ねる。小さいドット絵（1 ドット 1 画素）も出力の置き場に残す"""
        from chatdraw import postfx
        self.feature_tour("pixel")
        img = qimage_to_pil(self.canvas.flatten())
        dots = postfx.pixel_art(img, long=long, colors=colors)
        out = Path(self.settings.get("output_dir"))
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        small = out / f"{stamp}-pixel.png"
        dots.save(small)
        big = out / f"{stamp}-pixel-view.png"
        postfx.enlarge(dots, img.size).save(big)
        self.canvas.add_image_layer(str(big), "ドット絵")
        self.activity.add(str(small), f"ドット絵 {dots.width}×{dots.height}・{colors} 色")
        self.notify("ドット絵にしました", "ok", f"{dots.width}×{dots.height} ドット・{colors} 色。元の大きさの絵は履歴にあります")

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
                if not self.save_project():
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
        self.task.done.connect(then)
        self.task.failed.connect(self.fail)
        self.button.setEnabled(False)
        self.thread.start()

    def _history_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        it = self.history.itemAt(pos)
        path = it.data(Qt.UserRole) if it else None
        if not path:
            return
        m = QMenu(self)
        m.addAction("今の絵に重ねる", lambda: self.canvas.add_image_layer(path, "AI の絵"))
        m.addAction("この設定で描き直す", lambda: self.redo_from(path))
        m.addAction("この絵を開く", lambda: self.canvas.show_image(path))
        m.exec(self.history.mapToGlobal(pos))

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
        from chatdraw.models import IMAGES, all_images
        from chatdraw.setup import AUTO, has_image
        g = self.settings.get
        image, words = g("image_model"), g("words_model")
        if image == AUTO:
            have = [m for m in all_images() if has_image(m)]
            first = max(have, key=lambda m: m.score) if have else IMAGES[0]
            image, steps, guidance = first.repo, first.steps, first.guidance
        else:
            steps, guidance = g("steps"), g("guidance")
        old = getattr(self, "studio", None)
        painter = old.painter if old is not None and getattr(old.painter, "model", None) == image else Painter(image)
        painter.steps, painter.guidance = steps, guidance
        studio = Studio(Words(None if words == AUTO else Path(words)), painter, Path(g("output_dir")))
        studio.image_auto, studio.words_auto = g("image_model") == AUTO, words == AUTO
        studio.way = {"1つの模型で描く": "one", "構図と仕上げを分けて描く": "two"}.get(g("draw_way"), "auto")
        return studio

    def open_help(self, key: str):
        from chatdraw.helpview import HelpDialog
        HelpDialog(key, self).show()

    def open_logs(self):
        """記録（chatdraw.log、setup.log）の置き場を開く。困ったときに中を見たり、渡したりするため"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        DATA.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA)))

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
            if getattr(dlg, "model_dir_changed", False):
                self.notify("模型の置き場を変えました", "info", "次に起動したときから新しい置き場を使います。前の置き場の模型は動かしていません")
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
        self.statusBar().showMessage(f"新しい言葉の模型 {new.name} を裏で取っています", 6000)
        threading.Thread(target=self.upgrader.run, args=(None, new), daemon=True).start()

    # ---- AI のメニュー: 模型の切り替え ----
    def _fill_ai_menu(self):
        """開くたびに作り直す（取った・取っていないが変わるため）"""
        from chatdraw.models import IMAGES, offered_images
        from chatdraw.setup import AUTO, has_image
        menu = self.ai_menu
        menu.clear()
        now_image = self.settings.get("image_model")
        # 出すのは、確かめて推奨に届いた模型と、手元にある模型だけ（ほかは「模型の管理」で推奨の絞りを外すと出る）
        from chatdraw.models import manual_images
        images = [m for m in IMAGES if m in offered_images() or has_image(m)] + manual_images()
        menu.addSection("絵の模型")
        group = QActionGroup(menu)
        for key, name, have in [(AUTO, "おまかせ", True)] + [(m.repo, m.name, has_image(m)) for m in images]:
            act = QAction(name if have else f"{name}（未取得）", menu, checkable=True)
            act.setChecked(key == now_image)
            act.triggered.connect(lambda _=False, k=key: self.switch_model("絵の模型", k))
            group.addAction(act)
            menu.addAction(act)
        menu.addSeparator()
        menu.addAction(QAction("模型の管理…", self, triggered=self.manage_models))

    def manage_models(self):
        if self.feature_tour("manager", self.manage_models):
            return
        from chatdraw.manager import ModelManager
        ModelManager(self.settings, self).exec()
        self.studio = self._studio_from_settings()
        self.check_ai()

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
                self.settings.set("words_model", str(find_gguf(key) or key))   # 利用者が自分で置いた模型
                self.studio = self._studio_from_settings()
                self.check_ai()
                return
        if need:
            dlg = SetupDialog(self.settings, self, first=False)
            dlg.select(**({"image": key} if kind == "絵の模型" else {"words": key}))
            dlg.start(update=False)
            if not dlg.exec():
                return
        elif kind == "絵の模型":
            self.settings.set("image_model", key)
            if m is not None:
                self.settings.set("steps", m.steps)
                self.settings.set("guidance", m.guidance)
        else:
            self.settings.set("words_model", key if key in (AUTO, "") else str(words_path(m)))
        self.studio = self._studio_from_settings()
        self.check_ai()
        self.notify(f"{kind}を替えました", "ok")

    def show_preview(self, img):
        """AI が描いている途中の絵を、工程ごとにキャンバスの上に重ねて見せる（録画はしない）"""
        self.canvas.show_overlay(qimage_from_pil(img))

    def place(self, path: str):
        """描けた絵を置く。新しく描いて、まだ何も描いていないキャンバスなら絵を開く。
        キャンバスを元に描いたときと、描いている途中なら、元の絵を残して新しいレイヤーとして重ねる"""
        if self.mode.currentIndex() == 0:
            # 新しく描いた絵は、いつも同じ形で置く（キャンバスを置き換え、前の状態は元に戻すで戻せる）。
            # 前は、キャンバスの状態で置き換えたり上に重ねたりが変わり、大きさの違う絵が重なった
            self.canvas.replace_with_image(path, f"AI の絵 {len(self.images)}")
        else:
            self.canvas.add_image_layer(path, f"AI の絵 {len(self.images)}")

    def stop(self):
        self.studio.painter.stop = True
        self.statusBar().showMessage("止めています")

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
        from chatdraw.layouts import recommended
        recommended(self)

    def apply_layout(self, fn, *args):
        """配置を当て、絵を新しい大きさに合わせる"""
        fn(self, *args)
        from PySide6.QtCore import QTimer
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
            p["talk"][0].show()
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
            ("欄", [p[k][0].toggleViewAction() for k in PANEL_ORDER]),
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
            Step(lambda: p["talk"][0], "チャット", "描きたい絵を書いて「描く」を押します。\nAI とのやり取りはここに残ります。", show("talk")),
            Step(lambda: p["chat"][0], "AI の設定", "「新規」か「ラフから」、絵の大きさ、ラフに沿う強さ、絵の模型を選びます。", show("chat")),
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

    def _appear(self, d: QDockWidget, on: bool):
        """隠していた欄を出したときだけ、中身をふわっと出す（タブの切り替えでは動かさない）"""
        from chatdraw.motion import fade_in
        if on and getattr(d, "_was_hidden", False) and d.widget() is not None:
            fade_in(d.widget())
        d._was_hidden = not on and d.isHidden()

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
            if box.clickedButton() is save and not self.save_project() or box.clickedButton() not in (save, drop):
                e.ignore()
                return
        self.layout_store.setValue("running", 0)   # 正しく閉じた印（次の起動で戻すかを聞かない）
        # 次に開いたときも同じ並びにする
        self.layout_store.setValue("geometry9", self.saveGeometry())
        self.layout_store.setValue("state9", self.saveState())
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
        if self.feature_tour("open", self.open_image):
            return
        path, _ = QFileDialog.getOpenFileName(self, "開く", "", "作業ファイルと画像 (*.cdproj *.png *.jpg *.jpeg *.webp)")
        if path:
            self.open_path(path)

    def open_path(self, path: str):
        from chatdraw import project
        if path.endswith(project.SUFFIX):
            try:
                project.load(self.canvas, path)
            except (OSError, ValueError, KeyError) as e:
                self.notify("開けませんでした", "error", str(e))
                return
            self.project_path = path
        else:
            self.canvas.show_image(path)
            self.project_path = None
        self.dirty = False

    def save_project(self, ask: bool = False) -> bool:
        """作業ファイル（レイヤー・赤ペンの印ごと）に保存する。初めてか ask なら置き場を聞く。保存できたら True"""
        from chatdraw import project
        path = getattr(self, "project_path", None)
        if ask or not path:
            if self.feature_tour("project", lambda: self.save_project(ask)):
                return False
            path, _ = QFileDialog.getSaveFileName(self, "作業ファイルを保存", "drawing" + project.SUFFIX,
                                                  f"作業ファイル (*{project.SUFFIX})")
            if not path:
                return False
            if not path.endswith(project.SUFFIX):
                path += project.SUFFIX
        try:
            project.save(self.canvas, path)
        except OSError as e:
            self.notify("保存できませんでした", "error", str(e))
            return False
        self.project_path, self.dirty = path, False
        self.notify("保存しました", "ok", Path(path).name)
        return True

    def export_psd(self):
        from chatdraw import project
        dst, _ = QFileDialog.getSaveFileName(self, "PSD で書き出す", "drawing.psd", "PSD (*.psd)")
        if not dst:
            return
        try:
            project.export_psd(self.canvas, dst)
            self.notify("書き出しました", "ok", f"{Path(dst).name}（レイヤー {len(self.canvas.layers)} 枚）")
        except OSError as e:
            self.notify("書き出せませんでした", "error", str(e))

    def autosave(self):
        """変わっていれば、決まった置き場に作業ファイルを書く。落ちたときに次の起動で戻せるように"""
        from chatdraw import project
        if not getattr(self, "dirty", False) or not self.canvas.layers:
            return
        path = project.autosave_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            project.save(self.canvas, path)
            self.autosaved = True
        except OSError:
            pass   # 自動保存が書けなくても、描く邪魔はしない

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
        if getattr(self, "dirty", False) and not self.save_project():
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
        crashed = int(self.layout_store.value("running", 0))
        self.layout_store.setValue("running", 1)
        path = project.autosave_path()
        if not crashed or not path.exists():
            return False
        box = QMessageBox(QMessageBox.Question, "前の絵を戻す",
                          "前回は正しく閉じられませんでした。自動保存した絵を開きますか。", parent=self)
        yes = box.addButton("開く", QMessageBox.AcceptRole)
        box.addButton("開かない", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.open_path(str(path))
            self.project_path = None   # 自動保存の場所に上書き保存しない
            self.dirty = True
            return True
        return False

    def save_as(self) -> bool:
        """保存できたら True"""
        if not self.canvas.layers:
            return False
        if self.feature_tour("save", self.save_as):
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

    def hide_progress_if_idle(self, ms: int = 4000):
        """進みの欄は自分では隠さない。描き終わると消えて、結果も今の状態も分からなかった。閉じるのは利用者だけ"""

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
    app = QApplication(sys.argv)
    dark(app)
    from chatdraw import fit
    fit.install(app)
    w = Window()
    w.show()
    w.ask_models()
    w.upgrade_models()
    w.check_ai()
    w.offer_restore()
    w.maybe_tour()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(5000, w.check_update)   # 起動の邪魔をしないよう、少し待ってから確かめる
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
