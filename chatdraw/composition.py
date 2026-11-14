"""頼みに書かれた意図の言葉（迫力、躍動感、静か など）から構図を選び、描く言葉に足す。

構図を模型任せにすると、毎回の出来が運で決まった。かといって頼まれていない構図を種で足すと、
頼みと違う絵になり崩れた。だから、頼みの中に意図の言葉がはっきり書かれているときだけ構図を足し、
書かれていなければ何も返さない。足すのは構図（視点の高さ、カメラの距離と角度、線の向き、配置）の言葉だけで、
場所・服・髪・体の言葉は足さない（tests の FORBIDDEN が見る）。知識と出典は docs/knowledge/composition.md。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Composition:
    name: str        # 画面に出す構図の名前
    tags: tuple      # タグで頼む模型（SDXL のアニメの模型など）に渡す言葉
    sentence: str    # 文で頼む模型（FLUX など）に渡す言葉


# 意図の言葉 → 構図。順は問わず、頼みの中で先に出た意図から使う。
# 日本語は部分一致、英語は語の境目で一致させる（"calm" が "calmly" に、"still" が "still life" 以外に当たりすぎないよう語で見る）
TABLE: list[tuple[tuple, tuple, Composition]] = [
    (("迫力", "大迫力", "威圧", "圧倒"), ("powerful", "imposing", "overwhelming", "intimidating"),
     Composition("遠近法（あおり）", ("from below", "dynamic angle", "foreshortening", "perspective"),
                 "seen from a low angle with strong perspective and foreshortening")),
    (("躍動感", "躍動", "動きのある", "勢いのある", "勢い"), ("dynamic", "energetic", "lively", "action-packed"),
     Composition("対角線", ("diagonal composition", "dynamic angle", "dutch angle"),
                 "with a diagonal composition and a tilted dynamic angle")),
    (("静か", "穏やか", "のどか", "安らか"), ("quiet", "peaceful", "serene", "tranquil"),
     Composition("水平（真横）", ("horizontal composition", "from side", "eye level"),
                 "with a calm horizontal composition, seen from the side at eye level")),
    (("落ち着いた", "落ち着き", "安定感", "安定した"), ("calm", "stable", "steady"),
     Composition("日の丸（中央）", ("centered composition", "balanced composition", "eye level"),
                 "with a centered, balanced composition at eye level")),
    (("規則正しい", "整然", "端正", "厳か", "荘厳"), ("orderly", "formal", "solemn", "symmetrical"),
     Composition("垂直・左右対称", ("vertical composition", "symmetrical composition", "straight-on"),
                 "with a vertical, symmetrical composition seen straight on")),
    (("壮大", "雄大", "スケール感", "広大"), ("epic", "grand", "majestic", "vast"),
     Composition("引きのあおり", ("wide shot", "from below", "perspective"),
                 "as a wide shot from a low angle with deep perspective")),
    (("親しみ", "親近感", "身近"), ("friendly", "intimate", "approachable"),
     Composition("寄りの目の高さ", ("close-up", "eye level"),
                 "as a close-up at eye level")),
    (("緊張感", "不安", "不穏", "緊迫"), ("tense", "tension", "uneasy", "suspenseful"),
     Composition("傾き（ダッチアングル）", ("dutch angle", "tight framing"),
                 "with a tilted dutch angle and tight framing")),
    (("孤独", "寂しさ", "寂しげ", "余白"), ("lonely", "solitary", "isolated"),
     Composition("余白の多い引き", ("wide shot", "negative space", "rule of thirds"),
                 "as a wide shot with lots of negative space, subject on a third")),
    (("無力", "弱々しい", "小さく見せ"), ("helpless", "vulnerable"),
     Composition("俯瞰", ("from above", "high angle"),
                 "seen from a high angle looking down")),
]

MAX_INTENTS = 2   # 意図が 3 つ以上あっても、構図の言葉がぶつかり合わないよう先の 2 つまで


def _find(text: str, ja: tuple, en: tuple) -> int:
    """意図の言葉が最初に出た位置。無ければ -1"""
    best = -1
    low = text.lower()
    for w in ja:
        i = text.find(w)
        if i >= 0 and (best < 0 or i < best):
            best = i
    for w in en:
        m = re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)
        if m and (best < 0 or m.start() < best):
            best = m.start()
    return best


def pick(text: str) -> list[tuple[str, Composition]]:
    """頼みに書かれた意図と、それに合う構図。意図が書かれていなければ []"""
    if not text:
        return []
    hits = []
    for ja, en, comp in TABLE:
        i = _find(text, ja, en)
        if i >= 0:
            word = next((w for w in ja + en if text.lower().find(w.lower()) == i), "")
            hits.append((i, word or text[i:i + 4], comp))
    hits.sort(key=lambda h: h[0])
    out, seen = [], set()
    for _, word, comp in hits:
        if comp.name not in seen:
            seen.add(comp.name)
            out.append((word, comp))
    return out[:MAX_INTENTS]


def add(text: str, prompt: str, tags: bool = True) -> tuple[str, str]:
    """描く言葉に構図を足した物と、チャットに出す 1 行。意図が無ければ (prompt, "") をそのまま返す"""
    hits = pick(text)
    if not hits:
        return prompt, ""
    have = prompt.lower()
    added, notes = [], []
    for word, comp in hits:
        if tags:
            new = [t for t in comp.tags if t.lower() not in have and t not in added]
        else:
            new = [comp.sentence] if comp.sentence.lower() not in have else []
        if new:
            added += new
            notes.append(f"「{word}」から{comp.name}の構図")
    if not added:
        return prompt, ""
    joined = ", ".join(added)
    out = f"{prompt}, {joined}" if prompt else joined
    return out, "、".join(notes) + "を足しました: " + joined
