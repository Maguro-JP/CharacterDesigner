"""チャットで描くワードを変える頼みを読む。

描くワード（AI の欄の頼みの欄）は描画の模型への設定で、チャットは言語の模型への指示。チャットの文で描くワードを
書き換えるのは、「描くワードを〜に変えて」「描くワードに〜を足して」「描くワードから〜を消して」と頼まれたときだけにする。
前はチャットで「〜を描いて」と書くと、その文で描くワードの欄を置き換えていた（docs/knowledge/chat-vs-words.md の表）。
ここは言葉の決まりだけで読む（模型が無くても同じに動く）。読めなければ None。
"""
from __future__ import annotations

import re

_WORDS = r"(?:描くワード|描く言葉|描く内容|頼みの欄)"
_Q = r"[「『\"]?(.+?)[」』\"]?"
_SET = re.compile(rf"^\s*{_WORDS}\s*(?:を|は)\s*{_Q}\s*(?:に|へ)\s*(?:変えて|替えて|換えて|して|書き換えて|置き換えて)")
_ADD = re.compile(rf"^\s*{_WORDS}\s*(?:に|へ)\s*{_Q}\s*を?\s*(?:足して|追加して|加えて|入れて|付けて)")
_DEL = re.compile(rf"^\s*{_WORDS}\s*(?:から)\s*{_Q}\s*を?\s*(?:消して|外して|削って|取って|抜いて|除いて)")
_CLEAR = re.compile(rf"\s*{_WORDS}\s*を?\s*(?:消して|空にして|空けて|クリアして)(?:ください)?")
SEP = "、"


def _join(cur: str, add: str) -> str:
    cur = cur.strip().rstrip("、,， ")
    return f"{cur}{SEP}{add}" if cur else add


def _remove(cur: str, word: str) -> str:
    parts = [p.strip() for p in re.split(r"[、,，]", cur) if p.strip()]
    kept = [p for p in parts if p != word]
    if len(kept) == len(parts):   # 区切りの中の一部なら、その語だけを抜く
        out = cur.replace(word, "")
        return re.sub(r"\s{2,}", " ", re.sub(r"[、,，]\s*[、,，]", SEP, out)).strip(" 、,，")
    return SEP.join(kept)


def parse(text: str, current: str) -> tuple[str, str] | None:
    """(新しい描くワード, チャットに返す 1 行)。描くワードを変える頼みでなければ None"""
    t = (text or "").strip()
    cur = (current or "").strip()
    if _CLEAR.fullmatch(t.rstrip("。！! ")):
        return "", f"描くワードを空にしました（前は「{cur or '（空）'}」）"
    m = _SET.match(t)
    if m:
        new = m.group(1).strip()
        return new, f"描くワードを「{cur or '（空）'}」から「{new}」に変えました"
    m = _ADD.match(t)
    if m:
        add = m.group(1).strip()
        new = _join(cur, add)
        return new, f"描くワードに「{add}」を足しました（「{new}」）"
    m = _DEL.match(t)
    if m:
        word = m.group(1).strip()
        if word not in cur:
            return cur, f"描くワードに「{word}」はありません。変えていません（「{cur or '（空）'}」）"
        new = _remove(cur, word)
        return new, f"描くワードから「{word}」を消しました（「{new or '（空）'}」）"
    return None
