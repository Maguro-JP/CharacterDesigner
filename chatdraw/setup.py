"""模型の管理。初めての起動で候補を見せて選んでもらい、選んだ物を自動で取る。あとから入れ替えと更新もここで行う。

絵の模型が無いと絵は描けない。言葉の模型が無いときは、頼みをそのまま絵の模型に渡す（英語の頼みなら困らない）。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QRadioButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from chatdraw.engine import SKETCH_ADAPTER, SKETCH_FILES, Painter
from chatdraw.models import IMAGES, WORDS, ImageModel, WordsModel
from chatdraw.paths import HUB, OWN_LLM, ensure_shared, find_gguf, llm_target

LLM = OWN_LLM
AUTO = "auto"   # おまかせ。頼みごとに、手元の模型から合う物を AI が選ぶ
OLD_WORDS = OWN_LLM / "model.gguf"   # 一覧を作る前に取った言葉の模型（Qwen2.5 1.5B と同じ物）


def words_path(m: WordsModel) -> Path:
    """手元にある置き場（AdaptiveAIStudio と共有の置き場を先に見る）。無ければ、これから取る置き場"""
    found = find_gguf(m.file)
    if found is None and m.file == WORDS[0].file and OLD_WORDS.exists():
        return OLD_WORDS
    return found or llm_target() / m.file


def has_image(m: ImageModel) -> bool:
    return Painter(m.repo).ready()


def has_words(m: WordsModel) -> bool:
    return words_path(m).exists()


def llm_lib_ready() -> bool:
    return (LLM / "lib" / "llama_cpp").exists()


def missing() -> dict:
    """足りない物。絵の模型（ラフの部品を含む）と、言葉の模型（部品と本体）"""
    return {"image": not (any(has_image(m) for m in IMAGES) and Painter().sketch_ready()),
            "words": not (llm_lib_ready() and any(has_words(m) for m in WORDS))}


def folder_gb(d: Path) -> float:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e9 if d.exists() else 0.0


class Fetcher(QObject):
    """選んだ模型を取る。update=True なら、手元にあっても新しい版があるかを見て、あれば取り直す"""
    progress = Signal(str, int)
    finished = Signal(str)

    def run(self, image: ImageModel | None, words: WordsModel | None, update: bool = False):
        try:
            ensure_shared()
            if image is not None:
                self._image(image)
            if words is not None:
                self._words(words, update)
            self.finished.emit("")
        except Exception as e:  # 取れなかった理由をそのまま見せる
            self.finished.emit(f"取れませんでした: {e}")

    def _image(self, m: ImageModel):
        from huggingface_hub import snapshot_download
        start = folder_gb(HUB)
        done = threading.Event()

        def watch():
            while not done.wait(2):
                got = folder_gb(HUB) - start
                self.progress.emit(f"{m.name} を取っています（{got:.1f} / 約 {m.gb:.1f}GB）", min(99, int(got / max(m.gb, 0.1) * 100)))
        threading.Thread(target=watch, daemon=True).start()
        try:
            # 取ってある分は飛ばし、新しい版があればその差分だけを取る
            snapshot_download(m.repo, cache_dir=str(HUB), **m.files)
            snapshot_download(SKETCH_ADAPTER, cache_dir=str(HUB), **SKETCH_FILES)   # ラフから描く部品（約 0.15GB）
        finally:
            done.set()

    def _words(self, m: WordsModel, update: bool):
        lib = LLM / "lib"
        if not llm_lib_ready():
            self.progress.emit("言葉の模型を動かす部品を入れています", 0)
            # 元のソースから組むと数十分かかり、組み立ての道具も要るので、組み済みの配布物だけを使う
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(lib), "--only-binary", "llama-cpp-python",
                            "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu", "llama-cpp-python>=0.3.16"],
                           check=True)
        dest = have = words_path(m)
        with urllib.request.urlopen(urllib.request.Request(m.url, method="HEAD")) as r:
            remote = int(r.headers.get("Content-Length") or 0)
        if have.exists() and (not update or have.stat().st_size == remote):
            return   # 同じ大きさなら同じ版とみなして取り直さない
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        with urllib.request.urlopen(m.url) as r, open(part, "wb") as f:
            total, got = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    self.progress.emit(f"{m.name} を取っています（{got / 1e9:.1f} / {total / 1e9:.1f}GB）", got * 100 // total)
        part.replace(dest)   # 取り終わってから入れ替える。途中で止まっても前の版は使える


def card(radio: QRadioButton, good: str, meta: str, have: bool, recommended: bool) -> QFrame:
    """候補 1 つ分の札。名前・得意なこと・大きさと速さ・手元にあるか"""
    box = QFrame()
    box.setObjectName("card")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(2)
    top = QHBoxLayout()
    top.addWidget(radio)
    top.addStretch()
    for text, name in (("おすすめ", "badgeHot") if recommended else (None, None), ("取得済み", "badge") if have else (None, None)):
        if text:
            b = QLabel(text)
            b.setObjectName(name)
            top.addWidget(b)
    lay.addLayout(top)
    for text, name in ((good, "cardGood"), (meta, "cardMeta")):
        lb = QLabel(text)
        lb.setObjectName(name)
        lb.setWordWrap(True)
        lay.addWidget(lb)
    box.mousePressEvent = lambda _e: radio.setChecked(True)
    return box


class SetupDialog(QDialog):
    """模型の管理。1 枚目で選び、2 枚目で取り、3 枚目で使い方を案内する。first=False のときは入れ替えと更新に使う"""

    def __init__(self, settings=None, parent=None, first: bool = True):
        super().__init__(parent)
        self.settings = settings
        self.first = first
        self.setWindowTitle("はじめに" if first else "模型の管理")
        self.setMinimumWidth(760)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._choose_page())
        self.pages.addWidget(self._fetch_page())
        self.pages.addWidget(self._guide_page())
        lay = QVBoxLayout(self)
        lay.addWidget(self.pages)
        self.fetcher = Fetcher()
        self.fetcher.progress.connect(self._progress, Qt.QueuedConnection)
        self.fetcher.finished.connect(self._finished, Qt.QueuedConnection)

    # ---- 1 枚目: 選ぶ ----
    def _choose_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        title = QLabel("使う AI を選んでください" if self.first else "模型の入れ替えと更新")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)
        hint = QLabel("選んだ物を自動で取ります。あとから「AI」メニューでいつでも切り替えられます。")
        hint.setObjectName("cardMeta")
        lay.addWidget(hint)
        # 一度選んだことがあれば今の選択を、初めてならおすすめを選んでおく
        chose = self.settings is not None and int(self.settings.store.value("setup_done", 0))
        now_image = self.settings.get("image_model") if chose else None
        now_words = self.settings.get("words_model") if chose else None

        head = QLabel("絵の模型（絵を描く）")
        head.setObjectName("sectionHead")
        lay.addWidget(head)
        self.image_group = QButtonGroup(self)
        self.image_radios: dict[str, QRadioButton] = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        lay.addLayout(grid)
        r = QRadioButton("おまかせ")
        r.setChecked(now_image == AUTO)
        self.image_group.addButton(r)
        self.image_radios[AUTO] = r
        grid.addWidget(card(r, "頼みごとに、取ってある模型から合う物を AI が選ぶ", "取っていなければ、おすすめを取る", False, False), 0, 0)
        for i, m in enumerate(IMAGES, 1):
            r = QRadioButton(m.name)
            r.setChecked(m.repo == now_image if now_image else m.recommended)
            self.image_group.addButton(r)
            self.image_radios[m.repo] = r
            grid.addWidget(card(r, m.good, f"約 {m.gb:.0f}GB　{m.speed}", has_image(m), m.recommended), i // 2, i % 2)

        head = QLabel("言葉の模型（日本語の頼みを、絵の模型が分かる言葉に直す）")
        head.setObjectName("sectionHead")
        lay.addWidget(head)
        self.words_group = QButtonGroup(self)
        self.words_radios: dict[str, QRadioButton] = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        lay.addLayout(grid)
        r = QRadioButton("おまかせ")
        r.setChecked(now_words == AUTO)
        self.words_group.addButton(r)
        self.words_radios[AUTO] = r
        grid.addWidget(card(r, "長い頼みは大きい模型、短い頼みは速い模型を AI が選ぶ", "取っていなければ、おすすめを取る", False, False), 0, 0)
        for i, m in enumerate(WORDS, 1):
            r = QRadioButton(m.name)
            names = (m.file, OLD_WORDS.name) if m is WORDS[0] else (m.file,)
            r.setChecked(Path(now_words).name in names if now_words and now_words != AUTO else now_words is None and m.recommended)
            self.words_group.addButton(r)
            self.words_radios[m.file] = r
            grid.addWidget(card(r, m.good, f"約 {m.gb}GB", has_words(m), m.recommended), i // 2, i % 2)
        self.no_words = QRadioButton("使わない")
        self.words_group.addButton(self.no_words)
        grid.addWidget(card(self.no_words, "頼みをそのまま絵の模型に渡す。英語で頼むなら十分", "0GB", False, False), 2, 0)
        self.no_words.setChecked(now_words == "")
        if not any(r.isChecked() for r in self.words_group.buttons()):
            self.words_radios[WORDS[0].file].setChecked(True)

        row = QHBoxLayout()
        self.later = QPushButton("あとで")
        self.later.clicked.connect(self.reject)
        self.update_button = QPushButton("更新を確かめる")
        self.update_button.setToolTip("選んだ模型に新しい版があれば取り直す")
        self.update_button.clicked.connect(lambda: self.start(update=True))
        self.go = QPushButton("取って使う")
        self.go.setObjectName("primary")
        self.go.clicked.connect(lambda: self.start(update=False))
        row.addWidget(self.later)
        row.addStretch()
        if not self.first:
            row.addWidget(self.update_button)
        row.addWidget(self.go)
        lay.addLayout(row)
        return page

    def chosen(self) -> tuple[ImageModel | str, WordsModel | str | None]:
        """選んだ物。おまかせは AUTO、言葉の模型を使わないときは None"""
        image = AUTO if self.image_radios[AUTO].isChecked() else next(m for m in IMAGES if self.image_radios[m.repo].isChecked())
        if self.words_radios[AUTO].isChecked():
            return image, AUTO
        return image, next((m for m in WORDS if self.words_radios[m.file].isChecked()), None)

    def to_fetch(self) -> tuple[ImageModel | None, WordsModel | None]:
        """取る物。おまかせで手元に 1 つも無ければ、おすすめを取る"""
        image, words = self.chosen()
        if image == AUTO:
            image = None if any(has_image(m) for m in IMAGES) else next(m for m in IMAGES if m.recommended)
        if words == AUTO:
            words = None if any(has_words(m) for m in WORDS) else next(m for m in WORDS if m.recommended)
        return image, words

    def select(self, image: str | None = None, words: str | None = None):
        """メニューから選んだ物を選んでおく（words は WordsModel.file か AUTO、"" で使わない）"""
        if image is not None:
            self.image_radios[image].setChecked(True)
        if words == "":
            self.no_words.setChecked(True)
        elif words is not None:
            self.words_radios[words].setChecked(True)

    # ---- 2 枚目: 取る ----
    def _fetch_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.fetch_title = QLabel("準備しています")
        self.fetch_title.setObjectName("dialogTitle")
        self.label = QLabel("")
        self.label.setObjectName("cardMeta")
        self.label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.back = QPushButton("戻る")
        self.back.setVisible(False)
        self.back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        for w in (self.fetch_title, self.bar, self.label):
            lay.addWidget(w)
        lay.addStretch()
        lay.addWidget(self.back, 0, Qt.AlignRight)
        return page

    def start(self, update: bool):
        image, words = self.to_fetch()
        self.pages.setCurrentIndex(1)
        self.fetch_title.setText("更新を確かめています" if update else "準備しています")
        self.label.setText("初めての取得は回線によって数十分かかります。閉じずにお待ちください。")
        self.back.setVisible(False)
        threading.Thread(target=self.fetcher.run, args=(image, words, update), daemon=True).start()

    def _progress(self, msg: str, pct: int):
        self.label.setText(msg)
        self.bar.setValue(pct)

    def _finished(self, err: str):
        if err:
            self.fetch_title.setText("取れませんでした")
            self.label.setText(err)
            self.back.setVisible(True)
            return
        self.apply()
        self.bar.setValue(100)
        if self.first:
            self.pages.setCurrentIndex(2)
        else:
            self.accept()

    def apply(self):
        """選んだ模型を設定に書く。工程の数と頼みの効きは、その模型に合う値にする"""
        if self.settings is None:
            return
        image, words = self.chosen()
        if image == AUTO:
            self.settings.set("image_model", AUTO)
        else:
            self.settings.set("image_model", image.repo)
            self.settings.set("steps", image.steps)
            self.settings.set("guidance", image.guidance)
        self.settings.set("words_model", AUTO if words == AUTO else str(words_path(words)) if words else "")
        self.settings.set("setup_done", 1)

    # ---- 3 枚目: 案内 ----
    def _guide_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        title = QLabel("準備ができました")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)
        for n, (head, body) in enumerate((("頼んで描く", "右の AI の欄に描きたい絵を書き、「描く」を押します。"),
                                          ("ラフから描く", "左の道具で線を描き、「ラフから」を選んで「描く」を押すと、線の形に沿って描きます。"),
                                          ("描いている様子", "描いている途中の絵がキャンバスに出ます。工程と残り時間は右の履歴の欄に出ます。")), 1):
            box = QFrame()
            box.setObjectName("card")
            row = QHBoxLayout(box)
            num = QLabel(str(n))
            num.setObjectName("stepNum")
            num.setFixedSize(28, 28)
            num.setAlignment(Qt.AlignCenter)
            row.addWidget(num)
            text = QLabel(f"<b>{head}</b><br>{body}")
            text.setWordWrap(True)
            row.addWidget(text, 1)
            lay.addWidget(box)
        lay.addStretch()
        ok = QPushButton("はじめる")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignRight)
        return page
