"""模型の管理。目録の絵の模型を全部並べ、絞り込みと並べ替え、取得・使う・削除・更新と、Hugging Face の名前で足す入口を持つ。

見せるのは、名前・大きさ・世代・確かめたか・商用の可否・得意なこと（1 行）だけにする（内部の点数や置き場の道は見せない）。
まだ確かめていない模型も取って使えるが、「未確認」と書いて分ける。
消すのは、利用者がこの画面で選んで確かめたときだけ。使っている模型は消せない。
"""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from chatdraw.models import FILTERS, FITS, SORTS, WORDS, ImageModel, catalog_images, family, fits, heavy, machine, pick, verified_words
from chatdraw.paths import GGUF, HUB, OWN_LLM
from chatdraw.setup import AUTO, Fetcher, folder_gb


@dataclass
class Item:
    kind: str        # "image" か "words"
    name: str
    path: Path
    gb: float
    key: str         # 設定に書く値（絵は repo、言葉は道）


def installed() -> list[Item]:
    """手元にある模型。絵を描く模型（model_index.json がある物）と .gguf。部品（ラフ用など）は出さない"""
    items: list[Item] = []
    catalog = catalog_images()
    names = {m.repo: m.name for m in catalog}
    if HUB.is_dir():
        for d in sorted(HUB.glob("models--*")):
            repo = d.name[len("models--"):].replace("--", "/")
            if any(s.joinpath("model_index.json").exists() for s in d.glob("snapshots/*")):
                items.append(Item("image", names.get(repo, repo.split("/")[-1]), d, folder_gb(d), repo))
            for m in (m for m in catalog if m.file and m.hub == repo):   # 1 つのファイルで置かれた模型
                if any(s.joinpath(m.file).exists() for s in d.glob("snapshots/*")):
                    items.append(Item("image", m.name, d, folder_gb(d), m.repo))
    from chatdraw.models import manual_images
    for m in manual_images():
        items.append(Item("manual", m.name, Path(m.repo), m.gb, m.repo))   # 手で置いた物は、置いた人が消す（ここでは消さない）
    files = {m.file: m.name for m in WORDS}
    seen = set()
    for d in (GGUF, OWN_LLM):
        for f in sorted(d.glob("*.gguf")) if d.is_dir() else []:
            if f.is_symlink() or f.name in seen:
                continue
            seen.add(f.name)
            items.append(Item("words", files.get(f.name, f.stem), f, f.stat().st_size / 1e9, str(f)))
    return items


def delete(item: Item):
    """模型を消す。共有の置き場（と前の版の置き場）の中の物だけを消す"""
    root = HUB if item.kind == "image" else item.path.parent
    if root not in (HUB, GGUF, OWN_LLM) or not item.path.resolve().is_relative_to(root.resolve()):
        raise ValueError("置き場の外の物は消しません")
    if item.path.is_dir():
        shutil.rmtree(item.path)
    else:
        item.path.unlink()


class ModelManager(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("模型の管理")
        self.setMinimumWidth(520)
        self.body = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(list(FILTERS))
        self.filter.setToolTip("出す模型を絞ります。未確認の模型も取って使えます")
        self.sort = QComboBox()
        self.sort.addItems(list(SORTS))
        self.sort.setToolTip("並べ方")
        self.filter.currentTextChanged.connect(self.refresh)
        self.sort.currentTextChanged.connect(self.refresh)
        tools.addWidget(self.filter)
        tools.addWidget(self.sort)
        tools.addStretch()
        self.body.addLayout(tools)
        # 模型が多いので、並びだけを窓の中で流す（窓が画面より縦に長くならないように）
        from PySide6.QtWidgets import QScrollArea, QWidget as _W
        holder = _W()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        box = QScrollArea()
        box.setWidget(holder)
        box.setWidgetResizable(True)
        box.setFrameShape(QScrollArea.NoFrame)
        self.body.addWidget(box, 1)
        self.resize(560, 600)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("cardMeta")
        self.body.addWidget(self.bar)
        self.body.addWidget(self.status)
        add = QHBoxLayout()
        self.hf_name = QLineEdit()
        self.hf_name.setPlaceholderText("持ち主/名前")
        self.hf_name.setToolTip("Hugging Face の模型の名前（例: cagliostrolab/animagine-xl-4.0）。取れるか、読める形かを確かめてから一覧に足します")
        self.hf_name.returnPressed.connect(self.add_by_name)
        self.add_button = QPushButton("Hugging Face の名前で足す")
        self.add_button.setToolTip("diffusers の形か、.safetensors が 1 つの模型を足せます。足した物は「未確認」として一覧に出ます")
        self.add_button.clicked.connect(self.add_by_name)
        add.addWidget(self.hf_name, 1)
        add.addWidget(self.add_button)
        self.body.addLayout(add)
        hand = QHBoxLayout()
        open_dir = QPushButton("手で置く模型の置き場を開く")
        open_dir.setToolTip("ここに .safetensors か、model_index.json のあるフォルダーを置くと、一覧に出ます")
        open_dir.clicked.connect(self.open_manual_dir)
        pick = QPushButton("ファイルを選んで使う…")
        pick.setToolTip("手元の絵の模型（.safetensors）を選んで、そのまま使います。ファイルは動かしません")
        pick.clicked.connect(self.pick_file)
        hand.addWidget(open_dir)
        hand.addWidget(pick)
        hand.addStretch()
        self.body.addLayout(hand)
        row = QHBoxLayout()
        self.update_button = QPushButton("更新を確かめる")
        self.update_button.clicked.connect(self.update_all)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        row.addWidget(self.update_button)
        row.addStretch()
        row.addWidget(close)
        self.body.addLayout(row)
        self.fetcher = Fetcher()
        self.fetcher.progress.connect(lambda msg, pct: (self.status.setText(msg), self.bar.setValue(pct)), Qt.QueuedConnection)
        self.fetcher.finished.connect(self._fetched, Qt.QueuedConnection)
        self.prober = Prober()
        self.prober.done.connect(self._probed, Qt.QueuedConnection)
        self.refresh()

    def in_use(self, item: Item) -> bool:
        key = self.settings.get("image_model" if item.kind == "image" else "words_model")
        if key == AUTO:
            return False
        return key == item.key if item.kind == "image" else Path(key).name == item.path.name

    def refresh(self):
        """絵の模型は目録の全部を絞り込みと並べ替えで出す。言葉の模型は手元の物と確かめ済みの物を出す"""
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        have = installed()
        mine = {it.key: it for it in have if it.kind == "image"}
        head = QLabel("絵の模型")
        head.setObjectName("dialogTitle")
        self.list.addWidget(head)
        shown = pick(catalog_images(), self.filter.currentText(), self.sort.currentText())
        for m in shown:
            self.list.addWidget(self._image_row(m, mine.get(m.repo)))
        known = {m.repo for m in catalog_images()}
        if self.filter.currentText() == "すべて":
            for it in (it for it in mine.values() if it.key not in known):   # 目録に無い、前に取った物
                self.list.addWidget(self._row(it.name, f"{it.gb:.1f}GB", *self._image_actions(it.key, it)))
            for it in [x for x in have if x.kind == "manual"]:
                use = (lambda _=False, it=it: self.pick_file(it.key))
                self.list.addWidget(self._row(it.name, f"{it.gb:.1f}GB・手で置いた模型", "使用中" if self.settings.get("image_model") == it.key
                                              else "使う", None if self.settings.get("image_model") == it.key else use))
        if not shown:
            self.list.addWidget(QLabel("ありません"))
        head = QLabel("言葉の模型")
        head.setObjectName("dialogTitle")
        self.list.addWidget(head)
        words = [it for it in have if it.kind == "words"]
        for it in words:
            self.list.addWidget(self._row(it.name, f"{it.gb:.1f}GB", "使用中" if self.in_use(it) else "削除",
                                          None if self.in_use(it) else (lambda _=False, it=it: self.ask_delete(it))))
        names = {it.name for it in words}
        for m in verified_words():
            if m.name not in names:
                self.list.addWidget(self._row(m.name, f"{m.gb:.1f}GB", "取る", lambda _=False, m=m: self.fetch(m)))

    def _image_actions(self, key: str, it: "Item | None", m: ImageModel | None = None):
        """ボタンの組（名前と働き）。取っていなければ「取る」、取ってあれば「使う」と「削除」、使っている物は「使用中」"""
        if it is None:
            return "取る", (lambda _=False, m=m: self.fetch(m))
        if self.settings.get("image_model") == key:
            return "使用中", None
        return "使う", (lambda _=False, key=key, m=m: self.use(key, m)), "削除", (lambda _=False, it=it: self.ask_delete(it))

    def _image_row(self, m: ImageModel, it: "Item | None") -> QWidget:
        sure = "確かめ済み" if m.score > 0 else "未確認"
        deal = (m.commercial or "札を確かめる").split("（")[0]
        if not hasattr(self, "_pc"):
            self._pc = machine()   # この PC の VRAM とメモリ（1 回だけ測る）
        can = fits(m, *self._pc)
        need_vram, need_ram = heavy(m)
        meta = "・".join(x for x in (f"{m.gb:.1f}GB", family(m.family).name, sure, deal, FITS[can]) if x)
        pc = (f"この PC: VRAM {self._pc[0]:.0f}GB、メモリ {self._pc[1]:.0f}GB" if self._pc[0] else f"この PC: GPU なし、メモリ {self._pc[1]:.0f}GB")
        tip = "\n".join(x for x in (f"Hugging Face: {m.hub}" + (f" の {m.file}" if m.file else ""), m.good, f"商用: {m.commercial or '札を確かめる'}",
                                     f"重さ: GPU で描くには VRAM {need_vram:g}GB 以上、メモリ {need_ram:g}GB 以上（{pc}）",
                                     "まだ動かして確かめていない模型です。崩れが多いことがあります" if m.score <= 0 else "", m.note) if x)
        box = self._row(m.name, meta, *self._image_actions(m.repo, it, m), sub=m.good)
        box.setToolTip(tip)
        return box

    def use(self, key: str, m: ImageModel | None):
        self.settings.set("image_model", key)
        if m is not None:
            self.settings.set("steps", m.steps)
            self.settings.set("guidance", m.guidance)
        self.status.setText(f"{m.name if m else key} を使います" + ("（未確認の模型です）" if m is not None and m.score <= 0 else ""))
        self.refresh()

    def add_by_name(self):
        name = self.hf_name.text().strip()
        if not name:
            self.status.setText("Hugging Face の模型の名前を「持ち主/名前」の形で書いてください")
            return
        self.add_button.setEnabled(False)
        self.status.setText(f"{name} を確かめています")
        threading.Thread(target=self.prober.run, args=(name,), daemon=True).start()

    def _probed(self, entry, err: str):
        self.add_button.setEnabled(True)
        if err:
            self.status.setText(err)
            return
        from chatdraw.models import add_user_entry
        m = add_user_entry(entry)
        self.hf_name.clear()
        self.status.setText(f"{m.name} を一覧に足しました（{family(m.family).name}、約 {m.gb:.1f}GB、未確認）。「取る」で取れます")
        self.refresh()

    def open_manual_dir(self):
        """手で置く模型の置き場を作って開く（エクスプローラー）"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from chatdraw.models import manual_dir
        d = manual_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
        self.status.setText(f"{d} に置いたら、この窓を開き直すと一覧に出ます")

    def pick_file(self, path: str | None = None):
        from PySide6.QtWidgets import QFileDialog
        from chatdraw.models import is_local, local_model
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "絵の模型を選ぶ", "", "絵の模型 (*.safetensors)")
            if not path:
                return
        path = str(Path(path).resolve())
        if not is_local(path):
            self.status.setText("使えない形です。.safetensors のファイルか、model_index.json のあるフォルダーを選んでください")
            return
        m = local_model(path)
        from chatdraw.models import family as fam
        if m.family == "unknown":
            self.status.setText("形を見分けられませんでした。SDXL・SD1.5・FLUX.1 の .safetensors か、diffusers のフォルダーを選んでください")
            return
        self.settings.set("image_model", m.repo)
        self.settings.set("steps", m.steps)
        self.settings.set("guidance", m.guidance)
        self.status.setText(f"{m.name} を使います（{fam(m.family).name} として読みます）")
        self.refresh()

    def _row(self, name: str, size: str, action: str, fn, action2: str = "", fn2=None, sub: str = "") -> QWidget:
        box = QFrame()
        box.setObjectName("card")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 6, 8, 6)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(QLabel(name))
        meta = QLabel(size + (f"\n{sub}" if sub else ""))
        meta.setObjectName("cardMeta")
        text.addWidget(meta)
        row.addLayout(text, 1)
        for label, f in ((action, fn), (action2, fn2)):
            if not label:
                continue
            b = QPushButton(label)
            b.setEnabled(f is not None)
            if f is not None:
                b.clicked.connect(f)
            row.addWidget(b)
        return box

    def ask_delete(self, it: Item):
        ok = QMessageBox.question(self, "模型を消す",
                                  f"{it.name} を消しますか？\nほかの自作アプリも使っていることがあります。要るときは、もう一度取れます。",
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok != QMessageBox.Yes:
            return
        try:
            delete(it)
            self.status.setText(f"{it.name} を消しました")
        except Exception as e:
            self.status.setText(f"消せませんでした: {e}")
        self.refresh()

    def fetch(self, m):
        self.bar.setVisible(True)
        image = m if isinstance(m, ImageModel) else None
        words = m if m in WORDS else None
        threading.Thread(target=self.fetcher.run, args=(image, words), daemon=True).start()

    def update_all(self):
        """手元にある確かめ済みの模型に新しい版があれば取る"""
        from chatdraw.setup import has_image, has_words
        self.bar.setVisible(True)
        images = [m for m in catalog_images() if has_image(m)]
        words = [m for m in WORDS if has_words(m)]

        def run():
            for m in images:
                self.fetcher.run(m, None, True)
            for m in words:
                self.fetcher.run(None, m, True)
        threading.Thread(target=run, daemon=True).start()

    def _fetched(self, err: str):
        self.bar.setVisible(False)
        self.status.setText(err or "終わりました")
        self.refresh()


class Prober(QObject):
    """Hugging Face の名前を、窓を止めずに確かめる（ネットワークを待つため）"""
    done = Signal(object, str)

    def run(self, name: str):
        from chatdraw.hfadd import AddError, probe
        try:
            self.done.emit(probe(name), "")
        except AddError as e:
            self.done.emit(None, str(e))
        except Exception as e:  # 思わぬ返事も、理由を見せて止める
            self.done.emit(None, f"確かめられませんでした: {e}")
