"""落ちたときの記録。描いている途中に落ちても、何が起きたかが後から分かるようにする。

- faulthandler で、Python の外（Qt・torch の中）で落ちたときも、その時の各糸の呼び出しの並びを crash.log に残す
- 画面の糸と裏の糸で捕まえられなかった例外も、crash.log に残す（裏の糸の例外でアプリごと終わらないようにする）
- 次に起動したとき、前の回に書かれた記録があれば知らせる
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import time
import traceback
from pathlib import Path

_FILE = None


def path() -> Path:
    from chatdraw.paths import HOME
    return Path(HOME) / "crash.log"


def _write(text: str):
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n{text}\n")
    except OSError:
        pass


def install():
    """起動の初めに 1 回呼ぶ。記録の場所に書けないときは、何もせずに起動を続ける"""
    global _FILE
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        _FILE = open(p, "a", encoding="utf-8")   # faulthandler は開いたままのファイルに書く
        _FILE.write(f"\n==== 起動 {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
        _FILE.flush()
        faulthandler.enable(_FILE, all_threads=True)
    except OSError:
        _FILE = None

    def hook(kind, value, tb):
        _write("".join(traceback.format_exception(kind, value, tb)))
        sys.__excepthook__(kind, value, tb)

    def thread_hook(args):
        _write(f"裏の糸 {getattr(args.thread, 'name', '')}\n" +
               "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = hook
    threading.excepthook = thread_hook


def last_crash(since_size: int) -> str:
    """since_size より後ろに書かれた記録のうち、落ちた形跡（Fatal Python error / Traceback）があればその部分を返す"""
    try:
        data = path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = data[since_size:]
    return tail if ("Fatal Python error" in tail or "Traceback" in tail) else ""
