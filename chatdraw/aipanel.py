"""AI の欄。押すだけで描き方がそろう「AI プリセット」と、絵の雰囲気を決める「作風」を、大きなカードとチップで並べる。

描き方（新規・ラフから）、大きさ、ラフに沿う強さ、作風を 1 つずつ選ばせると、初めての人は何を選べばよいか分からない。
よく使う組み合わせをプリセットにして、1 回押せば描ける状態にする。自分の組み合わせも名前を付けて残せる。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

# 作風: (名前, 描く言葉に足すタグ, ヒント)。タグは英語のまま模型に渡す
STYLES: list[tuple[str, str, str]] = [
    ("おまかせ", "", "作風を足さず、頼みと絵の模型に任せます"),
    ("アニメ", "anime coloring, cel shading, clean lineart, vibrant colors", "くっきりした線と影のアニメの塗り"),
    ("厚塗り", "painterly, thick painting, rich lighting, detailed shading", "絵の具を重ねたような厚い塗り"),
    ("水彩", "watercolor, soft colors, paper texture, light wash", "にじみのある淡い水彩"),
    ("線画", "monochrome, lineart, ink drawing, white background", "色を塗らない線だけの絵"),
    ("デフォルメ", "chibi, super deformed, cute, big head", "頭の大きなかわいい等身"),
    ("SF", "science fiction, futuristic, neon lights, mecha details", "近未来の光と機械"),
    ("レトロ", "retro anime, 1990s style, film grain, muted colors", "90 年代のアニメの色合い"),
    ("スチームパンク", "steampunk, brass, gears, victorian, warm light", "真鍮と歯車の世界"),
    ("自然", "nature, forest, soft sunlight, green, flowers", "森と日差しのやわらかい光"),
]
STYLE_TAGS = {name: tags for name, tags, _ in STYLES}

SIZES = {"縦": (832, 1216), "横": (1216, 832), "正方形": (1024, 1024)}

# AI プリセット: (名前, ひとこと, 描き方 0=新規 1=ラフから, 大きさ, 作風, ラフに沿う強さ%)
PRESETS: list[tuple[str, str, int, str, str, int]] = [
    ("キャラデザ", "全身の立ち絵を縦長で", 0, "縦", "アニメ", 100),
    ("ラフを清書", "キャンバスの線を清書", 1, "縦", "アニメ", 100),
    ("ラフから自由に", "ラフを元に AI が整える", 1, "縦", "厚塗り", 60),
    ("イラスト", "場面の 1 枚を横長で", 0, "横", "厚塗り", 100),
    ("アイコン", "顔まわりを正方形で", 0, "正方形", "アニメ", 100),
    ("線画だけ", "塗らずに線で描く", 0, "縦", "線画", 100),
]
PROMPT_SUFFIX = {"キャラデザ": "full body, standing, simple background", "アイコン": "portrait, upper body, looking at viewer"}


class AiPanel(QWidget):
    changed = Signal()

    def __init__(self, w):
        super().__init__()
        self.w = w
        self.preset = ""
        self.style = "おまかせ"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(8)

        lay.addWidget(self._head("AI プリセット", "押すと描き方・大きさ・作風がそろいます"))
        self.preset_box = QGridLayout()
        self.preset_box.setSpacing(6)
        lay.addLayout(self.preset_box)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.fill_presets()

        lay.addWidget(self._head("作風", "絵の雰囲気。描く言葉に足します"))
        styles = QGridLayout()
        styles.setSpacing(4)
        self.style_group = QButtonGroup(self)
        self.style_buttons: dict[str, QPushButton] = {}
        for i, (name, _tags, tip) in enumerate(STYLES):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, n=name: self.set_style(n))
            self.style_group.addButton(b)
            self.style_buttons[name] = b
            styles.addWidget(b, i // 3, i % 3)
        lay.addLayout(styles)

        lay.addWidget(self._head("描き方", ""))
        self.mode_buttons = self._segment(["新規", "ラフから"], lambda i: w.mode.setCurrentIndex(i))
        lay.addLayout(self.mode_buttons[0])
        self.size_buttons = self._segment(list(SIZES), self._pick_size)
        lay.addLayout(self.size_buttons[0])
        w.mode.currentIndexChanged.connect(self.sync)
        w.size_pick.currentIndexChanged.connect(self.sync)

        row = QHBoxLayout()
        self.again = QPushButton("もう一度描く")
        self.again.setToolTip("前と同じ頼みを、別の種で描き直します")
        self.again.clicked.connect(w.draw_again)
        self.save_button = QPushButton("今の設定を保存")
        self.save_button.setToolTip("今の描き方・大きさ・作風を、自分の AI プリセットとして残します")
        self.save_button.clicked.connect(self.save_current)
        row.addWidget(self.again)
        row.addWidget(self.save_button)
        lay.addLayout(row)
        self.set_style("おまかせ")
        self.sync()

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

    def _pick_size(self, i: int):
        self.w.size_pick.setCurrentIndex(i)

    def _card(self, name: str, sub: str, own: bool = False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("aiPreset")
        b.setCheckable(True)
        b.setText(f"{name}\n{sub}")
        b.setToolTip(f"{name}: {sub}" + ("\n右クリックで消せます" if own else ""))
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setMinimumHeight(46)
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
            self.preset_box.addWidget(b, i // 2, i % 2)
            b.setChecked(name == self.preset)

    def apply(self, name: str, data: dict):
        """プリセットを当てる。描き方・大きさ・作風・強さをそろえ、頼みを書く欄に移る"""
        self.preset = name
        self.w.mode.setCurrentIndex(int(data.get("mode", 0)))
        self.w.size_pick.setCurrentIndex(list(SIZES).index(data.get("size", "縦")))
        self.w.strength.setValue(int(data.get("strength", 100)))
        self.set_style(data.get("style", "おまかせ"))
        for b in self.preset_group.buttons():
            b.setChecked(b.text().split("\n")[0] == name)
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
        name = name.strip()
        self.w.layout_store.setValue(f"ai_presets/{name}", json.dumps(self.current(), ensure_ascii=False))
        self.preset = name
        self.fill_presets()
        self.w.notify("AI プリセットを保存しました", "ok", f"「{name}」は AI の欄にいつでも出ます")

    def _own_menu(self, name: str, button):
        m = QMenu(self)
        m.addAction("消す", lambda: (self.w.layout_store.remove(f"ai_presets/{name}"), self.fill_presets()))
        m.exec(button.mapToGlobal(button.rect().bottomLeft()))

    # ---- 作風と同期 ----
    def set_style(self, name: str):
        self.style = name if name in STYLE_TAGS else "おまかせ"
        for n, b in self.style_buttons.items():
            b.setChecked(n == self.style)
        self.changed.emit()

    def style_tags(self) -> str:
        """描く言葉に足すタグ。作風と、プリセットの決まった言葉"""
        tags = [STYLE_TAGS.get(self.style, ""), PROMPT_SUFFIX.get(self.preset, "")]
        return ", ".join(t for t in tags if t)

    def sync(self, *_):
        for i, b in enumerate(self.mode_buttons[1]):
            b.setChecked(i == self.w.mode.currentIndex())
        for i, b in enumerate(self.size_buttons[1]):
            b.setChecked(i == self.w.size_pick.currentIndex())
            b.setEnabled(self.w.mode.currentIndex() == 0)   # ラフからはキャンバスの縦横に合わせる
