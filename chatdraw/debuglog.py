"""利用者のためのデバッグモード。裏の処理の記録を画面の「記録」の欄とファイルに流し、アプリが自分で掛けている制限を項目ごとに外す。

何で落ちたか・何で描けなかったかが画面からは見えず、利用者が直し方を決められなかったので置いた。
既定はオフ。オフの間は記録も制限の外しも何もしない（描く速さを変えない）。
子どもを性的に描く頼みを止める決まり（engine.refused）は、ここでは外せない。外す項目に入れていない。
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

# 外せる制限（キー, 見出し, 説明）。設定の窓に 1 つずつ出す
LIFTS = (
    ("budget", "メモリの予算による止め", "見積もりがメモリの予算を超えても、描く前に止めない（描いている途中の見張りは残す）"),
    ("steps", "工程の上限", "設定の工程の数の上限（80）と、同じ崩れが続いたときの描き直しの止めを外す"),
    ("checker", "作画監督による落とし", "検品の崩れで描き直さず、1 回目の絵をそのまま渡す（崩れは記録に出す）"),
    ("words", "言葉の自動の付け足しと打ち消し", "質の言葉・背景・safe の札・打ち消し（崩れ・体・nsfw）を足さず、頼んだ言葉と禁止ワードだけを渡す"),
)
KEEP_DAYS = 7      # 記録のファイルを残す日数。古い物は起動のたびに消す
RING = 2000        # 画面の欄に残す行の数

_lock = threading.Lock()
_state = {"on": False, "lifts": set()}
_lines: list[str] = []
_listeners: list = []


def configure(on: bool, lifts=()) -> None:
    with _lock:
        _state["on"] = bool(on)
        _state["lifts"] = {k for k in lifts if k in {x[0] for x in LIFTS}} if on else set()
    if on:
        prune()


def on() -> bool:
    return _state["on"]


def lifted(key: str) -> bool:
    """デバッグモードで、その制限を外しているか"""
    return _state["on"] and key in _state["lifts"]


def folder() -> Path:
    from chatdraw.paths import HOME
    return Path(HOME) / "logs"


def file() -> Path:
    return folder() / f"chatdraw-{time.strftime('%Y%m%d')}.log"


def prune(days: int = KEEP_DAYS, now: float | None = None) -> int:
    """KEEP_DAYS より古い記録のファイルを消す。消した数"""
    now = time.time() if now is None else now
    n = 0
    try:
        for p in folder().glob("chatdraw-*.log"):
            if now - p.stat().st_mtime > days * 86400:
                p.unlink()
                n += 1
    except OSError:
        pass
    return n


def free_ram() -> str:
    try:
        from chatdraw import membudget
        return f"{membudget.budget().free_ram:.1f}GB"
    except Exception:   # noqa: BLE001  空きが読めなくても記録は書く
        return "?"


def log(kind: str, msg: str, mem: bool = False) -> None:
    """kind は工程・言葉・検品・例外など。オフなら何もしない"""
    if not _state["on"]:
        return
    line = f"{time.strftime('%H:%M:%S')} [{kind}] {msg}" + (f"（空きメモリ {free_ram()}）" if mem else "")
    with _lock:
        _lines.append(line)
        del _lines[:-RING]
        listeners = list(_listeners)
    try:
        folder().mkdir(parents=True, exist_ok=True)
        with open(file(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    for fn in listeners:
        try:
            fn(line)
        except Exception:   # noqa: BLE001  欄が閉じていても裏の処理は止めない
            pass


def exception(where: str, e: BaseException) -> str:
    """例外の全文とトレースバックを記録に書き、その文を返す（オフでも文は返す。窓で見せるため）"""
    text = "".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip()
    log("例外", f"{where}\n{text}", mem=True)
    return text


def lines() -> list[str]:
    with _lock:
        return list(_lines)


def listen(fn) -> None:
    with _lock:
        _listeners.append(fn)


def unlisten(fn) -> None:
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)
