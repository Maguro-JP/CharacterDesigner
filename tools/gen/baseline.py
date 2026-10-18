"""頼みごとに書かれていなくても守る最低限（腕は 2 本、獣耳の亜人に人の耳は無い など）を、描く直前の言葉に足す。

決まりは styles/baseline.json に 1 か所だけ持つ。足すのは打ち消しが中心で、描く言葉は種族から当然に付く部位だけ足す
（猫娘なら cat ears, cat tail）。頼みごとが違う体を頼んだとき（多腕、九尾、ケンタウロス）は、その打ち消しを外す。
頼んだ言葉そのものは、どの打ち消しにも入れない（頼んだのに打ち消すと、模型は両方を弱めて中途半端に描く）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RULES = Path(__file__).resolve().parents[2] / "styles" / "baseline.json"


def _rules() -> dict:
    return json.loads(RULES.read_text(encoding="utf-8"))


def _words(text: str) -> list[str]:
    return [w.strip().lower() for w in text.split(",") if w.strip()]


def _has(text: str, word: str) -> bool:
    # 語の境で探す（elf を self に、devil を daredevil に見つけない）
    return re.search(r"(?<![a-z])" + re.escape(word.lower()) + r"(?![a-z])", text) is not None


def complete(prompt: str, negative: str = "") -> dict:
    """足す描く言葉（add）、足す打ち消し（negative）、外した打ち消し（relaxed）、何を足したかの説明（notes）"""
    r = _rules()
    low = prompt.lower()
    asked = set(_words(prompt))
    add, neg, notes = [], [], []
    for rule in r["implied"]:
        hit = next((w for w in rule["when"] if _has(low, w)), None)
        if not hit:
            continue
        new = [w for w in _words(rule.get("add", "")) if w not in asked and not _has(low, w)]
        if new:
            add += new
            notes.append(f"{hit} から {', '.join(new)} を足した")
        neg += _words(rule.get("negative", ""))
    person = any(_has(low, w) for w in r["person_words"]) or re.search(r"\d+(girl|boy|other)s?", low)
    if person:
        neg += r["humanoid_negative"]
    if _has(low, "solo"):
        neg += _words(r["solo_negative"])
    relaxed = []
    out = []
    for w in dict.fromkeys(neg):
        if w in asked or _has(low, w) or any(_has(low, k) for k in r["relaxed_by"].get(w, [])):
            relaxed.append(w)
            continue
        if w in _words(negative):
            continue
        out.append(w)
    # 種族の部位（足した言葉）と打ち消しが食い違わないようにする（centaur の four legs と extra legs など）
    out = [w for w in out if w not in add]
    if relaxed:
        notes.append(f"頼みごとに合わせて打ち消しから外した: {', '.join(relaxed)}")
    return {"add": add, "negative": out, "relaxed": relaxed, "notes": notes}
