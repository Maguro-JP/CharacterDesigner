"""一時停止して、その時点の状態を残す。時間切れ・メモリ不足・見張りで処理を打ち切るとき、捨てずにここへ書き、
次は同じ所から続ける（進み具合の欄の「再開」、起動したときの「続きから」）。

前は打ち切ると、描いた途中の工程・一括生成の残り・取りかけの模型が全部消え、始めからやり直すしかなかった。
利用者が押す緊急停止はここを通さない（止めたい物を勝手に続けない）。

置き場は作業の自動保存（project.autosave_path）と同じフォルダーの paused/。アプリを閉じても残る。
1 件は <鍵>.json（画面に出す見出しと、再開に要る頼みの値）と <鍵>.pickle（途中の絵や工程の状態。無い件もある）。
pickle は自分で書いた物だけを読む（この置き場の外の物は読まない）。
"""
from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Callable

ROOT: Path | None = None   # 試験が置き場を差し替える


class Paused(Exception):
    """一時停止した。key の件を読めば続きから始められる"""

    def __init__(self, msg: str, key: str | None = None):
        super().__init__(msg)
        self.key = key


def root() -> Path:
    if ROOT is not None:
        return ROOT
    from chatdraw.project import autosave_path
    return autosave_path().parent / "paused"


def key(*parts) -> str:
    return hashlib.sha1(json.dumps([str(p) for p in parts], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def is_pause(e: BaseException) -> bool:
    """止めて捨てる代わりに一時停止にする打ち切りか。メモリの見張り・メモリ不足・時間切れ・取得の切れ"""
    if isinstance(e, Paused):
        return True
    if type(e).__name__ in ("Stopped",):
        return False   # 利用者の緊急停止はそのまま止める
    if type(e).__name__ in ("MemoryDanger", "Resumable", "FetchPaused") or isinstance(e, (MemoryError, TimeoutError)):
        return True
    try:
        from chatdraw.engine import is_oom
        return is_oom(e)
    except Exception:   # noqa: BLE001
        return False


def save(k: str, kind: str, label: str, job: dict | None = None, state=None) -> Path:
    """1 件を書く。kind は phases・draw・batch・fetch。job は再開に要る頼みの値（JSON に書ける物）、state は途中の状態"""
    d = root()
    d.mkdir(parents=True, exist_ok=True)
    if state is not None:
        part = d / f"{k}.pickle.part"
        part.write_bytes(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))
        part.replace(d / f"{k}.pickle")   # 書き終えてから入れ替える（途中で落ちても前の件は読める）
    head = {"key": k, "kind": kind, "label": label, "job": job or {}, "has_state": state is not None,
            "at": time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 9 * 3600)) + "（日本時間）"}
    p = d / f"{k}.json"
    p.write_text(json.dumps(head, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def info(k: str) -> dict | None:
    try:
        return json.loads((root() / f"{k}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state(k: str):
    """途中の状態。無い・読めない件は None（始めからやり直す）"""
    p = root() / f"{k}.pickle"
    try:
        return pickle.loads(p.read_bytes()) if p.exists() else None
    except Exception:   # noqa: BLE001  古い版の状態など。読めなければ始めから
        return None


def listing() -> list[dict]:
    """残っている件。新しい順"""
    d = root()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        got = info(p.stem)
        if got:
            out.append(got)
    return out


def clear(k: str | None):
    if not k:
        return
    for suf in (".json", ".pickle"):
        (root() / f"{k}{suf}").unlink(missing_ok=True)


def wait_memory(need_gb: float, wait_s: float = 120.0, step_s: float = 5.0, free: Callable[[], float] | None = None,
                sleep: Callable[[float], None] = time.sleep, stopped: Callable[[], bool] = lambda: False) -> bool:
    """模型を降ろしたあと、空きが need_gb になるまで待つ。空けば True。待ちきれなければ False（呼び手が一時停止にする）"""
    if free is None:
        def free():
            try:
                import psutil
                return psutil.virtual_memory().available / 1e9
            except Exception:   # noqa: BLE001  測れなければ待たない
                return float("inf")
    waited = 0.0
    while True:
        if free() >= need_gb:
            return True
        if stopped() or waited >= wait_s:
            return False
        sleep(step_s)
        waited += step_s
