"""ライブラリーの欄。作品（描いた絵）・資料（置いた参考）・好み（読み取った結果）のタブ。

作品に「好き」「いまいち」を付け、資料に言葉を付けると、好みのタブに読み取った言葉が出る。
「好みを描く言葉に足す」を入れると、描くたびにその言葉を足し、避ける言葉を外して描く。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from chatdraw.library import DISLIKE, LIKE, NONE

MARK = {LIKE: "♥ 好き", DISLIKE: "× いまいち", NONE: ""}


def _grid() -> QListWidget:
    v = QListWidget()
    v.setViewMode(QListView.IconMode)
    v.setIconSize(QSize(88, 120))
    v.setGridSize(QSize(100, 150))
    v.setResizeMode(QListView.Adjust)
    v.setMovement(QListView.Static)
    v.setContextMenuPolicy(Qt.CustomContextMenu)
    v.setSelectionMode(QListWidget.ExtendedSelection)   # Ctrl や Shift で何枚か選んでまとめて消せる
    return v


class LibraryPanel(QWidget):
    def __init__(self, w):
        super().__init__()
        self.w = w
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self.works = _grid()
        self.works.setToolTip("描いた絵。右クリックで「好き」「いまいち」を付けると、好みを学びます")
        self.works.customContextMenuRequested.connect(lambda pos: self._menu(self.works, pos))
        self.works.itemDoubleClicked.connect(lambda it: self.w.layer_from_file(it.data(Qt.UserRole + 1), "ライブラリーの絵"))
        self.tabs.addTab(self.works, "作品")

        docs_page = QWidget()
        dl = QVBoxLayout(docs_page)
        dl.setContentsMargins(0, 4, 0, 0)
        self.docs = _grid()
        self.docs.setToolTip("置いた資料。右クリックで言葉を付けたり、参考画像にしたりできます")
        self.docs.customContextMenuRequested.connect(lambda pos: self._menu(self.docs, pos))
        add = QPushButton("資料を足す")
        add.setToolTip("好きな絵柄の絵やメモの画像を置きます。言葉を付けると好みに入ります")
        add.clicked.connect(self.add_doc)
        dl.addWidget(self.docs, 1)
        dl.addWidget(add)
        self.tabs.addTab(docs_page, "資料")

        taste = QWidget()
        tl = QVBoxLayout(taste)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.use = QCheckBox("好みを描く言葉に足す")
        self.use.setToolTip("好きな絵に多い言葉を足し、いまいちな絵に多い言葉を避けて描きます")
        self.use.setChecked(bool(int(self.w.layout_store.value("use_taste", 1))))
        self.use.toggled.connect(lambda on: self.w.layout_store.setValue("use_taste", int(on)))
        make = QPushButton("好みを AI プリセットにする")
        make.setToolTip("読み取った好み（画風と言葉）を、自分の AI プリセットとして残します")
        make.clicked.connect(self.make_preset)
        tl.addWidget(self.summary, 1)
        tl.addWidget(self.use)
        tl.addWidget(make)
        self.tabs.addTab(taste, "好み")
        from PySide6.QtGui import QAction
        for view in (self.works, self.docs):   # 選んだ絵を Delete キーで消す（確かめてからごみ箱へ）
            act = QAction("消す（ごみ箱へ）", view, shortcut="Delete", shortcutContext=Qt.WidgetWithChildrenShortcut)
            act.triggered.connect(lambda _=False, v=view: self.w.delete_images([it.data(Qt.UserRole + 1) for it in v.selectedItems()]))
            view.addAction(act)
        self.refresh()

    # ---- 見せる ----
    def _item(self, it: dict) -> QListWidgetItem:
        star = "★" if it["kind"] == "work" and it["path"] in self._favs else ""
        item = QListWidgetItem(star + MARK.get(it["rating"], "") if it["kind"] == "work" else (it["note"] or Path(it["path"]).name)[:10])
        pm = QPixmap(it["path"])
        if not pm.isNull():
            item.setIcon(QIcon(pm.scaled(176, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        item.setData(Qt.UserRole, it["id"])
        item.setData(Qt.UserRole + 1, it["path"])
        tip = [it["added"], it.get("text") or it.get("note", "")]
        if it.get("tags"):
            tip.append("言葉: " + ", ".join(it["tags"]))
        item.setToolTip("\n".join(t for t in tip if t))
        return item

    def add(self, item: dict):
        """足した 1 枚だけを先頭に並べる（全部を読み直さない）"""
        (self.works if item["kind"] == "work" else self.docs).insertItem(0, self._item(item))

    def refresh(self):
        from chatdraw.ownstyle import favorites
        self._favs = set(favorites())   # 1 回だけ読み、並べる絵ごとに読み直さない
        lib = self.w.library
        for view, rows in ((self.works, lib.works()), (self.docs, lib.docs())):
            view.clear()
            for it in rows:
                view.addItem(self._item(it))
        p = lib.profile()
        if p["rated"] == 0:
            text = "まだ好みを読み取れていません。\n作品を右クリックして「好き」「いまいち」を付けるか、資料に言葉を付けてください。"
        else:
            lines = [f"「好き」の絵 {p['liked']} 枚から読み取りました。"]
            if p["style"]:
                lines.append(f"よく選ぶ画風: {p['style']}")
            if p["tags"]:
                lines.append("好きな要素: " + ", ".join(p["tags"]))
            if p["avoid"]:
                lines.append("避ける要素: " + ", ".join(p["avoid"]))
            if not p["tags"] and not p["avoid"]:
                lines.append("同じ要素が 2 回以上出るまで、言葉は足しません。")
            text = "\n".join(lines)
        self.summary.setText(text)

    # ---- 操作 ----
    def _menu(self, view: QListWidget, pos, run: bool = True):
        it = view.itemAt(pos)
        if not it:
            return
        lib, item_id, path = self.w.library, it.data(Qt.UserRole), it.data(Qt.UserRole + 1)
        entry = lib.get(item_id)
        m = QMenu(self)
        if entry and entry["kind"] == "work":
            m.addAction("♥ 好き", lambda: self.rate(item_id, LIKE))
            m.addAction("× いまいち", lambda: self.rate(item_id, DISLIKE))
            m.addAction("評価を外す", lambda: self.rate(item_id, NONE))
            from chatdraw import ownstyle
            m.addAction("★ お気に入りを外す" if ownstyle.is_favorite(path) else "★ お気に入りにする",
                        lambda: (ownstyle.toggle(path), self.refresh()))
            m.addAction("学習用に集める", self.w.collect_favorites)
            m.addSeparator()
            m.addAction("この設定で描き直す", lambda: self.w.redo_from(path))
        else:
            m.addAction("参考画像にする", lambda: (self.w.reference.load(path), self.w.ai_panel.use_ref.setChecked(True)))
        m.addAction("今の絵に重ねる", lambda: self.w.layer_from_file(path, "ライブラリーの絵"))
        m.addAction("編集する（囲んで直す）", lambda: self.w.edit_image(path))
        m.addAction("言葉を付ける…", lambda: self.tag(item_id))
        m.addSeparator()
        if entry and entry["kind"] == "work":
            m.addAction("一覧から外す（絵は残す）", lambda: (lib.remove(item_id), self.refresh()))
        # 資料の写しも作品の絵も、すぐには消さずごみ箱へ移す（「ファイル」→「ごみ箱…」から戻せる）
        m.addAction("消す（ごみ箱へ）…", lambda: self.w.delete_images(self._chosen(view, path)))
        if not run:
            return m
        m.exec(view.mapToGlobal(pos))

    def _chosen(self, view: QListWidget, path: str) -> list[str]:
        """右クリックした絵と、一緒に選んでいる絵"""
        picked = [it.data(Qt.UserRole + 1) for it in view.selectedItems()]
        return picked if path in picked else [path]

    def rate(self, item_id: str, rating: int):
        self.w.library.rate(item_id, rating)
        self.w.feature_tour("taste")
        self.refresh()

    def tag(self, item_id: str, text: str | None = None):
        entry = self.w.library.get(item_id)
        if not entry:
            return
        if text is None:
            text, ok = QInputDialog.getText(self, "言葉を付ける", "この絵の好きな所（読点かカンマで区切る。例: 赤い髪、水彩）",
                                            text=", ".join(entry["tags"]))
            if not ok:
                return
        words = [t for t in text.replace("、", ",").split(",")]
        tr = self.w.studio.words

        def work():
            return [tr.to_prompt(t) if _has_ja(t) else t for t in words]

        def done(tags):
            if isinstance(tags, BaseException):
                tags = words   # 訳せなければ書いた言葉のまま残す
            self.w.library.set_tags(item_id, tags)
            self.refresh()
        if any(_has_ja(t) for t in words) and hasattr(tr, "ask") and hasattr(self.w, "in_background"):
            self.w.in_background(work, done)   # 言葉の模型で訳すのは裏で（画面の糸で訳すと数秒固まる）
        else:
            done(work())

    def add_doc(self, path: str | None = None, note: str | None = None):
        if not isinstance(path, (str, Path)):   # ボタンからは clicked の真偽（False）が来る。前はそれを道として読み、押すたびに落ちた
            path, _ = QFileDialog.getOpenFileName(self, "資料を足す", "", "画像 (*.png *.jpg *.jpeg *.webp)")
            if not path:
                return
        if note is None:
            note, ok = QInputDialog.getText(self, "資料のメモ", "この資料のどこが好きか（空でもよい）")
            if not ok:
                note = ""
        self.w.library.add_doc(path, note)
        self.w.feature_tour("library")
        self.tabs.setCurrentIndex(1)
        self.refresh()

    def make_preset(self):
        from chatdraw.aipanel import STYLE_TAGS
        p = self.w.library.profile()
        if not p["tags"] and not p["style"]:
            self.w.notify("まだ好みが足りません", "info", "「好き」を付けた絵が増えると作れます")
            return
        data = self.w.ai_panel.current()
        if p["style"] in STYLE_TAGS:
            data["style"] = p["style"]
        self.w.ai_panel.save_preset("あなたの好み", data)


def _has_ja(text: str) -> bool:
    return any(ord(ch) > 0x3000 for ch in text)
