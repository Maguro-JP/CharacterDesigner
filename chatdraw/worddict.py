"""単語辞書と、単語のお気に入り。利用者ごとのデータの置き場（data_home()/words.json）に持ち、リポジトリには入れない。

辞書の 1 行はタグ（絵の模型に渡す英語）ごと: 頼みの語、訳（画面の言語ごと、利用者が直した物）、使えた回数、通った回数、最後に使った日。
通った回数は、検品を通った絵の頼みに入っていた回数。使えた回数は、そのタグで描いた回数。
読めなかった語に利用者が付けたタグ（と、言葉の模型が 1 語ずつ訳したタグ）も terms に持ち、次からは頼みの読み取り（jaterms）が表より先に引く。
"""
from __future__ import annotations

import time
from pathlib import Path


def dict_file() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "words.json"


_cache: dict = {"mtime": None, "path": None, "data": None}


def _load() -> dict:
    """読めないファイルは控えを残して空として扱う（read_json）。同じファイルは更新の時刻が変わるまで読み直さない"""
    from chatdraw.paths import read_json
    path = dict_file()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = None
    if _cache["path"] == path and _cache["mtime"] == mtime and _cache["data"] is not None:
        return _cache["data"]
    data = read_json(path, dict, {})
    for key, kind in (("words", dict), ("favorites", list), ("terms", dict)):
        if not isinstance(data.get(key), kind):
            data[key] = kind()
    _cache.update(path=path, mtime=mtime, data=data)
    return data


def _save(data: dict):
    from chatdraw.paths import write_json
    write_json(dict_file(), data)
    _cache["data"] = None


def _today() -> str:
    return time.strftime("%Y-%m-%d")


# ---- 訳 ----
def _reverse() -> dict[str, str]:
    """表（jaterms）を逆に引く: タグ → 日本語の語。同じタグに語が何個もあるときは短い語（見出しの語）を取る"""
    from chatdraw import jaterms
    out: dict[str, str] = {}
    pairs = list(jaterms.TERMS.items())
    pairs += [(f"{cj}{'い' if cj in ('赤', '青', '黒', '白') else 'の'}{wj}", f"{ce} {we}")
              for cj, ce in jaterms.COLORS.items() for wj, we in jaterms._COLOR_WORDS.items()]
    for ja, tags in pairs:
        for tag in (t for t in tags.split(", ") if t):
            # 語幹（笑、乗）より見出しの語（笑顔、乗る）を取る。2 字以上の短い語を先にする
            if tag not in out or (len(ja) < 2, len(ja)) < (len(out[tag]) < 2, len(out[tag])):
                out[tag] = ja
    return out


_REV: dict[str, str] | None = None


def translation(tag: str, lang: str | None = None) -> str:
    """タグの訳を画面の言語で返す。利用者が直した訳 > 頼みの語 > 表の逆引き の順。英語の画面ではタグそのもの"""
    global _REV
    from chatdraw import i18n
    lang = lang or i18n.current()
    entry = _load()["words"].get(tag, {})
    own = (entry.get("tr") or {}).get(lang)
    if own:
        return str(own)
    if lang == "English":
        return tag
    if entry.get("ja"):
        return str(entry["ja"])
    if _REV is None:
        _REV = _reverse()
    return _REV.get(tag, "")


def set_translation(tag: str, text: str, lang: str | None = None):
    """訳を直す。空にすると直した訳を消し、元の訳（頼みの語・表）に戻す"""
    from chatdraw import i18n
    lang = lang or i18n.current()
    data = _load()
    entry = data["words"].setdefault(tag, {"ja": "", "tr": {}, "used": 0, "passed": 0, "last": ""})
    tr = entry.setdefault("tr", {})
    if text.strip():
        tr[lang] = text.strip()
    else:
        tr.pop(lang, None)
    _save(data)


# ---- 辞書 ----
def record(tags: list[str], passed: bool, words: dict[str, str] | None = None):
    """描いた 1 枚の頼みのタグを辞書に足す。words は タグ → 頼みの語（jaterms.align の対応）"""
    words = words or {}
    data = _load()
    today = _today()
    for tag in dict.fromkeys(t.strip() for t in tags if t and t.strip()):
        entry = data["words"].setdefault(tag, {"ja": "", "tr": {}, "used": 0, "passed": 0, "last": ""})
        entry["used"] = int(entry.get("used", 0)) + 1
        entry["passed"] = int(entry.get("passed", 0)) + (1 if passed else 0)
        entry["last"] = today
        if words.get(tag) and not entry.get("ja"):
            entry["ja"] = words[tag]
    _save(data)


def entries(only_passed: bool = True) -> list[dict]:
    """辞書の行。使えた語（通った回数が 1 以上）を、通った回数・最後に使った日の順に並べる"""
    rows = []
    for tag, e in _load()["words"].items():
        if only_passed and int(e.get("passed", 0)) < 1:
            continue
        rows.append({"tag": tag, "ja": e.get("ja", ""), "tr": translation(tag), "used": int(e.get("used", 0)),
                     "passed": int(e.get("passed", 0)), "last": e.get("last", "")})
    rows.sort(key=lambda r: r["tag"])
    rows.sort(key=lambda r: r["last"], reverse=True)
    rows.sort(key=lambda r: r["passed"], reverse=True)
    return rows


def forget(tag: str):
    data = _load()
    data["words"].pop(tag, None)
    _save(data)


# ---- 単語のお気に入り ----
def favorites() -> list[str]:
    return [str(t) for t in _load()["favorites"]]


def add_favorite(tag: str) -> bool:
    tag = tag.strip()
    data = _load()
    if not tag or tag in data["favorites"]:
        return False
    data["favorites"].append(tag)
    _save(data)
    return True


def remove_favorite(tag: str):
    data = _load()
    data["favorites"] = [t for t in data["favorites"] if t != tag]
    _save(data)


def is_favorite(tag: str) -> bool:
    return tag.strip() in _load()["favorites"]


# ---- 利用者の読み（読めなかった語に付けたタグ） ----
def terms() -> dict[str, str]:
    return {str(k): str(v) for k, v in _load()["terms"].items() if k}


def set_term(word: str, tags: str, source: str = "user"):
    """読めなかった語にタグを付ける。空のタグは「描く物を変えない語」として覚える（次から読めなかった語に出さない）。
    言葉の模型が訳した語（source=llm）は、利用者が直した語を上書きしない"""
    word = word.strip()
    if not word:
        return
    data = _load()
    src = data.setdefault("term_source", {})
    if source != "user" and src.get(word) == "user":
        return
    from chatdraw.engine import english_only
    data["terms"][word] = english_only(tags.strip())   # 日本語のタグは絵の模型に渡さない
    src[word] = source
    _save(data)


def remove_term(word: str):
    data = _load()
    data["terms"].pop(word, None)
    data.get("term_source", {}).pop(word, None)
    _save(data)
