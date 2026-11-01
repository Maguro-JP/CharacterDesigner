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
    from chatdraw.models import is_local
    if is_local(m.repo):
        return True   # 手で置いた模型は、置いてあること自体が「手元にある」
    return Painter(m.repo).ready()


def has_words(m: WordsModel) -> bool:
    return words_path(m).exists()


def llm_lib_ready() -> bool:
    return (LLM / "lib" / "llama_cpp").exists()


def missing() -> dict:
    """足りない物。絵の模型（ラフの部品を含む）と、言葉の模型（部品と本体）"""
    if not engine_ready():
        return {"image": True, "words": not llm_lib_ready()}
    from chatdraw.models import all_images
    return {"image": not any(has_image(m) for m in all_images()),
            "words": not (llm_lib_ready() and any(has_words(m) for m in WORDS))}


def engine_ready() -> bool:
    """絵を描く部品（torch と diffusers）が読めるか"""
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "diffusers", "transformers"))


def run_pip(args: list[str], say=lambda msg, pct: None, msg: str = "", pct: int = 0):
    """pip を動かし、出力を HOME/setup.log に残す。落ちたら最後の数行を理由として返す。
    pythonw.exe から起動したアプリには標準の入出力が無く、そのまま子に渡すと pip が入出力を作れずに落ちることがあるので、
    入力は空、出力はファイルに向ける。黒い窓も出さない"""
    from chatdraw.paths import HOME
    HOME.mkdir(parents=True, exist_ok=True)
    log = HOME / "setup.log"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with open(log, "a", encoding="utf-8", errors="replace") as f:
        f.write("\n$ pip " + " ".join(args) + "\n")
        f.flush()
        r = subprocess.run([sys.executable, "-m", "pip", *args], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                           creationflags=flags)
    if r.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
        raise RuntimeError(f"部品を入れられませんでした（pip の終了コード {r.returncode}）。記録: {log}\n" + "\n".join(tail))


DIFFUSERS = "diffusers>=0.37.0"   # 新しい世代の部品（Flux2Klein、ZImage、QwenImage、Chroma、Lumina2）が全部そろう版


def install_engine(say=lambda msg, pct: None):
    """絵を描く部品を、データの置き場（HOME/gen/lib）に入れる。NVIDIA の GPU があれば GPU 版、無ければ CPU 版の torch を取る。
    インストーラーに入れないのは、torch の版が機械の GPU で変わり（CUDA 版 約 2.5GB、CPU 版 約 200MB）、合わない方を配ると無駄になるため"""
    from chatdraw.paths import HOME
    lib = HOME / "gen" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    gpu = shutil.which("nvidia-smi") is not None
    index = "https://download.pytorch.org/whl/cu124" if gpu else "https://download.pytorch.org/whl/cpu"
    say("絵を描く部品を入れています（数分かかります）", -1)
    pip = ["install", "-q", "--disable-pip-version-check", "--no-cache-dir", "--target", str(lib), "--upgrade"]
    run_pip(pip + ["torch", "--index-url", index])
    # 後の部品（transformers など）は torch を欲しがり、そのままだと、ふつうの配り元の GPU 版（約 4GB 多い）で上書きした
    # （CPU の機械で 5.7GB になった）。入れた torch の版に固定して、同じ物を使わせる
    import re
    ver = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", (lib / "torch" / "version.py").read_text()).group(1)
    say("絵を描く部品の続きを入れています（数分かかります）", -1)
    # ai-edge-litert と onnxruntime は、描いた絵を検品する模型を読む部品（chatdraw/handcheck.py、requestcheck.py）
    # scipy と scikit-image は、模型を使わない仕上げ（chatdraw/finishers.py の retouch・ink・質感）が使う部品
    # diffusers は FLUX.2 klein（Flux2KleinPipeline）が入った 0.37 以上。古いと新しい世代の模型を読めない
    run_pip(pip + [DIFFUSERS, "transformers", "accelerate", "huggingface_hub", "safetensors", "ai-edge-litert", "onnxruntime",
                   "scipy", "scikit-image", f"torch=={ver}",
                   "--extra-index-url", index])
    if gpu:   # 大きい模型（FLUX、Qwen-Image など）の本体を 4 ビットに縮めて GPU に載せる部品。入らなくても縮めずに描ける
        try:
            run_pip(pip + ["bitsandbytes", f"torch=={ver}", "--extra-index-url", index])
        except RuntimeError:
            pass
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


class NoRoom(Exception):
    """置き場の空きが足りない"""


def free_gb(d: Path) -> float:
    """d（無ければ、ある所まで親をたどる）のある置き場の空き（GB）"""
    p = Path(d)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return float("inf")


def repo_dir(hub: str) -> Path:
    """Hugging Face の置き場（HUB）の中の、その模型のフォルダー"""
    return HUB / ("models--" + hub.replace("/", "--"))


def check_room(name: str, need_gb: float, have_gb: float = 0.0, where: Path = HUB):
    """取る前に空きを見る。途中で一杯になると、数十 GB を取った後で落ち、置き場も一杯のまま残った"""
    left = max(0.0, need_gb - have_gb)
    free = free_gb(where)
    if left > 0 and free < left + 1.0:   # 1GB は描く時の一時ファイルの分
        raise NoRoom(f"{name} を取るには、置き場（{where}）に約 {left + 1:.1f}GB の空きが要ります（今の空き {free:.1f}GB）。"
                     "要らない模型を「模型の管理」で消すか、置き場を空いているドライブに移してください")


NO_WEIGHTS = ("Tokenizer", "Scheduler", "FeatureExtractor", "ImageProcessor", "Processor")


def parts(index: dict) -> list[str]:
    """model_index.json に書かれた、重みの要る部品の名前（tokenizer や scheduler は重みが無いので外す）"""
    out = []
    for k, v in index.items():
        if k.startswith("_") or not isinstance(v, (list, tuple)) or len(v) < 2 or v[1] is None:
            continue
        if any(w in str(v[1]) for w in NO_WEIGHTS):   # T5TokenizerFast のように後ろに付く名前もある
            continue
        out.append(k)
    return out


def missing_parts(folder: Path, index: dict) -> list[str]:
    """取った模型のフォルダーで、重みのファイルが 1 つも無い部品。取る型（allow_patterns）に当たらなかった部品がここに出る"""
    out = []
    for k in parts(index):
        d = folder / k
        if not d.is_dir() or not any(f.suffix in (".safetensors", ".bin", ".gguf", ".pt") for f in d.iterdir()):
            out.append(k)
    return out


def part_files(names: list[str], part: str, variant: str | None) -> list[str]:
    """部品の重みのうち取る物。fp16 を選んだ模型は fp16 を、無ければ safetensors を、それも無ければ .bin を取る（同じ重みを 2 度取らない）"""
    mine = [n for n in names if n.startswith(part + "/")]
    conf = [n for n in mine if n.endswith((".json", ".txt", ".model"))]
    st = [n for n in mine if n.endswith(".safetensors")]
    half = [n for n in st if ".fp16." in n]
    full = [n for n in st if ".fp16." not in n]
    weights = (half if variant == "fp16" and half else full or half) or [n for n in mine if n.endswith(".bin")]
    return conf + weights


def friendly(e: Exception, hub: str) -> str:
    """取れなかった理由。同意の要る模型（gated）と、無い模型は、何をすればよいかを書く"""
    name = type(e).__name__
    if isinstance(e, NoRoom):
        return str(e)
    if "Gated" in name or "401" in str(e) or "403" in str(e):
        return (f"{hub} は Hugging Face で利用の同意が要る模型です。https://huggingface.co/{hub} で同意し、"
                "Hugging Face のトークンを設定（環境変数 HF_TOKEN）してから取り直してください")
    if "RepositoryNotFound" in name or "404" in str(e):
        return f"{hub} が Hugging Face に見つかりません（名前の誤りか、消された模型）"
    if isinstance(e, (ConnectionError, TimeoutError, OSError)) and "space" in str(e).lower():
        return f"置き場の空きが足りなくなりました: {e}"
    from chatdraw.engine import explain
    return explain(e)


class Fetcher(QObject):
    """選んだ模型を、描くのに要る部品まで全部取る。update=True なら、手元にあっても新しい版があるかを見て、あれば取り直す。
    途中で止まっても、取った分は残り、次は続きから取る（Hugging Face の取り方が続きから取る）"""
    progress = Signal(str, int)
    finished = Signal(str)

    def run(self, image: ImageModel | None, words: WordsModel | None, update: bool = False):
        try:
            ensure_shared()
            if not engine_ready():
                install_engine(self.progress.emit)
            from chatdraw.ratings import is_blocked
            if image is not None and is_blocked(image.repo):   # ブロックした模型は、どの道からも取らない
                self.finished.emit(f"{image.name} はブロックしています。模型の管理の「…」から解除できます")
                return
            if image is not None:
                self._image(image)
            if words is not None:
                self._words(words, update)
            self.finished.emit("")
        except Exception as e:  # 取れなかった理由を、何をすればよいか分かる形で見せる
            hub = image.hub if image is not None else words.repo if words is not None else ""
            self.finished.emit(f"取れませんでした: {friendly(e, hub)}")

    def _image(self, m: ImageModel):
        from huggingface_hub import snapshot_download
        from chatdraw.models import SINGLE_BASE, single_base_files
        check_room(m.name, m.gb, folder_gb(repo_dir(m.hub)))
        start = folder_gb(HUB)
        done = threading.Event()

        def watch():
            while not done.wait(2):
                got = folder_gb(HUB) - start
                self.progress.emit(f"{m.name} を取っています（{got:.1f} / 約 {m.gb:.1f}GB）", min(99, int(got / max(m.gb, 0.1) * 100)))
        threading.Thread(target=watch, daemon=True).start()
        try:
            # 取ってある分は飛ばし、新しい版があればその差分だけを取る
            folder = Path(snapshot_download(m.hub, cache_dir=str(HUB), **m.files))
            if m.file:
                # 1 つのファイルの模型は、部品の設定（と新しい世代では言葉の部品・VAE）を元の模型から借りて読む。先に取っておく
                base = SINGLE_BASE.get(m.family)
                if base:
                    self.progress.emit(f"{m.name} を読むための部品（{base}）を取っています", -1)
                    snapshot_download(base, cache_dir=str(HUB), **single_base_files(m.family))
            else:
                self._parts(m, folder)
            if m.family in SKETCH:   # ラフから描く部品は SD 系だけにある
                repo, files, _ = SKETCH[m.family]
                snapshot_download(repo, cache_dir=str(HUB), **files)   # ラフから描く部品（約 0.15〜0.3GB）
        finally:
            done.set()

    def _parts(self, m: ImageModel, folder: Path):
        """model_index.json の部品が全部そろったかを見て、取る型に当たらずに抜けた部品を足して取る。
        抜けたまま描くと、読む時に「no file named ...」で落ちた（.bin だけの部品、text_encoder_3 など）"""
        import json
        from huggingface_hub import HfApi, snapshot_download
        try:
            index = json.loads((folder / "model_index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        lack = missing_parts(folder, index)
        if not lack:
            return
        names = HfApi().list_repo_files(m.hub)
        want = [f for p in lack for f in part_files(names, p, m.variant)]
        if want:
            self.progress.emit(f"{m.name} の足りない部品（{'、'.join(lack)}）を取っています", -1)
            snapshot_download(m.hub, cache_dir=str(HUB), allow_patterns=want)
        still = missing_parts(folder, index)
        if still:
            raise FileNotFoundError(f"{m.name} の部品 {'、'.join(still)} の重みが Hugging Face に見つかりません")

    def _words(self, m: WordsModel, update: bool):
        lib = LLM / "lib"
        if not llm_lib_ready():
            self.progress.emit("言葉の模型を動かす部品を入れています（数分かかります）", -1)
            # 元のソースから組むと数十分かかり、組み立ての道具も要るので、組み済みの配布物だけを使う
            run_pip(["install", "-q", "--disable-pip-version-check", "--target", str(lib), "--only-binary", "llama-cpp-python",
                     "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu", "llama-cpp-python>=0.3.16"])
        dest = have = words_path(m)
        with urllib.request.urlopen(urllib.request.Request(m.url, method="HEAD")) as r:
            remote = int(r.headers.get("Content-Length") or 0)
        if have.exists() and (not update or have.stat().st_size == remote):
            return   # 同じ大きさなら同じ版とみなして取り直さない
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        got = part.stat().st_size if part.exists() else 0
        if remote and got >= remote:
            got = 0   # 前の版の途中の物。始めから取る
        check_room(m.name, (remote - got) / 1e9 if remote else m.gb, 0.0, dest.parent)
        req = urllib.request.Request(m.url, headers={"Range": f"bytes={got}-"} if got else {})
        with urllib.request.urlopen(req) as r:
            resumed = got and r.status == 206   # 続きから取れた。206 でなければ配り元が続きを受けないので始めから
            got = got if resumed else 0
            total = remote or got + int(r.headers.get("Content-Length") or 0)
            with open(part, "ab" if resumed else "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress.emit(f"{m.name} を取っています（{got / 1e9:.1f} / {total / 1e9:.1f}GB）", got * 100 // total)
        part.replace(dest)   # 取り終わってから入れ替える。途中で止まっても前の版は使え、次は続きから取る


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
        if hasattr(parent, "watch_fetch"):   # 窓の右下の進みにも出す
            parent.watch_fetch(self.fetcher)

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
        self.only_rec.setToolTip("外すと、一覧のほかの模型も出します。まだ確かめていない模型には印を付けます")
        self.only_rec.toggled.connect(self._relayout)
        lay.addWidget(self.only_rec)
        self.sections: list[tuple[QGridLayout, list[tuple[QFrame, bool]]]] = []
        # 一度選んだことがあれば今の選択を、初めてならおすすめを選んでおく
        chose = self.settings is not None and int(self.settings.store.value("setup_done", 0))
        now_image = self.settings.get("image_model") if chose else None

        head = QLabel("絵の模型")
        head.setObjectName("sectionHead")
        lay.addWidget(head)
        self.image_group = QButtonGroup(self)
        # 札を選んだら、手元の模型を使う選択は外す（残ると、選んだ札の模型が取られず設定にも入らなかった）
        self.image_group.buttonClicked.connect(lambda _b: setattr(self, "local", None))
        # 手で置いた模型を使っているときは、それを今の選択として持つ（無いと「おまかせ」に戻して書き換えた）
        from chatdraw.models import is_local, local_model
        self.local = local_model(now_image) if now_image and is_local(now_image) else None
        self.image_radios: dict[str, QRadioButton] = {}
        # 札が多い（30 余り）ので、札の並びだけを流す。窓が画面より縦に長くならないように
        from PySide6.QtWidgets import QScrollArea
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        box = QScrollArea()
        box.setWidget(holder)
        box.setWidgetResizable(True)
        box.setFrameShape(QScrollArea.NoFrame)
        box.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        box.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lay.addWidget(box, 1)
        r = QRadioButton("おまかせ")
        r.setChecked(now_image == AUTO)
        self.image_group.addButton(r)
        self.image_radios[AUTO] = r
        cards = [(card(r, "頼みに合う物を AI が選ぶ", "", False, False), True)]
        # 初めは推奨（点の届いた物）だけを出す。「推奨だけ表示」を外すと、一覧のほかの模型も取れる（まだ確かめていない物は印を付ける）。
        # いちばん点の高い物を「おすすめ」にする
        checked = verified_images()
        best_repo = checked[0].repo if checked else None
        images = checked + sorted((m for m in IMAGES if m.score <= 0), key=lambda m: m.name.lower())
        for m in images:
            best = m.repo == best_repo
            r = QRadioButton(m.name)
            r.setChecked(m.repo == now_image if now_image else best)
            self.image_group.addButton(r)
            self.image_radios[m.repo] = r
            from chatdraw.models import family as fam
            from chatdraw.ratings import rating_text
            meta = f"{rating_text(m)}・{fam(m.family).name}・{m.gb:.0f}GB" + (f"・{m.commercial}" if m.commercial else "")
            cards.append((card(r, m.good, meta, has_image(m), best), m.score >= PASS))
        self.sections.append((grid, cards))

        # 言葉の模型は性能で決まるので選ばせない。確かめていちばん点の高い物を自動で使う
        self._relayout()
        if not any(r.isChecked() for r in self.image_group.buttons()):
            self.image_radios[AUTO].setChecked(True)

        # 回線を使わずに、手元の模型を使う道。置き方は手順書の 3 章
        hand = QHBoxLayout()
        note = QLabel("手元に模型（.safetensors か diffusers のフォルダー）があるときは、取らずにそれを使えます。")
        note.setObjectName("cardMeta")
        note.setWordWrap(True)
        use_local = QPushButton("手元の模型を使う…")
        use_local.clicked.connect(self.use_local)
        guide = QPushButton("置き方を見る")
        guide.clicked.connect(lambda: __import__("chatdraw.helpview", fromlist=["HelpDialog"]).HelpDialog("install", self).show())
        hand.addWidget(note, 1)
        hand.addWidget(use_local)
        hand.addWidget(guide)
        lay.addLayout(hand)
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

    def use_local(self, path: str | None = None):
        """手元の絵の模型を選んで使う。ファイルは動かさない。ラフの部品と言葉の模型は、取れるときだけ取る"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from chatdraw.models import is_local, local_model
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "絵の模型を選ぶ", "", "絵の模型 (*.safetensors);;model_index.json (model_index.json)")
            if not path:
                return
            if Path(path).name == "model_index.json":
                path = str(Path(path).parent)   # diffusers のフォルダーは、中の model_index.json を選んでもらう
        path = str(Path(path).resolve())
        if not is_local(path):
            QMessageBox.information(self, "使えない形です", ".safetensors のファイルか、model_index.json のあるフォルダーを選んでください。")
            return
        m = local_model(path)
        if m.family == "unknown":
            QMessageBox.information(self, "見分けられない形です", "SDXL・SD1.5・FLUX.1 の .safetensors か、"
                                    "model_index.json のある diffusers のフォルダーを選んでください。")
            return
        self.local = m
        self.start(update=False)   # 絵の模型は取らず、描く部品と言葉の模型だけを用意する

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

    def chosen(self) -> tuple[ImageModel | str, WordsModel | None]:
        """選んだ絵の模型（おまかせは AUTO）と、使う言葉の模型（いちばん点の高い推奨。無ければ None）"""
        image = AUTO if self.image_radios[AUTO].isChecked() else next(m for m in IMAGES if m.repo in self.image_radios
                                                                        and self.image_radios[m.repo].isChecked())
        best = offered_words()
        if getattr(self, "local", None) is not None:
            image = self.local
        return image, best[0] if best else None

    def to_fetch(self) -> tuple[ImageModel | None, WordsModel | None]:
        """取る物。おまかせで手元に 1 つも無ければ、おすすめを取る"""
        image, words = self.chosen()
        if getattr(self, "local", None) is not None:
            image = None   # 手で置いた模型は取らない
        elif image == AUTO:
            image = None if any(has_image(m) for m in IMAGES) else (offered_images() or list(IMAGES))[0]
        if words is not None and has_words(words):
            words = None
        return image, words

    def select(self, image: str | None = None):
        """メニューから選んだ絵の模型を選んでおく"""
        if image is not None and image in self.image_radios:   # 一覧に無い模型（手で置いた物など）は選ばずに置く
            self.image_radios[image].setChecked(True)

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
        self.back.clicked.connect(lambda: (setattr(self, "local", None), self.pages.setCurrentIndex(0)))
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
        """pct が負なら、どこまで進んだか分からない作業（部品を入れる）。棒を往復させて、止まって見えないようにする。
        Qt の動く帯（範囲 0〜0）は、テーマの色を当てると止まって見えた（進みの欄と同じ直し）"""
        from PySide6.QtCore import QTimer
        self.label.setText(msg)
        if not hasattr(self, "_pulse"):
            self._pulse, self._pulse_at = QTimer(self), 0
            self._pulse.setInterval(60)

            def tick():
                self._pulse_at = (self._pulse_at + 3) % 200
                self.bar.setValue(self._pulse_at if self._pulse_at <= 100 else 200 - self._pulse_at)
            self._pulse.timeout.connect(tick)
        self.bar.setRange(0, 100)
        if pct < 0:
            self._pulse.start()
        else:
            self._pulse.stop()
            self.bar.setValue(pct)

    def _finished(self, err: str):
        if hasattr(self, "_pulse"):
            self._pulse.stop()
        self.bar.setRange(0, 100)
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
        self.settings.set("words_model", str(words_path(words)) if words else "")
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
