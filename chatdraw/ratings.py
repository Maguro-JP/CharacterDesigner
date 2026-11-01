"""模型の点とタグ。目録（catalog.json）の点とタグに、利用者が自分で付けた点とタグを重ねる。

目録の点は毎週の確かめ直しで書き換わるので、画面は毎回目録から読む（写しを持たない）。
利用者の点とタグ、お気に入り（★）と非表示はアプリのデータの置き場（model_prefs.json）に持ち、目録の更新で消えないようにする。
見せる点 = 利用者が付けた点があればそれ、無ければ目録の点。0 は「未確認」と書く。
"""
from __future__ import annotations

from pathlib import Path

UNRATED = "未確認"


def prefs_file() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "model_prefs.json"


def _load() -> dict:
    """読めないファイルは控え（.broken-<日時>）を残してから空として扱う。次の保存で印を失わないように"""
    from chatdraw.paths import read_json
    return read_json(prefs_file(), dict, {})


def _save(data: dict):
    from chatdraw.paths import write_json
    write_json(prefs_file(), data)


def user_rating(repo: str) -> int:
    try:
        return max(0, min(100, int(_load().get(repo, {}).get("rating", 0))))
    except (TypeError, ValueError):
        return 0


def set_user_rating(repo: str, value: int):
    """自分の点（0〜100）。0 にすると目録の点に戻す"""
    data = _load()
    entry = data.setdefault(repo, {})
    value = max(0, min(100, int(value)))
    if value:
        entry["rating"] = value
    else:
        entry.pop("rating", None)
    _save(data)
    changed()


def user_tags(repo: str) -> list[str]:
    tags = _load().get(repo, {}).get("tags", [])
    return [str(t) for t in tags] if isinstance(tags, list) else []


def set_user_tags(repo: str, tags: list[str]):
    data = _load()
    clean = []
    for t in tags:
        t = t.strip()
        if t and t not in clean:
            clean.append(t)
    data.setdefault(repo, {})["tags"] = clean
    _save(data)
    changed()


def rating(m) -> int:
    """見せる点。自分の点があればそれ、無ければ目録の点"""
    return user_rating(m.repo) or max(0, int(getattr(m, "score", 0)))


def rating_text(m) -> str:
    r = rating(m)
    return f"{r} 点" if r else UNRATED


def tags(m) -> list[str]:
    """目録のタグと自分のタグ（重ねずに）"""
    out = list(getattr(m, "tags", ()))
    out += [t for t in user_tags(m.repo) if t not in out]
    return out


def all_tags(models) -> list[str]:
    seen: list[str] = []
    for m in models:
        for t in tags(m):
            if t not in seen:
                seen.append(t)
    return seen


def has_tags(m, wanted) -> bool:
    """選んだタグを全部持つか（何も選んでいなければ全部通す）"""
    mine = set(tags(m))
    return all(t in mine for t in wanted)


def sort_key(m):
    """★ が先、次に点の高い順、同じ点なら確かめ済みが先、あとは名前"""
    return (0 if is_favorite(m.repo) else 1, -rating(m), 0 if getattr(m, "score", 0) > 0 else 1, m.name.lower())


# ---- お気に入り（★）と非表示。点と同じ model_prefs.json に持つ ----
LOW = 40   # これより低い点の模型は推奨に出さない（「すべて」には出す）


def _flag(repo: str, key: str) -> bool:
    return bool(_load().get(repo, {}).get(key, False))


def _set_flag(repo: str, key: str, on: bool):
    data = _load()
    entry = data.setdefault(repo, {})
    if on:
        entry[key] = True
    else:
        entry.pop(key, None)
    _save(data)
    changed()


def is_favorite(repo: str) -> bool:
    return _flag(repo, "favorite")


def set_favorite(repo: str, on: bool):
    _set_flag(repo, "favorite", on)


def is_hidden(repo: str) -> bool:
    """一覧と推奨に出さないか。ブロックした物も隠す（ブロックは非表示を含む）"""
    return _flag(repo, "hidden") or _flag(repo, "blocked")


def set_hidden(repo: str, on: bool):
    _set_flag(repo, "hidden", on)


def is_blocked(name: str) -> bool:
    """ブロックした模型か。ブロックした物は、おまかせ・推奨・AI のメニューのどこからも選ばれず、取りにも行かない"""
    return _flag(name, "blocked")


def set_blocked(name: str, on: bool):
    """解除すると、ブロックの前の非表示の印（hidden）だけが残る"""
    _set_flag(name, "blocked", on)


# ---- 模型の一覧が変わったことを知らせる（取った・消した・点・★・非表示）。AI のメニューと模型の表示を作り直すため ----
_LISTENERS: list = []


def on_change(fn):
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def changed():
    for fn in list(_LISTENERS):
        try:
            fn()
        except RuntimeError:   # 窓が先に閉じて Qt の部品が消えていたら、その知らせ先を外す
            _LISTENERS.remove(fn)
