"""好み（学び・お気に入り・評価）が触ってよい言葉と、触ってはいけない言葉の表。

好みから学んだ物が構図・姿勢・色・服・背景・人数・髪型・画面の明るさを動かすと、頼んでいない方へ絵が引っ張られ、
質が上がらずに頼みから外れた。好みが効いてよいのは質の言葉（描き込み、線、塗り、解像度）だけにする。
表に無い語は質の言葉と見なさない（知らない語は通さない側に倒す）。
"""
from __future__ import annotations

import re

# 好みが前に出したり足したりしてよい、質の言葉
QUALITY = ("masterpiece", "best quality", "high quality", "great quality", "good quality", "amazing quality",
           "very aesthetic", "aesthetic", "absurdres", "highres", "high score", "great score", "newest",
           "detailed", "highly detailed", "extremely detailed", "intricate details", "fine details", "ultra detailed",
           "detailed eyes", "beautiful detailed eyes", "detailed face",
           "clean lineart", "clean lines", "sharp lines", "fine lineart", "lineart quality",
           "smooth shading", "soft shading", "cel shading quality", "clean coloring", "polished",
           "sharp focus", "8k", "4k", "hd")

# 好みから足さない項目（その項目の語が 1 つでも入れば質の言葉ではない）
BLOCKED = {
    "composition": ("shot", "view", "angle", "from above", "from below", "from side", "from behind", "close-up",
                    "portrait", "full body", "upper body", "cowboy", "wide", "dutch", "depth of field", "bokeh"),
    "pose": ("standing", "sitting", "walking", "running", "jumping", "lying", "kneeling", "crouching", "leaning",
             "waving", "pose", "arms", "hands", "hand on", "looking", "stretching", "holding"),
    "color": ("red", "blue", "green", "yellow", "pink", "purple", "orange", "black", "white", "silver", "gold",
              "brown", "aqua", "monochrome", "pastel", "vivid", "colorful", "palette", "saturated", "sepia"),
    "clothes": ("uniform", "dress", "shirt", "skirt", "kimono", "armor", "coat", "jacket", "suit", "outfit", "costume",
                "swimsuit", "bikini", "hoodie", "robe", "hat", "boots", "clothes"),
    "background": ("background", "outdoors", "indoors", "scenery", "sky", "room", "street", "city", "forest", "beach",
                   "park", "night", "sunset", "landscape"),
    "people": ("1girl", "1boy", "2girls", "2boys", "solo", "multiple", "group", "girls", "boys", "couple", "crowd"),
    "hair": ("hair", "ponytail", "twintails", "braid", "bun", "bob cut"),
    "brightness": ("dark", "bright", "light", "lighting", "shadow", "contrast", "glow", "dim", "backlighting", "lens flare"),
}


def category(tag: str) -> str:
    """語の項目。質の言葉なら "quality"、止める項目ならその名前、どちらでもなければ "other\""""
    low = tag.strip().lower()
    for name, words in BLOCKED.items():
        if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in words):
            return name
    if low in QUALITY:
        return "quality"
    return "other"


def is_quality(tag: str) -> bool:
    return category(tag) == "quality"


def quality_only(tags) -> list[str]:
    """好みから使ってよい語だけを残す"""
    return [t for t in tags if is_quality(t)]
