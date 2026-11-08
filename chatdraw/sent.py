"""絵の模型に本当に渡した言葉の記録。

頼みの欄の目安は、描く仕組みが足す質の言葉、長さの切り詰め（CLIP の 77 語の枠）、打ち消しを含まないので、
模型が受け取った文と違った。模型を呼ぶ所ごとに、呼ぶ直前の文をここへ書き、欄のツールチップでそのまま見せる。
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_log: list[dict] = []
KEEP = 8


def record(where: str, prompt, negative=None, **extra) -> None:
    """模型を呼ぶ直前に呼ぶ。where は工程の名前（描く、直す、清書、手の直し、画風）"""
    e = {"where": where, "prompt": str(prompt or ""), "negative": str(negative or "")}
    e.update({k: str(v) for k, v in extra.items() if v})
    with _lock:
        _log.append(e)
        del _log[:-KEEP]


def last(n: int = KEEP) -> list[dict]:
    with _lock:
        return list(_log[-n:])


def clear() -> None:
    with _lock:
        _log.clear()


def tooltip_lines(n: int = 3) -> list[str]:
    """新しい順に、工程・渡した文・打ち消しの行"""
    out = []
    for e in reversed(last(n)):
        out.append(f"模型に渡した言葉（{e['where']}）: {e['prompt']}")
        if e.get("prompt_2"):
            out.append(f"  2 つ目の言葉の部品: {e['prompt_2']}")
        if e["negative"]:
            out.append(f"  打ち消し: {e['negative']}")
    return out
