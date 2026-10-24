"""おまかせのとき、頼みに合う模型を手元にある物から選ぶ。取っていない物は選ばない（勝手に数 GB を取らない）。

はっきりした言葉（写真、コスプレなど）があればそれで決める。無ければ言葉の模型に候補の説明を見せて選ばせる。
言葉だけで決める方が先なのは、2026-10-24 の試しで Qwen3.5 2B が「風景写真」「コスプレ」を取り違えたため（6 件中 2 件）。
"""
from __future__ import annotations

import re
from pathlib import Path

from chatdraw.models import IMAGES, PASS, WORDS, ImageModel

REAL = ("写真", "写実", "リアル", "実写", "photo", "realistic", "real ", "photorealistic", "風景写真")
KNOWN = ("コスプレ", "制服", "衣装", "版権", "原作", "cosplay", "uniform", "costume", "outfit")

PICK = ("Choose the best image model for the drawing request. Reply with the number only.\n{options}\n"
        "Choose {default} unless the request clearly needs what another model is better at.")


def installed_images() -> list[ImageModel]:
    from chatdraw.setup import has_image
    return [m for m in IMAGES if has_image(m)]


def choose_image(text: str, prompt: str, words=None, have: list[ImageModel] | None = None) -> tuple[ImageModel | None, str]:
    have = installed_images() if have is None else have
    if not have:
        return None, "手元に絵の模型がありません"
    if len(have) == 1:
        return have[0], "手元にある模型"
    low = f"{text} {prompt}".lower()
    def best(kind: str):
        cands = [m for m in have if kind in m.en]
        return max(cands, key=lambda m: m.score) if cands else None
    if any(w in low for w in REAL) and (m := best("realistic")):
        return m, "写実の頼み"
    if any(w in low for w in KNOWN) and (m := best("outfits")):
        return m, "衣装や既存の題材の頼み"
    if words is not None and getattr(words, "ready", lambda: False)():
        options = "\n".join(f"{i}. {m.en}" for i, m in enumerate(have, 1))
        default = max(range(1, len(have) + 1), key=lambda i: have[i - 1].score)
        try:
            m = re.search(r"\d+", words.ask(PICK.format(options=options, default=default), f"{text}\n{prompt}", max_tokens=4))
            if m and 1 <= int(m.group()) <= len(have):
                return have[int(m.group()) - 1], "AI が頼みから選びました"
        except Exception:
            pass   # 言葉の模型が動かなくても、言葉で決めて描く
    rec = max(have, key=lambda m: m.score)
    return rec, "アニメ絵の頼み"


def choose_words(text: str) -> Path | None:
    """長い頼みや細かい指定は大きい模型、短い頼みは速い模型。手元にある物だけから選ぶ"""
    from chatdraw.setup import has_words, words_path
    have = [m for m in WORDS if has_words(m)]
    if not have:
        return None
    detailed = len(text) > 60 or text.count("、") + text.count(",") >= 4
    good = [m for m in have if m.score >= PASS] or have   # 点の届かない模型は、ほかに無いときだけ使う
    pick = max(good, key=lambda m: m.gb) if detailed else max(good, key=lambda m: m.score)
    return words_path(pick)
