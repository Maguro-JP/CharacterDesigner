"""チャットの一言を、設定を変える・加工するの操作に読む。

chatplan は描く・直す・拡大・書き出しの段取りを読むが、「4枚ずつ描くようにして」は「ずつ描くよう」を 4 回描き、
「綺麗にして」「水彩風にして」「大きさを1024にして」は操作にならず、言葉の模型が無いと何もしなかった。
ここは言葉の決まりだけで読む（模型が無くても同じに動き、試験で答えが決まる）。読めなければ None を返し、今までの流れに任せる。
返す reply は、決めたことをチャットに返す 1 行。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _n(s: str) -> int:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return int(s) if s.isdigit() else _NUM.get(s, 0)


@dataclass
class Intent:
    kind: str          # "count" "size" "style" "finisher"
    arg: object = None
    reply: str = ""


# 画風の名前 → 今の絵に掛ける仕上げ（finishers.REGISTRY）と、これから描く絵の画風（aipanel.STYLES）
STYLES = {"水彩": ("style_watercolor", "水彩"), "厚塗り": ("style_thick", "厚塗り"), "アニメ": ("style_anime", "アニメ"),
          "セル": ("style_cel", "アニメ"), "線画": ("style_lineart", None)}
_STYLE_RE = re.compile(r"(" + "|".join(STYLES) + r")(?:画|塗り)?(?:風|調|の画風|の塗り)?\s*(?:に|で)\s*(?:して|する|変えて|替えて|直して)")
_CLEAN_RE = re.compile(r"^(?:この絵を|絵を|全体を)?\s*(?:綺麗|きれい|キレイ)に(?:して|する|整えて|仕上げて)?[。！!]?$")
_COUNT_RE = re.compile(r"(\d+|[０-９]+|[一二三四五六七八九十])\s*枚\s*(?:ずつ|づつ)|枚数を\s*(\d+|[０-９]+|[一二三四五六七八九十])"
                       r"|(\d+|[０-９]+|[一二三四五六七八九十])\s*枚(?:で|に)\s*(?:して|する|描くようにして)")
_SIZE_WORDS = {"縦長": "縦", "縦向き": "縦", "縦に": "縦", "横長": "横", "横向き": "横", "横に": "横", "正方形": "正方形", "真四角": "正方形"}
_SIZE_RE = re.compile(r"(?:大きさ|サイズ|解像度|画面の形|形)を?\s*(.+?)\s*(?:に|へ)\s*(?:して|する|変えて)|"
                      r"(縦長|横長|正方形|真四角|縦向き|横向き)(?:の絵)?\s*(?:に|で)\s*(?:して|する|描くようにして)")
# 描く対象の言葉。これがあれば設定ではなく描く頼み（「猫を4枚描いて」は 4 回描く）
_DRAW_RE = re.compile(r"描いて|描く$|かいて")


def parse(text: str, has_image: bool = True) -> Intent | None:
    t = text.strip()
    m = _COUNT_RE.search(t)
    if m and ("ずつ" in t or "づつ" in t or "枚数" in t or "ように" in t or not _DRAW_RE.search(t)):
        n = _n(next(g for g in m.groups() if g))
        if n:
            n = max(1, min(n, 20))
            return Intent("count", n, f"これから 1 回に {n} 枚ずつ描きます（AI の欄の枚数を {n} にしました）")
    m = _SIZE_RE.search(t)
    if m:
        word = (m.group(1) or m.group(2) or "").strip()
        pick = _size_of(word)
        if pick:
            from chatdraw.aipanel import SIZES
            w, h = SIZES[pick]
            return Intent("size", pick, f"描く大きさを「{pick}」（{w}×{h}）にしました"
                                        + ("" if pick in word or word in _SIZE_WORDS else f"（「{word}」に一番近い形）"))
    m = _STYLE_RE.search(t)
    if m:
        fin, draw_style = STYLES[m.group(1)]
        if has_image:
            return Intent("finisher", fin, f"今の絵に「{m.group(1)}」の画風を掛けます（新しいレイヤーに置きます。元に戻すで戻せます）")
        if draw_style:
            return Intent("style", draw_style, f"これから描く絵の画風を「{draw_style}」にしました")
    if _CLEAN_RE.match(t):
        return Intent("finisher", "retouch", "今の絵の線と塗りを整えます（新しいレイヤーに置きます。元に戻すで戻せます）")
    return None


def _size_of(word: str) -> str | None:
    for k, v in _SIZE_WORDS.items():
        if k in word:
            return v
    if word in ("縦", "横"):
        return word
    nums = [int(x) for x in re.findall(r"\d+", word.translate(str.maketrans("０１２３４５６７８９", "0123456789")))]
    if len(nums) == 1:
        return "正方形"
    if len(nums) >= 2:
        w, h = nums[:2]
        return "正方形" if abs(w - h) < min(w, h) * 0.15 else ("横" if w > h else "縦")
    return None
