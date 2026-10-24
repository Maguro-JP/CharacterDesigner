"""模型の管理。初めての起動で候補を見せて選んでもらい、選んだ物を自動で取る。あとから入れ替えと更新もここで行う。

絵の模型が無いと絵は描けない。言葉の模型が無いときは、頼みをそのまま絵の模型に渡す（英語の頼みなら困らない）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QRadioButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from chatdraw.engine import SKETCH, Painter
from chatdraw.models import (IMAGES, PASS, WORDS, ImageModel, WordsModel, offered_images, offered_words, verified_images,
                             verified_words)
from chatdraw.paths import HUB, OWN_LLM, ensure_shared, find_gguf, llm_target

LLM = OWN_LLM
AUTO = "auto"   # おまかせ。頼みごとに、手元の模型から合う物を AI が選ぶ


def words_path(m: WordsModel) -> Path:
    """手元にある置き場（AdaptiveAIStudio と共有の置き場を先に見る）。無ければ、これから取る置き場"""
    return find_gguf(m.file) or llm_target() / m.file


def has_image(m: ImageModel) -> bool:
    return Painter(m.repo).ready()


def has_words(m: WordsModel) -> bool:
    return words_path(m).exists()


def llm_lib_ready() -> bool:
    return (LLM / "lib" / "llama_cpp").exists()


def missing() -> dict:
    """足りない物。絵の模型（ラフの部品を含む）と、言葉の模型（部品と本体）"""
    if not engine_ready():
        return {"image": True, "words": not llm_lib_ready()}
    return {"image": not (any(has_image(m) for m in IMAGES) and Painter().sketch_ready()),
            "words": not (llm_lib_ready() and any(has_words(m) for m in WORDS))}


def engine_ready() -> bool:
    """絵を描く部品（torch と diffusers）が読めるか"""
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "diffusers", "transformers"))


def install_engine(say=lambda msg, pct: None):
    """絵を描く部品を、データの置き場（HOME/gen/lib）に入れる。NVIDIA の GPU があれば GPU 版、無ければ CPU 版の torch を取る。
    インストーラーに入れないのは、torch の版が機械の GPU で変わり（CUDA 版 約 2.5GB、CPU 版 約 200MB）、合わない方を配ると無駄になるため"""
    from chatdraw.paths import HOME
    lib = HOME / "gen" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    gpu = shutil.which("nvidia-smi") is not None
    index = "https://download.pytorch.org/whl/cu124" if gpu else "https://download.pytorch.org/whl/cpu"
    say("絵を描く部品を入れています", 0)
    pip = [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--no-cache-dir", "--target", str(lib), "--upgrade"]
    subprocess.run(pip + ["torch", "--index-url", index], check=True)
    # 後の部品（transformers など）は torch を欲しがり、そのままだと、ふつうの配り元の GPU 版（約 4GB 多い）で上書きした
    # （CPU の機械で 5.7GB になった）。入れた torch の版に固定して、同じ物を使わせる
    import re
    ver = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", (lib / "torch" / "version.py").read_text()).group(1)
    say("絵を描く部品を入れています", 50)
    subprocess.run(pip + ["diffusers", "transformers", "accelerate", "huggingface_hub", "safetensors", f"torch=={ver}",
                          "--extra-index-url", index], check=True)
    say("絵を描く部品を入れています", 90)
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    import importlib
    importlib.invalidate_caches()


def folder_gb(d: Path) -> float:
    # Hugging Face の置き場は、同じ中身を blobs と snapshots（別名）の 2 か所から指す。別名をそのまま数えると 2 倍になった
    if not d.exists():
        return 0.0
    seen = {f.resolve() for f in d.rglob("*") if f.is_file()}
    return sum(f.stat().st_size for f in seen) / 1e9


class Fetcher(QObject):
    """選んだ模型を取る。update=True なら、手元にあっても新しい版があるかを見て、あれば取り直す"""
    progress = Signal(str, int)
    finished = Signal(str)

    def run(self, image: ImageModel | None, words: WordsModel | None, update: bool = False):
        try:
            ensure_shared()
            if not engine_ready():
                install_engine(self.progress.emit)
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
            repo, files, _ = SKETCH[m.family]
            snapshot_download(repo, cache_dir=str(HUB), **files)   # ラフから描く部品（約 0.15〜0.3GB）
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
    for text, name in (("おすすめ", "badgeHot") if recommended else (None, None), ("✓", "badge") if have else (None, None)):
        if text:
            b = QLabel(text)
            b.setObjectName(name)
            top.addWidget(b)
    lay.addLayout(top)
    for text, name in ((good, "cardGood"), (meta, "cardMeta")):
        if not text:
            continue
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
        hint = QLabel("あとから「AI」メニューで切り替えられます。")
        hint.setObjectName("cardMeta")
        lay.addWidget(hint)
        self.only_rec = QCheckBox("推奨だけ表示")
        self.only_rec.setChecked(True)
        self.only_rec.setToolTip("外すと、動作を確かめたほかの模型も出します")
        self.only_rec.toggled.connect(self._relayout)
        lay.addWidget(self.only_rec)
        self.sections: list[tuple[QGridLayout, list[tuple[QFrame, bool]]]] = []
        # 一度選んだことがあれば今の選択を、初めてならおすすめを選んでおく
        chose = self.settings is not None and int(self.settings.store.value("setup_done", 0))
        now_image = self.settings.get("image_model") if chose else None
        now_words = self.settings.get("words_model") if chose else None

        head = QLabel("絵の模型")
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
        cards = [(card(r, "頼みに合う物を AI が選ぶ", "", False, False), True)]
        # 出すのは動作を確かめた模型だけ（取っていなくても出す）。点の届いた物が推奨で、いちばん高い物を「おすすめ」にする
        images = verified_images()
        for m in images:
            best = m is images[0]
            r = QRadioButton(m.name)
            r.setChecked(m.repo == now_image if now_image else best)
            self.image_group.addButton(r)
            self.image_radios[m.repo] = r
            cards.append((card(r, m.good, f"{m.gb:.0f}GB", has_image(m), best), m.score >= PASS))
        self.sections.append((grid, cards))

        head = QLabel("言葉の模型")
        head.setToolTip("日本語の頼みを、絵の模型が分かる言葉に直す")
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
        cards = [(card(r, "頼みに合う物を AI が選ぶ", "", False, False), True)]
        words = verified_words()
        for m in words:
            best = m is words[0]
            r = QRadioButton(m.name)
            r.setChecked(Path(now_words).name == m.file if now_words and now_words != AUTO else now_words is None and best)
            self.words_group.addButton(r)
            self.words_radios[m.file] = r
            cards.append((card(r, m.good, f"{m.gb}GB", has_words(m), best), m.score >= PASS))
        self.no_words = QRadioButton("使わない")
        self.words_group.addButton(self.no_words)
        cards.append((card(self.no_words, "英語で頼むなら要らない", "", False, False), True))
        self.sections.append((grid, cards))
        self._relayout()
        self.no_words.setChecked(now_words == "")
        if not any(r.isChecked() for r in self.words_group.buttons()):
            (self.words_radios[words[0].file] if words else self.no_words).setChecked(True)
        if not any(r.isChecked() for r in self.image_group.buttons()):
            self.image_radios[AUTO].setChecked(True)

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

    def _relayout(self):
        """「推奨だけ表示」に合わせて札を並べ直す。隠した札の所に穴を空けない。選んでいる札は隠さない"""
        only = self.only_rec.isChecked()
        for grid, cards in self.sections:
            for box, _ in cards:
                grid.removeWidget(box)
            shown = [box for box, rec in cards if rec or not only or box.findChild(QRadioButton).isChecked()]
            for box, _ in cards:
                box.setVisible(box in shown)
            for i, box in enumerate(shown):
                grid.addWidget(box, i // 2, i % 2)

    def chosen(self) -> tuple[ImageModel | str, WordsModel | str | None]:
        """選んだ物。おまかせは AUTO、言葉の模型を使わないときは None"""
        image = AUTO if self.image_radios[AUTO].isChecked() else next(m for m in IMAGES if m.repo in self.image_radios
                                                                        and self.image_radios[m.repo].isChecked())
        if self.words_radios[AUTO].isChecked():
            return image, AUTO
        return image, next((m for m in WORDS if m.file in self.words_radios and self.words_radios[m.file].isChecked()), None)

    def to_fetch(self) -> tuple[ImageModel | None, WordsModel | None]:
        """取る物。おまかせで手元に 1 つも無ければ、おすすめを取る"""
        image, words = self.chosen()
        if image == AUTO:
            image = None if any(has_image(m) for m in IMAGES) else offered_images()[0]
        if words == AUTO:
            words = None if any(has_words(m) for m in WORDS) else offered_words()[0]
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
