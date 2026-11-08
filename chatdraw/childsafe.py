"""子どもを性的に描く頼みかの判定。アプリが止めるのはこれだけで、模型（AI）には判定させない。

前の判定は、打ち消しの言葉（no nsfw、下着なし、下着が見えないように）も「性的な言葉」と数え、
英語を語の途中でも探した（minor scratches の minor を未成年と読む、sexy の中に sex を見る）。
そのせいで普通の頼みや子どものキャラクターデザインまで止め、「描けませんでした」になっていた。

ここでは、打ち消した言葉を外し、英語は語の切れ目で探し、子どもを表す語と性的な語が「並んだ」ときだけ止める。
子どもを表す語だけ、性的な語だけでは止めない（子どものキャラクターデザインは描ける）。
"""
from __future__ import annotations

import re

# 子どもを表す語。英語の minor は「小さな」の意味で普通に使うので入れない
MINOR = ("子ども", "子供", "こども", "幼女", "幼児", "児童", "小学生", "中学生", "未成年", "少女", "少年", "女の子", "男の子",
         "child", "children", "kid", "kids", "toddler", "underage", "little girl", "little boy", "young girl", "young boy")
# 性的な語。水着・下着の服そのものは、性的な語と並ばなければ止めない（子どもの水着の絵は普通に描く）
SEXUAL = ("裸", "全裸", "半裸", "ヌード", "エロ", "えっち", "エッチ", "性的", "性行為", "セックス", "R18", "R-18", "18禁", "成人向け",
          "nude", "naked", "nudity", "nsfw", "sex", "sexual", "explicit", "erotic", "porn", "hentai", "topless", "bottomless",
          "nipple", "nipples", "genitals", "lingerie", "uncensored")
# 語そのものが子どもの性的な描写を指す。いつでも止める
ALWAYS = ("ロリ", "ショタ", "loli", "lolicon", "shota", "shotacon")

_EN_NEG = re.compile(r"(?<![a-z0-9])(?:no|not|without|avoid|never|non)[\s\-]+[a-z0-9_:\- ]*?(?=[,.;()\n]|$)", re.I)
_EN_FREE = re.compile(r"[a-z0-9_]+-free", re.I)
_JA_NEG = re.compile(r"[^\s、，,。]+?(?:なし|無し|禁止|を描かない|は描かない|が見えないように|を見せない|を避ける|を避けて|NG)")


def plain(text: str) -> str:
    """打ち消した言葉を除いた頼み"""
    t = _EN_NEG.sub(" ", text or "")
    t = _EN_FREE.sub(" ", t)
    return _JA_NEG.sub(" ", t)


def hits(words, text: str) -> list[str]:
    """英語の語は語の切れ目で、日本語の語はそのまま探す"""
    low = text.lower()
    out = []
    for w in words:
        wl = w.lower()
        if wl.isascii():
            if re.search(r"(?<![a-z0-9])" + re.escape(wl) + r"(?![a-z0-9])", low):
                out.append(w)
        elif wl in low:
            out.append(w)
    return out


def reason(text: str) -> str | None:
    """止める理由。止めないなら None"""
    t = plain(text)
    a = hits(ALWAYS, t)
    if a:
        return f"「{a[0]}」は子どもを性的に描く言葉なので描きません"
    m, s = hits(MINOR, t), hits(SEXUAL, t)
    if m and s:
        return f"子どもを表す言葉（{m[0]}）と性的な言葉（{s[0]}）が並んでいるので描きません"
    return None
