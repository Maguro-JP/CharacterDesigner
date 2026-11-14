"""模型のお気に入り（役目ごとの模型）。構図・仕上げ・顔・手・背景・直しに、利用者が選んだ模型を使う。

おまかせ（おすすめ）は点と合い方で模型を選ぶので、利用者が使いたい模型が選ばれないことがあった。
お気に入りを置いた役目は、その模型を必ず使う（取っていない・ブロックした物は使わず、そのときだけおまかせの順に戻す）。
置き場はアプリのデータの置き場（model_roles.json）。目録の更新では消えない。

描き方の分け方:
- 絵の模型を 1 つだけ選んで短く頼んだときは、その模型で 1 回描くだけ（速い流れ）
- おまかせ・お気に入り・プリセット・細かい頼みのときは、役目ごとの模型で工程を分けて描く（精度の流れ、chatdraw/omakase.py）
どちらの流れでも、頼みに書かれていない言葉は模型に足さない。
"""
from __future__ import annotations

from pathlib import Path

FAV = "favorites"   # 設定の image_model がこれなら、役目ごとのお気に入りで描く

# 役目: (名前, ツールチップ)。並びは画面の並び
ROLES = {
    "compose": ("構図", "人物の形と配置を最初に描く模型"),
    "finish": ("仕上げ・全体", "構図を元に全体を描き上げる模型（2 段で描くときの仕上げ）"),
    "face": ("顔", "顔の描き込みと描き直しに使う模型"),
    "hand": ("手", "手・指の描き込みと描き直しに使う模型"),
    "background": ("背景", "背景のある頼みで構図を描く模型（構図のお気に入りが無いとき）"),
    "fix": ("直し・加工", "足・髪・体の直しと、赤ペンや加工の直しに使う模型"),
}
# 検品が返す部位（omakase の fix の鍵）と役目の対応。足・髪・体は「直し・加工」
KIND_ROLE = {"hand": "hand", "face": "face", "foot": "fix", "hair": "fix", "body": "fix"}

DETAILED_CHARS = 60   # これより長い頼み、または区切りが 4 つ以上の頼みを「細かい指示」とする（choose.choose_words と同じ目安）


def roles_file() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "model_roles.json"


DEFAULT_SET = "標準"


def _raw() -> dict:
    """置き場の中身。{"active": 名前, "sets": {名前: {役目: 模型}}}。前の形（役目の辞書 1 つ）は「標準」の編成として読む"""
    from chatdraw.paths import read_json
    data = read_json(roles_file(), dict, {})
    if "sets" not in data:
        data = {"active": DEFAULT_SET, "sets": {DEFAULT_SET: {k: v for k, v in data.items() if k in ROLES}}}
    sets = {str(n): {k: str(v) for k, v in (d or {}).items() if k in ROLES and v} for n, d in (data.get("sets") or {}).items()}
    if not sets:
        sets = {DEFAULT_SET: {}}
    active = data.get("active") if data.get("active") in sets else next(iter(sets))
    return {"active": active, "sets": sets}


def _write(data: dict):
    from chatdraw.paths import write_json
    write_json(roles_file(), data)


def load() -> dict:
    """今の編成の役目ごとの模型"""
    d = _raw()
    return dict(d["sets"][d["active"]])


def save(data: dict):
    """今の編成に書く"""
    d = _raw()
    d["sets"][d["active"]] = {k: v for k, v in data.items() if k in ROLES and v}
    _write(d)


# ---- 編成（役目ごとの模型の組）。構図・顔・背景などの組を名前を付けて持ち、切り替える ----
def sets() -> list[str]:
    return list(_raw()["sets"])


def active() -> str:
    return _raw()["active"]


def get_set(name: str) -> dict:
    return dict(_raw()["sets"].get(name, {}))


def save_set(name: str, data: dict, use: bool = True):
    """編成を作るか直す。use なら今の編成にする"""
    name = name.strip()
    if not name:
        raise ValueError("編成の名前が空です")
    d = _raw()
    d["sets"][name] = {k: v for k, v in data.items() if k in ROLES and v}
    if use:
        d["active"] = name
    _write(d)


def use_set(name: str):
    d = _raw()
    if name not in d["sets"]:
        raise KeyError(name)
    d["active"] = name
    _write(d)


def rename_set(old: str, new: str):
    new = new.strip()
    d = _raw()
    if old not in d["sets"]:
        raise KeyError(old)
    if not new or (new in d["sets"] and new != old):
        raise ValueError("その名前は使えません（空か、ほかの編成と同じ）")
    d["sets"] = {(new if n == old else n): v for n, v in d["sets"].items()}
    if d["active"] == old:
        d["active"] = new
    _write(d)


def delete_set(name: str):
    """編成を消す。最後の 1 つは消さずに空にする（お気に入りの置き場を無くさない）"""
    d = _raw()
    d["sets"].pop(name, None)
    if not d["sets"]:
        d["sets"] = {DEFAULT_SET: {}}
    if d["active"] not in d["sets"]:
        d["active"] = next(iter(d["sets"]))
    _write(d)


def get(role: str) -> str:
    return load().get(role, "")


def set_role(role: str, repo: str):
    """役目の模型を置く。空にするとお気に入りを外し、その役目はおまかせの順で選ぶ"""
    if role not in ROLES:
        raise KeyError(role)
    data = load()
    if repo:
        data[role] = repo
    else:
        data.pop(role, None)
    save(data)


def any_set() -> bool:
    return bool(load())


def resolve(role: str, have, data: dict | None = None):
    """役目のお気に入りの模型（手元にあり、ブロックしていない物）。無ければ None"""
    repo = (load() if data is None else data).get(role, "")
    if not repo:
        return None
    from chatdraw.ratings import is_blocked
    if is_blocked(repo):
        return None
    return next((m for m in have if m.repo == repo), None)


def detailed(text: str) -> bool:
    """細かい指示か。長い頼みか、区切り（、 ,）の多い頼み"""
    t = text or ""
    return len(t) > DETAILED_CHARS or t.count("、") + t.count(",") + t.count("，") >= 4


def precise(image_mode: str, text: str, preset: str = "") -> bool:
    """精度の流れで描くか。image_mode は "auto"（おまかせ）、FAV、"single"（模型を 1 つ選んだ）"""
    from chatdraw.aipanel import DEFAULT_PRESET
    if image_mode in ("auto", FAV):
        return True
    return bool(preset and preset != DEFAULT_PRESET) or detailed(text)


def apply(plan, have, data: dict | None = None, single=None):
    """おまかせの段取り（omakase.Plan）の役目ごとの模型を、お気に入り（single があればその模型だけ）に置き換える。
    置き換えた役目は先頭に置き、ほかの候補は後ろに残す（お気に入りが描けなかったときの戻り道）。
    返すのは置き換えた役目の名前の一覧"""
    data = load() if data is None else data
    used = []

    def first(cands, m, why):
        return [(m, why)] + [c for c in cands if c[0].repo != m.repo]

    if single is not None:
        plan.compose = [(single, "選んだ模型")]
        # 選んだ模型だけで描く。囲みの中を直せない世代なら、ほかの模型で直さず、直しの工程を飛ばす（選んだ模型を上書きしない）
        can_fix = any(c[0].repo == single.repo for cands in plan.fix.values() for c in cands)
        for kind in list(plan.fix):
            plan.fix[kind] = [(single, "選んだ模型")] if can_fix else []
        if not can_fix:
            plan.notes.append(f"{single.name} は囲みの中の直しができないので、直しの工程は飛ばします")
        return ["選んだ模型"]
    comp = resolve("compose", have, data)
    if comp is None and plan.parts.get("background"):
        comp = resolve("background", have, data)
        if comp is not None:
            used.append(ROLES["background"][0])
    elif comp is not None:
        used.append(ROLES["compose"][0])
    if comp is not None:
        plan.compose = first(plan.compose, comp, "お気に入り")
    for kind, role in KIND_ROLE.items():
        m = resolve(role, have, data)
        if m is None or kind not in plan.fix:
            continue
        from chatdraw.models import family as fam
        if not fam(m.family).inpaint:   # 囲みの中だけ直せない世代は直しに使えない（使うと囲みの外まで描き変わる）
            plan.notes.append(f"{ROLES[role][0]}のお気に入り {m.name} は囲みの中の直しができないので、直しはおまかせで選びます")
            continue
        plan.fix[kind] = first(plan.fix[kind], m, "お気に入り")
        if ROLES[role][0] not in used:
            used.append(ROLES[role][0])
    return used


def two_stage(have, data: dict | None = None):
    """お気に入りの構図と仕上げで 2 段に描けるなら (構図, 仕上げ)。片方だけ置いたときは、置かなかった方を手元から選ぶ"""
    from chatdraw import twostage
    data = load() if data is None else data
    comp, fin = resolve("compose", have, data), resolve("finish", have, data)
    if comp is None and fin is None:
        return None
    base = twostage.pick(have, fin.repo if fin is not None else "")
    if comp is not None and comp.family not in twostage.COMPOSERS:
        return None   # 文で頼めない世代は 2 段の構図に使えない。構図のお気に入りは 1 つの模型の構図で使う
    if fin is not None and fin.family != "sdxl":
        return None
    if base is None and (comp is None or fin is None):
        return None
    return (comp or base[0], fin or base[1])
