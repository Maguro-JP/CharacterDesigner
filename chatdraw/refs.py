"""参考資料: 好きな作家・作品の言葉（登録した作風）と、手元の参考画像の検索。

登録した作風は、利用者が自分で書いた言葉を名前と組で残す（利用者ごとの QSettings。リポジトリにも作品の画像にも触らない）。
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
    """登録した作風の一覧。足す・直す・消す。選んで「使う」と、AI の欄の描く内容の後ろに言葉を足す"""

    def __init__(self, favorites: Favorites, parent=None, on_use=None):
        super().__init__(parent)
        self.setWindowTitle("登録した作風")
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


# ---- 学習セット（参考画像の組） ----
# 模型ごと・キャラクターごとに参考画像の組を残す。描くときは組の絵を 1 枚に並べて IP-Adapter に渡し、見た目を寄せる。
# 手元で LoRA を学習させる所までは作らない。学習には kohya の形（絵と同じ名前の .txt に言葉）で書き出し、外の道具に渡す。
# 置き場はアプリのデータの置き場の refsets.json（絵は写さず道だけを持つ。絵を外へ上げることはしない）
KINDS = {"model": "模型", "character": "キャラクター"}


def refsets_file() -> Path:
    from chatdraw import paths
    return paths.data_home() / "refsets.json"


class RefSets:
    def all(self) -> list[dict]:
        from chatdraw import paths
        v = paths.read_json(refsets_file(), list, [])
        return [d for d in v if isinstance(d, dict) and d.get("name")]

    def _save(self, items: list[dict]):
        from chatdraw import paths
        paths.write_json(refsets_file(), items)

    def get(self, name: str) -> dict | None:
        return next((d for d in self.all() if d["name"] == name), None)

    def put(self, name: str, kind: str = "character", target: str = "", images=(), words: str = "") -> dict:
        name = name.strip()
        if not name:
            raise ValueError("組の名前を入れてください")
        if kind not in KINDS:
            raise ValueError(f"組の種類は {', '.join(KINDS)} のどれかです")
        old = self.get(name) or {}
        d = {"name": name, "kind": kind, "target": target.strip(), "words": words.strip() or old.get("words", ""),
             "images": list(dict.fromkeys([*old.get("images", []), *[str(Path(p)) for p in images]]))}
        self._save([x for x in self.all() if x["name"] != name] + [d])
        return d

    def remove_image(self, name: str, path: str):
        d = self.get(name)
        if d:
            d["images"] = [p for p in d["images"] if p != path]
            self._save([x for x in self.all() if x["name"] != name] + [d])

    def remove(self, name: str):
        self._save([d for d in self.all() if d["name"] != name])

    def for_target(self, kind: str, target: str) -> list[dict]:
        return [d for d in self.all() if d["kind"] == kind and d["target"] == target]


def reference_image(images, size: int = 512):
    """組の絵を 1 枚に並べる（IP-Adapter に 1 枚で渡すため）。読めた絵が無ければ None"""
    from PIL import Image
    pics = []
    for p in images:
        try:
            with Image.open(p) as im:
                pics.append(im.convert("RGB"))
        except (OSError, ValueError):
            continue
    if not pics:
        return None
    if len(pics) == 1:
        return pics[0]
    n = min(len(pics), 4)
    cols = 2
    rows = (n + 1) // 2
    cell = size // 2
    sheet = Image.new("RGB", (cell * cols, cell * rows), "white")
    for i, im in enumerate(pics[:n]):
        im = im.copy()
        im.thumbnail((cell, cell))
        sheet.paste(im, ((i % cols) * cell + (cell - im.width) // 2, (i // cols) * cell + (cell - im.height) // 2))
    return sheet


def export_kohya(refset: dict, out: Path | None = None, repeats: int = 10) -> dict:
    """kohya の形で書き出す: <out>/<繰り返し>_<名前>/ に絵と、同じ名前の .txt（組の言葉と、絵の隣の頼み）"""
    import shutil
    from chatdraw import paths
    safe = re.sub(r"[^\w\-]+", "_", refset["name"]).strip("_") or "set"
    root = Path(out) if out else paths.data_home() / "datasets" / safe
    folder = root / f"{repeats}_{safe}"
    folder.mkdir(parents=True, exist_ok=True)
    done, missing = [], []
    for i, src in enumerate(refset.get("images", []), 1):
        p = Path(src)
        if not p.is_file():
            missing.append(src)
            continue
        dst = folder / f"{i:03d}{p.suffix.lower()}"
        shutil.copyfile(p, dst)
        side = _meta_text(p) if p.with_suffix(".json").is_file() else ""
        words = ", ".join(x for x in (refset.get("words", ""), side.strip()) if x)
        dst.with_suffix(".txt").write_text(words, encoding="utf-8")
        done.append(str(dst))
    return {"dir": str(root), "folder": str(folder), "images": done, "missing": missing}


class RefSetDialog(QDialog):
    """学習セットの窓。組を作り、絵を足し、「参考画像に使う」で IP-Adapter に渡す絵にし、kohya の形で書き出す"""

    def __init__(self, store: RefSets, parent=None, on_use=None, target: str = "", kind: str = "character"):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox, QLabel
        self.setWindowTitle("学習セット")
        self.resize(500, 420)
        self.store, self.on_use = store, on_use
        self.sets = QListWidget()
        self.sets.currentItemChanged.connect(self._pick)
        self.images = QListWidget()
        self.name = QLineEdit()
        self.name.setPlaceholderText("組の名前（例: 主人公の参考）")
        self.kind = QComboBox()
        for k, ja in KINDS.items():
            self.kind.addItem(ja, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.kind.setToolTip("模型ごとの組か、キャラクターごとの組か")
        self.target = QLineEdit(target)
        self.target.setPlaceholderText("模型の名前か、キャラクターの id")
        self.words = QLineEdit()
        self.words.setPlaceholderText("言葉（英語で。書き出すときに .txt に書きます）")
        self.words.setToolTip("kohya の形で書き出すとき、絵ごとの .txt に書く言葉。LoRA のきっかけの言葉にもなります")
        form = QFormLayout()
        form.addRow("名前", self.name)
        form.addRow("種類", self.kind)
        form.addRow("対象", self.target)
        form.addRow("言葉", self.words)
        row = QHBoxLayout()
        for label, tip, fn in (("保存", "名前・種類・対象・言葉を残します（同じ名前は上書き）", self.save),
                               ("絵を足す…", "手元の絵を組に足します。絵は写さず、置き場の道だけを残します", self.add_images),
                               ("参考画像に使う", "組の絵を 1 枚に並べて参考画像に置きます。描くとき IP-Adapter で見た目を寄せます", self.use),
                               ("書き出す", "kohya の形（絵と同じ名前の .txt）で書き出します。学習は外の道具で行います", self.export),
                               ("消す", "選んだ組を一覧から消します（絵は消しません）", self.remove)):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        self.status = QLabel("")
        self.status.setObjectName("cardMeta")
        self.status.setWordWrap(True)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lists = QHBoxLayout()
        lists.addWidget(self.sets, 1)
        lists.addWidget(self.images, 2)
        lay.addLayout(lists, 1)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(self.status)
        lay.addWidget(box)
        self.refill()

    def refill(self, keep: str = ""):
        self.sets.clear()
        for d in self.store.all():
            it = QListWidgetItem(d["name"])
            it.setToolTip(f"{KINDS.get(d['kind'], d['kind'])}: {d['target'] or '（対象なし）'}・{len(d['images'])} 枚")
            self.sets.addItem(it)
            if d["name"] == keep:
                self.sets.setCurrentItem(it)

    def current(self) -> dict | None:
        it = self.sets.currentItem()
        return self.store.get(it.text()) if it else self.store.get(self.name.text().strip())

    def _pick(self, cur, _prev=None):
        d = self.store.get(cur.text()) if cur else None
        self.images.clear()
        if d:
            self.name.setText(d["name"])
            self.kind.setCurrentIndex(max(0, self.kind.findData(d["kind"])))
            self.target.setText(d["target"])
            self.words.setText(d["words"])
            for p in d["images"]:
                it = QListWidgetItem(Path(p).name)
                it.setToolTip(p)
                self.images.addItem(it)

    def save(self, images=()):
        try:
            d = self.store.put(self.name.text(), self.kind.currentData(), self.target.text(), images or (), self.words.text())
        except ValueError as e:
            self.status.setText(str(e))
            return None
        self.refill(d["name"])
        self.status.setText(f"{d['name']}: {len(d['images'])} 枚")
        return d

    def add_images(self, paths=None):
        if not isinstance(paths, (list, tuple)):
            from PySide6.QtWidgets import QFileDialog
            paths, _ = QFileDialog.getOpenFileNames(self, "絵を足す", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if paths:
            self.save(paths)

    def use(self):
        d = self.current()
        im = reference_image(d["images"]) if d else None
        if im is None:
            self.status.setText("組に読める絵がありません。「絵を足す…」で足してください")
            return None
        from chatdraw import paths
        out = paths.data_home() / "refsets" / (re.sub(r"[^\w\-]+", "_", d["name"]) + ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)
        if self.on_use:
            self.on_use(str(out), d)
        self.status.setText(f"{d['name']} を参考画像に置きました")
        return str(out)

    def export(self):
        d = self.current()
        if not d:
            self.status.setText("組を選んでください")
            return None
        res = export_kohya(d)
        self.status.setText(f"{len(res['images'])} 枚を書き出しました: {res['folder']}"
                            + (f"（見つからない絵 {len(res['missing'])} 枚）" if res["missing"] else ""))
        return res

    def remove(self):
        it = self.sets.currentItem()
        if it:
            self.store.remove(it.text())
            self.images.clear()
            self.refill()
