"""日本語の頼みから、絵の模型が分かる英語のタグを拾う表。

言葉の模型（.gguf）が無いと、日本語の頼みをそのまま絵の模型に渡していた。SDXL の模型は日本語を読めないので、
頼みと全く違う絵が出た。言葉の模型があっても、直した英語から大事な語（水着、髪の色など）が抜けることがあった。
この表で拾った語は、言葉の模型が無いときはそのまま使い、あるときは抜けた分を足す。
長い語から先に拾う（「ビキニ」より先に「白いビキニ」、「女の子」より先に「女の子たち」）。
"""
from __future__ import annotations

import re

from chatdraw.body import WOMAN

COLORS = {"赤": "red", "青": "blue", "黒": "black", "白": "white", "金": "blonde", "銀": "silver", "緑": "green", "茶": "brown",
          "ピンク": "pink", "紫": "purple", "黄": "yellow", "オレンジ": "orange", "水色": "light blue", "紺": "navy blue", "灰": "grey"}

TERMS = {
    # 人
    "女性": WOMAN, "女の人": WOMAN,
    "大人の女性": WOMAN, "お姉さん": WOMAN,
    "女の子": "1girl, solo", "少女": "1girl, solo", "男性": "1boy, solo, adult man", "男の人": "1boy, solo, adult man",
    "男の子": "1boy, solo", "少年": "1boy, solo", "老人": "old man, elderly", "おばあさん": "old woman, elderly",
    "騎士": "knight, armor", "女騎士": "1girl, solo, knight, armor", "魔法使い": "mage, robe", "メイド": "maid, maid headdress",
    "猫耳": "cat ears", "狐耳": "fox ears", "エルフ": "elf, pointy ears",
    # 服
    "ビキニ": "bikini", "水着": "swimsuit", "競泳水着": "competition swimsuit", "スクール水着": "school swimsuit",
    "ワンピース水着": "one-piece swimsuit", "制服": "school uniform", "セーラー服": "serafuku, sailor collar",
    "ドレス": "dress", "着物": "kimono", "浴衣": "yukata", "鎧": "armor", "パーカー": "hoodie", "スカート": "skirt",
    "ジーンズ": "jeans", "ジャケット": "jacket", "コート": "coat", "マフラー": "scarf", "セーター": "sweater", "Tシャツ": "t-shirt",
    "シャツ": "shirt", "ブラウス": "blouse", "ブーツ": "boots", "リボン": "ribbon", "ネクタイ": "necktie", "手袋": "gloves",
    "スーツ": "suit", "白衣": "lab coat", "エプロン": "apron", "ショートパンツ": "shorts", "ミニスカート": "miniskirt",
    "ロングスカート": "long skirt", "マント": "cape", "ピアス": "earrings", "ネックレス": "necklace", "サングラス": "sunglasses", "眼鏡": "glasses", "メガネ": "glasses", "帽子": "hat", "麦わら帽子": "straw hat",
    # 髪と目
    "長い髪": "long hair", "長髪": "long hair", "ロングヘア": "long hair", "短い髪": "short hair", "ショートヘア": "short hair",
    "髪ロング": "long hair", "髪ショート": "short hair", "ロング": "long hair", "ポニーテール": "ponytail", "ツインテール": "twintails", "おさげ": "braid", "ボブ": "bob cut",
    # 表情と姿勢
    "笑顔": "smile", "笑う": "smile", "微笑む": "light smile", "泣く": "crying, tears", "怒る": "angry", "照れる": "blush",
    "立つ": "standing", "立っている": "standing", "座る": "sitting", "座っている": "sitting", "走る": "running",
    "寝る": "lying", "振り返る": "looking back", "手を振る": "waving", "ピース": "v, peace sign", "腕を組む": "crossed arms",
    "日よけ": "hand up, shading eyes", "腰に手": "hand on own hip", "腰に当て": "hand on own hip", "手を上げ": "hand up",
    "両手を上げ": "arms up", "手を組": "own hands clasped", "見上げ": "looking up", "見下ろ": "looking down", "歩": "walking",
    "跳": "jumping", "飛ぶ": "flying", "飛ん": "flying", "泳": "swimming", "ほうき": "broom", "箒": "broom", "傘": "umbrella",
    "剣": "sword", "銃": "gun", "弓": "bow (weapon)", "盾": "shield", "カップ": "cup", "スマホ": "smartphone", "鞄": "bag", "バッグ": "bag", "杖": "staff", "花": "flower", "本": "book", "しゃがむ": "squatting", "しゃが": "squatting", "持つ": "holding", "泣い": "crying, tears", "腕を組": "crossed arms", "ひざまず": "kneeling", "抱え": "holding", "持っ": "holding",
    "読ん": "reading", "読む": "reading", "食べ": "eating", "飲ん": "drinking", "飲む": "drinking", "歌っ": "singing", "歌う": "singing",
    "踊": "dancing", "料理": "cooking", "戦っ": "fighting", "戦う": "fighting", "眠": "sleeping", "ウインク": "wink", "目を閉じ": "closed eyes",
    "正面": "facing viewer, looking at viewer", "横顔": "profile", "後ろ姿": "from behind", "背中": "from behind",
    "全身": "full body", "上半身": "upper body", "顔": "portrait, close-up",
    # 場所と時
    "海": "beach, ocean", "砂浜": "beach", "浜辺": "beach", "海辺": "beach, ocean", "夏": "summer", "ビーチ": "beach", "プール": "pool", "森": "forest", "街": "city street",
    "教室": "classroom", "部屋": "indoors, room", "空": "sky", "夜": "night", "夕焼け": "sunset", "夕日": "sunset",
    "図書館": "library", "カフェ": "cafe", "公園": "park", "城": "castle", "神社": "shrine", "屋上": "rooftop", "駅": "train station",
    "山": "mountain", "川": "river", "室内": "indoors", "屋外": "outdoors", "朝": "morning", "昼": "day", "砂漠": "desert", "草原": "grassland",
    "雨": "rain", "雪": "snow", "桜": "cherry blossoms", "白い背景": "simple background, white background",
}

# 役柄と生き物。表に無いと、言葉の模型が無いときに落ちて、ただの人物が描かれた
for _k, _v in {"魔女": "witch, witch hat", "天使": "angel, angel wings, halo", "悪魔": "demon, demon horns", "吸血鬼": "vampire",
               "侍": "samurai, katana", "忍者": "ninja", "巫女": "miko", "アイドル": "idol", "看護師": "nurse", "警察官": "police uniform",
               "海賊": "pirate", "魔法少女": "magical girl", "メカ": "mecha", "ロボット": "robot",
               "猫": "cat", "犬": "dog", "鳥": "bird", "狼": "wolf", "うさ耳": "rabbit ears", "角": "horns", "翼": "wings", "尻尾": "tail",
               "雨傘": "umbrella", "ヘッドホン": "headphones", "ギター": "guitar", "カメラ": "camera", "星空": "starry sky",
               "月": "moon", "炎": "fire", "水中": "underwater", "宇宙": "space"}.items():
    TERMS.setdefault(_k, _v)

# 頼みの 30 本の試験（chatdraw/tests/test_words.py）で落ちた語と、その周りのよく使う語。表に無いと、言葉の模型が無いときに
# 黙って捨てられ、頼みと違う絵が出た（紅茶を運ぶメイドが、何も持たないメイドになった）
for _k, _v in {"紅茶": "tea, teacup", "お茶": "tea", "コーヒー": "coffee, coffee cup", "ケーキ": "cake", "パン": "bread",
               "りんご": "apple", "アイス": "ice cream", "お弁当": "bento", "運ん": "carrying", "運ぶ": "carrying",
               "弾く": "playing instrument", "弾い": "playing instrument", "ピアノ": "piano", "バイオリン": "violin",
               "弓使い": "archer", "構え": "fighting stance", "構える": "fighting stance", "窓際": "window, by the window", "窓": "window",
               "手をつな": "holding hands", "手を繋": "holding hands", "抱きしめ": "hug", "羽織": "", "巻い": "", "巻く": "", "巻": "",
               "屋根": "rooftop", "刀": "katana", "川辺": "riverside, river", "病院": "hospital", "廊下": "hallway", "見て": "looking at viewer",
               "見る": "looking", "見つめ": "staring", "乗っ": "riding", "乗る": "riding", "乗": "riding", "祭り": "festival", "夏祭り": "summer festival",
               "金魚すくい": "goldfish scooping", "金魚": "goldfish", "船": "ship, boat", "電車": "train", "車": "car", "自転車": "bicycle",
               "前": "", "上": "", "辺": "", "使い": "", "の上": "", "の前": "", "横": "", "隣": "", "中": "",
               "ベッド": "bed", "椅子": "chair", "机": "desk", "階段": "stairs", "橋": "bridge", "庭": "garden", "台所": "kitchen",
               "学校": "school", "遊園地": "amusement park", "水族館": "aquarium", "ステージ": "stage", "教会": "church", "廃墟": "ruins",
               "雲": "cloud", "虹": "rainbow", "雷": "lightning", "風": "wind", "霧": "fog", "光": "light rays", "影": "shadow",
               "春": "spring (season)", "秋": "autumn", "冬": "winter", "紅葉": "autumn leaves", "向日葵": "sunflower", "ひまわり": "sunflower", "薔薇": "rose", "バラ": "rose",
               "泣き顔": "crying", "驚く": "surprised", "驚い": "surprised", "悲しい": "sad", "眠そう": "sleepy", "真剣": "serious",
               "ドヤ顔": "smug", "舌を出": "tongue out", "頬杖": "head rest", "手を伸ば": "reaching out", "指さ": "pointing", "指差": "pointing",
               "ジャンプ": "jumping", "寝転": "lying", "伸び": "stretching", "書い": "writing", "描い": "drawing", "撮っ": "taking picture",
               "子猫": "kitten", "うさぎ": "rabbit", "ドラゴン": "dragon", "妖精": "fairy", "人魚": "mermaid", "獣耳": "animal ears",
               "王女": "princess", "姫": "princess", "王子": "prince", "王様": "king", "女王": "queen", "シスター": "nun", "探偵": "detective",
               "学生": "student", "先生": "teacher", "医者": "doctor", "兵士": "soldier", "冒険者": "adventurer", "弓": "bow (weapon)",
               "髪飾り": "hair ornament", "カチューシャ": "hairband", "ヘアピン": "hairclip", "靴": "shoes", "サンダル": "sandals",
               "ニーソ": "thighhighs", "タイツ": "pantyhose", "ワンピース": "dress", "ローブ": "robe", "フード": "hood", "和服": "kimono",
               "ゴスロリ": "gothic lolita", "チャイナドレス": "china dress", "体操服": "gym uniform", "パジャマ": "pajamas",
               "赤髪": "red hair", "茶髪": "brown hair", "青髪": "blue hair", "白髪": "white hair", "銀髪": "silver hair", "金髪": "blonde hair",
               "黒髪": "black hair", "ピンク髪": "pink hair", "オッドアイ": "heterochromia", "そばかす": "freckles", "八重歯": "fang",
               "笑": "smile", "微笑": "light smile", "怒っ": "angry", "照れ": "blush"}.items():
    TERMS.setdefault(_k, _v)

# 描く物を変えない言い回し。拾ったことにして、伝わらない言葉の欄に出さない（タグは付けない）
QUIET = ("かけた", "かけて", "着た", "着て", "着てい", "身につけ", "付けた", "している", "いる", "下で", "の下", "前で", "中で", "姿", "人物", "描いて", "描く",
         "キャラクター", "イラスト", "感じ", "雰囲気", "かぶっ", "かぶる", "かぶり", "被っ", "被る", "締め", "さし", "さす",
         "二人", "2人", "２人", "ふたり", "三人", "3人", "３人", "四人", "4人", "４人")   # 人数は _count で読む
for _q in QUIET:
    TERMS.setdefault(_q, "")

# 「長い茶髪」「短い黒髪」のように、長さと色が髪に付いた言い方
_LENGTH = {"長い": "long hair", "短い": "short hair"}
# 色はすぐ後ろの物に付ける（「赤い帽子と青いドレス」を red hat と blue dress にする。色だけ別に渡すと、模型は色を別の物に塗った）
_COLOR_WORDS = {"髪": "hair", "目": "eyes", "瞳": "eyes", "ビキニ": "bikini", "水着": "swimsuit", "ドレス": "dress", "服": "clothes",
                "帽子": "hat", "スカート": "skirt", "着物": "kimono", "浴衣": "yukata", "リボン": "ribbon", "マフラー": "scarf",
                "ジャケット": "jacket", "コート": "coat", "セーター": "sweater", "シャツ": "shirt", "ブーツ": "boots", "靴": "shoes",
                "傘": "umbrella", "手袋": "gloves", "ネクタイ": "necktie", "鎧": "armor", "マント": "cape", "エプロン": "apron",
                "ワンピース": "dress", "ローブ": "robe", "セーラー服": "serafuku", "パーカー": "hoodie"}

# 打ち消し（「帽子なし」「眼鏡は無し」「傘を持たない」）。打ち消した物は描く言葉に入れず、描かない物（negative prompt）に回す。
# 打ち消しを読まずに「帽子」だけ拾うと、頼みと逆に帽子が描かれた
_NEG = r"(?:は|を|も)?(?:なし|無し|ナシ|なく|無く|ない|無い|抜き|不要|いらない|要らない|禁止)"
_NEG_VERB = r"(?:を)?(?:(?:持た|かけ|被ら|かぶら|着|付け)(?:ない|ず)|外し|脱い|脱ぎ)"

# 人数。「二人の女性」は 2girls にし、1 人の言葉（1girl、solo）を外す
_COUNT = {"二人": 2, "2人": 2, "２人": 2, "ふたり": 2, "三人": 3, "3人": 3, "３人": 3, "四人": 4, "4人": 4, "４人": 4}
_FEMALE = ("女性", "女の人", "お姉さん", "女の子", "少女", "女騎士", "女")
_MALE = ("男性", "男の人", "男の子", "少年", "男")


_STEM_END = "るうくぐすつぬぶむ"


def user_terms() -> dict[str, str]:
    """利用者が画面で直した語（読めなかった語に付けたタグ）と、言葉の模型が 1 語ずつ訳した語。表より先に引く"""
    try:
        from chatdraw import worddict
        return worddict.terms()
    except Exception:   # 置き場が読めなくても表だけで読む
        return {}


def _spans(text: str, extra: dict[str, str] | None = None) -> tuple[list[tuple[int, int, str, bool]], list[bool]]:
    """頼みを左から読み、拾った語の (始め, 終わり, タグ, 打ち消しか) と、拾った字の印を返す"""
    spans: list[tuple[int, int, str, bool]] = []
    taken = [False] * len(text)

    def take(start: int, end: int, tag: str):
        if any(taken[start:end]):
            return
        m = re.match(_NEG, text[end:]) or re.match(_NEG_VERB, text[end:])
        if m:   # すぐ後ろが打ち消しなら、描かない物に回す
            end += m.end()
        for i in range(start, end):
            taken[i] = True
        spans.append((start, end, tag, bool(m)))
    # 利用者が直した語を先に引く（表の語より長くても短くても、利用者の読みを正にする）
    for ja, en in sorted((extra if extra is not None else user_terms()).items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(ja), text):
            take(m.start(), m.end(), en)
    # 色と物の組（赤い髪、青い目、白いビキニ）を先に拾う
    for cj, ce in sorted(COLORS.items(), key=lambda kv: -len(kv[0])):
        for wj, we in sorted(_COLOR_WORDS.items(), key=lambda kv: -len(kv[0])):
            for m in re.finditer(f"{cj}(?:色)?(?:い|の)?{wj}", text):
                take(m.start(), m.end(), f"{ce} {we}")
    for lj, le in _LENGTH.items():
        for m in re.finditer(f"{lj}(?=[^、。 ]{{0,3}}髪)", text):
            take(m.start(), m.end(), le)
    for ja, en in sorted(TERMS.items(), key=lambda kv: -len(kv[0])):
        # 動きの言葉は終わりの形を変えて書かれる（振る・振っている・振って、寝る・寝ている）。終わりの 1 字を除いた語幹でも拾う。
        # 語幹が仮名だけで 1 字になるもの（「いる」の「い」）は、ほかの語の字を取ってしまうので拾わない
        keys = [ja]
        if ja[-1] in _STEM_END and len(ja) >= 2 and (len(ja) >= 3 or re.match(r"[一-鿿]", ja[0])):
            keys.append(ja[:-1])
        for key in keys:
            for m in re.finditer(re.escape(key), text):
                take(m.start(), m.end(), en)
    # 日本語の頼みに混ぜた英語のタグ（単語のお気に入りから足した語、「猫耳の少女、red scarf」）はそのまま描く物にする（表の語の後に拾い、Tシャツの T を取らない）。
    # 前は日本語の語だけを表で拾い、混ぜた英語は黙って落ちていた
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9 ()'_.:-]*", text):
        word = m.group().strip(" .:-")
        if word:
            take(m.start(), m.start() + len(word), word)
    return sorted(spans), taken


def _scan(text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[bool]]:
    """頼みを左から読み、(位置, タグ) の描く物・描かない物と、拾った字の印を返す"""
    spans, taken = _spans(text)
    found = [(a, tag) for a, _b, tag, neg in spans if tag and not neg]
    negs = [(a, tag) for a, _b, tag, neg in spans if tag and neg]
    return found, negs, taken


def _flat(pairs: list[tuple[int, str]]) -> list[str]:
    out: list[str] = []
    for _, tag in sorted(pairs):
        for t in tag.split(", "):
            if t and t not in out:
                out.append(t)
    return out


def _count(text: str, tags: list[str]) -> list[str]:
    """人数の言葉（二人の女性、女性と男性）を、1 人の言葉（1girl、solo）と食い違わないタグに直す"""
    n = next((v for k, v in _COUNT.items() if k in text), 0)
    girl = any(w in text for w in _FEMALE)
    boy = any(w in text for w in _MALE)
    if not n and not (girl and boy):
        return tags
    rest = [t for t in tags if t not in ("1girl", "1boy", "solo")]
    if n and girl and not boy:
        head = [f"{n}girls"]
    elif n and boy and not girl:
        head = [f"{n}boys"]
    elif n > 2:
        head = ["1girl", "1boy", "multiple people"]
    else:
        head = ["1girl", "1boy"]
    return head + rest


def tags_from(text: str) -> list[str]:
    """日本語の頼みから拾った描く物のタグ（順は頼みの中の順）。打ち消した物は入れない"""
    found, negs, _ = _scan(text)
    neg = set(_flat(negs))
    return _count(text, [t for t in _flat(found) if t not in neg])


def negatives(text: str) -> list[str]:
    """打ち消した物（帽子なし → hat）。描かない物（negative prompt）に足す"""
    return _flat(_scan(text)[1])


_FILLER = set("のがをにでとはもへやてっいるたなだですますしたいる、。・ 　!！?？")


def _gaps(text: str, taken: list[bool]) -> list[tuple[int, str]]:
    """拾えなかった字のまとまり（つなぎの字を除く）を (位置, 語) で返す"""
    out, cur, at = [], "", 0
    for i, (ch, t) in enumerate(zip(text, taken)):
        if t or ch in _FILLER or not re.match(r"[぀-ヿ一-鿿]", ch):
            if len(cur) >= 2 or re.search(r"[一-鿿]", cur):   # 漢字は 1 字でも意味がある（乗った、持った）
                out.append((at, cur))
            cur = ""
        else:
            if not cur:
                at = i
            cur += ch
    if len(cur) >= 2 or re.search(r"[一-鿿]", cur):
        out.append((at, cur))
    return out


def leftover(text: str) -> list[str]:
    """表で拾えなかった言葉（つなぎの字を除いた残り）。模型に伝わらない言葉として利用者に見せる"""
    return [w for _a, w in _gaps(text, _spans(text)[1])]


def align(text: str) -> list[dict]:
    """頼みを語ごとに分け、どの語がどのタグになったかを頼みの順で返す。
    kind は draw（描く物）、neg（描かない物）、quiet（描く物を変えない言い回し）、lost（読めなかった語）。
    読めなかった語は捨てずに返し、画面で利用者が直せるようにする（黙って落とすと、頼みと違う絵になった）"""
    spans, taken = _spans(text)
    rows = [(a, {"word": text[a:b], "tags": [t for t in tag.split(", ") if t],
                 "kind": "neg" if neg else ("draw" if tag else "quiet")}) for a, b, tag, neg in spans]
    rows += [(a, {"word": w, "tags": [], "kind": "lost"}) for a, w in _gaps(text, taken)]
    return [r for _a, r in sorted(rows, key=lambda x: x[0])]


def coverage(text: str) -> tuple[int, int]:
    """(語の数, 読めなかった語の数)。言い回し（quiet）は語に数えない"""
    rows = [r for r in align(text) if r["kind"] != "quiet"]
    return len(rows), sum(r["kind"] == "lost" for r in rows)


def merge(prompt: str, tags: list[str]) -> str:
    """言葉の模型が直した英語に、表で拾った語のうち抜けた物を足す"""
    have = prompt.lower()
    extra = [t for t in tags if t.lower() not in have]
    return ", ".join([prompt] + extra) if extra and prompt else prompt or ", ".join(tags)
