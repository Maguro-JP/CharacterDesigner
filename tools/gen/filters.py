"""描く前の判定。子どもを性的に描くことだけを止める固定の制限（設定では外せない）。

利用者のフィルターと宗教・文化の知らせは外した（描けるようにするのが先、2026-10-24 の利用者の指示）。
ほかの所（free_text など）は check() と negative() を呼ぶだけにする。説明は docs/filters.md。
"""
from __future__ import annotations

import re

# 固定の制限。子どもを性的に描くことだけを止める。子どもを表す語だけ、性的な語だけでは止めない
SEXUAL = ["裸", "ヌード", "全裸", "半裸", "エロ", "えっち", "エッチ", "性的", "性行為", "セックス", "下着", "ランジェリー",
          "乳首", "おっぱい", "R-18", "R18", "18禁", "成人向け", "アダルト", "水着", "セクシー",
          "nsfw", "nude", "naked", "nudity", "nipple", "nipples", "topless", "bottomless", "sex", "sexual", "explicit",
          "lingerie", "underwear", "panties", "bra", "sexy", "erotic", "porn", "hentai", "genitals", "cleavage",
          "areola", "uncensored", "r-18", "r18", "swimsuit", "bikini"]
MINOR = ["子ども", "子供", "こども", "幼女", "幼児", "児童", "小学生", "中学生", "未成年", "幼い", "少女", "少年", "女の子", "男の子",
         "child", "children", "kid", "kids", "toddler", "teen", "teenage", "underage", "minor", "schoolgirl", "schoolboy",
         "little girl", "little boy", "young girl", "young boy", "elementary school",
         # 高校生・制服の題材も 18 歳未満に見える人物として扱う（固定の制限。描画確認 回7 の高校生の題材）
         "high school", "high school student", "school uniform", "serafuku", "sailor uniform", "高校生", "女子高生", "男子高校生"]
# 語そのものが子どもの性的な描写を指すもの。いつでも止める
ALWAYS = ["ロリ", "ショタ", "loli", "lolicon", "shota", "shotacon"]
# 子どもを表す語があるとき、いつも打ち消しに足す構図（低い視点・腿を中心にした構図）。
# 高校生の題材で、膝上の構図と座りの組み合わせから低い視点の絵が 8 枚中 5 枚出た（描画確認 回7）。固定の制限なので設定では外せない
MINOR_NEGATIVE = "from below, thigh focus, crotch focus, upskirt, pantyshot, ass focus"
# 性的な語があるとき、打ち消しに足す（模型が幼い顔と体に寄せることがあるため）
SAFE_NEGATIVE = "loli, shota, child, underage"


def _hits(words, text: str) -> list[str]:
    return [w for w in words if _hit({"words": [w]}, text)]


def fixed(text: str) -> str | None:
    """固定の制限に当たれば理由。設定では外せない"""
    a = _hits(ALWAYS, text)
    if a:
        return f"「{a[0]}」は子どもを性的に描く言葉なので描かない（固定の制限。docs/filters.md）"
    sexual, minor = _hits(SEXUAL, text), _hits(MINOR, text)
    if sexual and minor:
        return f"子どもを表す言葉（{minor[0]}）と性的な言葉（{sexual[0]}）が並んでいるので描かない（固定の制限。docs/filters.md）"
    return None


def has_minor(text: str) -> bool:
    return bool(_hits(MINOR, text) or _hits(ALWAYS, text))


def has_sexual(text: str) -> bool:
    return bool(_hits(SEXUAL, text))


def _hit(f: dict, text: str) -> str | None:
    low = text.lower()
    tokens = set(re.findall(r"[a-z0-9\-]+", low))
    # 古い書き方（ja / en に分けた一覧）も読む
    for w in list(f.get("words", [])) + list(f.get("ja", [])) + list(f.get("en", [])):
        w = str(w).strip().lower()
        if not w:
            continue
        # 英数字だけの1語は語の単位で比べる（braid の中の bra を拾わない）。それ以外（空白を含む語、英数字以外の文字）は文字列で探す
        if re.fullmatch(r"[a-z0-9\-]+", w):
            if w in tokens:
                return w
        elif w in low:
            return w
    return None


def advice_lines(text: str) -> list[str]:
    """知らせる中身。今は出さない（呼ぶ側を変えずに済むよう残す）"""
    return []


def cultural(text: str) -> list[dict]:
    return []


def check(text: str, path=None) -> str | None:
    """止める理由。固定の制限に当たったときだけ。当たらなければ None"""
    return fixed(text)


def negative(prompt: str = "", path=None) -> str:
    """打ち消しに足す言葉。性的な語があるときの子どもの言葉と、子どもを表す語があるときの構図"""
    parts = [SAFE_NEGATIVE] if has_sexual(prompt) else []
    if has_minor(prompt):
        parts.append(MINOR_NEGATIVE)
    return ", ".join(parts)
