"""利用者のフィルター: 描きたくないものを、利用者が自分で決めて止める。

既定ではどれも切ってある（最初から規制はしない）。使う人が config/filters.json で入れたものだけが働く。
1つのフィルターは「名前・入れるか・止める言葉・打ち消しに足す言葉」。言葉はどの言語で書いてもよく、1つの一覧に並べる。
止める言葉が頼みごとか描く言葉に出たら、描かずに理由を返す。打ち消しの言葉は、入れている間いつも足す。

設定ファイルが無いときは、下の PRESETS（全部切った状態）を使う。書き方の見本は config/filters.example.json。

固定の制限（設定では外せない）は、子どもを性的に描くことだけ。docs/filters.md に利用者向けの説明がある。
宗教・文化の配慮（styles/cultural.json）は止めずに知らせる。知らずに描いて見る人を傷つけるのを防ぐのが目的で、
描くかは利用者が決める。止めたい人は「宗教・文化への配慮」のフィルターを入れる。
判定はこのファイルの1か所で行い、ほかの所（free_text など）は check() を呼ぶだけにする。
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
    # 言葉は styles/cultural.json の hate と caution の決まりから組む（cultural_words）。ここで一覧を二重に持たない
    {"name": "宗教・文化への配慮", "enabled": False, "cultural": True, "words": [], "negative": ""},
]
CULTURAL = ROOT / "styles" / "cultural.json"


# 固定の制限。子どもを性的に描くことだけを止める。子どもを表す語だけ、性的な語だけでは止めない
SEXUAL = ["裸", "ヌード", "全裸", "半裸", "エロ", "えっち", "エッチ", "性的", "性行為", "セックス", "下着", "ランジェリー",
          "乳首", "おっぱい", "R-18", "R18", "18禁", "成人向け", "アダルト", "水着", "セクシー",
          "nsfw", "nude", "naked", "nudity", "nipple", "nipples", "topless", "bottomless", "sex", "sexual", "explicit",
          "lingerie", "underwear", "panties", "bra", "sexy", "erotic", "porn", "hentai", "genitals", "cleavage",
          "areola", "uncensored", "r-18", "r18", "swimsuit", "bikini"]
MINOR = ["子ども", "子供", "こども", "幼女", "幼児", "児童", "小学生", "中学生", "未成年", "幼い", "少女", "少年", "女の子", "男の子",
         "child", "children", "kid", "kids", "toddler", "teen", "teenage", "underage", "minor", "schoolgirl", "schoolboy",
         "little girl", "little boy", "young girl", "young boy", "elementary school"]
# 語そのものが子どもの性的な描写を指すもの。いつでも止める
ALWAYS = ["ロリ", "ショタ", "loli", "lolicon", "shota", "shotacon"]
# 性的な語があるとき、打ち消しに足す（模型が幼い顔と体に寄せることがあるため）
SAFE_NEGATIVE = "loli, shota, child, underage"


def _hits(words, text: str) -> list[str]:
    return [w for w in words if _hit({"words": [w]}, text)]


def fixed(text: str) -> str | None:
    """固定の制限に当たれば理由。設定では外せない"""
    a = _hits(ALWAYS, text)
    if a:
        return f"「{a[0]}」は子どもを性的に描く言葉なので描かない（固定の制限。docs/filters.md）"
    sexual, minor = _hits(SEXUAL, text), _hits(MINOR, text)
    if sexual and minor:
        return f"子どもを表す言葉（{minor[0]}）と性的な言葉（{sexual[0]}）が並んでいるので描かない（固定の制限。docs/filters.md）"
    return None


def has_minor(text: str) -> bool:
    return bool(_hits(MINOR, text) or _hits(ALWAYS, text))


def has_sexual(text: str) -> bool:
    return bool(_hits(SEXUAL, text))


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


def _rules() -> list[dict]:
    try:
        return json.loads(CULTURAL.read_text(encoding="utf-8"))["rules"]
    except (OSError, ValueError, KeyError):
        return []


def cultural(text: str) -> list[dict]:
    """宗教・文化の上で見る人を傷つけやすい描写に当たれば、知らせる中身の一覧（止めはしない）。
    words が出たとき（with があれば、それも並んだとき）に当たる。triggers だけのときは、誤って描かれやすい場面として知らせる"""
    out = []
    for r in _rules():
        w = _hit({"words": r.get("words", [])}, text) if r.get("words") else None
        if w and r.get("with") and not _hit({"words": r["with"]}, text):
            w = None
        t = None if w else _hit({"words": r.get("triggers", [])}, text)
        if w or (t and not r.get("words")):
            out.append({"id": r["id"], "topic": r["topic"], "level": r["level"], "hit": w or t,
                        "why": r["why"], "instead": r["instead"]})
    return out


def cultural_negative(text: str) -> str:
    """場面の言葉（軍服、寺など）から、模型が頼まれずに描きやすい印を打ち消しに足す"""
    return ", ".join(r["negative"] for r in _rules() if r.get("negative")
                     and _hit({"words": r.get("triggers", []) + r.get("words", [])}, text))


def cultural_words(levels=("hate", "caution")) -> list[str]:
    return [w for r in _rules() if r["level"] in levels and not r.get("with") for w in r.get("words", [])]


def advice_lines(text: str) -> list[str]:
    """画面や記録にそのまま出せる1行ずつの知らせ"""
    mark = {"hate": "差別の象徴", "caution": "宗教・文化の配慮", "advise": "描き方の注意"}
    return [f"{mark[a['level']]}「{a['topic']}」（{a['hit']}）: {a['why']}。{a['instead']}" for a in cultural(text)]


def check(text: str, path: Path | None = None) -> str | None:
    """止める理由。先に固定の制限、次に利用者が入れているフィルター。当たらなければ None"""
    why = fixed(text)
    if why:
        return why
    for f in active(path):
        w = _hit(dict(f, words=list(f.get("words", [])) + cultural_words()) if f.get("cultural") else f, text)
        if not w and f.get("cultural"):
            # 組み合わせの決まり（宗教の装い＋性的な言葉など）も、入れている間は止める
            w = next((a["hit"] for a in cultural(text) if a["level"] in ("hate", "caution")), None)
        if w:
            return f"利用者のフィルター「{f['name']}」で止めた（{w}）。config/filters.json で切れる"
    return None


def negative(prompt: str = "", path: Path | None = None) -> str:
    """打ち消しに足す言葉。入れているフィルターの分と、性的な語があるときの子どもの言葉"""
    parts = [SAFE_NEGATIVE] if has_sexual(prompt) else []
    parts += [x for x in [cultural_negative(prompt)] if x]
    return ", ".join(parts + [f["negative"] for f in active(path) if f.get("negative")])
