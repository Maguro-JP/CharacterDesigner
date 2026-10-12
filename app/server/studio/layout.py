"""画面の配置。コードではなくデータ（.cache/app/layout.json）で持つ（手本: Maguro-JP/AdaptiveAIStudio の docs/UI.md）。

自分でファイルを直しても、画面で仕切りを動かしても、AI に頼んで書き換えさせても配置が変わる。
AI に触らせる以上、壊れた配置は必ず来る。読めない・形が違う配置は既定に直して返し、画面を真っ白にしない。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

# 置ける板。画面（app/web/src/panels.tsx の PANELS）と同じ名前にそろえる。test_layout.py が食い違いを見る
PANEL_KINDS = {
    "prompt": "頼みごと",        # 頼みごと・描く言葉・言葉の模型の入れ替え
    "canvas": "大きく見る",      # 選んだ1枚を大きく
    "paint": "描く",             # 筆圧・パレット・手ぶれ補正で、選んだ絵を下絵に手で描く
    "gallery": "描いた絵",       # 描いた絵の一覧
    "queue": "仕事",             # 仕事の進み
    "roster": "役割",            # 役割ごとの今の出来事
    "log": "出来事",             # 役割の出来事を時間順に
    "memory": "覚えていること",  # 通った描く言葉と seed、落ちた理由
    "proposals": "提案",         # 待機中に拾った提案（承認するまで描かない）
    "demi": "亜人の設定資料",    # 亜人の種を選んで描く（前からの欄）
}

DEFAULT = {
    "id": "studio",
    "name": "スタジオ",
    "root": {
        "type": "split", "direction": "row", "sizes": [0.28, 0.47, 0.25],
        "children": [
            {"type": "split", "direction": "column", "sizes": [0.62, 0.38],
             "children": [{"type": "panel", "panel": "prompt"}, {"type": "panel", "panel": "queue"}]},
            {"type": "split", "direction": "column", "sizes": [0.72, 0.28],
             "children": [{"type": "tabs", "children": [{"type": "panel", "panel": "canvas"}, {"type": "panel", "panel": "paint"}]},
                          {"type": "panel", "panel": "gallery"}]},
            {"type": "tabs", "children": [{"type": "panel", "panel": "roster"}, {"type": "panel", "panel": "proposals"}, {"type": "panel", "panel": "log"},
                                          {"type": "panel", "panel": "memory"}, {"type": "panel", "panel": "demi"}]},
        ],
    },
}


def _valid(node, depth=0) -> bool:
    if not isinstance(node, dict) or depth > 6:
        return False
    t = node.get("type")
    if t == "panel":
        return node.get("panel") in PANEL_KINDS
    kids = node.get("children")
    if t not in ("split", "tabs") or not isinstance(kids, list) or not kids or len(kids) > 6:
        return False
    if t == "split":
        if node.get("direction") not in ("row", "column"):
            return False
        sizes = node.get("sizes")
        if not (isinstance(sizes, list) and len(sizes) == len(kids) and all(isinstance(x, (int, float)) and x > 0 for x in sizes)):
            return False
    return all(_valid(k, depth + 1) for k in kids)


def repair(data) -> tuple[dict, list[str]]:
    """読める形に直す。直したことを返す（黙って直さない。画面に出す）。"""
    notes = []
    if not isinstance(data, dict) or not _valid(data.get("root")):
        return copy.deepcopy(DEFAULT), ["配置が読めないので既定に戻した"]
    out = {"id": str(data.get("id", "custom"))[:40], "name": str(data.get("name", "自分の配置"))[:40], "root": data["root"]}
    # 比率は合計 1 にそろえる（手で書いて合計がずれても、はみ出さないように）
    def norm(n):
        if n["type"] == "split":
            total = sum(n["sizes"])
            n["sizes"] = [round(x / total, 4) for x in n["sizes"]]
        for k in n.get("children", []):
            norm(k)
    norm(out["root"])
    return out, notes


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {**copy.deepcopy(DEFAULT), "notes": []}
    layout, notes = repair(data)
    return {**layout, "notes": notes}


def save(path: Path, data) -> dict:
    layout, notes = repair(data)
    if notes:
        raise ValueError(notes[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(layout, ensure_ascii=False, indent=1))
    tmp.replace(path)
    return {**layout, "notes": []}
