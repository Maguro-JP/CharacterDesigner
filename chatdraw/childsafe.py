"""子どもを性的に描く頼みかの判定。アプリが止めるのはこれだけで、模型（AI）には判定させない。

前の判定は、打ち消しの言葉（no nsfw、下着なし、下着が見えないように）も「性的な言葉」と数え、
英語を語の途中でも探した（minor scratches の minor を未成年と読む、sexy の中に sex を見る）。
そのせいで普通の頼みや子どものキャラクターデザインまで止め、「描けませんでした」になっていた。

ここでは、打ち消した言葉を外し、英語は語の切れ目で探し、子どもを表す語と性的な語が「並んだ」ときだけ止める。
子どもを表す語だけ、性的な語だけでは止めない（子どものキャラクターデザインは描ける）。
"""
from __future__ import annotations

import re

# 止めるのは、子どもを性的に描く頼みだけ。ほかは何も止めない（道具は頼まれた通りに描く。2026-11-08 の利用者の指示）。
# 取り違えを減らすため、どちらの一覧も意味が 1 つに決まる語だけにする。
# 子どもを表す語: 少女・少年・女の子・高校生・制服などアニメで大人にも使う語は入れない
MINOR = ("子ども", "子供", "こども", "幼女", "幼児", "児童", "小学生", "未就学", "乳児",
         "toddler", "infant", "elementary school", "little girl", "little boy", "underage", "child", "children")
# 性的な語: 服（水着・下着）、見せ方（セクシー）、打ち消しによく出る札（nsfw）、性別の sex は入れない
SEXUAL = ("裸", "全裸", "ヌード", "性的", "性行為", "セックス", "エロ", "R18", "R-18", "18禁",
          "nude", "naked", "nudity", "sexual", "sex act", "having sex", "erotic", "porn", "hentai", "genitals", "nipples")
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
