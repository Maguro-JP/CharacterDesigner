"""裏の糸が今なにを待っているかの札。進みの知らせを出せない所（部品の取得、メモリの空き待ち、工程の確かめの窓）が札を立て、
描く糸の見張り（app.Job の心拍）が、知らせの途切れた間にこの札を進み具合の欄へ出す。
前は、こうした所が知らせを出さずに数十秒〜数分待ち、利用者には「ずっと止まっている」としか見えなかった"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()
_notes: list[tuple[str, float]] = []   # 入れ子に立てられるので積む。一番上が今の待ち


def current() -> tuple[str, float] | None:
    """(待っている物, 待ち始めた時刻)。札が無ければ None"""
    with _lock:
        return _notes[-1] if _notes else None


@contextmanager
def waiting(what: str):
    item = (what, time.monotonic())
    with _lock:
        _notes.append(item)
    try:
        yield
    finally:
        with _lock:
            if item in _notes:
                _notes.remove(item)
