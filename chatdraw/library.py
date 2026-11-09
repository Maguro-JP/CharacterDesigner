"""ライブラリー（作った絵）と資料（ドキュメント）を貯め、そこから利用者の好みを読み取る。

決まった物しか作れない道具にしないため、描く言葉の足し方は利用者の手元で育てる。
- 作品: 描いた絵はすべて自動で入る。「好き」「いまいち」を付けられる
- 資料: 利用者が置いた参考の絵やメモ。言葉（タグ）を付けられる
- 好み: 「好き」の作品と資料に多く出る言葉・作風・模型を数え、「いまいち」に多く出る言葉を避ける
置き場は利用者ごとのデータの置き場（paths.HOME / library）。git にもアプリの本体にも入れない。
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from collections import Counter
from pathlib import Path

LIKE, NONE, DISLIKE = 1, 0, -1
MIN_SEEN = 2   # 好みにするには、少なくとも 2 回出た言葉だけを使う（1 回だけの偶然に振り回されない）
# 好みに数えない言葉（どの絵にも付く決まり文句）
COMMON = {"masterpiece", "best quality", "1girl", "1boy", "solo", "simple background", "white background", ""}


def _tags(text: str) -> list[str]:
    return [t.strip().lower() for t in (text or "").replace("\n", ",").split(",") if t.strip()]


class Library:
    def __init__(self, root: Path | None = None):
        from chatdraw.paths import HOME
        self.root = Path(root) if root else HOME / "library"
        self.index = self.root / "index.json"
        self.items: list[dict] = []
        self.load()

    def load(self):
        try:
            self.items = json.loads(self.index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        part = self.index.with_suffix(".part")
        part.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
        part.replace(self.index)

    # ---- 足す・付ける・消す ----
    def add_work(self, path: str, meta: dict | None = None) -> dict:
        """描いた絵を作品として足す（絵はその場に置いたまま、場所だけ覚える）"""
        meta = meta or {}
        if not meta:
            from chatdraw.finishers import sidecar
            meta = sidecar(path)   # PNG に埋めた頼み。前の版の絵は隣の .json
        item = {"id": uuid.uuid4().hex[:12], "kind": "work", "path": str(path), "added": time.strftime("%Y-%m-%d %H:%M"),
                "text": meta.get("text", ""), "prompt": meta.get("prompt", ""), "style": meta.get("style_name", ""),
                "model": meta.get("model", ""), "seed": meta.get("seed"), "rating": NONE, "tags": [], "note": ""}
        self.items.insert(0, item)
        self.save()
        return item

    def add_doc(self, src: str, note: str = "", tags: list[str] | None = None) -> dict:
        """資料を足す。元のファイルが消えても困らないよう、ライブラリーの置き場に写しを取る"""
        docs = self.root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        dst = docs / f"{uuid.uuid4().hex[:8]}-{Path(src).name}"
        shutil.copy2(src, dst)
        item = {"id": uuid.uuid4().hex[:12], "kind": "doc", "path": str(dst), "added": time.strftime("%Y-%m-%d %H:%M"),
                "text": "", "prompt": "", "style": "", "model": "", "seed": None, "rating": LIKE,
                "tags": [t.strip().lower() for t in (tags or []) if t.strip()], "note": note}
        self.items.insert(0, item)
        self.save()
        return item

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def rate(self, item_id: str, rating: int):
        item = self.get(item_id)
        if item:
            item["rating"] = rating
            self.save()

    def set_tags(self, item_id: str, tags: list[str], note: str | None = None):
        item = self.get(item_id)
        if item:
            item["tags"] = [t.strip().lower() for t in tags if t.strip()]
            if note is not None:
                item["note"] = note
            self.save()

    def remove(self, item_id: str):
        """一覧から外す。作品の絵は消さない（描いた絵の置き場に残る）。資料はライブラリーが取った写しだけを消す"""
        item = self.get(item_id)
        if not item:
            return
        self.items.remove(item)
        if item["kind"] == "doc":
            Path(item["path"]).unlink(missing_ok=True)
        self.save()

    def take(self, paths: list[str]) -> list[dict]:
        """その絵の記録を一覧から外して返す（ごみ箱へ移すとき。戻すときに put_back で戻せるように記録ごと返す）"""
        want = {str(p) for p in paths}
        gone = [i for i in self.items if i["path"] in want]
        if gone:
            self.items = [i for i in self.items if i["path"] not in want]
            self.save()
        return gone

    def put_back(self, items: list[dict]):
        """ごみ箱から戻した記録を一覧に戻す。新しい順の並びを保つため、足した時刻で並べ直す"""
        have = {i["id"] for i in self.items}
        self.items.extend(i for i in items if i["id"] not in have)
        self.items.sort(key=lambda i: i.get("added", ""), reverse=True)
        self.save()

    def works(self) -> list[dict]:
        return [i for i in self.items if i["kind"] == "work"]

    def docs(self) -> list[dict]:
        return [i for i in self.items if i["kind"] == "doc"]

    # ---- 好み ----
    def profile(self, top: int = 8) -> dict:
        """好みの言葉・避ける言葉・よく選ぶ作風と模型。評価が少ないうちは空のまま（勝手に寄せない）"""
        like, dislike = Counter(), Counter()
        styles, models = Counter(), Counter()
        rated = 0
        for i in self.items:
            words = set(_tags(i.get("prompt", ""))) | set(i.get("tags", []))
            words -= COMMON
            if i["rating"] == LIKE:
                rated += 1
                like.update(words)
                if i.get("style") and i["style"] != "おまかせ":
                    styles[i["style"]] += 1
                if i.get("model"):
                    models[i["model"]] += 1
            elif i["rating"] == DISLIKE:
                rated += 1
                dislike.update(words)
        tags = [t for t, n in like.most_common() if n >= MIN_SEEN and n > dislike[t]][:top]
        avoid = [t for t, n in dislike.most_common() if n >= MIN_SEEN and like[t] == 0][:top]
        return {"tags": tags, "avoid": avoid, "style": styles.most_common(1)[0][0] if styles else "",
                "model": models.most_common(1)[0][0] if models else "", "rated": rated,
                "liked": sum(1 for i in self.items if i["rating"] == LIKE)}
