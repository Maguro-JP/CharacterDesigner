"""利用者のフィルター: 描きたくないものを、利用者が自分で決めて止める。

既定ではどれも切ってある（最初から規制はしない）。使う人が config/filters.json で入れたものだけが働く。
1つのフィルターは「名前・入れるか・止める言葉・打ち消しに足す言葉」。言葉はどの言語で書いてもよく、1つの一覧に並べる。
止める言葉が頼みごとか描く言葉に出たら、描かずに理由を返す。打ち消しの言葉は、入れている間いつも足す。

設定ファイルが無いときは、下の PRESETS（全部切った状態）を使う。書き方の見本は config/filters.example.json。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "filters.json"

# 用意しておく型。どれも切ってある。入れるかは利用者が決める
PRESETS = [
    {"name": "グロテスク", "enabled": False,
     "words": ["グロ", "流血", "内臓", "切断", "死体", "腐敗", "gore", "guro", "blood", "bloody", "dismemberment", "decapitation", "corpse", "intestines", "severed"],
     "negative": "gore, blood, injury, wound"},
    {"name": "性的な表現", "enabled": False,
     "words": ["裸", "ヌード", "エロ", "性的", "下着", "R18", "R-18", "nsfw", "nude", "naked", "nipples", "explicit", "lingerie", "underwear", "erotic", "hentai"],
     "negative": "nsfw, nude, explicit"},
    {"name": "暴力", "enabled": False,
     "words": ["暴力", "殴る", "拷問", "violence", "torture", "beating"],
     "negative": "violence"},
    {"name": "ホラー", "enabled": False,
     "words": ["ホラー", "恐怖", "怨霊", "horror", "creepy", "scary"],
     "negative": "horror"},
]


def load(path: Path | None = None) -> list[dict]:
    """利用者のフィルターを読む。壊れた設定でも描く処理は止めず、既定（全部切った状態）に戻す"""
    p = path or CONFIG
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("filters", []) if isinstance(data, dict) else []
        return [f for f in items if isinstance(f, dict) and f.get("name")]
    except (OSError, ValueError):
        return [dict(f) for f in PRESETS]


def active(path: Path | None = None) -> list[dict]:
    return [f for f in load(path) if f.get("enabled")]


def _hit(f: dict, text: str) -> str | None:
    low = text.lower()
    tokens = set(re.findall(r"[a-z0-9\-]+", low))
    # 古い書き方（ja / en に分けた一覧）も読む
    for w in list(f.get("words", [])) + list(f.get("ja", [])) + list(f.get("en", [])):
        w = str(w).strip().lower()
        if not w:
            continue
        # 英数字だけの1語は語の単位で比べる（braid の中の bra を拾わない）。それ以外（空白を含む語、英数字以外の文字）は文字列で探す
        if re.fullmatch(r"[a-z0-9\-]+", w):
            if w in tokens:
                return w
        elif w in low:
            return w
    return None


def check(text: str, path: Path | None = None) -> str | None:
    """入れているフィルターに当たれば、止める理由。当たらなければ None"""
    for f in active(path):
        w = _hit(f, text)
        if w:
            return f"利用者のフィルター「{f['name']}」で止めた（{w}）。config/filters.json で切れる"
    return None


def negative(path: Path | None = None) -> str:
    """入れているフィルターの打ち消しの言葉をまとめる"""
    return ", ".join(f["negative"] for f in active(path) if f.get("negative"))
