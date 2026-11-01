"""模型の管理。目録の絵の模型を全部並べ、絞り込みと並べ替え、取得・使う・削除・更新と、Hugging Face の名前で足す入口を持つ。

見せるのは、名前・点（1 つの数）・大きさ・世代・商用の可否・得意なこと（1 行）・タグだけにする（点の細目や置き場の道は見せない）。
点は利用者が付けた点があればそれ、無ければ目録の点（ratings）。既定の並びは点の高い順。
手元にある模型はどの絞り込みでも先頭に出し、その中で ★（お気に入り）を先にする。非表示にした物は「非表示にした模型」にだけ出す。
ボタンが増えて並びが混まないように、まれにしか使わない操作（点・タグ・削除、ディレクトリ）はドロップダウンにまとめる。
まだ確かめていない模型も取って使えるが、「未確認」と書いて分ける。
消すのは、利用者がこの画面で選んで確かめたときだけ。使っている模型は消せない。
"""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget)

from chatdraw.models import FILTERS, FITS, HIDDEN, SORTS, WORDS, ImageModel, catalog_images, family, fits, heavy, machine, pick, run_mode, verified_words
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
        # タグはいくつでも選べるドロップダウン。選んだタグを全部持つ模型だけを出す
        self.tag_button = QToolButton()
        self.tag_button.setText("タグ")
        self.tag_button.setPopupMode(QToolButton.InstantPopup)
        self.tag_button.setToolTip("好みのタグで絞ります（いくつでも選べます）。自分のタグは各模型の「…」から足せます")
        self.tag_menu = QMenu(self.tag_button)
        self.tag_menu.aboutToShow.connect(self._fill_tags)
        self.tag_button.setMenu(self.tag_menu)
        self.chosen_tags: list[str] = []
        tools.addWidget(self.filter)
        tools.addWidget(self.sort)
        tools.addWidget(self.tag_button)
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
        row = QHBoxLayout()
        # ディレクトリは 1 つのドロップダウンにまとめる（模型の置き場と、手で置く模型の置き場）
        self.folder_button = QToolButton()
        self.folder_button.setText("ディレクトリを開く")
        self.folder_button.setPopupMode(QToolButton.InstantPopup)
        self.folder_button.setToolTip("模型の置き場をエクスプローラーで開きます。無ければ作ってから開きます")
        folder_menu = QMenu(self.folder_button)
        folder_menu.setToolTipsVisible(True)
        from chatdraw.paths import LLM_HOME
        a = folder_menu.addAction("模型の置き場", lambda: self.open_dir(LLM_HOME))
        a.setToolTip("絵と言葉の模型を置く所。ほかの自作アプリと共有します")
        a = folder_menu.addAction("手で置く模型", self.open_manual_dir)
        a.setToolTip("ここに .safetensors か、model_index.json のあるディレクトリを置くと、一覧に出ます")
        self.folder_button.setMenu(folder_menu)
        pick = QPushButton("ファイルを選んで使う…")
        pick.setToolTip("手元の絵の模型（.safetensors）を選んで、そのまま使います。ファイルは動かしません")
        pick.clicked.connect(self.pick_file)
        self.update_button = QPushButton("更新を確かめる")
        self.update_button.setToolTip("手元にある確かめ済みの模型に新しい版があれば取ります")
        self.update_button.clicked.connect(self.update_all)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        row.addWidget(self.folder_button)
        row.addWidget(pick)
        row.addWidget(self.update_button)
        row.addStretch()
        row.addWidget(close)
        self.body.addLayout(row)
        self.fetcher = Fetcher()
        self.fetcher.progress.connect(lambda msg, pct: (self.status.setText(msg), self.bar.setValue(pct)), Qt.QueuedConnection)
        self.fetcher.finished.connect(self._fetched, Qt.QueuedConnection)
        if hasattr(parent, "watch_fetch"):   # 窓の右下の進みにも出す（この窓を閉じても進みが見える）
            parent.watch_fetch(self.fetcher)
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
        hiding = self.filter.currentText() == HIDDEN
        if not hiding:   # おまかせも 1 つの選び方として出す（描くたびに手元の模型から頼みに合う物を選ぶ）
            auto = self.settings.get("image_model") == AUTO
            self.list.addWidget(self._row("おまかせ", "手元の模型から、頼みに合い点の高い物を描くたびに選びます",
                                          "使用中" if auto else "使う", None if auto else self.use_auto))
        catalog = catalog_images()
        shown = pick(catalog, self.filter.currentText(), self.sort.currentText(), self.chosen_tags, have=mine)
        known = {m.repo for m in catalog}
        if not hiding:   # 手元にある物は、どの絞り込みでも先頭に出す（目録に無い、前に取った物と手で置いた物も）
            for it in (it for it in mine.values() if it.key not in known):
                self.list.addWidget(self._row(it.name, f"{it.gb:.1f}GB・取得済み", *self._image_actions(it.key, it)))
            for it in [x for x in have if x.kind == "manual"]:
                use = (lambda _=False, it=it: self.pick_file(it.key))
                self.list.addWidget(self._row(it.name, f"{it.gb:.1f}GB・手で置いた模型", "使用中" if self.settings.get("image_model") == it.key
                                              else "使う", None if self.settings.get("image_model") == it.key else use))
        for m in shown:
            self.list.addWidget(self._image_row(m, mine.get(m.repo)))
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
        """ボタン（名前と働き）。取っていなければ「取る」、取ってあれば「使う」、使っている物は「使用中」。削除は「…」の中"""
        if it is None:
            return "取る", (lambda _=False, m=m: self.fetch(m))
        if self.settings.get("image_model") == key:
            return "使用中", None
        return "使う", (lambda _=False, key=key, m=m: self.use(key, m)), "削除", (lambda _=False, it=it: self.ask_delete(it))

    def _more(self, m: ImageModel, actions: tuple) -> QMenu:
        """「…」のドロップダウン（行の右クリックでも同じ物）。自分の点、自分のタグ、非表示・ブロック（解除）、停止、削除"""
        from chatdraw.ratings import is_blocked, is_hidden
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        def add(label, fn, tip, enabled=True):
            a = menu.addAction(label, fn)
            a.setToolTip(tip)
            a.setEnabled(enabled)
            return a
        add("自分の点を付ける…", lambda m=m: self.ask_rating(m), "0〜100 の自分の点。目録の点より先に使います")
        add("自分のタグ…", lambda m=m: self.ask_tags(m), "好みで探すためのタグを足します")
        menu.addSeparator()
        blocked = is_blocked(m.repo)
        if blocked:
            add("ブロックを解除", lambda m=m: self.set_blocked(m, False), "おまかせ・推奨・AI のメニューに戻し、取れるようにします")
        else:
            if is_hidden(m.repo):
                add("表示に戻す", lambda m=m: self.set_hidden(m, False), "一覧と推奨に戻します")
            else:
                add("非表示にする", lambda m=m: self.set_hidden(m, True),
                    "一覧と推奨に出しません。取ってある物は「非表示にした模型」の絞り込みで出せます")
            add("ブロックする", lambda m=m: self.set_blocked(m, True),
                "非表示に加えて、おまかせ・推奨・AI のメニューのどこからも選ばず、取りにも行きません")
        menu.addSeparator()
        w = self.parent()
        mine = getattr(getattr(getattr(w, "studio", None), "painter", None), "model", None) == m.repo
        add("描いている処理を止める", self.stop_drawing, "いま描いている処理を止めます。途中の絵は捨て、キャンバスは元のままです",
            bool(mine and getattr(w, "drawing", lambda: False)()))
        add("メモリから降ろす", lambda m=m: self.unload(m), "読み込んだこの模型をメモリから降ろします。次に描くときに読み直します",
            bool(mine and w.studio.painter.loaded()))
        if len(actions) > 2 and actions[3] is not None and not blocked:
            menu.addSeparator()
            menu.addAction(actions[2], actions[3])
        return menu

    def set_hidden(self, m: ImageModel, on: bool):
        from chatdraw.ratings import set_hidden
        set_hidden(m.repo, on)
        self.status.setText(f"{m.name} を" + ("非表示にしました。「非表示にした模型」の絞り込みから戻せます" if on else "表示に戻しました"))
        self.refresh()

    def set_blocked(self, m: ImageModel, on: bool):
        from chatdraw.ratings import set_blocked
        from chatdraw.setup import AUTO
        if on and self.settings.get("image_model") == m.repo:   # 使っている模型をブロックしたら、おまかせに戻す
            self.settings.set("image_model", AUTO)
        set_blocked(m.repo, on)
        self.status.setText(f"{m.name} を" + ("ブロックしました。「非表示にした模型」の絞り込みから解除できます" if on else "ブロックを解除しました"))
        self.refresh()

    def stop_drawing(self):
        w = self.parent()
        if hasattr(w, "stop"):
            w.stop()
            self.status.setText("止めています。途中の絵は捨て、キャンバスは元のままです")

    def unload(self, m: ImageModel):
        w = self.parent()
        if hasattr(w, "unload_model"):
            self.status.setText(w.unload_model(m.repo))
        self.refresh()

    def toggle_favorite(self, m: ImageModel):
        from chatdraw.ratings import is_favorite, set_favorite
        set_favorite(m.repo, not is_favorite(m.repo))
        self.refresh()

    def use_auto(self):
        self.settings.set("image_model", AUTO)
        self.status.setText("おまかせにしました。描くたびに、手元の模型から頼みに合う物を選びます")
        self._changed()

    def _changed(self):
        """一覧を作り直し、AI のメニューにも知らせる"""
        from chatdraw.ratings import changed
        self.refresh()
        changed()

    def ask_rating(self, m: ImageModel):
        from chatdraw.ratings import set_user_rating, user_rating
        value, ok = QInputDialog.getInt(self, "自分の点", f"{m.name} の点（0〜100。0 にすると確かめた点に戻ります）",
                                        user_rating(m.repo), 0, 100)
        if ok:
            set_user_rating(m.repo, value)
            self.refresh()

    def ask_tags(self, m: ImageModel):
        from chatdraw.ratings import set_user_tags, user_tags
        text, ok = QInputDialog.getText(self, "自分のタグ", f"{m.name} に付けるタグ（、で区切る）", text="、".join(user_tags(m.repo)))
        if ok:
            set_user_tags(m.repo, [t for t in text.replace(",", "、").split("、")])
            self.refresh()

    def _fill_tags(self):
        from chatdraw.ratings import all_tags
        self.tag_menu.clear()
        clear = self.tag_menu.addAction("絞らない", lambda: self.set_tags([]))
        clear.setEnabled(bool(self.chosen_tags))
        self.tag_menu.addSeparator()
        for t in all_tags(catalog_images()):
            a = self.tag_menu.addAction(t)
            a.setCheckable(True)
            a.setChecked(t in self.chosen_tags)
            a.toggled.connect(lambda on, t=t: self.set_tags([x for x in self.chosen_tags if x != t] + ([t] if on else [])))

    def set_tags(self, tags: list[str]):
        self.chosen_tags = list(tags)
        self.tag_button.setText("タグ" + (f"（{len(tags)}）" if tags else ""))
        self.tag_button.setToolTip("選んでいるタグ: " + "、".join(tags) if tags else "好みのタグで絞ります（いくつでも選べます）")
        self.refresh()

    def _image_row(self, m: ImageModel, it: "Item | None") -> QWidget:
        from chatdraw.ratings import rating_text, tags, user_rating
        sure = rating_text(m) + ("（自分の点）" if user_rating(m.repo) else "")
        deal = (m.commercial or "札を確かめる").split("（")[0]
        if not hasattr(self, "_pc"):
            self._pc = machine()   # この PC の VRAM とメモリ（1 回だけ測る）
        can = fits(m, *self._pc)
        need_vram, need_ram = heavy(m)
        how = "動き方: " + run_mode(m, *self._pc) if can != "no" else ""   # GPU か、分けて GPU か、CPU か
        meta = "・".join(x for x in (sure, f"{m.gb:.1f}GB", family(m.family).name, deal, FITS[can], how) if x)
        pc = (f"この PC: VRAM {self._pc[0]:.0f}GB、メモリ {self._pc[1]:.0f}GB" if self._pc[0] else f"この PC: GPU なし、メモリ {self._pc[1]:.0f}GB")
        tip = "\n".join(x for x in (f"Hugging Face: {m.hub}" + (f" の {m.file}" if m.file else ""), m.good, f"商用: {m.commercial or '札を確かめる'}",
                                     f"重さ: GPU で描くには VRAM {need_vram:g}GB 以上、メモリ {need_ram:g}GB 以上（{pc}）",
                                     "まだ動かして確かめていない模型です。崩れが多いことがあります" if m.score <= 0 else "", m.note) if x)
        actions = self._image_actions(m.repo, it, m)
        sub = m.good + ("\n" + " ".join(f"#{t}" for t in tags(m)) if tags(m) else "")
        if it is not None:
            meta = "取得済み・" + meta
        box = self._row(m.name, meta, *actions[:2], sub=sub, more=self._more(m, actions), star=m)
        box.setToolTip(tip)
        return box

    def use(self, key: str, m: ImageModel | None):
        self.settings.set("image_model", key)
        if m is not None:
            self.settings.set("steps", m.steps)
            self.settings.set("guidance", m.guidance)
        self.status.setText(f"{m.name if m else key} を使います" + ("（未確認の模型です）" if m is not None and m.score <= 0 else ""))
        self._changed()

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
        self._changed()

    def open_manual_dir(self):
        """手で置く模型の置き場を作って開く（エクスプローラー）"""
        from chatdraw.models import manual_dir
        d = self.open_dir(manual_dir())
        self.status.setText(f"{d} に置いたら、この窓を開き直すと一覧に出ます")

    def open_dir(self, path) -> Path:
        from chatdraw.folders import open_folder
        return open_folder(path)

    def pick_file(self, path: str | None = None):
        from PySide6.QtWidgets import QFileDialog
        from chatdraw.models import is_local, local_model
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "絵の模型を選ぶ", "", "絵の模型 (*.safetensors)")
            if not path:
                return
        path = str(Path(path).resolve())
        if not is_local(path):
            self.status.setText("使えない形です。.safetensors のファイルか、model_index.json のあるディレクトリを選んでください")
            return
        m = local_model(path)
        from chatdraw.models import family as fam
        if m.family == "unknown":
            self.status.setText("形を見分けられませんでした。SDXL・SD1.5・FLUX.1 の .safetensors か、diffusers のディレクトリを選んでください")
            return
        self.settings.set("image_model", m.repo)
        self.settings.set("steps", m.steps)
        self.settings.set("guidance", m.guidance)
        self.status.setText(f"{m.name} を使います（{fam(m.family).name} として読みます）")
        self.refresh()

    def _row(self, name: str, size: str, action: str, fn, action2: str = "", fn2=None, sub: str = "", more: QMenu | None = None,
             star: ImageModel | None = None) -> QWidget:
        box = QFrame()
        box.setObjectName("card")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 6, 8, 6)
        if star is not None:   # ★ を押すと、お気に入りを付ける・外す
            from chatdraw.ratings import is_favorite
            fav = is_favorite(star.repo)
            b = QToolButton()
            b.setText("★" if fav else "☆")
            b.setCheckable(True)
            b.setChecked(fav)
            b.setAutoRaise(True)
            b.setToolTip("お気に入りを外します" if fav else "お気に入りにします。★ の模型は手元の模型の中で先頭に出ます")
            b.clicked.connect(lambda _=False, m=star: self.toggle_favorite(m))
            box.star = b
            row.addWidget(b)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(QLabel(name))
        meta = QLabel(size + (f"\n{sub}" if sub else ""))
        meta.setObjectName("cardMeta")
        meta.setWordWrap(True)   # 長い説明で横に流れて「…」が窓の外に出ないように
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
        if more is not None:
            b = QToolButton()
            b.setText("…")
            b.setPopupMode(QToolButton.InstantPopup)
            b.setToolTip("自分の点・自分のタグ・非表示・ブロック・停止・削除。行の右クリックでも出ます")
            b.setMenu(more)
            box.more = more
            box.setContextMenuPolicy(Qt.CustomContextMenu)
            box.customContextMenuRequested.connect(lambda pos, box=box: box.more.popup(box.mapToGlobal(pos)))
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
        self._changed()

    def fetch(self, m):
        from chatdraw.ratings import is_blocked
        if isinstance(m, ImageModel) and is_blocked(m.repo):
            self.status.setText(f"{m.name} はブロックしています。「…」から解除すると取れます")
            return
        self.bar.setVisible(True)
        image = m if isinstance(m, ImageModel) else None
        words = m if m in WORDS else None
        threading.Thread(target=self.fetcher.run, args=(image, words), daemon=True).start()

    def update_all(self):
        """手元にある確かめ済みの模型に新しい版があれば取る"""
        from chatdraw.setup import has_image, has_words
        self.bar.setVisible(True)
        from chatdraw.ratings import is_blocked
        images = [m for m in catalog_images() if has_image(m) and not is_blocked(m.repo)]
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
        self._changed()


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
