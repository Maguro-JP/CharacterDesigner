"""おまかせのとき、頼みに合う模型を手元にある物から選ぶ。取っていない物は選ばない（勝手に数 GB を取らない）。

はっきりした言葉（写真、コスプレなど）があればそれで決める。無ければ言葉の模型に候補の説明を見せて選ばせる。
言葉だけで決める方が先なのは、2026-10-24 の試しで Qwen3.5 2B が「風景写真」「コスプレ」を取り違えたため（6 件中 2 件）。
"""
from __future__ import annotations

import re
from pathlib import Path

from chatdraw.models import PASS, WORDS, ImageModel

REAL = ("写真", "写実", "リアル", "実写", "photo", "realistic", "real ", "photorealistic", "風景写真")
KNOWN = ("コスプレ", "制服", "衣装", "版権", "原作", "cosplay", "uniform", "costume", "outfit")
CHIBI = ("ちび", "デフォルメ", "chibi", "deformed", "sd キャラ")
PENCIL = ("鉛筆", "線画", "スケッチ", "pencil", "sketch", "lineart")

PICK = ("Choose the best image model for the drawing request. Reply with the number only.\n{options}\n"
        "Choose {default} unless the request clearly needs what another model is better at.")


def installed_images() -> list[ImageModel]:
    from chatdraw.models import all_images
    from chatdraw.setup import has_image
    return [m for m in all_images() if has_image(m)]


def _need(low: str) -> tuple[str, str]:
    """頼みが求める作風（real / chibi / pencil / known / anime）と、その理由"""
    if any(w in low for w in REAL):
        return "real", "写実の頼み"
    if any(w in low for w in CHIBI):
        return "chibi", "ちびキャラの頼み"
    if any(w in low for w in PENCIL):
        return "pencil", "線画の頼み"
    if any(w in low for w in KNOWN):
        return "known", "衣装や既存の題材の頼み"
    return "anime", "アニメ絵の頼み"


def fit(m: ImageModel, need: str) -> int:
    """頼みへの合い方（0〜100）。はっきり合う物は点の差より先にする。目録の英語の説明とタグから決める"""
    from chatdraw.models import style
    from chatdraw.ratings import tags
    en, tg = m.en.lower(), set(tags(m))
    if need == "real":
        return 100 if style(m) == "real" else 25 if "semi-realistic" in en or "写実寄り" in tg else 0
    if need == "chibi":
        return 100 if "chibi" in en or "ちびキャラ向き" in tg else 20 if style(m) == "anime" else 0
    if need == "pencil":
        return 100 if "pencil" in en or "lineart" in en else 20 if "線が細い" in tg else 0
    if need == "known":
        return 100 if "outfits" in en or "many characters" in en or "existing characters" in en else 30 if style(m) == "anime" else 0
    return 40 if style(m) == "anime" else 10 if style(m) == "other" else 0


def merit(m: ImageModel, need: str) -> float:
    """選ぶ順。頼みへの合い方 + 点（利用者の点か目録の点）+ ★。点の低すぎる物（ratings.LOW 未満を利用者が付けた物）は後ろ"""
    from chatdraw.ratings import LOW, is_favorite, rating, user_rating
    r = rating(m)
    low = 1 if user_rating(m.repo) and r < LOW else 0
    return -1000 * low + fit(m, need) + r * 0.5 + (15 if is_favorite(m.repo) else 0)


def choose_image(text: str, prompt: str, words=None, have: list[ImageModel] | None = None) -> tuple[ImageModel | None, str]:
    """手元の模型から、頼みに合い点の高い物を選ぶ。返すのは (模型, 理由)。非表示にした物は、ほかに無いときだけ使う"""
    from chatdraw.ratings import is_hidden
    have = installed_images() if have is None else have
    have = [m for m in have if not __import__("chatdraw.ratings").ratings.is_blocked(m.repo)]
    have = [m for m in have if not is_hidden(m.repo)] or list(have)
    if not have:
        return None, "手元に絵の模型がありません"
    if len(have) == 1:
        return have[0], "手元にある模型"
    need, why = _need(f"{text} {prompt}".lower())
    ranked = sorted(have, key=lambda m: -merit(m, need))
    best = ranked[0]
    if need == "anime" and words is not None and getattr(words, "ready", lambda: False)():
        # はっきりした言葉が無いときだけ、言葉の模型に説明を見せて選ばせる。既定は点と合い方で決めた物
        options = "\n".join(f"{i}. {m.en}" for i, m in enumerate(have, 1))
        try:
            hit = re.search(r"\d+", words.ask(PICK.format(options=options, default=have.index(best) + 1), f"{text}\n{prompt}", max_tokens=4))
            if hit and 1 <= int(hit.group()) <= len(have):
                return have[int(hit.group()) - 1], "AI が頼みから選びました"
        except Exception:
            pass   # 言葉の模型が動かなくても、言葉で決めて描く
    return best, why


def choose_words(text: str) -> Path | None:
    """長い頼みや細かい指定は大きい模型、短い頼みは速い模型。手元にある物だけから選ぶ"""
    from chatdraw.setup import has_words, words_path
    have = [m for m in WORDS if has_words(m)]
    if not have:
        return None
    detailed = len(text) > 60 or text.count("、") + text.count(",") >= 4
    good = [m for m in have if m.score >= PASS] or have   # 点の届かない模型は、ほかに無いときだけ使う
    from chatdraw.engine import _LOADED
    loaded = [m for m in good if str(words_path(m)) in _LOADED]
    if loaded:   # 読んである模型を使う。頼みごとに替えると、そのたびに読み直しで 100 秒以上待たせた
        return words_path(loaded[0])
    pick = max(good, key=lambda m: m.gb) if detailed else max(good, key=lambda m: m.score)
    return words_path(pick)
