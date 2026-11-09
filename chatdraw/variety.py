"""頼みに書かれていない所（背景・場所・ポーズ・髪型・服・表情・構図・光）を、描くたびに種から選んで足す。

頼みの言葉だけで描かせると、模型はいつも同じ無地の背景・同じ正面の立ち姿・同じ髪型を描き、似た絵ばかりになった
（同じ頼みで描いた頼みの言葉どうしの重なりは、足す前は平均 0.9 を超えていた。chatdraw/tests/test_variety.py）。
利用者が 1 語でも書いた項目は利用者の物なので足さない。種で選ぶので、種を固定すれば同じ組み合わせで描き直せる。
表の各項目は偏りが出ないよう 16 以上を持つ（1 つの語が出る割合を 1/16 以下にする）。
"""
from __future__ import annotations

import random
import re

# (タグの模型に渡す言葉, 文で頼む模型に渡す言葉)
PLACES = [
    ("outdoors, park, cherry blossoms, falling petals, blue sky", "in a park under blooming cherry trees with falling petals"),
    ("outdoors, forest, sunbeam, light rays, grass", "in a forest with sunbeams falling through the leaves"),
    ("outdoors, rooftop, city, clouds", "on a school rooftop overlooking the city"),
    ("indoors, library, bookshelf", "in a library between tall bookshelves"),
    ("outdoors, flower field, wind, blue sky", "in a flower field on a windy day"),
    ("indoors, classroom, window, curtains", "in a classroom by the window"),
    ("outdoors, night, starry sky, city lights", "under a starry night sky with distant city lights"),
    ("outdoors, shrine, torii, autumn leaves", "at a shrine with a torii gate and autumn leaves"),
    ("outdoors, seaside, harbor, boats", "at a seaside harbor with boats"),
    ("indoors, greenhouse, plants, glass roof", "inside a greenhouse full of plants"),
    ("outdoors, street, shopping district, lanterns", "in a lively shopping street with lanterns"),
    ("indoors, cafe, table, cup, window", "in a cozy cafe by the window"),
    ("outdoors, beach, ocean, waves, sand", "on a sandy beach with waves"),
    ("outdoors, snow, winter, snowing, trees", "in a snowy winter landscape"),
    ("outdoors, rain, umbrella, wet street, reflections", "on a rainy street with reflections on the ground"),
    ("indoors, bedroom, bed, plush toy, window", "in a bedroom with plush toys"),
    ("outdoors, train station, platform, railroad", "on a train station platform"),
    ("outdoors, mountain, cliff, valley, clouds", "on a mountain cliff above a valley of clouds"),
    ("outdoors, river, bridge, willow", "on a bridge over a quiet river"),
    ("indoors, castle, throne room, pillars, chandelier", "in a grand castle hall with chandeliers"),
    ("outdoors, fantasy, floating island, waterfall", "on a floating island with waterfalls"),
    ("outdoors, desert, ruins, sand dunes", "among ancient ruins in the desert"),
    ("underwater, bubbles, fish, coral reef", "underwater near a coral reef with fish"),
    ("indoors, kitchen, cooking, sunlight", "in a sunny kitchen"),
    ("outdoors, festival, yukata stalls, night, fireworks", "at a summer festival with fireworks"),
    ("outdoors, garden, roses, fountain", "in a rose garden with a fountain"),
    ("indoors, workshop, tools, wooden shelves", "in a cluttered workshop"),
    ("outdoors, cyberpunk city, neon lights, night", "in a neon-lit futuristic city at night"),
]
POSES = [
    ("standing, hand on hip", "standing with a hand on the hip"), ("sitting, crossed legs", "sitting with crossed legs"),
    ("walking", "walking"), ("running", "running"), ("arms up, stretching", "stretching with arms up"),
    ("leaning forward", "leaning forward"), ("looking back", "looking back over the shoulder"),
    ("hands behind back", "with hands behind the back"), ("sitting, hugging knees", "sitting and hugging the knees"),
    ("waving", "waving"), ("jumping", "jumping"), ("leaning against wall", "leaning against a wall"),
    ("kneeling", "kneeling"), ("lying on grass", "lying on the grass"), ("reaching out", "reaching out a hand"),
    ("holding own hair", "touching the hair"), ("peace sign", "making a peace sign"), ("crouching", "crouching"),
]
HAIRS = [
    ("long hair", "long hair"), ("short hair", "short hair"), ("bob cut", "a bob cut"), ("ponytail", "a ponytail"),
    ("twintails", "twin tails"), ("braid", "a braid"), ("messy hair", "messy hair"), ("hair bun", "a hair bun"),
    ("side ponytail", "a side ponytail"), ("wavy hair", "wavy hair"), ("very long hair", "very long hair"),
    ("hime cut", "a hime cut"), ("medium hair", "medium length hair"), ("twin braids", "twin braids"),
    ("spiked hair", "spiky hair"), ("drill hair", "drill curls"),
]
HAIR_COLORS = [
    ("black hair", "black hair"), ("brown hair", "brown hair"), ("blonde hair", "blonde hair"), ("silver hair", "silver hair"),
    ("white hair", "white hair"), ("red hair", "red hair"), ("pink hair", "pink hair"), ("blue hair", "blue hair"),
    ("purple hair", "purple hair"), ("green hair", "green hair"), ("orange hair", "orange hair"), ("aqua hair", "aqua hair"),
    ("gradient hair", "gradient hair"), ("light brown hair", "light brown hair"), ("dark blue hair", "dark blue hair"),
    ("streaked hair", "streaked hair"),
]
CLOTHES = [
    ("school uniform, serafuku", "a sailor school uniform"), ("hoodie, shorts", "a hoodie and shorts"),
    ("sundress", "a sundress"), ("kimono", "a kimono"), ("maid outfit", "a maid outfit"), ("armor, cape", "armor and a cape"),
    ("witch hat, robe", "a witch hat and robe"), ("casual clothes, jacket, jeans", "a jacket and jeans"),
    ("sweater, long skirt", "a sweater and a long skirt"), ("suit, necktie", "a suit with a necktie"),
    ("track suit", "a track suit"), ("lab coat", "a lab coat"), ("gothic lolita dress", "a gothic dress"),
    ("military uniform", "a military uniform"), ("idol costume", "an idol costume"), ("chef uniform", "a chef uniform"),
    ("adventurer outfit, belt, boots", "an adventurer outfit with boots"), ("raincoat", "a raincoat"),
    ("cheongsam", "a qipao dress"), ("overalls", "overalls"),
]
FACES = [
    ("smile", "smiling"), ("open mouth, laughing", "laughing"), ("serious", "with a serious look"), ("blush, shy", "blushing shyly"),
    ("wink", "winking"), ("surprised", "surprised"), ("pout", "pouting"), ("closed eyes, smile", "smiling with closed eyes"),
    ("determined", "with a determined look"), ("sleepy", "looking sleepy"), ("smug", "with a smug grin"),
    ("gentle smile", "with a gentle smile"), ("crying, tears", "teary-eyed"), ("expressionless", "expressionless"),
    ("angry", "looking angry"), ("grin", "grinning"),
]
SHOTS = [
    ("full body", "full body shot"), ("cowboy shot", "cowboy shot"), ("upper body", "upper body shot"),
    ("from above", "seen from above"), ("from below", "seen from below"), ("from side", "seen from the side"),
    ("dutch angle", "with a tilted camera"), ("wide shot", "a wide shot"), ("close-up", "a close-up"),
    ("dynamic angle", "a dynamic angle"), ("from behind, looking back", "seen from behind"), ("portrait", "a portrait"),
    ("three quarter view", "a three quarter view"), ("full body, depth of field", "full body with depth of field"),
    ("knee shot", "a knee-up shot"), ("over the shoulder", "an over the shoulder view"),
]
LIGHTS = [
    ("sunlight", "in bright sunlight"), ("sunset, orange light", "in warm sunset light"), ("backlighting", "backlit"),
    ("rim light", "with rim light"), ("soft lighting", "with soft light"), ("moonlight", "in moonlight"),
    ("dappled sunlight", "in dappled sunlight"), ("golden hour", "at golden hour"), ("overcast", "on an overcast day"),
    ("neon lighting", "lit by neon"), ("candlelight", "by candlelight"), ("morning light", "in morning light"),
    ("dramatic lighting", "with dramatic lighting"), ("lens flare", "with a lens flare"), ("twilight", "at twilight"),
    ("lantern light", "in lantern light"),
]

# 項目ごとに、頼みにあれば「利用者が決めた」と見なす語（英語の語と日本語の語）
TABLES = {
    "place": (PLACES, ("background", "outdoors", "indoors", "scenery", "landscape", "sky", "room", "street", "city", "forest",
                       "beach", "sea", "ocean", "park", "garden", "field", "classroom", "cafe", "library", "shrine", "temple",
                       "castle", "mountain", "river", "lake", "stage", "interior", "school", "office", "bedroom", "kitchen",
                       "station", "underwater", "space", "desert", "snow", "rain", "背景", "場所", "部屋", "街", "森", "海",
                       "空", "教室", "公園", "屋外", "室内", "白地", "no humans")),
    "pose": (POSES, ("standing", "sitting", "walking", "running", "jumping", "lying", "kneeling", "pose", "squatting",
                     "crouching", "leaning", "立ち", "座", "歩", "走", "寝", "ポーズ", "姿勢", "跳")),
    "hair": (HAIRS, ("hair", "ponytail", "twintails", "braid", "bun", "bob", "bald", "髪", "ポニーテール", "ツインテール",
                     "おさげ", "三つ編み")),
    "hair_color": (HAIR_COLORS, tuple(t for t, _s in HAIR_COLORS) + ("blonde", "黒髪", "金髪", "銀髪", "茶髪", "白髪", "赤髪", "髪の色")),
    "clothes": (CLOTHES, ("uniform", "dress", "shirt", "skirt", "kimono", "armor", "coat", "jacket", "suit", "outfit",
                          "costume", "clothes", "swimsuit", "hoodie", "robe", "服", "制服", "着物", "ドレス", "スカート",
                          "鎧", "衣装", "コート", "水着", "パーカー")),
    "face": (FACES, ("smile", "smiling", "crying", "angry", "laugh", "expression", "blush", "serious", "surprised", "wink",
                     "笑", "泣", "怒", "表情", "照れ")),
    "shot": (SHOTS, ("full body", "upper body", "portrait", "close-up", "cowboy shot", "from above", "from below",
                     "from side", "from behind", "wide shot", "全身", "上半身", "バストアップ", "アップ", "構図", "アングル")),
    "light": (LIGHTS, ("light", "lighting", "sunlight", "sunset", "moonlight", "night", "dark", "光", "照明", "夕", "夜", "朝")),
}
# 人を描かない頼み（背景美術など）には、人の項目を足さない
PERSON = ("pose", "hair", "hair_color", "clothes", "face")
NO_PERSON = ("no humans", "scenery only", "人のいない", "風景だけ")


def _has(text: str, words) -> bool:
    low = text.lower()
    for w in words:
        if re.search(r"[a-z]", w):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                return True
        elif w in text:
            return True
    return False


def fixed(text: str) -> set[str]:
    """利用者が書いた項目（足さない項目）"""
    out = {k for k, (_t, words) in TABLES.items() if _has(text, words)}
    if _has(text, NO_PERSON):
        out |= set(PERSON)
    return out


def pick(seed: int, text: str) -> dict[str, tuple[str, str]]:
    """種から、書かれていない項目の語を 1 つずつ選ぶ。返すのは {項目: (タグ, 文)}"""
    rng = random.Random(f"variety-{seed}")   # 種だけで決まる（種を固定すれば同じ組み合わせ）
    keep = fixed(text)
    return {k: table[rng.randrange(len(table))] for k, (table, _w) in TABLES.items() if k not in keep}


# タグの模型（SD 系）は CLIP の 75 語片より後ろを捨て、収まらないと頭の決まり文句と質のタグから外す（engine.fit_tokens）。
# 足しすぎて質のタグが落ちると崩れが増えるので、足すのはこの語片の数まで。大事な順（場所 → 構図 → ポーズ → …）に足す
TAG_BUDGET = 55
ORDER = ("place", "shot", "pose", "hair_color", "hair", "clothes", "face", "light")


def pieces(text: str) -> int:
    """CLIP の語片の数のおよそ（英単語と記号を 1 つずつ）"""
    return len(re.findall(r"[a-z]+|[^\sa-z]", text.lower()))


def vary(prompt: str, seed: int, tags: bool = True, text: str = "") -> str:
    """頼みの言葉の後ろに、書かれていない項目を足す（頼みの方を先に効かせる）。text は利用者の元の頼み"""
    if not prompt.strip():
        return prompt
    chosen = pick(seed, f"{text}\n{prompt}")
    if not chosen:
        return prompt
    if not tags:
        return prompt.rstrip(" .") + ", " + ", ".join(chosen[k][1] for k in ORDER if k in chosen) + "."
    out = prompt.rstrip(", ")
    for k in ORDER:
        if k in chosen and pieces(f"{out}, {chosen[k][0]}") <= TAG_BUDGET:
            out = f"{out}, {chosen[k][0]}"
    return out
