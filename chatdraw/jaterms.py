"""日本語の頼みから、絵の模型が分かる英語のタグを拾う表。

言葉の模型（.gguf）が無いと、日本語の頼みをそのまま絵の模型に渡していた。SDXL の模型は日本語を読めないので、
頼みと全く違う絵が出た。言葉の模型があっても、直した英語から大事な語（水着、髪の色など）が抜けることがあった。
この表で拾った語は、言葉の模型が無いときはそのまま使い、あるときは抜けた分を足す。
長い語から先に拾う（「ビキニ」より先に「白いビキニ」、「女の子」より先に「女の子たち」）。
"""
from __future__ import annotations

import re

COLORS = {"赤": "red", "青": "blue", "黒": "black", "白": "white", "金": "blonde", "銀": "silver", "緑": "green", "茶": "brown",
          "ピンク": "pink", "紫": "purple", "黄": "yellow", "オレンジ": "orange", "水色": "light blue", "紺": "navy blue", "灰": "grey"}

TERMS = {
    # 人
    "女性": "1girl, solo, adult woman, mature female", "女の人": "1girl, solo, adult woman, mature female",
    "大人の女性": "1girl, solo, adult woman, mature female", "お姉さん": "1girl, solo, adult woman, mature female",
    "女の子": "1girl, solo", "少女": "1girl, solo", "男性": "1boy, solo, adult man", "男の人": "1boy, solo, adult man",
    "男の子": "1boy, solo", "少年": "1boy, solo", "老人": "old man, elderly", "おばあさん": "old woman, elderly",
    "二人": "2people", "騎士": "knight, armor", "魔法使い": "mage, robe", "メイド": "maid, maid headdress",
    "猫耳": "cat ears", "狐耳": "fox ears", "エルフ": "elf, pointy ears",
    # 服
    "ビキニ": "bikini", "水着": "swimsuit", "競泳水着": "competition swimsuit", "スクール水着": "school swimsuit",
    "ワンピース水着": "one-piece swimsuit", "制服": "school uniform", "セーラー服": "serafuku, sailor collar",
    "ドレス": "dress", "着物": "kimono", "浴衣": "yukata", "鎧": "armor", "パーカー": "hoodie", "スカート": "skirt",
    "ジーンズ": "jeans", "眼鏡": "glasses", "メガネ": "glasses", "帽子": "hat", "麦わら帽子": "straw hat",
    # 髪と目
    "長い髪": "long hair", "ロングヘア": "long hair", "短い髪": "short hair", "ショートヘア": "short hair",
    "ポニーテール": "ponytail", "ツインテール": "twintails", "おさげ": "braid", "ボブ": "bob cut",
    # 表情と姿勢
    "笑顔": "smile", "笑う": "smile", "微笑む": "light smile", "泣く": "crying, tears", "怒る": "angry", "照れる": "blush",
    "立つ": "standing", "立っている": "standing", "座る": "sitting", "座っている": "sitting", "走る": "running",
    "寝る": "lying", "振り返る": "looking back", "手を振る": "waving", "ピース": "v, peace sign", "腕を組む": "crossed arms",
    "全身": "full body", "上半身": "upper body", "顔": "portrait, close-up",
    # 場所と時
    "海": "beach, ocean", "砂浜": "beach", "ビーチ": "beach", "プール": "pool", "森": "forest", "街": "city street",
    "教室": "classroom", "部屋": "indoors, room", "空": "sky", "夜": "night", "夕焼け": "sunset", "夕日": "sunset",
    "雨": "rain", "雪": "snow", "桜": "cherry blossoms", "白い背景": "simple background, white background",
}

_COLOR_WORDS = {"髪": "hair", "目": "eyes", "瞳": "eyes", "ビキニ": "bikini", "水着": "swimsuit", "ドレス": "dress", "服": "clothes"}


def tags_from(text: str) -> list[str]:
    """日本語の頼みから拾ったタグ（順は頼みの中の順）"""
    found: list[tuple[int, str]] = []
    taken = [False] * len(text)

    def take(start: int, end: int, tag: str):
        if not any(taken[start:end]):
            for i in range(start, end):
                taken[i] = True
            found.append((start, tag))
    # 色と物の組（赤い髪、青い目、白いビキニ）を先に拾う
    for cj, ce in sorted(COLORS.items(), key=lambda kv: -len(kv[0])):
        for wj, we in _COLOR_WORDS.items():
            for m in re.finditer(f"{cj}(?:色)?(?:い|の)?{wj}", text):
                take(m.start(), m.end(), f"{ce} {we}")
    for ja, en in sorted(TERMS.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(ja), text):
            take(m.start(), m.end(), en)
    out: list[str] = []
    for _, tag in sorted(found):
        for t in tag.split(", "):
            if t not in out:
                out.append(t)
    return out


def merge(prompt: str, tags: list[str]) -> str:
    """言葉の模型が直した英語に、表で拾った語のうち抜けた物を足す"""
    have = prompt.lower()
    extra = [t for t in tags if t.lower() not in have]
    return ", ".join([prompt] + extra) if extra and prompt else prompt or ", ".join(tags)
