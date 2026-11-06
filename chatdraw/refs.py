"""参考資料: 好きな作家・作品の言葉（お気に入りの作風）と、手元の参考画像の検索。

お気に入りの作風は、利用者が自分で書いた言葉を名前と組で残す（利用者ごとの QSettings。リポジトリにも作品の画像にも触らない）。
描くときに「お気に入りの○○で」と頼むか、一覧で選ぶと、その言葉を描く頼みの後ろに足す。日本語のまま書いた言葉は、
絵の模型に渡す前に english_only が落とすので、英語で書くよう一覧の欄で案内する。

参考画像の検索は、ライブラリーの作品（頼み・タグ・メモ）と、利用者が選んだ手元のフォルダー（ファイル名と、隣の .json・PNG に埋めた頼み）
をタグで探す。ウェブは探さない（どこから来た絵か分からない物を参考にしない）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

KEY = "favorite_styles"
IMAGES = (".png", ".jpg", ".jpeg", ".webp")
SCAN_LIMIT = 5000   # 1 回に見るファイルの上限。大きなフォルダーで固まらない


class Favorites:
    def __init__(self, store: QSettings | None = None):
        self.store = store or QSettings("CharacterDesigner", "chatdraw-settings")

    def all(self) -> list[dict]:
        try:
            v = json.loads(self.store.value(KEY, "[]") or "[]")
            return [d for d in v if isinstance(d, dict) and d.get("name")] if isinstance(v, list) else []
        except (TypeError, ValueError):
            return []

    def _save(self, items: list[dict]):
        self.store.setValue(KEY, json.dumps(items, ensure_ascii=False))

    def put(self, name: str, words: str, note: str = ""):
        name = name.strip()
        if not name:
            return
        items = [d for d in self.all() if d["name"] != name]
        items.append({"name": name, "words": words.strip(), "note": note.strip()})
        self._save(items)

    def remove(self, name: str):
        self._save([d for d in self.all() if d["name"] != name])

    def get(self, name: str) -> dict | None:
        return next((d for d in self.all() if d["name"] == name), None)

    def find_in(self, text: str) -> dict | None:
        """頼みの中に書かれたお気に入りの名前（長い名前を先に見る）"""
        for d in sorted(self.all(), key=lambda d: len(d["name"]), reverse=True):
            if d["name"] in text:
                return d
        return None

    def apply(self, text: str) -> tuple[str, dict | None]:
        """頼みにお気に入りの名前があれば、名前と「お気に入りの」「風で」を除き、言葉を後ろに足す"""
        d = self.find_in(text)
        if d is None:
            return text, None
        rest = re.sub(r"(お気に入りの|好きな)?\s*" + re.escape(d["name"]) + r"\s*(の作風|の画風|風)?\s*(で|の)?", " ", text, count=1)
        rest = re.sub(r"\s+", " ", rest).strip(" 、。")
        return (f"{rest}, {d['words']}" if rest else d["words"]), d


def _tokens(query: str) -> list[str]:
    from chatdraw.jaterms import tags_from
    words = [w for w in re.split(r"[\s,、，。]+", query) if len(w) >= 2]
    tags = [t.strip().lower() for t in ", ".join(tags_from(query)).split(",") if t.strip() and t.strip() not in ("solo",)]
    return list(dict.fromkeys(tags + [w.lower() for w in words]))


def _score(hay: str, toks: list[str]) -> int:
    hay = hay.lower()
    return sum(1 for t in toks if t and t in hay)


def _meta_text(path: Path) -> str:
    side = path.with_suffix(".json")
    try:
        if side.is_file():
            d = json.loads(side.read_text(encoding="utf-8"))
            return " ".join(str(d.get(k, "")) for k in ("text", "prompt", "tags"))
    except (OSError, ValueError):
        pass
    if path.suffix.lower() == ".png":
        try:
            from PIL import Image
            with Image.open(path) as im:
                return " ".join(str(v) for v in (im.info or {}).values() if isinstance(v, str))[:2000]
        except Exception:   # noqa: BLE001  読めない絵は名前だけで探す
            return ""
    return ""


def find_images(query: str, items: list[dict] = (), folders: list[str] = (), limit: int = 12) -> list[tuple[int, str]]:
    """探す言葉に合う参考画像を、合った数の多い順に返す [(合った数, 道), …]。合わない物は返さない"""
    toks = _tokens(query)
    if not toks:
        return []
    found: dict[str, int] = {}
    for it in items or ():
        hay = " ".join([str(it.get(k, "")) for k in ("text", "prompt", "note", "style", "path")] + list(it.get("tags") or []))
        s = _score(hay, toks)
        if s and it.get("path"):
            found[str(it["path"])] = max(found.get(str(it["path"]), 0), s)
    seen = 0
    for folder in folders or ():
        root = Path(folder).expanduser()
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if seen >= SCAN_LIMIT:
                break
            if p.suffix.lower() not in IMAGES:
                continue
            seen += 1
            s = _score(p.stem.replace("_", " ").replace("-", " "), toks) or _score(_meta_text(p), toks)
            if s:
                found[str(p)] = max(found.get(str(p), 0), s)
    return sorted(((s, p) for p, s in found.items()), key=lambda x: (-x[0], x[1]))[:limit]


class FavoritesDialog(QDialog):
    """お気に入りの作風の一覧。足す・直す・消す。選んで「使う」と、AI の欄の描く内容の後ろに言葉を足す"""

    def __init__(self, favorites: Favorites, parent=None, on_use=None):
        super().__init__(parent)
        self.setWindowTitle("お気に入りの作風")
        self.resize(460, 360)
        self.fav = favorites
        self.on_use = on_use
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        self.name = QLineEdit()
        self.name.setPlaceholderText("呼び名（例: 好きな水彩）")
        self.words = QLineEdit()
        self.words.setPlaceholderText("描く言葉（英語で。例: watercolor, soft pastel colors, thick lineart）")
        self.words.setToolTip("絵の模型は日本語を読めないので、英語の言葉で書きます。日本語は描くときに外します")
        form = QFormLayout()
        form.addRow("名前", self.name)
        form.addRow("言葉", self.words)
        row = QHBoxLayout()
        for label, tip, fn in (("保存", "名前と言葉を一覧に残します（同じ名前は上書き）", self._save),
                               ("消す", "選んだ物を一覧から消します", self._remove),
                               ("使う", "選んだ物の言葉を、描く内容の後ろに足します", self._use)):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.list)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(box)
        self.refill()

    def refill(self):
        self.list.clear()
        for d in self.fav.all():
            it = QListWidgetItem(d["name"])
            it.setToolTip(d["words"])
            self.list.addItem(it)

    def _pick(self, cur, _prev=None):
        d = self.fav.get(cur.text()) if cur else None
        if d:
            self.name.setText(d["name"])
            self.words.setText(d["words"])

    def _save(self):
        self.fav.put(self.name.text(), self.words.text())
        self.refill()

    def _remove(self):
        it = self.list.currentItem()
        if it:
            self.fav.remove(it.text())
            self.refill()

    def _use(self):
        it = self.list.currentItem()
        d = self.fav.get(it.text()) if it else None
        if d and self.on_use:
            self.on_use(d)
