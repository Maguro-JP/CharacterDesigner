"""自由に描く: 日本語の頼みごとを、手元の言葉の模型で描く言葉（英語のタグ）に直し、Animagine で描く。

亜人の設定資料（demi_text）の枠に入らない頼みごと（「赤いマフラーの騎士の少年」）のためのもの。
描く言葉は画面で見て直してから描ける。直した言葉も、描く前にもう一度同じ検査を通す。

描く内容の判定は tools/gen/filters.py の1か所で行う（利用者のフィルターと、子どもを性的に描くことだけを止める固定の制限）。
ここは頼みごとと描く言葉をそこへ渡すだけで、自分では禁止の一覧を持たない。説明は docs/filters.md。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

QUALITY = "masterpiece, best quality, very aesthetic, absurdres"
# 設定資料用の打ち消し（people.NEGATIVE）から、自由な絵で要る背景・動物の打ち消しを外したもの
NEGATIVE = ("lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, "
            "worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, artist name")


def blocked_text(text: str) -> str | None:
    import filters
    return filters.check(text)


def blocked_tags(tags) -> str | None:
    import filters
    return filters.check(", ".join(str(t) for t in tags))


def has_minor(prompt: str) -> bool:
    """子どもを表す語があるか（出来た絵の肌の検査を、子どもの頼みごとにだけ掛けるため）"""
    import filters
    return filters.has_minor(prompt)


# 性的な語があるときに打ち消しへ足す言葉（描き直しで使う）。中身は filters に置く
SAFE_NEGATIVE = "loli, shota, child, underage"


SYSTEM = (
    "日本語のキャラクターの頼みごとを、アニメ絵の画像生成（Animagine XL、Danbooru のタグ）に渡す英語のタグに直す。\n"
    "- tags: 人数と性別（1girl、1boy など）を最初に置き、髪の色と髪型、目の色、服、持ち物、表情、ポーズ、構図（full body、upper body など）、背景の順に、"
    "短い英語のタグで並べる。頼みごとに無いことは足さない（言われていない髪の色・目の色・持ち物を書かない。手本の言葉を写さない）。"
    "ただし構図と背景が無ければ full body と simple background を足す\n"
    "- negative: 頼みごとで「〜なし」「〜しない」と言われたものを英語のタグで入れる。無ければ空\n"
    "- summary: どう読んだかを日本語の1文で\n"
    "- allowed: 子どもを性的に描く頼みごとなら false、それ以外は true（大人の性的な表現・露出は true）\n"
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


def _words():
    import json
    d = json.loads((Path(__file__).resolve().parents[2] / "casts" / "free-words.json").read_text())["words"]
    return sorted(d.items(), key=lambda kv: -len(kv[0]))


def ensure_words(text: str, tags: list[str]) -> tuple[list[str], list[str]]:
    """頼みごとに対応表の言葉があるのに描く言葉に入っていなければ足す。足したものも返す（出来事に出すため）。
    小さい言葉の模型は「スチームパンク」を落として robot mechanic と読んだ。突き合わせ（tagger）は描く言葉と絵の間しか見ないので、
    頼みごとから描く言葉への落ちはここで止める。長い言葉から当て、当たった所は消してから次へ（「魔法使い」の中の「杖」を拾わないため）"""
    rest, added = text, []
    low = {t.lower() for t in tags}
    for ja, en in _words():
        if ja in rest:
            rest = rest.replace(ja, "　")
            alts = [a.strip().lower() for a in en.split("|")]
            if not any(a in t for a in alts for t in low):
                added.append(en.split("|")[0])
                low.add(alts[0])
    if not added:
        return tags, []
    head = [t for t in tags if re.fullmatch(r"\d+(girl|boy|other)s?|solo", t)]
    return head + added + [t for t in tags if t not in head], added


def describe(text: str, local=None, recalled=()) -> dict:
    """頼みごとを描く言葉に直す。返り値: {allowed, reason, prompt, negative, tags, summary, reader, notes}。
    読み手が無いとき: 頼みごとが英語のタグならそのまま使い、日本語なら手元の模型を起こすよう返す。"""
    notes = []
    why = blocked_text(text)
    if why:
        return {"allowed": False, "reason": why, "prompt": "", "negative": "", "tags": [], "summary": "", "reader": "check", "notes": notes}
    got, reader = None, None
    if local is not None:
        try:
            # 前に通った似た頼みごと（記憶）があれば、手本の受け答えに足す。同じ人の好みに寄せるため
            mem = tuple((r["text"], {"tags": [t.strip() for t in r["prompt"].split(",") if t.strip()], "negative": [],
                                     "summary": "前に通った描き方", "allowed": True, "reason": ""}) for r in recalled if r.get("text"))
            got, reader = local.chat_json(SYSTEM, text, SCHEMA, examples=EXAMPLES + mem), "local"
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
    if reader == "local":
        tags, filled = ensure_words(text, tags)
        if filled:
            notes.append(f"言葉の模型が落とした {', '.join(filled)} を対応表から足した")
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
    import filters
    # 宗教・文化の配慮は止めずに知らせる（描くかは利用者が決める）。頼みごとと描く言葉の両方で見る
    notes += [n for n in filters.advice_lines(text + ", " + ", ".join(tags)) if n not in notes]
    return {"allowed": True, "reason": "", "prompt": ", ".join(tags), "negative": ", ".join(neg), "tags": tags,
            "summary": got.get("summary", ""), "reader": reader, "notes": notes}


def full_prompt(prompt: str, negative: str = "") -> tuple[str, str]:
    """描く直前の言葉。画質の言葉を足し、打ち消しには描かないものを必ず入れる。描かない言葉があれば ValueError。"""
    why = blocked_tags(prompt.split(","))
    if why:
        raise ValueError(why)
    pos = ", ".join(x for x in (prompt.strip().strip(","), QUALITY) if x)
    import filters
    neg = ", ".join(x for x in (filters.negative(prompt), negative.strip().strip(","), NEGATIVE) if x)
    return pos, neg


def draw(prompt: str, negative: str, out: Path, seed: int = 0, count: int = 1, width: int = 832, height: int = 1216,
         steps: int = 24, on_image=None, lora: str = "", pose: str = "", pose_strength: float = 0.93,
         ref: str = "", ref_scale: float = 0.5, hires: float = 1.0, long: int = 0, face: bool = False,
         light: str = "", hair_color: str = "", hair_inner: str = "", light_strength: float = 0.78,
         control: str = "", control_scale: float = 0.5, control_end: float = 0.4) -> list[str]:
    """Animagine で count 枚描き、out/try-<k>.png に置く。seed は 1 枚ごとに 1 ずつ進める（同じ設定で描き直せる）。
    ref は参考画像のファイル（tools/gen/refsearch.py で保存したもの）。画風と色を読ませる（IP-Adapter、強さ ref_scale）。
    姿勢の下絵（pose）と一緒には使えない（下絵から描き直す経路は手本を読まない）。
    hires が 1 より大きければ、描いた絵をその倍率に引き伸ばして弱く描き直す（tools/gen/hires.py。1.5 倍で1枚 約6分増える）。
    light（光の設計の名前。tools/gen/lightplan.py の PLANS）を渡すと、その光を当てた 3D の素体を撮って下絵にし、
    そこから描く（強さ light_strength）。立体に沿った影と縁の光が下絵から来る。hair_color と hair_inner は素体の髪と内側の色。
    control（姿勢の下絵。奥行きの絵、近いほど白）を渡すと、形だけを ControlNet で縛って描く。持ち方とポーズを指定どおりにする
    （言葉だけでは「両手で柄・切っ先を床」が描き方を変えた6枚とも守られなかった）。縛るのは描く途中まで（control_end）。
    最後まで縛ると人形の裸の輪郭がそのまま出た。強さ 0.5・前半 4 割が一番よかった（docs/knowledge/ai-drawing-notes.md）。
    face なら、顔と髪の周りを切り出して大きく描き直す（tools/gen/detail.py。下絵と同じ言葉を渡す。約3分増える）。
    順番は 描く → hires → 顔 → 拡大。拡大は最後の仕上げで、形の崩れは直さない。
    long が 0 より大きければ、最後に長い辺がその画素数になるまで AI で拡大する（tools/gen/upscale.py。4096 で1枚 約5分増える）"""
    import torch
    import design
    import people
    pos, neg = full_prompt(prompt, negative)
    pipe = people.pipe()
    # 素材の棚の LoRA（assets.get が使えると言ったものだけ）。描き終わったら外し、次の仕事に持ち越さない
    import assets
    item = assets.get(lora) if lora else None
    if lora and item is None:
        raise ValueError(f"素材「{lora}」は使えない（無いか、出典とライセンスが書かれていない）")
    if item:
        if item["trigger"] and item["trigger"] not in pos:
            pos = f"{item['trigger']}, {pos}"
        pipe.load_lora_weights(str(assets.path(lora)), adapter_name=lora)
        pipe.set_adapters([lora], adapter_weights=[item["weight"]])
    # 姿勢の下絵があれば、その絵から描き直す（img2img）。構図と姿勢は下絵から、絵柄と中身は言葉から来る
    under = None
    if pose:
        from PIL import Image
        import demi
        path = assets.get_pose(pose)
        if path is None:
            raise ValueError(f"姿勢の下絵「{pose}」は使えない（無いか、出典とライセンスが書かれていない）")
        under = Image.open(path).convert("RGB").resize((width, height))
        pose_strength = next(x["strength"] for x in assets.list_poses() if x["name"] == pose)
        draw_pipe = demi.img2img()
    elif light:
        from PIL import Image
        import demi
        import lightplan
        lightplan.underlay(light, out / "light-underlay.png", hair_color, hair_inner, size=(width, height))
        under = Image.open(out / "light-underlay.png").convert("RGB")
        pose_strength = light_strength
        draw_pipe = demi.img2img()
    elif control:
        draw_pipe = people.control_pipe()
    else:
        draw_pipe = pipe
    ref_kw = {}
    if ref and under is None:
        from PIL import Image
        people.use_reference()
        pipe.set_ip_adapter_scale(max(0.0, min(1.0, ref_scale)))
        ref_kw["ip_adapter_image"] = Image.open(ref).convert("RGB")
    elif people._IP and under is None:
        # 前の仕事で手本を読み込んだままなら、手本の無い絵は強さ 0 で白い絵を渡す（渡さないと止まる）
        from PIL import Image
        pipe.set_ip_adapter_scale(0.0)
        ref_kw["ip_adapter_image"] = Image.new("RGB", (224, 224), "white")
    if control and ref_kw:
        # 描く本体を共有しているので、手本を読む部品が載っていれば下絵の経路にも同じ部品を渡す（無いと止まる）
        draw_pipe.register_modules(image_encoder=pipe.image_encoder, feature_extractor=pipe.feature_extractor)
    try:
        pe, ne, pp, np_ = design.encode_xl(draw_pipe, pos, neg)
        names = []
        for k in range(count):
            common = dict(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                          num_inference_steps=steps, guidance_scale=6.0, generator=torch.Generator().manual_seed(seed + k))
            if under is not None:
                im = draw_pipe(image=under, strength=pose_strength, **common).images[0]
            elif control:
                from PIL import Image
                cimg = Image.open(control).convert("RGB").resize((width, height))
                im = draw_pipe(control_image=[cimg], control_mode=[1], controlnet_conditioning_scale=control_scale,
                               control_guidance_end=control_end, width=width, height=height, **common, **ref_kw).images[0]
            else:
                im = draw_pipe(width=width, height=height, **common, **ref_kw).images[0]
            name = f"try-{k}.png"
            im.save(out / name)
            if hires > 1.0:
                import hires as hires_mod
                hires_mod.upscale(out / name, out / name, prompt, negative, scale=hires, seed=seed + k)
            if face:
                import detail as detail_mod
                detail_mod.detail(out / name, out / name, prompt, negative, seed=seed + k)
            if long > 0:
                import upscale as upscale_mod
                upscale_mod.upscale(out / name, out / name, long)
            names.append(name)
            # 描いたら必ず検品する。結果は <絵>.qc.json。呼び忘れで検品なしの絵が次へ回らないよう、ここで毎回走らせる
            import qc
            qc.auto_check(str(out / name), prompt)
            if on_image:
                on_image(k, name)
    finally:
        if item:
            pipe.unload_lora_weights()
    return names
