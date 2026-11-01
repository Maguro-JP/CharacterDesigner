"""大きいファイル（言葉の模型の .gguf）を、切れても続きから取る

画面（Qt）を持たないので、そのまま試験できる。
取り直しの決まりは AdaptiveAIStudio の取得（src/runtime/model-install.ts）と同じにしている。

- 黙り込んだら打ち切る（timeout）。打ち切りが無いと、相手が繋いだまま何も送らないときに永久に止まる
- 切れた・黙った・配り元の一時的な不調（429、5xx）は、間を 2・4・8 秒と空けて、続きから取り直す
- 配り元に無い（404 など）は取り直さない。何度やっても同じ
- 取れた長さが合わないものは入れ替えない。.part を残して、次は続きから取る
- .gguf は頭の 4 文字（GGUF）を確かめてから入れ替える。違えば .part を消す（壊れた物を模型として置かない）
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


class Resumable(Exception):
    """続きから取り直せば直る失敗"""


def _once(url: str, part: Path, total: int, progress: Callable[[int, int], None], timeout: float, opener) -> None:
    got = part.stat().st_size if part.exists() else 0
    if total and got >= total:
        got = 0   # 前の版の途中の物。始めから取る
    req = urllib.request.Request(url, headers={"Range": f"bytes={got}-"} if got else {})
    try:
        r = opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 429 or e.code >= 500:
            raise Resumable(f"配り元が一時的に応じません（{e.code}）") from e
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise Resumable(f"繋がりませんでした（{e}）") from e
    with r:
        resumed = bool(got) and r.status == 206   # 206 でなければ配り元が続きを受けないので始めから
        got = got if resumed else 0
        size = total or got + int(r.headers.get("Content-Length") or 0)
        try:
            with open(part, "ab" if resumed else "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    progress(got, size)
        except (TimeoutError, ConnectionError, OSError) as e:
            raise Resumable(f"途中で切れました（{got / 1e9:.2f}GB まで取れています）") from e
    if size and got != size:
        raise Resumable(f"途中で切れました（{got / 1e9:.2f} / {size / 1e9:.2f}GB）")


def fetch_resumable(url: str, dest: Path, total: int = 0, progress: Callable[[int, int], None] = lambda g, t: None,
                    timeout: float = 60.0, retries: int = 3, sleep: Callable[[float], None] = time.sleep,
                    opener=urllib.request.urlopen, note: Callable[[str], None] = lambda s: None) -> Path:
    """url を dest に取る。total は HEAD で分かった大きさ（分からなければ 0）"""
    part = dest.with_suffix(".part")
    for i in range(retries + 1):
        try:
            _once(url, part, total, progress, timeout, opener)
            break
        except Resumable as e:
            if i >= retries:
                raise
            wait = 2 * 2 ** i
            note(f"{e}。{wait} 秒おいて、続きから取り直します（{i + 1}/{retries}）")
            sleep(wait)
    if dest.suffix == ".gguf":
        with open(part, "rb") as f:
            if f.read(4) != b"GGUF":
                part.unlink(missing_ok=True)
                raise ValueError(f"取れたものが GGUF ではありません: {url}")
    part.replace(dest)   # 取り終わってから入れ替える。途中で止まっても前の版は使え、次は続きから取る
    return dest
