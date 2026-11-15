"""修正依頼の一覧（chatdraw/fixrequests.json と、利用者が足した物）。

AI の絵の崩れは人が指示して直すので、よく出る崩れの直しの指示を名前・絵の模型に渡す言葉・直しの強さの組で用意しておく。
名前は赤ペンの印の指示の欄にそのまま書く。直すときは lookup で名前から言葉と強さを引く（日本語を模型にそのまま渡さない）。
利用者が足した指示は data_home の fixrequests.user.json に持つ（git に入れない、更新で消えない）。
"""
from __future__ import annotations

import json
from pathlib import Path

BUILTIN = Path(__file__).with_name("fixrequests.json")
USER_PART = "自分の指示"


def user_file() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "fixrequests.user.json"


def _read(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("requests", []) if isinstance(data, dict) else data
    return [r for r in items if isinstance(r, dict) and str(r.get("name", "")).strip()]


def builtin() -> list[dict]:
    return _read(BUILTIN)


def user() -> list[dict]:
    return [dict(r, part=USER_PART) for r in _read(user_file())]


def all_requests() -> list[dict]:
    return builtin() + user()


def parts() -> list[str]:
    """部位の並び（一覧の順）。足した物があれば最後に「自分の指示」"""
    try:
        order = json.loads(BUILTIN.read_text(encoding="utf-8")).get("parts", [])
    except (OSError, ValueError):
        order = []
    for r in builtin():
        if r["part"] not in order:
            order.append(r["part"])
    return order + ([USER_PART] if user() else [])


def by_part() -> dict[str, list[dict]]:
    out = {p: [] for p in parts()}
    for r in all_requests():
        out.setdefault(r["part"], []).append(r)
    return out


def lookup(note: str) -> dict | None:
    """指示の欄の文が修正依頼の名前と同じなら、その依頼を返す（利用者が足した物を先に見る）"""
    note = (note or "").strip()
    if not note:
        return None
    for r in user() + builtin():
        if r["name"].strip() == note:
            return r
    return None


def add_user(name: str, prompt: str = "", strength: float | None = None) -> dict | None:
    """自分の指示を一覧に足す。同じ名前があれば言葉と強さを書き換える。足した依頼を返す（名前が空なら None）"""
    name = (name or "").strip()
    if not name:
        return None
    items = _read(user_file())
    item = {"name": name}
    if prompt.strip():
        item["prompt"] = prompt.strip()
    if strength is not None:
        item["strength"] = max(0.05, min(1.0, float(strength)))
    items = [r for r in items if r["name"] != name] + [item]
    path = user_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requests": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(item, part=USER_PART)


def remove_user(name: str) -> bool:
    items = _read(user_file())
    keep = [r for r in items if r["name"] != name]
    if len(keep) == len(items):
        return False
    user_file().write_text(json.dumps({"requests": keep}, ensure_ascii=False, indent=1), encoding="utf-8")
    return True
