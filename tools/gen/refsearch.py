"""参考画像を探して手元に置く。描くときの手本（画風と色を読ませる IP-Adapter）や、描く人の資料に使う。

  python3 tools/gen/refsearch.py search "knight armor" [--n 12] [--commercial]
  python3 tools/gen/refsearch.py save <検索結果の id>
  python3 tools/gen/refsearch.py list

探す先は Openverse（CC ライセンスと public domain の画像の検索。鍵は要らない）。どの画像も作者・ライセンス・元のページを
一緒に残し、使う人が条件（表示、非営利など）を確かめられるようにする。
保存した画像は .cache/app/refs に置き、リポジトリには入れない（参考にした作品の画像そのものは置かない決まり）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = ROOT / ".cache" / "app" / "refs"
INDEX = REFS / "index.jsonl"
API = "https://api.openverse.org/v1/images/"
UA = "CharacterDesigner/0.1 (reference search for character design)"
# 営利で使えるライセンス（--commercial のとき、これだけを返す）
COMMERCIAL = {"by", "by-sa", "cc0", "pdm"}


def _get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search(query: str, n: int = 12, commercial: bool = False) -> list[dict]:
    """参考画像を探す。返すのは画像の URL と、使う条件（作者・ライセンス・元のページ）"""
    q = {"q": query, "page_size": max(1, min(n, 40)), "mature": "false"}
    if commercial:
        q["license_type"] = "commercial"
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(q)))
    out = []
    for r in data.get("results", []):
        lic = r.get("license", "")
        if commercial and lic not in COMMERCIAL:
            continue
        out.append({
            "id": r["id"], "title": r.get("title") or "", "url": r.get("url", ""),
            "thumb": r.get("thumbnail") or r.get("url", ""), "creator": r.get("creator") or "",
            "license": lic, "license_version": r.get("license_version") or "", "license_url": r.get("license_url") or "",
            "landing": r.get("foreign_landing_url") or "", "source": r.get("source") or "",
        })
    return out


def _safe_id(rid: str) -> str:
    # 検索結果の id は UUID。ファイル名に使うので、英数とハイフン以外は落とす
    return "".join(c for c in rid if c.isalnum() or c == "-")[:64] or hashlib.sha1(rid.encode()).hexdigest()[:16]


def save(item: dict) -> dict:
    """検索結果の1件を手元に置く。画像は .cache/app/refs/<id>.jpg、条件は index.jsonl に残す"""
    from io import BytesIO

    from PIL import Image
    rid = _safe_id(str(item.get("id", "")))
    REFS.mkdir(parents=True, exist_ok=True)
    path = REFS / f"{rid}.jpg"
    if not path.exists():
        raw = _get(item["url"])
        im = Image.open(BytesIO(raw)).convert("RGB")
        im.thumbnail((1024, 1024))
        im.save(path, quality=90)
    rec = {k: item.get(k, "") for k in ("title", "creator", "license", "license_version", "license_url", "landing", "source", "url")}
    rec["id"] = rid
    rec["file"] = path.name
    saved = {r["id"]: r for r in list_saved()}
    saved[rid] = rec
    INDEX.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in saved.values()), encoding="utf-8")
    return rec


def list_saved() -> list[dict]:
    if not INDEX.exists():
        return []
    out = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if (REFS / str(r.get("file", ""))).exists():
            out.append(r)
    return out


def path_of(rid: str) -> Path | None:
    """保存した参考画像のファイル。無ければ None"""
    p = REFS / f"{_safe_id(rid)}.jpg"
    return p if p.exists() else None


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--n", type=int, default=12)
    s.add_argument("--commercial", action="store_true", help="営利で使えるライセンスだけ")
    v = sub.add_parser("save")
    v.add_argument("id")
    v.add_argument("--query", default="", help="id を探し直すための検索語（省くと id で探す）")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "search":
        print(json.dumps(search(a.query, a.n, a.commercial), ensure_ascii=False, indent=1))
    elif a.cmd == "save":
        hit = [r for r in search(a.query or a.id, 40) if r["id"] == a.id]
        if not hit:
            print("その id は検索結果に無い。--query で探した語を渡す", file=sys.stderr)
            return 1
        print(json.dumps(save(hit[0]), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(list_saved(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
