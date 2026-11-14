"""描き続けるほど頼みが通りやすくなる仕組み。描いた絵ごとの記録から、タグごと・模型ごとの通りやすさを学び、言葉の直しと既定の設定に戻す。

記録は 1 枚 1 行（data_home()/draw_log.jsonl）: 頼みのタグ、模型、検品の外れ（崩れの数と、描かれなかった頼み）、通ったか、利用者の判定。
学んだ物の使い道は 2 つだけにする。
- 描かれにくいタグを、描く言葉の前に出す（engine.emphasize と同じ並べ替え）。足しも消しもしない
- 通りにくい模型の「頼みの効き」（guidance）を少し上げる

偏らないための決まり（好みで選ばれた物だけが強まり、頼みの語が落ちるのを避ける）:
- 学びの重みに上限を付ける（MAX_WEIGHT、前に出すのは MAX_MOVE 個まで、guidance は MAX_NUDGE まで）
- 少ない回数のタグは弱く数える（PRIOR 回分の「外れていない」を前に置いてから割る）
- 一定の割合（EXPLORE）で、学びを使わない描き方も試す。その回の記録は explored として残す
- 頼みに無い語を学びから足さない。並べ替えるだけなので、頼みの語は 1 つも落ちない
- 利用者の判定（良い・悪い・直した）は検品より弱く数え（VERDICT_WEIGHT）、「良い」はどのタグも強めない
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

PRIOR = 8.0            # 少ない回数を弱く数える。8 回分の「外れていない」を前に置く
MAX_WEIGHT = 0.5       # 外れやすさ（0〜1）の上限。これを超えて強めない
MIN_WEIGHT = 0.15      # これより弱いタグは前に出さない
MAX_MOVE = 3           # 1 回に前へ出すタグの数の上限
MAX_NUDGE = 1.0        # guidance を上げる幅の上限
EXPLORE = 0.2          # 学びを使わずに描く割合
VERDICT_WEIGHT = 0.5   # 利用者の判定の重み（検品 1 回を 1 とする）


def log_file() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "draw_log.jsonl"


def _tags(prompt: str) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in prompt.split(",") if t.strip()))


def record(path: str, prompt: str, model: str, flaws: int, missing: list[str], passed: bool, explored: bool = False,
           style: str = "", size=None):
    """描いた 1 枚を記録に足す。prompt は頼みのタグ（足した背景や作風は入れない）。style（画風のタグ）と size（幅, 高さ）は
    利用者の統計（chatdraw/userstats.py）に使う。描く言葉には戻さない"""
    row = {"path": str(path), "time": time.strftime("%Y-%m-%d %H:%M"), "tags": _tags(prompt), "model": model or "",
           "flaws": int(flaws), "missing": [m for m in missing if m], "passed": bool(passed), "explored": bool(explored), "verdict": "",
           "style": style or "", "size": list(size) if size else []}
    f = log_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")


def rows() -> list[dict]:
    try:
        lines = log_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue   # 書きかけの行は飛ばす
        if isinstance(r, dict):
            out.append(r)
    return out


VERDICTS = {"good": "良い", "bad": "悪い", "fixed": "直した"}


def set_verdict(path: str, verdict: str) -> bool:
    """利用者の判定（good・bad・fixed、空で消す）を、その絵の記録に付ける。記録の無い絵は False"""
    if verdict and verdict not in VERDICTS:
        raise ValueError(verdict)
    all_rows = rows()
    hit = False
    for r in all_rows:
        if r.get("path") == str(path):
            r["verdict"] = verdict
            hit = True
    if hit:
        # 別名に書いてから替える（書きかけで記録を失わない）
        f = log_file()
        part = f.with_name(f.name + ".part")
        part.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows), encoding="utf-8")
        part.replace(f)
    return hit


def verdict_of(path: str) -> str:
    return next((r.get("verdict", "") for r in reversed(rows()) if r.get("path") == str(path)), "")


def stats() -> dict:
    """タグごと・模型ごとの数。miss はタグが描かれなかった重み、fail は通らなかった重み、n は数えた重み"""
    tags: dict[str, dict] = {}
    models: dict[str, dict] = {}
    for r in rows():
        missing = {m.lower() for m in r.get("missing", [])}
        v = r.get("verdict", "")
        for t in r.get("tags", []):
            s = tags.setdefault(t, {"n": 0.0, "miss": 0.0})
            s["n"] += 1
            s["miss"] += 1 if t.lower() in missing else 0
        m = models.setdefault(r.get("model", ""), {"n": 0.0, "fail": 0.0})
        m["n"] += 1
        m["fail"] += 0 if r.get("passed") else 1
        if v in ("bad", "fixed"):   # 利用者が崩れを見つけた絵は、検品を通っていても通りにくさに数える（弱く）
            m["n"] += VERDICT_WEIGHT
            m["fail"] += VERDICT_WEIGHT
        elif v == "good":           # 「良い」は通りやすさにだけ弱く数え、タグは強めない（好みに引っ張られない）
            m["n"] += VERDICT_WEIGHT
    return {"tags": tags, "models": models}


def weight(tag: str, st: dict | None = None) -> float:
    """タグの描かれにくさ（0〜MAX_WEIGHT）。少ない回数は PRIOR で弱める"""
    s = (st or stats())["tags"].get(tag)
    if not s:
        return 0.0
    return min(MAX_WEIGHT, s["miss"] / (s["n"] + PRIOR))


def model_fail(model: str, st: dict | None = None) -> float:
    s = (st or stats())["models"].get(model or "")
    if not s:
        return 0.0
    return min(1.0, s["fail"] / (s["n"] + PRIOR))


def adjust(prompt: str, model: str = "", rng: random.Random | None = None) -> tuple[str, list[str], bool]:
    """頼みのタグを、学んだ描かれにくさで並べ替える。(直した言葉, 前に出したタグ, 学びを使わなかったか) を返す。
    頼みに無いタグは足さず、頼みのタグは消さない（並べ替えるだけ）"""
    from chatdraw.engine import emphasize
    if (rng or random).random() < EXPLORE:
        return prompt, [], True
    st = stats()
    scored = sorted(((weight(t, st), t) for t in _tags(prompt)), reverse=True)
    move = [t for w, t in scored if w >= MIN_WEIGHT][:MAX_MOVE]
    return (emphasize(prompt, move) if move else prompt), move, False


def guidance(model: str, base: float) -> float:
    """通りにくい模型ほど頼みの効きを少し上げる（MAX_NUDGE まで）"""
    return round(base + MAX_NUDGE * model_fail(model), 2)


def summary() -> str:
    """設定 → 学びの様子に出す短い説明"""
    st = stats()
    n = len(rows())
    hard = sorted(((weight(t, st), t) for t in st["tags"]), reverse=True)[:5]
    hard = [f"{t}（{w:.2f}）" for w, t in hard if w >= MIN_WEIGHT]
    return f"記録 {n} 枚。描かれにくいタグ: " + ("、".join(hard) if hard else "まだありません")
