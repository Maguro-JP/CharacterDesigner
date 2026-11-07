"""元の頼みと今の頼みの食い違いを見つける。

直しの頼みが、描いたときの描くワードや赤ペンの指示を消す・別の色や物に替えるとき、
黙って進めると元の指示が無視されたように見えた。食い違った語を並べて、利用者に確かめるための判定。
言葉の模型は使わない（窓を出すかの判定に数秒待たせない）。拾えるのは決まった形だけで、拾い漏れはある。
"""
from __future__ import annotations

import re

COLORS = {
    "赤": "赤", "あか": "赤", "red": "赤", "青": "青", "あお": "青", "blue": "青", "黄": "黄", "黄色": "黄", "yellow": "黄",
    "緑": "緑", "みどり": "緑", "green": "緑", "白": "白", "しろ": "白", "white": "白", "黒": "黒", "くろ": "黒", "black": "黒",
    "金": "金", "金色": "金", "blonde": "金", "gold": "金", "銀": "銀", "銀色": "銀", "silver": "銀", "茶": "茶", "茶色": "茶",
    "brown": "茶", "紫": "紫", "purple": "紫", "ピンク": "ピンク", "桃色": "ピンク", "pink": "ピンク", "橙": "橙", "オレンジ": "橙",
    "orange": "橙", "灰": "灰", "灰色": "灰", "grey": "灰", "gray": "灰", "水色": "水色",
}
_COLOR_RE = "|".join(sorted(map(re.escape, COLORS), key=len, reverse=True))
_REMOVE = r"(?:を|は)?\s*(?:消して|消す|無くして|なくして|無しに|なしに|外して|はずして|取って|とって|要らない|いらない|やめて|削って)"
_SPLIT = re.compile(r"[、，,。/\n]+|\s+と\s+")


def terms(text: str) -> list[str]:
    """頼みを語の並びにする（読点・カンマ・改行で区切る）"""
    return [t.strip() for t in _SPLIT.split(text or "") if t.strip()]


def _colored(term: str) -> list[tuple[str, str]]:
    """「赤い髪」「red hair」「髪は赤」から (物, 色) を取る"""
    out = []
    for m in re.finditer(rf"({_COLOR_RE})(?:い|の|色の|色)?\s*([^\s、,を]+)", term):
        out.append((m.group(2).lower(), COLORS[m.group(1)]))
    for m in re.finditer(rf"([^\s、,を]+?)\s*(?:を|は|が)\s*({_COLOR_RE})", term):
        out.append((m.group(1).lower(), COLORS[m.group(2)]))
    return out


def conflicts(original: list[str] | str, new: str) -> list[tuple[str, str]]:
    """元の頼み（語の並びか文）と今の頼みの食い違い。(元の語, 今の頼みの所) の並びを返す"""
    old = terms(original) if isinstance(original, str) else [t for s in original for t in terms(s)]
    if not old or not (new or "").strip():
        return []
    found: list[tuple[str, str]] = []
    for part in terms(new):
        # 消す: 「帽子を消して」の帽子が元の語に入っていれば食い違い
        m = re.search(rf"(.+?){_REMOVE}", part)
        if m:
            obj = m.group(1).strip().lower()
            for t in old:
                if obj and (obj in t.lower() or t.lower() in obj):
                    found.append((t, part))
                    break
            continue
        # 替える: 同じ物の色が違う
        for thing, color in _colored(part):
            for t in old:
                for othing, ocolor in _colored(t):
                    if (othing in thing or thing in othing) and ocolor != color:
                        found.append((t, part))
        # 替える: 「剣を斧に」の剣が元の語にある
        m = re.search(r"(.+?)を\s*(.+?)に(?:して|替えて|変えて|する)?$", part)
        if m and not _colored(part):
            obj = m.group(1).strip().lower()
            for t in old:
                if obj and obj in t.lower():
                    found.append((t, part))
                    break
    seen, out = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def drop(new: str, parts: list[str]) -> str:
    """今の頼みから、食い違った所を外した残り（「元のまま」を選んだとき）"""
    gone = set(parts)
    return "、".join(t for t in terms(new) if t not in gone)
