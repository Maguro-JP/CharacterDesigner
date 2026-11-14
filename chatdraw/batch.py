"""一括生成: 頼みの一覧（1 行 1 つ、または CSV）を、枚数と種を付けて順に描く。

1 枚が失敗しても残りを描き続け、最後に描けた数と失敗した理由を返す（1 枚の失敗で全部が止まると、
夜に流した一覧が朝には 1 枚も無かった、になる）。止めるのは利用者が「止める」を押したときだけ。
描く処理そのもの（言葉の訳・検品・保存）は呼び手が渡す draw(text, seed) が持つ。ここは並べて回すだけ。
"""
from __future__ import annotations

import csv
import io

HEADERS = {"prompt": "text", "頼み": "text", "text": "text", "count": "count", "枚数": "count",
           "seed": "seed", "種": "seed", "negative": "negative", "禁止ワード": "negative"}
MAX_COUNT = 100   # 1 行の枚数の上限（打ち間違いで 10000 枚にしないため）


class BadLine(ValueError):
    """読めない行。理由は利用者に見せる日本語で持つ"""


def _int(v, what: str, line: int) -> int:
    try:
        return int(str(v).strip())
    except ValueError:
        raise BadLine(f"{line} 行目: {what}「{v}」は数ではありません") from None


def parse(text: str, count: int = 1, seed: int = 0, as_csv: bool | None = None) -> tuple[list[dict], list[tuple[int, str, str]]]:
    """頼みの一覧を読む。返すのは (描く物の並び, 読めなかった行 [(行, 中身, 理由)])。
    1 行目が見出し（頼み・枚数・種・禁止ワード、または prompt・count・seed・negative）なら CSV として読む。
    見出しの無い行は、行全体を 1 つの頼みにする（英語のタグの頼みは読点で区切るので、読点で列に分けない）。
    # で始まる行と空の行は飛ばす"""
    rows = [r for r in text.splitlines()]
    first = next((r for r in rows if r.strip() and not r.lstrip().startswith("#")), "")
    head = [h.strip().lower() for h in next(csv.reader([first]))] if first else []
    if as_csv is None:
        as_csv = bool(head) and all(h in HEADERS for h in head) and "text" in {HEADERS[h] for h in head}
    jobs, bad = [], []
    if as_csv:
        reader = csv.reader(io.StringIO(text))
        cols = None
        for n, rec in enumerate(reader, 1):
            if not rec or not "".join(rec).strip() or rec[0].lstrip().startswith("#"):
                continue
            if cols is None:
                cols = [HEADERS.get(h.strip().lower(), "") for h in rec]
                if "text" not in cols:   # 見出しの無い CSV: 頼み, 枚数, 種 の順
                    cols = ["text", "count", "seed", "negative"][:len(rec)]
                else:
                    continue
            d = {c: v.strip() for c, v in zip(cols, rec) if c}
            try:
                if not d.get("text"):
                    raise BadLine(f"{n} 行目: 頼みが空です")
                c = _int(d["count"], "枚数", n) if d.get("count") else count
                if not 1 <= c <= MAX_COUNT:
                    raise BadLine(f"{n} 行目: 枚数は 1〜{MAX_COUNT} にしてください")
                jobs.append({"line": n, "text": d["text"], "count": c,
                             "seed": _int(d["seed"], "種", n) if d.get("seed") else seed + n,
                             "negative": d.get("negative", "")})
            except BadLine as e:
                bad.append((n, ",".join(rec), str(e)))
        return jobs, bad
    for n, r in enumerate(rows, 1):
        r = r.strip()
        if r and not r.startswith("#"):
            jobs.append({"line": n, "text": r, "count": count, "seed": seed + n, "negative": ""})
    return jobs, bad


def total(jobs: list[dict]) -> int:
    return sum(j["count"] for j in jobs)


def run(jobs: list[dict], draw, say=lambda m: None, stopped=lambda: False, done=lambda path, job: None) -> dict:
    """順に描く。draw(text, seed, negative) は描いた絵の置き場を返す。done は 1 枚描けるたびに呼ぶ（ライブラリーに入れる）。
    返すのは {"done": [置き場], "failed": [(行, 頼み, 理由)], "stopped": 止めたか, "total": 描く予定の枚数}"""
    from chatdraw.engine import Stopped
    n, k = total(jobs), 0
    out = {"done": [], "failed": [], "stopped": False, "total": n}
    for j in jobs:
        for i in range(j["count"]):
            if stopped():
                out["stopped"] = True
                return out
            k += 1
            say(f"一括生成 {k}/{n}: {j['text'][:40]}")
            try:
                path = draw(j["text"], j["seed"] + i, j.get("negative", ""))
            except Stopped:
                out["stopped"] = True
                return out
            except Exception as e:   # noqa: BLE001  1 枚の失敗で残りを止めない。理由は最後にまとめて出す
                from chatdraw.engine import explain
                out["failed"].append((j["line"], j["text"], explain(e)))
                continue
            out["done"].append(str(path))
            done(str(path), j)
    return out


def summary(res: dict) -> str:
    head = f"{len(res['done'])} / {res['total']} 枚を描きました"
    if res.get("stopped"):
        head += "（途中で止めました）"
    lines = [head] + [f"{line} 行目「{text[:30]}」: {why}" for line, text, why in res["failed"]]
    return "\n".join(lines)
