"""AI の欄。押すだけで描き方がそろう「AI プリセット」と、絵の雰囲気を決める「画風」を、大きなカードとチップで並べる。

描き方（新規・ラフから）、大きさ、ラフに沿う強さ、画風を 1 つずつ選ばせると、初めての人は何を選べばよいか分からない。
よく使う組み合わせをプリセットにして、1 回押せば描ける状態にする。自分の組み合わせも名前を付けて残せる。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QLineEdit, QSlider, QSpinBox, QButtonGroup, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QScrollArea, QSizePolicy, QTabWidget, QToolButton, QVBoxLayout, QWidget)

# 画風: (名前, 描く言葉に足すタグ, ヒント)。タグは英語のまま模型に渡す
STYLES: list[tuple[str, str, str]] = [
    ("おまかせ", "", "画風を足さず、頼みと絵の模型に任せます"),
    ("アニメ", "anime coloring, cel shading, clean lineart, vibrant colors", "くっきりした線と影のアニメの塗り"),
    ("厚塗り", "painterly, thick painting, rich lighting, detailed shading", "絵の具を重ねたような厚い塗り"),
    ("水彩", "watercolor, soft colors, paper texture, light wash", "にじみのある淡い水彩"),
    ("SF", "science fiction, futuristic, neon lights, mecha details", "近未来の光と機械"),
    ("レトロ", "retro anime, 1990s style, film grain, muted colors", "90 年代のアニメの色合い"),
    ("スチームパンク", "steampunk, brass, gears, victorian, warm light", "真鍮と歯車の世界"),
    ("自然", "nature, forest, soft sunlight, green, flowers", "森と日差しのやわらかい光"),
]
STYLE_TAGS = {name: tags for name, tags, _ in STYLES}

SIZES = {"縦": (832, 1216), "横": (1216, 832), "正方形": (1024, 1024)}

# AI プリセット: (名前, ひとこと, 描き方 0=新規 1=ラフから, 大きさ, 画風, ラフに沿う強さ%)
# 先頭の「標準」は最初の状態。どのプリセットを選んだあとでも、押せば元に戻せる
DEFAULT_PRESET = "標準"
PRESETS: list[tuple[str, str, int, str, str, int]] = [
    (DEFAULT_PRESET, "最初の設定に戻す", 0, "縦", "おまかせ", 100),
    ("キャラデザ", "全身の立ち絵を縦長で", 0, "縦", "アニメ", 100),
    ("ラフを清書", "キャンバスの線を清書", 1, "縦", "アニメ", 100),
    ("ラフから自由に", "ラフを元に AI が整える", 1, "縦", "厚塗り", 60),
    ("イラスト", "場面の 1 枚を横長で", 0, "横", "厚塗り", 100),
    ("アイコン", "顔まわりを正方形で", 0, "正方形", "アニメ", 100),
    ("赤ペンで直す", "囲んだ所を指示どおりに", 2, "縦", "おまかせ", 45),
]
PROMPT_SUFFIX = {"キャラデザ": "full body, standing, simple background", "アイコン": "portrait, upper body, looking at viewer"}


# タブ: (名前, ヒント)。初めに開くのは先頭の「描く内容」
SECTIONS = [
    ("描く内容", "描きたい絵と、描かない物を書きます"),
    ("作風", "AI プリセットと画風。押すだけで描き方・大きさ・画風がそろいます"),
    ("模型", "絵を描く模型を選びます"),
    ("詳しい設定", "枚数・種・参考画像・ラフに沿う強さ"),
    ("加工", "出来た絵から作ります。元の絵は残し、新しいレイヤーに重ねます"),
]


class Section(QScrollArea):
    """AI の欄のタブ 1 枚。中身が長いときはタブの中だけを縦に流す（描くボタンはタブの外にあり、隠れない）"""

    def __init__(self, tabs: QTabWidget, title: str):
        super().__init__()
        self.tabs = tabs
        self.title = title
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.box = QWidget()
        self.box.setObjectName("scrollInner")
        outer = QVBoxLayout(self.box)
        outer.setContentsMargins(2, 6, 2, 6)
        outer.setSpacing(8)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)
        outer.addStretch()
        self.setWidget(self.box)

    def is_open(self) -> bool:
        return self.tabs.currentWidget() is self

    def set_open(self, on: bool = True):
        """このタブを前に出す（開け閉めの区切りだった頃の呼び方を残す）"""
        if on:
            self.tabs.setCurrentWidget(self)


class AiPanel(QWidget):
    changed = Signal()

    def __init__(self, w):
        super().__init__()
        self.w = w
        self.preset = DEFAULT_PRESET
        self.style = "おまかせ"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)
        # 項目が多いので、タブに分ける。初めに開くのは描く内容。描くボタンはタブの外（下）に置き、どのタブからも押せる
        self.tabs = QTabWidget()
        from chatdraw.tabdock import DragOutTabBar
        self.tabs.setTabBar(DragOutTabBar(self.tabs))   # タブを足す前に替える。並べ替えと、欄の外へ出すドラッグ
        self.tabs.setObjectName("aiTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.sections: dict[str, Section] = {}
        for name, tip in SECTIONS:
            sec = Section(self.tabs, name)
            i = self.tabs.addTab(sec, name)
            self.tabs.setTabToolTip(i, tip)
            self.sections[name] = sec
        outer.addWidget(self.tabs, 1)
        # 描くボタンの帯。窓の側で「描く」「止める」などを入れる
        self.draw_bar = QHBoxLayout()
        self.draw_bar.setSpacing(4)
        outer.addLayout(self.draw_bar)
        self.tabs.setCurrentIndex(0)

        # 描く内容: 頼み（チャットの欄から移した）、模型に渡る言葉の目安、禁止ワード。頼みの欄と描くボタンは窓の側で足す
        lay = self.sections["描く内容"].body
        self.preview = QLabel("")
        self.preview.setObjectName("hint")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview.setToolTip("描く内容のうち、絵の模型に渡る言葉の目安です。言葉の模型が入っていれば、描くときにさらに整えます")
        self.negative = QLineEdit()
        self.negative.setPlaceholderText("禁止ワード（描かない物。例: 帽子、文字、hat）")
        self.negative.setToolTip("描かせたくない物を書きます。読点か , で区切ります。日本語は表で英語に直します。\n"
                                 "模型の決まった禁止ワードと、描く内容の「〜なし」に足して渡します")
        self.negative.textChanged.connect(lambda _t: self.preview_timer.start())
        from PySide6.QtCore import QTimer
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(250)   # 打つたびに表を引かない
        self.preview_timer.timeout.connect(self.update_preview)

        lay = self.sections["作風"].body
        lay.addWidget(self._head("AI プリセット", "押すと描き方・大きさ・画風がそろいます"))
        self.preset_box = QGridLayout()
        self.preset_box.setSpacing(6)
        lay.addLayout(self.preset_box)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.fill_presets()

        lay.addWidget(self._head("画風", "絵の雰囲気。描く言葉に足します"))
        styles = QGridLayout()
        styles.setSpacing(4)
        self.style_group = QButtonGroup(self)
        self.style_buttons: dict[str, QPushButton] = {}
        for i, (name, _tags, tip) in enumerate(STYLES):
            b = QPushButton(name if len(name) <= 5 else name[:4] + "…")   # 長い名前は詰め、全部はカーソルを合わせたときに出す
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setToolTip(f"{name}: {tip}")
            b.clicked.connect(lambda _=False, n=name: self.set_style(n))
            self.style_group.addButton(b)
            self.style_buttons[name] = b
            styles.addWidget(b, i // 3, i % 3)
        lay.addLayout(styles)

        lay.addWidget(self._head("描き方", ""))
        self.mode_buttons = self._segment(["新規", "ラフから", "直す"], lambda i: w.mode.setCurrentIndex(i))
        for b, tip in zip(self.mode_buttons[1], ("白紙から描きます", "キャンバスの線の形に沿って描きます",
                                                  "赤ペンで囲んだ所か、四角で選んだ所だけを描き直します")):
            b.setToolTip(tip)
        lay.addLayout(self.mode_buttons[0])
        self.size_buttons = self._segment(list(SIZES), self._pick_size)
        lay.addLayout(self.size_buttons[0])
        w.mode.currentIndexChanged.connect(self.sync)
        w.size_pick.currentIndexChanged.connect(self.sync)

        # 枚数・種・参考画像。どれも頼まなければ今までどおり（1 枚、毎回違う種、参考画像なし）
        lay = self.sections["詳しい設定"].body
        lay.addWidget(self._head("枚数と種", "何枚描くか。種を固定すると、同じ頼みで同じ絵になります"))
        self.count_buttons = self._segment(["1 枚", "2 枚", "4 枚"], lambda i: None)
        self.count_buttons[1][0].setChecked(True)
        lay.addLayout(self.count_buttons[0])
        seed_row = QHBoxLayout()
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setToolTip("種。前に描いた絵の種が入ります")
        self.seed_lock = QCheckBox("種を固定")
        self.seed_lock.setToolTip("固定すると、同じ頼みと設定で同じ絵になります。外すと毎回違う絵になります")
        seed_row.addWidget(self.seed, 1)
        seed_row.addWidget(self.seed_lock)
        lay.addLayout(seed_row)
        ref_row = QHBoxLayout()
        self.use_ref = QCheckBox("参考画像に寄せる")
        self.use_ref.setToolTip("表示の欄の「参考画像」の絵柄や雰囲気を借りて描きます。\n初めて使うときに部品（約 3GB）を取ります")
        self.ref_scale = QSlider(Qt.Horizontal)
        self.ref_scale.setRange(10, 100)
        self.ref_scale.setValue(60)
        self.ref_scale.setToolTip("寄せる強さ")
        self.use_ref.toggled.connect(lambda on: on and self.w.feature_tour("reference_ai"))
        ref_row.addWidget(self.use_ref)
        ref_row.addWidget(self.ref_scale, 1)
        lay.addLayout(ref_row)
        row = QHBoxLayout()
        self.again = QPushButton("もう一度描く")
        self.again.setToolTip("前と同じ頼みを、別の種で描き直します")
        self.again.clicked.connect(w.draw_again)
        self.save_button = QPushButton("今の設定を保存")
        self.save_button.setToolTip("今の描き方・大きさ・画風を、自分の AI プリセットとして残します")
        self.save_button.clicked.connect(self.save_current)
        row.addWidget(self.again)
        row.addWidget(self.save_button)
        lay.addLayout(row)
        lay = self.sections["加工"].body
        fx = QHBoxLayout()
        self.chibi_button = QPushButton("ちびキャラに")
        self.chibi_button.setToolTip("頭の大きなデフォルメに、AI が描き直します")
        self.chibi_button.clicked.connect(w.make_chibi)
        self.lineart_button = QPushButton("線画に")
        self.lineart_button.setToolTip("今の絵から線だけを取り出し、白地の線画にします")
        self.lineart_button.clicked.connect(w.make_lineart)
        fx.addWidget(self.lineart_button)
        self.pixel_button = QPushButton("ドット絵に")
        self.pixel_button.setToolTip("長い辺 128 ドット・24 色のドット絵にします")
        self.pixel_button.clicked.connect(lambda: w.make_pixel())
        fx.addWidget(self.chibi_button)
        fx.addWidget(self.pixel_button)
        lay.addLayout(fx)
        self.upscale_button = QPushButton("絵を 2 倍に拡大")
        self.upscale_button.setToolTip("線と塗りを保ったまま、今の絵を 2 倍の大きさにします")
        self.upscale_button.clicked.connect(w.upscale_canvas)
        lay.addWidget(self.upscale_button)
        self.set_style("おまかせ")
        self.sync()
        self.fit_narrow()

    def fit_narrow(self):
        """ボタンの文字の長さで欄の幅が決まらないようにする（狭い欄では 1 列に並べ替える）"""
        from PySide6.QtWidgets import QAbstractButton, QSpinBox, QTabBar
        for b in self.findChildren(QAbstractButton) + self.findChildren(QSpinBox):
            if isinstance(b.parent(), QTabBar):
                continue   # タブの送りボタンは Qt の大きさのまま
            if b.maximumWidth() < 200 or b.objectName() == "suggest":
                continue   # 幅を決めたボタン（■・☆）と、横に流す言葉のボタンは縮めない（幅が 0 になって消えた）
            b.setMinimumWidth(0)
            sp = b.sizePolicy()
            sp.setHorizontalPolicy(QSizePolicy.Ignored)
            b.setSizePolicy(sp)

    def avoid_words(self) -> list[str]:
        """禁止ワードの欄の言葉を、模型に渡す英語にする。日本語は表で直し、直せない言葉はそのまま渡す"""
        import re
        from chatdraw.jaterms import tags_from
        out = []
        for word in (x.strip() for x in re.split(r"[,、，\n]", self.negative.text())):
            if not word:
                continue
            got = tags_from(word) if re.search(r"[぀-ヿ一-鿿]", word) else []
            out += [t for t in (got or [word]) if t not in out]
        return out

    def update_preview(self):
        """模型に渡る言葉の目安を出す。表だけで引く（言葉の模型は描くときに 1 回だけ使う）"""
        import re
        from chatdraw.jaterms import leftover, negatives, tags_from
        text = self.w.entry.text().strip() if hasattr(self.w, "entry") else ""
        lines = []
        if text:
            if re.search(r"[぀-ヿ一-鿿]", text):
                tags, lost, neg = tags_from(text), leftover(text), negatives(text)
            else:
                tags, lost, neg = [text], [], []
            lines.append("模型に渡る言葉: " + (", ".join(tags) or "（表で拾えた言葉はありません）"))
            if lost:
                lines.append("英語にならない言葉: " + "、".join(lost))
        else:
            neg = []
        avoid = neg + [a for a in self.avoid_words() if a not in neg]
        if avoid:
            lines.append("描かない物: " + ", ".join(avoid))
        self.preview.setText("\n".join(lines))
        self.preview.setVisible(bool(lines))

    # ---- 部品 ----
    def _head(self, title: str, tip: str) -> QLabel:
        h = QLabel(title)
        h.setObjectName("sectionHead")
        h.setToolTip(tip)
        return h

    def _segment(self, labels: list[str], on_pick):
        row = QHBoxLayout()
        row.setSpacing(0)
        group = QButtonGroup(self)
        buttons = []
        for i, label in enumerate(labels):
            b = QPushButton(label)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(labels) - 1 else "mid")
            b.clicked.connect(lambda _=False, i=i: on_pick(i))
            group.addButton(b)
            buttons.append(b)
            row.addWidget(b)
        return row, buttons

    def count(self) -> int:
        return (1, 2, 4)[next((i for i, b in enumerate(self.count_buttons[1]) if b.isChecked()), 0)]

    def set_count(self, n: int):
        for b, k in zip(self.count_buttons[1], (1, 2, 4)):
            b.setChecked(k == n)

    def seeds(self) -> list[int]:
        """描く種の並び。固定なら欄の種から、外していれば新しい種から、枚数分を続けて使う"""
        import random
        first = self.seed.value() if self.seed_lock.isChecked() else random.randrange(0, 2_000_000_000)
        return [first + i for i in range(self.count())]

    def reference(self):
        """寄せる参考画像（PIL）。寄せない・置いていないなら None"""
        path = getattr(self.w.reference, "path", None)
        if not self.use_ref.isChecked() or not path:
            return None
        from PIL import Image
        return Image.open(path).convert("RGB")

    def _pick_size(self, i: int):
        self.w.size_pick.setCurrentIndex(i)

    def _card(self, name: str, sub: str, own: bool = False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("aiPreset")
        b.setCheckable(True)
        b.setText(name)   # 説明はボタンに書かず、カーソルを合わせたときに出す（ボタンが大きくなり、欄を取りすぎた）
        b.setToolTip(f"{name}: {sub}" + ("\n右クリックで消せます" if own else ""))
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setMinimumHeight(28)
        b.setMinimumWidth(0)
        if own:
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p, n=name, b=b: self._own_menu(n, b))
        return b

    # ---- プリセット ----
    def own_presets(self) -> dict[str, dict]:
        store = self.w.layout_store
        store.beginGroup("ai_presets")
        names = store.childKeys()
        store.endGroup()
        out = {}
        for n in sorted(names):
            try:
                out[n] = json.loads(store.value(f"ai_presets/{n}"))
            except (TypeError, ValueError):
                continue
        return out

    def fill_presets(self):
        while self.preset_box.count():
            item = self.preset_box.takeAt(0)
            if item.widget():
                self.preset_group.removeButton(item.widget())
                item.widget().deleteLater()
        cards = [(name, sub, dict(mode=m, size=s, style=st, strength=k), False) for name, sub, m, s, st, k in PRESETS]
        cards += [(n, "自分のプリセット", d, True) for n, d in self.own_presets().items()]
        for i, (name, sub, data, own) in enumerate(cards):
            b = self._card(name, sub, own)
            b.clicked.connect(lambda _=False, n=name, d=data: self.apply(n, d))
            self.preset_group.addButton(b)
            cols = self._cols()
            self.preset_box.addWidget(b, i // cols, i % cols)
            b.setChecked(name == self.preset)

    def _cols(self) -> int:
        """欄が狭いときはカードを 1 列にする（2 列のまま狭めると、カードの文字が欄の外にはみ出した）"""
        return 3 if self.width() >= 300 else 2

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = self._cols()
        if cols != getattr(self, "_laid_cols", None):
            self._laid_cols = cols
            buttons = [self.preset_box.itemAt(i).widget() for i in range(self.preset_box.count())]
            for b in buttons:
                self.preset_box.removeWidget(b)
            for i, b in enumerate(buttons):
                self.preset_box.addWidget(b, i // cols, i % cols)
            self.fit_narrow()

    def apply(self, name: str, data: dict):
        """プリセットを当てる。描き方・大きさ・画風・強さをそろえ、頼みを書く欄に移る"""
        self.preset = name
        self.w.mode.setCurrentIndex(int(data.get("mode", 0)))
        self.w.size_pick.setCurrentIndex(list(SIZES).index(data.get("size", "縦")))
        self.w.strength.setValue(int(data.get("strength", 100)))
        self.set_style(data.get("style", "おまかせ"))
        if name == DEFAULT_PRESET:   # 標準に戻すときは、枚数・種・参考画像も最初の状態にする
            self.count_buttons[1][0].setChecked(True)
            self.seed_lock.setChecked(False)
            self.use_ref.setChecked(False)
            self.ref_scale.setValue(60)
        for b in self.preset_group.buttons():
            b.setChecked(b.text() == name)
        self.w.entry.setFocus()
        self.w.feature_tour("ai_presets")
        self.w.statusBar().showMessage(f"AI プリセット「{name}」にしました")
        self.changed.emit()

    def apply_name(self, name: str) -> bool:
        for n, _sub, m, s, st, k in PRESETS:
            if n == name:
                self.apply(n, dict(mode=m, size=s, style=st, strength=k))
                return True
        own = self.own_presets()
        if name in own:
            self.apply(name, own[name])
            return True
        return False

    def current(self) -> dict:
        return dict(mode=self.w.mode.currentIndex(), size=list(SIZES)[self.w.size_pick.currentIndex()],
                    style=self.style, strength=self.w.strength.value())

    def save_current(self, name: str | None = None):
        if not name:
            name, ok = QInputDialog.getText(self, "AI プリセットを保存", "名前")
            if not ok or not name.strip():
                return
        self.save_preset(name.strip(), self.current())

    def save_preset(self, name: str, data: dict):
        self.w.layout_store.setValue(f"ai_presets/{name}", json.dumps(data, ensure_ascii=False))
        self.preset = name
        self.fill_presets()
        self.w.notify("AI プリセットを保存しました", "ok", f"「{name}」は AI の欄にいつでも出ます")

    def _own_menu(self, name: str, button):
        m = QMenu(self)
        m.addAction("消す", lambda: (self.w.layout_store.remove(f"ai_presets/{name}"), self.fill_presets()))
        m.exec(button.mapToGlobal(button.rect().bottomLeft()))

    # ---- 画風と同期 ----
    def set_style(self, name: str):
        self.style = name if name in STYLE_TAGS else "おまかせ"
        for n, b in self.style_buttons.items():
            b.setChecked(n == self.style)
        self.changed.emit()

    def style_tags(self) -> str:
        """描く言葉に足すタグ。画風と、プリセットの決まった言葉"""
        tags = [STYLE_TAGS.get(self.style, ""), PROMPT_SUFFIX.get(self.preset, ""), ", ".join(self.taste()["tags"])]
        return ", ".join(t for t in tags if t)

    def taste(self) -> dict:
        """ライブラリーから読み取った好み。「好みを描く言葉に足す」を外していれば空"""
        lib = getattr(self.w, "library", None)
        if lib is None or not int(self.w.layout_store.value("use_taste", 1)):
            return {"tags": [], "avoid": []}
        return lib.profile()

    def sync(self, *_):
        for i, b in enumerate(self.mode_buttons[1]):
            b.setChecked(i == self.w.mode.currentIndex())
        for i, b in enumerate(self.size_buttons[1]):
            b.setChecked(i == self.w.size_pick.currentIndex())
            b.setEnabled(self.w.mode.currentIndex() == 0)   # ラフから・直すはキャンバスの縦横に合わせる
        for b in self.count_buttons[1]:
            b.setEnabled(self.w.mode.currentIndex() != 2)   # 直すときは 1 回だけ
