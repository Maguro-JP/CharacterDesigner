"""自由に描く: 日本語の頼みごとを、手元の言葉の模型で描く言葉（英語のタグ）に直し、Animagine で描く。

亜人の設定資料（demi_text）の枠に入らない頼みごと（「赤いマフラーの騎士の少年」）のためのもの。
描く言葉は画面で見て直してから描ける。直した言葉も、描く前にもう一度同じ検査を通す。

肌を見せる絵・性的な絵は描かない。頼みごとと描く言葉の両方を検査し、当たれば描かずに理由を返す。
打ち消しにも必ず入れる（模型が勝手に寄せることがあるため）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 描かないもの。頼みごと（日本語）と描く言葉（英語）の両方で見る
BLOCK_JA = ("裸", "ヌード", "全裸", "半裸", "エロ", "えっち", "エッチ", "性的", "性行為", "セックス", "下着", "ランジェリー",
            "乳首", "おっぱい", "R-18", "R18", "18禁", "成人向け", "アダルト", "ロリ", "ショタ")
BLOCK_EN = ("nsfw", "nude", "naked", "nudity", "nipple", "nipples", "topless", "bottomless", "sex", "sexual", "explicit",
            "lingerie", "underwear", "panties", "bra", "sexy", "erotic", "porn", "hentai", "loli", "shota", "genitals", "cleavage",
            "areola", "uncensored", "r-18", "r18")
SAFE_NEGATIVE = "nsfw, nude, naked, nipples, explicit, lingerie, underwear, cleavage"
QUALITY = "masterpiece, best quality, very aesthetic, absurdres"
# 設定資料用の打ち消し（people.NEGATIVE）から、自由な絵で要る背景・動物の打ち消しを外したもの
NEGATIVE = ("lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, "
            "worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, artist name")


def blocked_text(text: str) -> str | None:
    for w in BLOCK_JA:
        if w.lower() in text.lower():
            return f"「{w}」を含む頼みごとは描かない（肌を見せる絵・性的な絵は描かない決まり）"
    return blocked_tags(re.split(r"[,、\n]", text))


def blocked_tags(tags) -> str | None:
    for t in tags:
        words = set(re.findall(r"[a-z0-9\-]+", str(t).lower()))
        hit = sorted(words & set(BLOCK_EN))
        if hit:
            return f"描く言葉「{str(t).strip()}」に描かない言葉（{', '.join(hit)}）が入っている"
    return None


SYSTEM = (
    "日本語のキャラクターの頼みごとを、アニメ絵の画像生成（Animagine XL、Danbooru のタグ）に渡す英語のタグに直す。\n"
    "- tags: 人数と性別（1girl、1boy など）を最初に置き、髪の色と髪型、目の色、服、持ち物、表情、ポーズ、構図（full body、upper body など）、背景の順に、"
    "短い英語のタグで並べる。頼みごとに無いことは足さない（言われていない髪の色・目の色・持ち物を書かない。手本の言葉を写さない）。"
    "ただし構図と背景が無ければ full body と simple background を足す\n"
    "- negative: 頼みごとで「〜なし」「〜しない」と言われたものを英語のタグで入れる。無ければ空\n"
    "- summary: どう読んだかを日本語の1文で\n"
    "- allowed: 肌を見せる絵・性的な絵・子どもを性的に描く頼みごとなら false、それ以外は true\n"
    "- reason: allowed が false のときの理由（日本語）。true なら空"
)
# 手本の受け答え。小さい模型（0.5B）は説明だけだと日本語のタグや「no ○○」の打ち消しを返した
EXAMPLES = (
    ("青い髪のメイドの女の子、紅茶を運んでいる", {
        "tags": ["1girl", "solo", "blue hair", "maid", "maid headdress", "apron", "holding tray", "teacup", "smile", "full body", "simple background"],
        "negative": [], "summary": "紅茶を運ぶ青い髪のメイドの少女として読んだ", "allowed": True, "reason": ""}),
    ("黒いコートの探偵の青年、夜の街、帽子なし", {
        "tags": ["1boy", "solo", "black coat", "detective", "trench coat", "serious", "upper body", "night", "city", "street"],
        "negative": ["hat"], "summary": "夜の街にいる黒いコートの探偵の青年として読んだ。帽子は描かない", "allowed": True, "reason": ""}),
)

SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {"type": "array", "items": {"type": "string"}},
        "negative": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "allowed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["tags", "negative", "summary", "allowed", "reason"],
    "additionalProperties": False,
}


# 髪と目の色のタグの色が、頼みごとに言われているか見るための対応。模型は言われていない色（手本の blue hair）を足した
COLOR_JA = {"blue": "青蒼水", "red": "赤紅朱", "pink": "ピンク桃", "white": "白銀", "silver": "銀白", "black": "黒",
            "blonde": "金黄", "yellow": "黄金", "brown": "茶栗", "green": "緑翠", "purple": "紫", "grey": "灰グレー銀",
            "gray": "灰グレー銀", "orange": "オレンジ橙", "aqua": "水青", "golden": "金黄"}


def _unasked_colors(tags, text) -> list[str]:
    """髪・目の色のタグのうち、頼みごとにその色の言葉が無いものを落とす"""
    out = []
    for t in tags:
        m = re.fullmatch(r"(\w+) (hair|eyes)", t.lower())
        if m and m.group(1) in COLOR_JA and not any(ch in text for ch in COLOR_JA[m.group(1)]):
            continue
        out.append(t)
    return out


def _clean(tags, negative=False) -> list[str]:
    """タグを整える: 前後の空白、重複、空、長すぎるもの（模型が文章を書いたとき）、英語でないもの
    （描く模型は日本語のタグを読めない）を落とす。打ち消しでは「no ○○」の no を外し、「なし」だけのものを落とす"""
    out, seen = [], set()
    for t in tags:
        t = re.sub(r"\s+", " ", str(t)).strip().strip(",").strip()
        if negative:
            t = re.sub(r"^(no|without|not)\s+", "", t, flags=re.I)
        if not re.fullmatch(r"[\x20-\x7e]+", t or "x"):
            continue
        if t and len(t) <= 60 and t.lower() not in seen and t.lower() not in ("no", "none", "nothing"):
            seen.add(t.lower())
            out.append(t)
    return out


def describe(text: str, local=None) -> dict:
    """頼みごとを描く言葉に直す。返り値: {allowed, reason, prompt, negative, tags, summary, reader, notes}。
    読み手が無いとき: 頼みごとが英語のタグならそのまま使い、日本語なら手元の模型を起こすよう返す。"""
    notes = []
    why = blocked_text(text)
    if why:
        return {"allowed": False, "reason": why, "prompt": "", "negative": "", "tags": [], "summary": "", "reader": "check", "notes": notes}
    got, reader = None, None
    if local is not None:
        try:
            got, reader = local.chat_json(SYSTEM, text, SCHEMA, examples=EXAMPLES), "local"
        except Exception as e:
            notes.append(f"手元の模型で読めなかった（{type(e).__name__}: {str(e)[:120]}）")
    if got is None:
        if re.fullmatch(r"[\x20-\x7e\n]+", text.strip()):
            got, reader = {"tags": text.split(","), "negative": [], "summary": "英語のタグとしてそのまま使った",
                           "allowed": True, "reason": ""}, "tags"
        else:
            if local is not None and notes and "LocalLLMError" in notes[0] and "HTTP Error" not in notes[0] and "urlopen" not in notes[0]:
                why = f"手元の模型（{local.model or '既定'}）では描く言葉に直せなかった。画面の「言葉の模型」で大きい模型に替えるか、英語のタグをカンマ区切りで書く"
            elif local is not None and notes:
                why = "手元の模型の窓口につながらない。`sh app/start.sh` で起こすか、画面の「言葉の模型」で窓口を選ぶ。英語のタグをカンマ区切りで書いてもよい"
            else:
                why = "日本語を描く言葉に直す手元の模型が無い。`sh tools/llm/setup.sh` で入れて app/start.sh で起こすか、英語のタグをカンマ区切りで書く"
            return {"allowed": False, "reason": why, "prompt": "", "negative": "", "tags": [], "summary": "",
                    "reader": None, "notes": notes}
    tags = _unasked_colors(_clean(got.get("tags", [])), text)
    neg = _clean(got.get("negative", []), negative=True)
    if tags and not any(re.fullmatch(r"\d+(girl|boy|other)s?", t) for t in tags):
        # 人数と性別が無いと、描く模型は人を描かないことがある。頼みごとの言葉から足す
        who = "1boy" if re.search(r"少年|男|青年|おじ|お兄|彼|王子|紳士", text) else "1girl"
        tags = [who, "solo"] + tags
    if not got.get("allowed", True):
        return {"allowed": False, "reason": got.get("reason") or "描かない頼みごと", "prompt": "", "negative": "",
                "tags": tags, "summary": got.get("summary", ""), "reader": reader, "notes": notes}
    why = blocked_tags(tags)
    if why:
        return {"allowed": False, "reason": why, "prompt": "", "negative": "", "tags": tags,
                "summary": got.get("summary", ""), "reader": reader, "notes": notes}
    if not tags:
        return {"allowed": False, "reason": "描く言葉が1つも作れなかった。言い方を変えて頼む", "prompt": "", "negative": "",
                "tags": [], "summary": got.get("summary", ""), "reader": reader, "notes": notes}
    return {"allowed": True, "reason": "", "prompt": ", ".join(tags), "negative": ", ".join(neg), "tags": tags,
            "summary": got.get("summary", ""), "reader": reader, "notes": notes}


def full_prompt(prompt: str, negative: str = "") -> tuple[str, str]:
    """描く直前の言葉。画質の言葉を足し、打ち消しには描かないものを必ず入れる。描かない言葉があれば ValueError。"""
    why = blocked_tags(prompt.split(","))
    if why:
        raise ValueError(why)
    pos = ", ".join(x for x in (prompt.strip().strip(","), QUALITY) if x)
    neg = ", ".join(x for x in (SAFE_NEGATIVE, negative.strip().strip(","), NEGATIVE) if x)
    return pos, neg


def draw(prompt: str, negative: str, out: Path, seed: int = 0, count: int = 1, width: int = 832, height: int = 1216,
         steps: int = 24, on_image=None) -> list[str]:
    """Animagine で count 枚描き、out/try-<k>.png に置く。seed は 1 枚ごとに 1 ずつ進める（同じ設定で描き直せる）。"""
    import torch
    import design
    import people
    pos, neg = full_prompt(prompt, negative)
    pipe = people.pipe()
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    names = []
    for k in range(count):
        im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  num_inference_steps=steps, guidance_scale=6.0, width=width, height=height,
                  generator=torch.Generator().manual_seed(seed + k)).images[0]
        name = f"try-{k}.png"
        im.save(out / name)
        names.append(name)
        if on_image:
            on_image(k, name)
    return names
