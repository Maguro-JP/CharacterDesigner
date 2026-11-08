"""頼みに書かれていない所（背景・場所・ポーズ・髪型・服・表情・構図・光）を、描くたびに種から選んで足す。

頼みの言葉だけで描かせると、模型はいつも同じ無地の背景・同じ正面の立ち姿・同じ髪型を描き、似た絵ばかりになった
（同じ頼みで描いた頼みの言葉どうしの重なりは、足す前は平均 0.9 を超えていた。chatdraw/tests/test_variety.py）。
利用者が 1 語でも書いた項目は利用者の物なので足さない。種で選ぶので、種を固定すれば同じ組み合わせで描き直せる。
表の各項目は偏りが出ないよう 16 以上を持つ（1 つの語が出る割合を 1/16 以下にする）。
"""
from __future__ import annotations

import random
import re
import threading

_lock = threading.Lock()

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
# 上の語だけでは、頼んだ場所・動き・役柄の服を「書かれていない」と読み、ぶつかる語を足していた
# （夜の屋上でギターを弾く少年に beach と sitting, hugging knees、メイドに jacket, jeans、手を振る少女に kneeling）。
# 頼みの 30 本（chatdraw/tests/test_words.py の SENTENCES）で足した語とぶつかった物を、項目の語に足す
_MORE = {
    "place": ("rooftop", "hospital", "hallway", "grassland", "festival", "ship", "boat", "cherry blossoms", "starry sky",
              "riverside", "train", "church", "ruins", "pool", "bridge", "stairs", "window", "shore", "meadow", "sunset",
              "屋上", "神社", "草原", "祭", "船", "桜", "星空", "病院", "廊下", "川", "浜", "図書館", "カフェ", "城", "砂漠",
              "雪", "雨", "山", "駅", "庭", "窓", "屋根"),
    "pose": ("waving", "reading", "holding", "carrying", "singing", "drinking", "eating", "flying", "riding",
             "fighting stance", "looking back", "looking up", "looking down", "hand up", "arms up", "shading eyes",
             "playing instrument", "holding hands", "hug", "dancing", "swimming", "crossed arms", "hand on own hip",
             "peace sign", "cooking", "writing", "pointing", "stretching", "reaching out", "sleeping", "goldfish scooping",
             "振", "読", "持", "運", "歌", "飲", "食", "飛", "乗", "構え", "見上げ", "見下ろ", "弾", "抱", "踊", "泳", "ひざまず", "しゃが"),
    "clothes": ("maid", "knight", "miko", "nurse", "witch", "samurai", "ninja", "idol", "pirate", "vampire", "mage",
                "yukata", "serafuku", "bikini", "lab coat", "cape", "police", "magical girl", "princess", "nun", "soldier",
                "detective", "メイド", "騎士", "巫女", "看護師", "魔女", "侍", "忍者", "アイドル", "海賊", "吸血鬼",
                "魔法使い", "浴衣", "ビキニ", "白衣", "マント", "姫", "シスター", "兵士", "探偵"),
    "face": ("closed eyes", "sleeping", "sad", "smug", "tears", "眠", "悲"),
    "hair_color": ("elderly", "old man", "old woman", "老人", "おばあさん"),
}
TABLES = {k: (table, words + _MORE.get(k, ())) for k, (table, words) in TABLES.items()}

# 人を描かない頼み（背景美術など）と、人でない物を描く頼み（ロボット、竜）には、人の項目を足さない
PERSON = ("pose", "hair", "hair_color", "clothes", "face")
NO_PERSON = ("no humans", "scenery only", "人のいない", "風景だけ", "robot", "mecha", "dragon", "ロボット", "メカ", "ドラゴン")


def _has(text: str, words) -> bool:
    low = text.lower()
    for w in words:
        if re.search(r"[a-z]", w):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                return True
        elif w in text:
            return True
    return False


# 場所の語を含むが、場所ではなく役柄を表す語（「雪女」の雪を、雪の場所を頼んだと読んで場所を足さなかった）
_SCENE_ONLY = re.compile("雪女|雪ん子|雪の精|雨女|海賊|海女|森ガール|空手")


def fixed(text: str) -> set[str]:
    """利用者が書いた項目（足さない項目）"""
    out = {k for k, (_t, words) in TABLES.items() if _has(_SCENE_ONLY.sub("", text) if k == "place" else text, words)}
    if _has(text, NO_PERSON):
        out |= set(PERSON)
    return out


def pick(seed: int, text: str) -> dict[str, tuple[str, str]]:
    """種から、書かれていない項目の語を 1 つずつ選ぶ。返すのは {項目: (タグ, 文)}。
    場所だけは種でくじ引きにせず、頼みの言葉から読み解いた場面の中から選ぶ（scene_for）"""
    rng = random.Random(f"variety-{seed}")   # 種だけで決まる（種を固定すれば同じ組み合わせ）
    keep = fixed(text)
    out = {k: table[rng.randrange(len(table))] for k, (table, _w) in TABLES.items() if k not in keep}
    if "place" in out:
        out["place"] = scene_for(text, seed)[0]
    # 頼んだ動き・持ち物は体と手が入らないと描けない。寄りの構図を足すと、剣を持って立つ騎士が顔だけの絵になった
    if "pose" in keep and out.get("shot", ("",))[0] in TIGHT:
        wide = [s for s in SHOTS if s[0] not in TIGHT]
        out["shot"] = wide[rng.randrange(len(wide))]
    return out


# ---- 頼みから場面を読み解く ----
# 場所を種のくじ引きで足すと、水着の子に雪景色、騎士に教室のように、頼みにふさわしくない場所が付いた。
# 頼みの言葉（服・役柄・持ち物・季節・時刻・天気）から利用者が望む場面を読み、その場面の場所の中からだけ種で選ぶ。
# 読み解けないときは、でたらめな場所より無地や簡単な背景の方がよいので、それを足す
SIMPLE = [("simple background, white background", "on a plain white background"),
          ("simple background, gradient background", "on a simple gradient background")]

S = {  # 場所の名前 → (タグ, 文)。中身は PLACES と同じ物を使い、足りない場面だけここで足す
    "beach": PLACES[12], "harbor": PLACES[8], "pool": ("outdoors, poolside, swimming pool, blue sky", "at a sunny poolside"),
    "classroom": PLACES[5], "rooftop": PLACES[2], "schoolroad": ("outdoors, school route, street, trees, morning", "on the road to school"),
    "library": PLACES[3], "meadow": ("outdoors, grassland, meadow, blue sky, clouds", "on a wide grassy plain"),
    "castle": PLACES[19], "battlefield": ("outdoors, battlefield, ruins, smoke, dramatic sky", "on a battlefield under a dramatic sky"),
    "study": ("indoors, study room, bookshelf, candles, magic circle", "in a wizard's study full of books and candles"),
    "forest": PLACES[1], "snowfield": ("outdoors, snowfield, snow, winter, snowing", "on a snowy field in falling snow"),
    "bedroom": PLACES[15], "kitchen": PLACES[23], "shrine": ("outdoors, shrine, torii, stone path, trees", "at a shrine with a torii gate"), "festival": PLACES[24],
    "park_sakura": PLACES[0], "flowers": PLACES[4], "rain_street": PLACES[14], "night_city": PLACES[6],
    "cyber": PLACES[27], "workshop": PLACES[26], "cafe": PLACES[11], "stage": ("indoors, stage, spotlight, concert", "on a concert stage under spotlights"),
    "hospital": ("indoors, hospital, hallway, white walls", "in a bright hospital hallway"),
    "lab": ("indoors, laboratory, desk, monitors", "in a laboratory"), "office": ("indoors, office, desk, window", "in an office"),
    "ship": ("outdoors, ship deck, ocean, sails", "on the deck of a sailing ship"), "underwater": PLACES[22],
    "garden": PLACES[25], "autumn_shrine": PLACES[7], "desert": PLACES[21], "fantasy": PLACES[20],
    "mansion": ("indoors, mansion, hallway, carpet, chandelier", "in an elegant mansion hallway"),
    "gym": ("indoors, gymnasium, wooden floor", "in a school gymnasium"), "street": PLACES[10],
    "church": ("indoors, church, stained glass, pews", "in a church with stained glass"),
    "space": ("space, stars, planet, nebula", "in outer space among stars"),
    "dojo": ("indoors, dojo, wooden floor, tatami", "in a wooden dojo"),
}
# 場面の表。上から順に見て、頼みに語が 1 つでもあれば、その場面の場所を候補にする（複数当たれば候補を合わせる）。
# 語は日本語の頼みと、言葉の模型が訳したタグの両方で見る
SCENES = [
    ("水着", ("水着", "ビキニ", "swimsuit", "bikini", "swimwear", "競泳"), ("beach", "pool")),
    ("雪女・冬", ("雪女", "yuki-onna", "雪ん子", "雪の精"), ("snowfield",)),
    ("寝間着", ("寝間着", "パジャマ", "pajamas", "nightgown", "寝巻", "ネグリジェ", "sleepwear"), ("bedroom",)),
    ("料理人", ("料理人", "コック", "シェフ", "chef", "cook", "パティシエ", "料理", "cooking", "apron", "エプロン"), ("kitchen",)),
    ("制服", ("制服", "セーラー服", "学ラン", "ブレザー", "school uniform", "serafuku", "gakuran", "blazer", "女子高生",
             "男子高校生", "高校生", "中学生", "生徒", "student", "schoolgirl", "schoolboy", "ランドセル"), ("classroom", "schoolroad")),
    ("騎士・剣", ("鎧", "剣", "騎士", "戦士", "勇者", "armor", "sword", "knight", "warrior", "paladin", "盾", "shield",
               "槍", "spear", "兵士", "soldier"), ("meadow", "castle", "battlefield")),
    ("魔法使い", ("魔法使い", "魔女", "魔術師", "魔導士", "witch", "wizard", "mage", "sorcerer", "魔法の杖", "staff", "wand",
               "魔導書", "grimoire"), ("study", "forest")),
    ("巫女・和装", ("巫女", "miko", "神主", "shrine maiden"), ("shrine",)),
    ("浴衣", ("浴衣", "yukata", "夏祭り"), ("festival",)),
    ("着物", ("着物", "kimono", "振袖", "袴", "hakama"), ("shrine", "garden")),
    ("侍・忍者", ("侍", "samurai", "忍者", "ninja", "刀", "katana", "武士"), ("dojo", "autumn_shrine", "forest")),
    ("アイドル", ("アイドル", "idol", "歌手", "singer", "ステージ", "マイク", "microphone"), ("stage",)),
    ("看護師・医者", ("看護師", "ナース", "nurse", "医者", "doctor"), ("hospital",)),
    ("研究者", ("白衣", "lab coat", "科学者", "scientist", "研究者", "博士"), ("lab",)),
    ("会社員", ("スーツ", "suit", "会社員", "サラリーマン", "businessman", "office lady", "秘書"), ("office", "street")),
    ("海賊・船乗り", ("海賊", "pirate", "船乗り", "sailor", "船長", "captain"), ("ship", "harbor")),
    ("人魚", ("人魚", "mermaid", "マーメイド"), ("underwater",)),
    ("メイド・執事", ("メイド", "maid", "執事", "butler"), ("mansion", "cafe")),
    ("姫・王族", ("姫", "princess", "王女", "女王", "queen", "王子", "prince", "王様", "king", "ドレス"), ("castle", "garden")),
    ("シスター・聖職者", ("シスター", "nun", "神父", "priest", "聖女", "司祭"), ("church",)),
    ("運動", ("体操服", "gym uniform", "ジャージ", "track suit", "体育", "陸上", "バスケ", "バレー"), ("gym",)),
    ("職人", ("職人", "鍛冶", "blacksmith", "大工", "engineer", "技師", "メカニック", "mechanic"), ("workshop",)),
    ("近未来", ("サイバーパンク", "cyberpunk", "近未来", "アンドロイド", "android", "サイボーグ", "cyborg", "ハッカー"), ("cyber", "night_city")),
    ("宇宙", ("宇宙飛行士", "astronaut", "宇宙服", "spacesuit"), ("space",)),
    ("砂漠の旅", ("砂漠", "desert", "踊り子", "dancer", "アラビアン"), ("desert",)),
    ("エルフ・妖精", ("エルフ", "elf", "妖精", "fairy", "ドライアド"), ("forest", "fantasy", "flowers")),
    ("読書", ("本を読", "読書", "reading", "司書", "librarian"), ("library",)),
    ("喫茶", ("ウェイトレス", "waitress", "バリスタ", "barista", "コーヒー", "coffee", "紅茶"), ("cafe",)),
    ("傘・雨", ("傘", "umbrella", "レインコート", "raincoat", "長靴"), ("rain_street",)),
    ("桜", ("桜", "花見", "sakura", "cherry blossom"), ("park_sakura",)),
    ("花", ("花冠", "花束", "bouquet", "flower crown", "花屋", "florist"), ("flowers", "garden")),
]
# 季節・時刻・天気の語。頼みにあれば、その語と食い違う場所を外す（夏の服に雪、夜の頼みに日差しの公園）
SEASONS = {
    "夏": (("夏", "summer", "真夏", "猛暑", "ひまわり", "sunflower"), ("snowfield",)),
    "冬": (("冬", "winter", "雪", "snow", "マフラー", "scarf", "コート", "クリスマス", "christmas"),
          ("beach", "pool", "festival", "flowers", "park_sakura", "underwater")),
    "春": (("春", "spring", "入学"), ("snowfield", "festival")),
    "秋": (("秋", "autumn", "fall", "紅葉", "ハロウィン", "halloween"), ("snowfield", "park_sakura", "pool")),
    "夜": (("夜", "night", "深夜", "月夜", "moonlight", "星空"), ("park_sakura", "flowers", "schoolroad", "pool")),
    "雨": (("雨", "rain", "梅雨"), ("beach", "pool", "snowfield", "flowers")),
}
# 季節・時刻・天気だけが書かれ、服や役柄から場面が読めないときに選ぶ場所
SEASON_PLACES = {"夏": ("beach", "festival"), "冬": ("snowfield",), "春": ("park_sakura", "flowers"), "秋": ("autumn_shrine", "forest"),
                 "夜": ("night_city",), "雨": ("rain_street",)}
# 室内の物（寝間着・料理・机）を頼んだのに外の場所、外の物（水着）を頼んだのに室内、を避けるための区分け
INDOOR = {"classroom", "library", "castle", "study", "bedroom", "kitchen", "workshop", "cafe", "stage", "hospital", "lab",
          "office", "mansion", "gym", "church", "dojo"}

_log: list[dict] = []
KEEP = 8


def scene_for(text: str, seed: int) -> tuple[tuple[str, str], str]:
    """頼みの言葉から場面を読み、場所の (タグ, 文) と選んだ理由を返す。読めなければ無地・簡単な背景"""
    rng = random.Random(f"scene-{seed}")
    hits = [(name, places) for name, words, places in SCENES if _has(text, words)]
    seasons = [k for k, (words, _bad) in SEASONS.items() if _has(text, words)]
    bad = {b for k in seasons for b in SEASONS[k][1]}
    # 表の上の場面ほど頼みをよく表す（「雪女の白い着物」は着物より雪女）。当たった場面を上から見て、
    # 季節・時刻・天気と食い違わない場所が残る最初の場面を使う。候補を混ぜると、雪女に庭が付いた
    picked, scene = [], ""
    for name, places in hits:
        picked = [p for p in places if p not in bad]
        if picked:
            scene = name
            break
    why = f"頼みの「{scene}」から" if scene else ""
    if not picked and seasons and not hits:
        picked = [p for k in seasons for p in SEASON_PLACES[k] if p not in bad]
        why = "季節・時刻・天気の「" + "・".join(seasons) + "」から"
    if picked:
        if seasons and scene:
            why += "「" + "・".join(seasons) + "」と食い違う場所を外して"
        name = picked[rng.randrange(len(picked))]
        place, reason = S[name], why + f"場所「{name}」を選んだ（候補 {', '.join(picked)}）"
    else:
        place = SIMPLE[rng.randrange(len(SIMPLE))]
        reason = ("頼みの場面と季節・時刻・天気が食い違い、ふさわしい場所が無いので" if hits or seasons else "頼みから場面を読み解けないので") + "無地・簡単な背景にした"
    with _lock:
        _log.append({"text": text.strip(), "seed": seed, "place": place[0], "reason": reason})
        del _log[:-KEEP]
    return place, reason


def last(n: int = KEEP) -> list[dict]:
    """足した場所と選んだ理由の記録（新しい物が後ろ。chatdraw/sent.py の記録と同じ形で後から見られる）"""
    with _lock:
        return list(_log[-n:])


TIGHT = ("close-up", "portrait", "upper body")


# タグの模型（SD 系）は CLIP の 75 語片より後ろを捨て、収まらないと頭の決まり文句と質のタグから外す（engine.fit_tokens）。
# 足しすぎて質のタグが落ちると崩れが増えるので、足すのはこの語片の数まで。大事な順（場所 → 構図 → ポーズ → …）に足す
# 前は場所・構図・ポーズ・髪・髪の色・服・表情・光を 55 語片まで足し、頼みと合わせて 75 を超えると、
# 頭の質の言葉（masterpiece, best quality, absurdres）が外れて質が落ち、頼んでいない髪型・表情・構図に引っ張られた。
# 足すのは 0.5.10 と同じ場所（背景）だけにし、頼みと合わせてこの数までに抑える（残りを質の言葉に残す）
TAG_BUDGET = 40
ORDER = ("place",)


def added_words() -> set[str]:
    """ここで足しうる場所の語（engine.fit_tokens が、長すぎるときに質の言葉より先に外す）"""
    return {w.strip().lower() for tag, _s in list(PLACES) + list(S.values()) + SIMPLE for w in tag.split(",")}


def pieces(text: str) -> int:
    """CLIP の語片の数のおよそ（英単語と記号を 1 つずつ）"""
    return len(re.findall(r"[a-z]+|[^\sa-z]", text.lower()))


def vary(prompt: str, seed: int, tags: bool = True, text: str = "") -> str:
    """頼みの言葉の後ろに、書かれていない項目を足す（頼みの方を先に効かせる）。text は利用者の元の頼み"""
    if not prompt.strip():
        return prompt
    chosen = {k: v for k, v in pick(seed, f"{text}\n{prompt}").items() if k in ORDER}
    if not chosen:
        return prompt
    if not tags:
        keys = [k for k in ORDER if k in chosen][:room_for(prompt)]
        return prompt.rstrip(" .") + ", " + ", ".join(chosen[k][1] for k in keys) + "."
    out = prompt.rstrip(", ")
    room = room_for(prompt)
    for k in ORDER:
        if room <= 0:
            break
        if k in chosen and pieces(f"{out}, {chosen[k][0]}") <= TAG_BUDGET:
            out = f"{out}, {chosen[k][0]}"
            room -= 1
    return out


def room_for(prompt: str) -> int:
    """足してよい項目の数。頼みの語が多いほど少なくする。8 項目を毎回足すと、頼んだ語より足した語の方が多くなり、
    頼み（持ち物、服の色）が薄まって描かれなかった。基準の体の言葉は頼みではないので数えない"""
    try:
        from chatdraw.jaterms import _BODY
    except Exception:   # noqa: BLE001
        _BODY = ()
    asked = [t for t in (x.strip() for x in prompt.split(",")) if t and t not in _BODY
             and t.lower() not in ("1girl", "1boy", "solo", "1other")]
    return max(1, len(ORDER) - len(asked))
