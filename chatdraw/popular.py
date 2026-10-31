"""確かめる順を、世の中でよく使われている順にする。Actions で確かめる模型（config/verify-models.txt）を並べ替える。

よく使われている模型ほど、利用者が「取る」を押す見込みが高いので、先に点を付けておく。
人気は Hugging Face の数（直近 30 日の取得数、同じなら いいね の数）で測る。
確かめる対象は、点がまだ 0 で、30GB 以下の物だけ（30GB を超える物は Actions の機械の置き場に入らない）。

使い方: python3 -m chatdraw.popular            # 並びを見せる
        python3 -m chatdraw.popular --write    # config/verify-models.txt を書き換える（見出しの行はそのまま）
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

API = "https://huggingface.co/api/models/{}"
LIST = Path(__file__).resolve().parents[1] / "config" / "verify-models.txt"
MAX_GB = 30


def fetch_json(repo: str) -> dict:
    with urllib.request.urlopen(API.format(repo), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def popularity(repo: str, fetch=fetch_json) -> tuple[int, int]:
    """(取得数, いいね)。取れないときは (0, 0)（並びの最後にする。止めない）"""
    try:
        data = fetch(repo)
        return int(data.get("downloads", 0) or 0), int(data.get("likes", 0) or 0)
    except Exception:
        return 0, 0


def eligible(repos: list[str]) -> list[str]:
    """点が 0 で 30GB 以下の物だけ残す。目録に無い名前は、大きさが分からないのでそのまま残す"""
    from chatdraw.models import catalog_images
    by = {m.repo: m for m in catalog_images()}
    by.update({m.hub: m for m in catalog_images() if m.hub not in by})
    out = []
    for r in repos:
        m = by.get(r)
        if m is None or (m.score <= 0 and m.gb <= MAX_GB):
            out.append(r)
    return out


def order(repos: list[str], fetch=fetch_json) -> list[tuple[str, int, int]]:
    """よく使われている順。(名前, 取得数, いいね) を返す。同じ数なら元の順"""
    from chatdraw.models import catalog_images
    hub = {m.repo: m.hub for m in catalog_images()}
    rows = [(r, *popularity(hub.get(r, r), fetch)) for r in eligible(repos)]
    return sorted(rows, key=lambda x: (-x[1], -x[2]))


def read_list(path: Path = LIST) -> tuple[list[str], list[str]]:
    """(見出しの行, 模型の名前)"""
    head, repos = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            if not repos:
                head.append(line)
            continue
        repos.append(line.strip())
    return head, repos


def write_list(head: list[str], repos: list[str], path: Path = LIST):
    path.write_text("\n".join(head + repos) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    head, repos = read_list()
    rows = order(repos)
    for r, dl, likes in rows:
        print(f"{dl:>9}  {likes:>5}  {r}")
    if "--write" in argv:
        write_list(head, [r for r, _, _ in rows])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
