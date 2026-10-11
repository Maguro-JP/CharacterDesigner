"""素材の棚（docs/app/PLAN.md の M8 の T2）。描く模型に後から足す素材を .cache/assets/ に置き、画面で選ぶ。

今扱うのは LoRA（作風・服・キャラクターを足す、SDXL 用の .safetensors）。1つの素材は
`.cache/assets/lora/<名前>.safetensors` と、出典を書いた `<名前>.json` の組で置く:

  {"title": "表示名", "source": "取ってきた URL", "license": "ライセンス名", "trigger": "効かせる言葉（任意）", "weight": 0.8}

json が無い・license が空の素材は一覧に出すが使わない（ライセンスの分からない素材で描かない）。

  python3 tools/gen/assets.py add <URL> <名前> --license <ライセンス> [--title ..] [--trigger ..]   取って置く
  python3 tools/gen/assets.py list
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LORA = ROOT / ".cache" / "assets" / "lora"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def list_loras() -> list[dict]:
    out = []
    for f in sorted(LORA.glob("*.safetensors")) if LORA.exists() else []:
        meta = {}
        try:
            meta = json.loads(f.with_suffix(".json").read_text())
        except (OSError, ValueError):
            pass
        usable = bool(str(meta.get("license", "")).strip())
        out.append({"name": f.stem, "title": meta.get("title", f.stem), "source": meta.get("source", ""),
                    "license": meta.get("license", ""), "trigger": meta.get("trigger", ""),
                    "weight": float(meta.get("weight", 0.8)), "usable": usable,
                    "why": "" if usable else "出典とライセンスが書かれていないので使わない",
                    "mb": round(f.stat().st_size / 1e6, 1)})
    return out


def get(name: str) -> dict | None:
    """使える LoRA だけを返す。名前の形も見る（ファイルの場所を外へ向けさせない）"""
    if not NAME.match(name or ""):
        return None
    return next((x for x in list_loras() if x["name"] == name and x["usable"]), None)


def path(name: str) -> Path:
    return LORA / f"{name}.safetensors"


def add(url: str, name: str, license: str, title: str = "", trigger: str = "", weight: float = 0.8) -> dict:
    if not NAME.match(name):
        raise ValueError("名前は英小文字・数字・ハイフンで 48 文字まで")
    if not license.strip():
        raise ValueError("ライセンスが分からない素材は置かない")
    LORA.mkdir(parents=True, exist_ok=True)
    tmp = LORA / f"{name}.part"
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(path(name))
    path(name).with_suffix(".json").write_text(json.dumps(
        {"title": title or name, "source": url, "license": license, "trigger": trigger, "weight": weight}, ensure_ascii=False, indent=1))
    return get(name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    a.add_argument("url"); a.add_argument("name"); a.add_argument("--license", required=True)
    a.add_argument("--title", default=""); a.add_argument("--trigger", default=""); a.add_argument("--weight", type=float, default=0.8)
    sub.add_parser("list")
    o = ap.parse_args()
    if o.cmd == "add":
        print(json.dumps(add(o.url, o.name, o.license, o.title, o.trigger, o.weight), ensure_ascii=False))
    else:
        print(json.dumps(list_loras(), ensure_ascii=False, indent=1))
