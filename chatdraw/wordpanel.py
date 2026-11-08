"""描くワードの欄まわりの、単語の部品。

- 単語のお気に入りの段（WordRow）: 登録した語をボタンで並べ、押すと描くワードの欄に足す。描くワードの登録（文のまとまり）とは別の段
- 読めなかった語の段（LostRow）: 頼みのうち絵の模型の言葉にならなかった語を出し、押せばタグを付けて直せる（黙って落とさない）
- 単語辞書の窓（WordDialog）: 今の頼みの対応表（語 → タグ）、使えた語の辞書（訳・回数・最後に使った日）、学びの様子

訳は画面の言語（i18n）で出し、ツールチップに書く。ボタンの説明もツールチップに出す。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from chatdraw import worddict
from chatdraw.flowlayout import FlowLayout

KINDS = {"draw": "描く物", "neg": "描かない物", "quiet": "言い回し", "lost": "読めなかった語"}


def _japanese(text: str) -> bool:
    return bool(re.search(r"[぀-ヿ一-鿿]", text))


def gloss(word: str) -> str:
    """語の訳。日本語の語は絵の模型に渡るタグ、英語のタグは画面の言語の訳"""
    if _japanese(word):
        from chatdraw.jaterms import tags_from
        return ", ".join(t for t in tags_from(word) if t)
    return worddict.translation(word)


def add_word(entry, word: str):
    """描くワードの欄に 1 語足す（前の言葉の後ろに、読点で区切って）"""
    text = entry.text().rstrip()
    if word in [w.strip() for w in re.split(r"[,、，\n]", text)]:
        return
    entry.setText(f"{text}、{word}" if text and not text.endswith(("、", ",", "，")) else text + word)


def ask_favorite(parent, entry) -> str | None:
    """★ を押したとき。欄で選んだ語があればそれ、無ければ今の頼みの語から選んで登録する"""
    sel = entry.textCursor().selectedText().strip() if hasattr(entry, "textCursor") else ""
    if sel:
        worddict.add_favorite(sel)   # 登録済みでも、選んだ語を返す（段を作り直す）
        return sel
    from chatdraw.jaterms import align
    words = [r["word"] for r in align(entry.text()) if r["kind"] in ("draw", "lost")]
    if not words:
        word, ok = QInputDialog.getText(parent, "単語を登録", "お気に入りにする語（日本語でも英語のタグでも）")
        word = word.strip()
        if ok and word:
            worddict.add_favorite(word)
            return word
        return None
    m = QMenu(parent)
    for w in dict.fromkeys(words):
        act = m.addAction(("★ " if worddict.is_favorite(w) else "") + w)
        act.setData(w)
        act.setToolTip(gloss(w))
    m.setToolTipsVisible(True)
    act = m.exec(parent.mapToGlobal(parent.rect().bottomLeft())) if parent.isVisible() else None
    if act is None:
        return None
    worddict.add_favorite(act.data())
    return act.data()


def entry_menu(entry, on_change=None):
    """描くワードの欄の右クリック。いつもの編集のメニューに、選んだ語を単語のお気に入りに登録する項目を足す"""
    m = entry.createStandardContextMenu()
    sel = entry.textCursor().selectedText().strip()
    m.addSeparator()
    act = m.addAction(f"「{sel[:12]}」を単語のお気に入りに登録" if sel else "単語のお気に入りに登録（語を選んでから）")
    act.setEnabled(bool(sel))
    act.triggered.connect(lambda: (worddict.add_favorite(sel), on_change and on_change()))
    return m


class WordRow(QWidget):
    """単語のお気に入りの段。登録した語のボタン、★（語を登録）、辞書…"""

    def __init__(self, entry, on_change=None, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.on_change = on_change
        self.setObjectName("scrollInner")
        self.flow = FlowLayout(self)
        self.star = QPushButton("☆語")
        self.star.setObjectName("suggest")
        self.star.setToolTip("描くワードの欄の語を 1 語ずつお気に入りに登録します（欄で語を選んでから押すと、その語）")
        self.star.clicked.connect(self.register)
        self.book = QPushButton("辞書…")
        self.book.setObjectName("suggest")
        self.book.setToolTip("単語辞書を開きます。今の頼みの語がどのタグになったか、描いて使えた語と訳、学びの様子を見られます")
        self.book.clicked.connect(self.open_dialog)
        self.reload()

    def chips(self) -> list[QPushButton]:
        return [self.flow.itemAt(i).widget() for i in range(self.flow.count())
                if self.flow.itemAt(i).widget() not in (self.star, self.book)]

    def reload(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            w = it.widget()
            if w is not None and w not in (self.star, self.book):
                w.deleteLater()
        for word in worddict.favorites():
            b = QPushButton(word if len(word) <= 18 else word[:17] + "…")
            b.setObjectName("suggest")
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("word", word)
            tr = gloss(word)
            b.setToolTip((f"訳: {tr}\n" if tr else "") + "押すと描くワードの欄に足します。右クリックで訳を直す・外す")
            b.clicked.connect(lambda _=False, w=word: add_word(self.entry, w))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, c=b, w=word: self.menu(c, pos, w))
            self.flow.addWidget(b)
        self.flow.addWidget(self.star)
        self.flow.addWidget(self.book)
        self.updateGeometry()

    def menu(self, chip, pos, word: str, run: bool = True):
        m = QMenu(self)
        m.addAction("描くワードに足す", lambda: add_word(self.entry, word))
        m.addAction("訳を直す…", lambda: self.edit_translation(word))
        m.addSeparator()
        m.addAction("お気に入りから外す", lambda: self.remove(word))
        if run:
            m.exec(chip.mapToGlobal(pos))
        return m

    def edit_translation(self, word: str, text: str | None = None):
        if text is None:
            text, ok = QInputDialog.getText(self, "訳を直す", f"「{word}」の訳（空にすると元の訳に戻します）", text=gloss(word))
            if not ok:
                return
        worddict.set_translation(word, text)
        self.reload()

    def remove(self, word: str):
        worddict.remove_favorite(word)
        self.reload()
        if self.on_change:
            self.on_change()

    def register(self):
        if ask_favorite(self.star, self.entry):
            self.reload()
            if self.on_change:
                self.on_change()

    def open_dialog(self):
        dlg = WordDialog(self.entry, self, self.window())
        dlg.show()
        return dlg


class LostRow(QWidget):
    """読めなかった語の段。押すと、その語に付けるタグを聞いて辞書に覚える"""

    def __init__(self, entry, on_change=None, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.on_change = on_change
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.head = QLabel("読めなかった語:")
        self.head.setObjectName("hint")
        self.head.setToolTip("絵の模型の言葉（英語のタグ）にならなかった語です。このままでは絵に描かれません。押すとタグを付けて直せます")
        lay.addWidget(self.head)
        self.box = QWidget()
        self.flow = FlowLayout(self.box)
        lay.addWidget(self.box, 1)
        self.words: list[str] = []
        self.hide()

    def update_words(self, words: list[str]):
        self.words = list(dict.fromkeys(words))
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for w in self.words:
            b = QPushButton(w)
            b.setObjectName("suggest")
            b.setProperty("word", w)
            b.setToolTip(f"「{w}」にタグを付けます（例: carrot）。空で付けると、描く物を変えない語として覚えます")
            b.clicked.connect(lambda _=False, x=w: self.fix(x))
            self.flow.addWidget(b)
        self.setVisible(bool(self.words))

    def fix(self, word: str, tags: str | None = None):
        if tags is None:
            tags, ok = QInputDialog.getText(self, "読めなかった語を直す", f"「{word}」を絵の模型に渡すタグ（英語、, で区切る）")
            if not ok:
                return
        worddict.set_term(word, tags)
        if self.on_change:
            self.on_change()


class WordDialog(QDialog):
    """単語辞書の窓。対応表・単語辞書・学び"""

    def __init__(self, entry, row: WordRow | None = None, parent=None):
        super().__init__(parent)
        self.entry, self.row = entry, row
        self.setWindowTitle("単語辞書")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        # 対応表: 今の頼みを語ごとに分け、どの語がどのタグになったか。読めなかった語はダブルクリックで直す
        self.map = QTableWidget(0, 3)
        self.map.setHorizontalHeaderLabels(["語", "タグ", "種類"])
        self.map.setToolTip("今の描くワードの語が、どのタグで絵の模型に渡るかです。行をダブルクリックするとタグを直せます")
        self.map.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.map.cellDoubleClicked.connect(lambda r, _c: self.fix_row(r))
        self.map.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabs.addTab(self.map, "対応表")
        # 単語辞書: 描いて使えた語。訳の列は直せる。★ で単語のお気に入りに入れる
        page = QWidget()
        pl = QVBoxLayout(page)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "語", "訳", "使えた", "通った", "最後に使った日"])
        self.table.setToolTip("検品を通った絵の頼みに入っていた語です。訳の欄はダブルクリックで直せます。☆ を押すとお気に入りに入ります")
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._edited)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        pl.addWidget(self.table)
        self.tabs.addTab(page, "単語辞書")
        self.learn = QLabel("")
        self.learn.setWordWrap(True)
        self.learn.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.learn.setToolTip("描いた絵ごとの記録から学んだ、描かれにくいタグです。前に出して描きます（足しも消しもしません）")
        self.tabs.addTab(self.learn, "学び")
        close = QPushButton("閉じる")
        close.setToolTip("単語辞書を閉じます")
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, Qt.AlignRight)
        self.reload()

    def reload(self):
        from chatdraw import wordlearn
        from chatdraw.jaterms import align
        self.rows = align(self.entry.text())
        self.map.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for c, v in enumerate((r["word"], ", ".join(r["tags"]), KINDS[r["kind"]])):
                self.map.setItem(i, c, QTableWidgetItem(v))
        self._filling = True
        self.dict_rows = worddict.entries()
        self.table.setRowCount(len(self.dict_rows))
        for i, e in enumerate(self.dict_rows):
            star = QPushButton("★" if worddict.is_favorite(e["tag"]) else "☆")
            star.setFixedWidth(32)
            star.setToolTip("単語のお気に入りに入れる・外す")
            star.clicked.connect(lambda _=False, t=e["tag"]: self.toggle(t))
            self.table.setCellWidget(i, 0, star)
            for c, v in enumerate((e["tag"], e["tr"], str(e["used"]), str(e["passed"]), e["last"]), 1):
                it = QTableWidgetItem(v)
                if c != 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, it)
        self._filling = False
        self.learn.setText(wordlearn.summary())

    def toggle(self, tag: str):
        if worddict.is_favorite(tag):
            worddict.remove_favorite(tag)
        else:
            worddict.add_favorite(tag)
        self.reload()
        if self.row:
            self.row.reload()

    def _edited(self, item):
        if getattr(self, "_filling", False) or item.column() != 2:
            return
        worddict.set_translation(self.dict_rows[item.row()]["tag"], item.text())
        if self.row:
            self.row.reload()

    def _table_menu(self, pos):
        it = self.table.itemAt(pos)
        if it is None:
            return
        tag = self.dict_rows[it.row()]["tag"]
        self.table_menu(tag).exec(self.table.viewport().mapToGlobal(pos))

    def table_menu(self, tag: str):
        m = QMenu(self)
        m.addAction("描くワードに足す", lambda: add_word(self.entry, tag))
        m.addAction("お気に入りから外す" if worddict.is_favorite(tag) else "お気に入りに登録", lambda: self.toggle(tag))
        m.addSeparator()
        m.addAction("辞書から消す…", lambda: self._forget(tag))
        return m

    def _forget(self, tag: str):
        from chatdraw import confirm
        w = self.parentWidget()
        while w is not None and not hasattr(w, "layout_store"):   # 辞書の窓の親（アプリの窓）の覚えた答えを使う
            w = w.parentWidget()
        if w is not None and confirm.ask(w, "forget", "辞書から消す", f"「{tag}」を単語辞書から消します。",
                                                      [("yes", "消す")]) != "yes":
            return
        worddict.forget(tag)
        self.reload()

    def fix_row(self, i: int, tags: str | None = None):
        word = self.rows[i]["word"]
        if tags is None:
            tags, ok = QInputDialog.getText(self, "タグを直す", f"「{word}」を絵の模型に渡すタグ（英語、, で区切る）",
                                            text=", ".join(self.rows[i]["tags"]))
            if not ok:
                return
        worddict.set_term(word, tags)
        self.reload()
