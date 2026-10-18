"""頼みごとで特に指定しない限り守る最低限の決まりを、描く直前の言葉に足す（腕は 2 本、獣耳の亜人に人の耳は無い、
頼んでいない帽子は描かない、持ち物は 1 つ、靴は左右そろう など）。画像生成の模型が間違えやすい所を、描く前に打ち消しで縛るのが目的。

決まりは styles/baseline.json に 1 か所だけ持つ。人物の絵に必ず掛ける決まり（person）と、言葉があるときに掛ける決まり（when）があり、
頼みごとが違うものを頼んだとき（六本腕、九尾、二刀流、帽子）は unless でその決まりを外す。頼んだことが決まりより先。
頼んだ言葉そのものは、どの打ち消しにも入れない（頼んだのに打ち消すと、模型は両方を弱めて中途半端に描く）。
各決まりの check は、描いたあとにその決まりが守られたかを見る検品（qc の問題の名前）。
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
    """足す描く言葉（add）、足す打ち消し（negative）、頼みごとで外した決まり（relaxed）、掛けた決まりの id（applied）、説明（notes）"""
    r = _rules()
    low = prompt.lower()
    asked = set(_words(prompt))
    given = set(_words(negative))
    person = any(_has(low, w) for w in r["person_words"]) or re.search(r"\d+(girl|boy|other)s?", low) is not None
    add, neg, notes, relaxed, applied = [], [], [], [], []
    for rule in r["rules"]:
        hit = next((w for w in rule["when"] if _has(low, w)), None)
        if not (hit or (rule["person"] and person)):
            continue
        why = next((w for w in rule["unless"] if _has(low, w)), None)
        if why:
            relaxed.append(rule["id"])
            notes.append(f"「{rule['topic']}」は {why} を頼んだので掛けない")
            continue
        applied.append(rule["id"])
        new = [w for w in rule["add"] if w not in asked and not _has(low, w) and w not in add]
        if new:
            add += new
            notes.append(f"{hit} から {', '.join(new)} を足した")
        neg += [w for w in rule["negative"] if w not in asked and not _has(low, w) and w not in given]
    neg = [w for w in dict.fromkeys(neg) if w not in add]
    # 外した決まりの打ち消しは、決まり文句（free_text.NEGATIVE）や他の決まりから入っても消す
    drop = {w for rule in r["rules"] if rule["id"] in relaxed for w in rule["negative"]}
    neg = [w for w in neg if w not in drop]
    return {"add": add, "negative": neg, "relaxed": sorted(drop), "applied": applied, "notes": notes}


def checks(applied: list[str]) -> dict:
    """掛けた決まりと、描いたあとにそれを確かめる検品（qc の問題の名前）"""
    by = {x["id"]: x for x in _rules()["rules"]}
    return {i: by[i]["check"] for i in applied if by.get(i, {}).get("check")}
