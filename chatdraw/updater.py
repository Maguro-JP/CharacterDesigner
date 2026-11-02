"""アプリ本体の更新を確かめて、新しい Setup.exe を取る。

公開されている最新の版（GitHub の releases/latest）と手元の VERSION を比べる。新しければ Setup.exe を取って置き場を返し、
入れるかどうかは利用者が決める（勝手に入れない）。確かめられないとき（ネットが無い、公開されていない）は黙って何もしない。
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from chatdraw.paths import HOME, ROOT

REPO = "maguro-jp/characterdesigner"
URL = os.environ.get("CD_UPDATE_URL", f"https://api.github.com/repos/{REPO}/releases/latest")


def current() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def _tuple(v: str) -> tuple:
    out = []
    for part in v.lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def newer(latest: str, mine: str) -> bool:
    return _tuple(latest) > _tuple(mine)


def check(url: str = URL, timeout: float = 8.0, quiet: bool = True) -> dict | None:
    """新しい版があれば {version, setup, page, notes} を返す。無い・確かめられないなら None。
    quiet=False なら、確かめられないときは例外のまま返す（自分で押した「更新を確かめる」で、
    ネットに届かないのに「今の版が最新です」と出していたのを避ける）"""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "CharacterDesigner"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        if not quiet:
            raise
        return None
    version = str(data.get("tag_name") or data.get("version") or "")
    if not version or not newer(version, current()):
        return None
    setup = next((a.get("browser_download_url") for a in data.get("assets", [])
                  if str(a.get("name", "")).lower().endswith(".exe")), None)
    return {"version": version.lstrip("vV"), "setup": setup, "page": data.get("html_url", ""),
            "notes": (data.get("body") or "").strip()[:400]}


def download(url: str, on_progress=None) -> Path:
    """Setup.exe を更新の置き場に取る。途中で切れても壊れたファイルを残さないよう、別名で取ってから名前を替える"""
    dest = HOME / "updates" / url.rsplit("/", 1)[-1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "CharacterDesigner"})
    with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            got += len(chunk)
            if on_progress and total:
                on_progress(got, total)
    part.replace(dest)
    return dest
