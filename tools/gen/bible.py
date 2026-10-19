"""設定資料集: キャラクターと世界観を保存し、場面・構図・服・ポーズを変えても同じキャラクターとして描かせる。

画像生成の AI はキャラクターを覚えない。同じ頼み方でも、描くたびに顔・髪・服の細部・色が変わる。
そこで、キャラクターごとに「変えない言葉」（髪・目・体・いつもの服）、色見本、装飾と持ち物、手本の絵を残し、
描くときは毎回それを組み立て直して渡す。手本の絵は IP-Adapter で読ませ、言葉で決めきれない顔つきや配色を寄せる。
世界観も同じく、世界ごとに雰囲気の言葉と場所（背景）を残す。

置き場所: bible/characters/<id>.json と bible/characters/<id>/（手本の絵）、bible/worlds/<id>.json と bible/worlds/<id>/

  python3 tools/gen/bible.py new-character knight --name 灯りの騎士 --look "1girl, brown hair, ..." --outfit "silver plate armor, ..."
  python3 tools/gen/bible.py add-item knight lantern --name ランタン --tags "holding lantern" [--image path]
  python3 tools/gen/bible.py add-image knight color path/to/image.png      # 手本の絵（color / lineart / sheet など）
  python3 tools/gen/bible.py palette knight                                # 手本の色の絵から色見本を取る
  python3 tools/gen/bible.py new-world citadel --name 灯りの城塞 --tags "medieval fantasy, snowy mountains, ..."
  python3 tools/gen/bible.py add-location citadel gate --name 城門 --tags "castle gate, snow, night, torches"
  python3 tools/gen/bible.py prompt knight --scene "walking" --pose "looking back" --world citadel --location gate --items lantern
  python3 tools/gen/bible.py draw knight OUTDIR --scene ... [--outfit "差し替える服"] [--ref-scale 0.6] [--count 2]
  python3 tools/gen/bible.py show knight
  python3 tools/gen/bible.py sheet knight OUT.html                         # 設定資料のページ（絵を埋め込んだ1つの HTML）
  python3 tools/gen/bible.py body knight                                   # 体の設計図（部位の数。検品で照らす）
  python3 tools/gen/bible.py set-body nagi ryu                              # 設計図を選ぶ（既定は humanoid。casts/body-plans.json）
  python3 tools/gen/bible.py set-eyes knight --tags "tareme, large brown eyes, ..." --notes "垂れ目。ハイライトは右上に2つ"
  python3 tools/gen/bible.py add-expression knight wry --name 苦笑い --tags "wry smile, sweatdrop, one eye closed"
  python3 tools/gen/bible.py expressions knight OUTDIR [--base 顔の基準の絵] [--only smile,angry]   # 表情差分
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIBLE = ROOT / "bible"


def _path(kind: str, ident: str) -> Path:
    return BIBLE / kind / f"{ident}.json"


def load(kind: str, ident: str) -> dict:
    p = _path(kind, ident)
    if not p.exists():
        raise SystemExit(f"{kind} の {ident} は保存されていない（{p}）")
    return json.loads(p.read_text(encoding="utf-8"))


def save(kind: str, data: dict) -> Path:
    p = _path(kind, data["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def new_character(ident: str, name: str, look: str, outfit: str, negative: str = "", notes: str = "") -> dict:
    data = {"id": ident, "name": name,
            "look": look,          # 変えない見た目（性別・髪・目・体つき）
            "outfit": outfit,      # いつもの服（描くときに差し替えられる）
            "negative": negative,  # このキャラクターで描かせたくないもの
            "items": [],           # 装飾・持ち物・道具
            "images": {},          # 手本の絵（color: 色の手本、lineart: 線画、sheet: 設定画）
            "palette": [],         # 色見本（手本の色の絵から取る）
            "notes": notes}
    save("characters", data)
    return data


def add_item(ident: str, item: str, name: str, tags: str, desc: str = "", image: str | None = None,
             hold: str = "", size: str = "", avoid: str = "") -> dict:
    """持ち物・装飾を足す。hold は持ち方・付け方（どちらの手で、どこを握るか、どこに提げるか）、size は大きさ。
    名前だけで描かせると、持ち方が不自然になり、大きさも描くたびに変わった（背丈ほどの大スパナがふつうの大きさになった）"""
    data = load("characters", ident)
    entry = {"id": item, "name": name, "tags": tags, "desc": desc, "hold": hold, "size": size, "avoid": avoid}
    if image:
        entry["image"] = _copy(image, "characters", ident, f"item-{item}")
    data["items"] = [i for i in data["items"] if i["id"] != item] + [entry]
    save("characters", data)
    return entry


# 表情の既定。キャラクターに expressions が無ければこれを使い、あれば足し合わせる（同じ id は差し替える）。
# 言葉は口・眉・目の3つを必ず書く。「smile」だけだと口だけ笑って目と眉が無表情のままの絵になりやすいため
DEFAULT_EXPRESSIONS = [
    {"id": "neutral", "name": "ふだん", "tags": "neutral expression, closed mouth, relaxed eyebrows"},
    {"id": "smile", "name": "笑顔", "tags": "gentle smile, closed mouth smile, soft eyes, relaxed eyebrows"},
    {"id": "laugh", "name": "大笑い", "tags": "laughing, open mouth, closed eyes, happy, raised eyebrows"},
    {"id": "angry", "name": "怒り", "tags": "angry, furrowed brow, v-shaped eyebrows, clenched teeth, glaring"},
    {"id": "sad", "name": "悲しみ", "tags": "sad, downturned eyebrows, teary eyes, frown, looking down"},
    {"id": "surprised", "name": "驚き", "tags": "surprised, wide eyes, small pupils, open mouth, raised eyebrows"},
    {"id": "blush", "name": "照れ", "tags": "embarrassed, blush, averted eyes, worried eyebrows, wavy mouth"},
    {"id": "determined", "name": "決意", "tags": "determined, serious, narrowed eyes, closed mouth, furrowed brow"},
]


def set_eyes(ident: str, tags: str, notes: str = "") -> dict:
    """目の設計を決める。tags は描く言葉（形・瞳の色・ハイライト・まつ毛・眉）、notes は人が読む意図。
    目は顔の印象の大半を決めるのに、look の「brown eyes」だけでは描くたびに形もハイライトも変わった"""
    data = load("characters", ident)
    data["eyes"] = {"tags": tags, "notes": notes}
    save("characters", data)
    return data["eyes"]


def body_plan(ident: str) -> dict:
    """キャラクターの体の設計図（casts/body-plans.json）。body が無ければ人型。検品の棚卸しで部位の数を照らす"""
    plans = json.loads((ROOT / "casts" / "body-plans.json").read_text(encoding="utf-8"))["plans"]
    key = load("characters", ident).get("body", "humanoid")
    if key not in plans:
        raise SystemExit(f"体の設計図「{key}」は無い。選べるもの: {', '.join(plans)}")
    return {"id": key, **plans[key]}


def set_body(ident: str, plan: str) -> dict:
    """体の設計図を選ぶ（humanoid、quadruped、dragon、ryu、centaur など）"""
    data = load("characters", ident)
    data["body"] = plan
    save("characters", data)
    return body_plan(ident)


def add_expression(ident: str, expr: str, name: str, tags: str) -> dict:
    """そのキャラクターらしい表情を足す（既定の表情と同じ id なら差し替える）。性格に合う表情をここに持つ"""
    data = load("characters", ident)
    entry = {"id": expr, "name": name, "tags": tags}
    data["expressions"] = [e for e in data.get("expressions", []) if e["id"] != expr] + [entry]
    save("characters", data)
    return entry


def expressions_of(ident: str) -> list[dict]:
    """既定の表情に、キャラクター固有の表情を重ねた一覧（既定の順のあとに固有のもの）"""
    own = {e["id"]: e for e in load("characters", ident).get("expressions", [])}
    out = [own.pop(e["id"], e) for e in DEFAULT_EXPRESSIONS]
    return out + list(own.values())


def _copy(src: str, kind: str, ident: str, stem: str) -> str:
    from PIL import Image
    d = BIBLE / kind / ident
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{stem}.jpg"
    im = Image.open(src).convert("RGB")
    im.thumbnail((832, 1216))
    im.save(out, quality=88)
    return str(out.relative_to(ROOT))


def add_image(ident: str, role: str, src: str) -> str:
    data = load("characters", ident)
    data["images"][role] = _copy(src, "characters", ident, role)
    save("characters", data)
    return data["images"][role]


def palette(ident: str, n: int = 8) -> list[str]:
    """色の手本の人物の中から、多い色を n 色取る（背景は除く）。描いた絵の色がずれたかを見比べるのに使う"""
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    data = load("characters", ident)
    src = ROOT / data["images"]["color"]
    im = Image.open(src).convert("RGB")
    alpha = np.asarray(design.cut_background(im).getchannel("A")) > 0
    px = np.asarray(im)[alpha]
    q = Image.fromarray(px.reshape(-1, 1, 3)).quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    counts = sorted(q.getcolors(), reverse=True)
    pal = q.getpalette()
    data["palette"] = ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _, i in counts]
    save("characters", data)
    return data["palette"]


def new_world(ident: str, name: str, tags: str, desc: str = "") -> dict:
    data = {"id": ident, "name": name, "tags": tags, "desc": desc, "locations": []}
    save("worlds", data)
    return data


def add_location(ident: str, loc: str, name: str, tags: str, desc: str = "", image: str | None = None, avoid: str = "") -> dict:
    data = load("worlds", ident)
    entry = {"id": loc, "name": name, "tags": tags, "desc": desc, "avoid": avoid}
    if image:
        entry["image"] = _copy(image, "worlds", ident, f"loc-{loc}")
    data["locations"] = [x for x in data["locations"] if x["id"] != loc] + [entry]
    save("worlds", data)
    return entry


def prompt(ident: str, scene: str = "", pose: str = "", outfit: str | None = None, items: list[str] | None = None,
           world: str | None = None, location: str | None = None, framing: str = "full body",
           background: bool = True, eyes_after_outfit: bool = False) -> tuple[str, str]:
    """描く言葉を組み立てる。変えない見た目を先頭に置く（後ろの言葉ほど効きが弱い。長い言葉は 75 語ずつ全部読ませている）。
    服は差し替えがあればそれを、無ければいつもの服。持ち物は名前で選ぶ（省くと全部）。場所があれば背景を付ける"""
    c = load("characters", ident)
    chosen = [i for i in c["items"] if items is None or i["id"] in items]
    # 持ち物は、物の言葉に持ち方・付け方と大きさを必ず添える
    item_words = [", ".join(x for x in (i["tags"], i.get("size", ""), i.get("hold", "")) if x) for i in chosen]
    # 持ち物は服より前に置く（後ろに置くと効きが弱く、大スパナが腰袋の小さなスパナになった）
    # 目の設計は見た目のすぐ後に置く（先頭ほど強く効く。目は顔の印象を決める）
    eyes = c.get("eyes", {}).get("tags", "")
    worn = outfit if outfit is not None else c["outfit"]
    # 目の言葉は長い（50 語ほど）。目を先に置くと服の色が 75 語の 2 つ目の塊に押され、紺のコートが 4 枚とも別の色になった。
    # eyes_after_outfit で目を服の後ろへ回す（比べてから既定を決める）
    parts = ([c["look"], *item_words, worn, eyes] if eyes_after_outfit else [c["look"], eyes, *item_words, worn]) + [pose, scene, framing]
    avoid_loc = ""
    if world:
        w = load("worlds", world)
        loc = next((x for x in w["locations"] if x["id"] == location), None) if location else None
        parts += [loc["tags"] if loc else "", w["tags"]]
        avoid_loc = loc.get("avoid", "") if loc else ""
    elif background:
        # 背景を別に持つ使い方（ensemble.py drawin、背景は下書きにある）では付けない
        parts.append("simple background, white background")
    # ジャンルの塗りと線。頭身に合う塗り方を一緒に渡す（写実寄りの塗りで 2 頭身、などの組み合わせは崩れて見える）
    g = genre(ident)
    parts.append(g.get("words", ""))
    pos = ", ".join(p.strip() for p in parts if p and p.strip())
    # 同じ物が2つ、設定に無い道具や武器、宙に浮いた物が描かれた（床に2本目のスパナ、騎士の手の黒い棒）
    guard = "duplicate items, extra weapons, extra tools, floating objects, holding unrelated object"
    # 持ち物と場所ごとの描かせないもの（腰袋に差した小さなスパナ、大広間の樽や木箱）
    avoid = [i.get("avoid", "") for i in chosen] + [avoid_loc]
    neg = ", ".join(x for x in (c.get("negative", ""), guard, g.get("negative", ""), *avoid) if x)
    return pos, neg


# 描くモード。AI が人物を絵（イラスト）にするのは、キャラデザモードで設計がそろってから。
# 設計を飛ばして言葉だけで描くと、描くたびに服・色・持ち物・顔が変わり、手や脚の数も崩れた（2026-10-17、人物 20 枚が 20 枚とも戻った）。
# 人が参考資料を付けて描くよう指示したときは、人が設計を持っているので、イラストレーターモードですぐ描いてよい


def design_status(ident: str) -> dict:
    """キャラデザモードで、まだそろっていないものを返す。missing が空なら、イラストに描いてよい。
    何をそろえるか（資料の 8 区分）は tools/gen/charsheet.py の SECTIONS が決める"""
    import charsheet
    st = charsheet.status(ident)
    missing = [f'{v["title"]}: {m}' for v in st["sections"].values() for m in v["missing"]]
    return {"id": ident, "ready": not missing, "missing": missing}


class DesignNotReady(RuntimeError):
    pass


def require_design(ident: str, reference: str | None = None) -> str:
    """描く前に呼ぶ。人の参考資料があればイラストレーターモード、無ければ設計がそろっていることを求める"""
    if reference:
        if not Path(reference).exists():
            raise DesignNotReady(f"参考資料が見つからない: {reference}")
        return "illustrator"
    st = design_status(ident)
    if not st["ready"]:
        raise DesignNotReady("キャラデザモードが終わっていない（足りないもの: " + "、".join(st["missing"]) +
                             "）。先に設計をそろえるか、人の参考資料を --reference で渡す")
    return "design"


def reference_path(ident: str, roles: tuple[str, ...] = ("color",)) -> Path | None:
    """IP-Adapter に読ませる手本の絵。roles の順に、最初にあるものを返す"""
    imgs = load("characters", ident).get("images", {})
    return next((ROOT / imgs[r] for r in roles if imgs.get(r)), None)


def reference_image(ident: str, roles: tuple[str, ...] = ("color",)):
    from PIL import Image
    p = reference_path(ident, roles)
    return Image.open(p).convert("RGB") if p else None


def draw(ident: str, outdir: str, count: int = 1, seed: int = 0, ref_scale: float = 0.6, base: str | None = None,
         strength: float = 0.8, reference: str | None = None, designing: bool = False, depth: str | None = None,
         depth_scale: float = 0.6, depth_end: float = 1.0, **kw) -> list[str]:
    """組み立てた言葉で描く。色の手本があれば IP-Adapter で読ませる（顔つき・配色を寄せる）。
    ref_scale を上げるほど手本に似るが、構図やポーズも手本に引っ張られる。
    base に下絵（人形に持ち物を持たせて描いた絵、tools/engine/pose_prop.py）を渡すと、そこから描き換える。
    言葉だけでは手と持ち物のつながりが崩れたため、位置だけは下絵で決める。strength が低いほど下絵の形が残る"""
    # 設計の手順（三面図・表情差分の基準の顔）は、設計を作るために描くので門を通らない（designing=True）。
    # 門を付けた直後、三面図そのものが「三面図がまだ無い」で止まった（2026-10-17）
    if not designing:
        require_design(ident, reference)
    import torch
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    import free_text
    import people
    c = load("characters", ident)
    pos, neg = prompt(ident, **kw)
    pos, neg = free_text.full_prompt(pos, neg)
    pipe = people.pipe()
    start = None
    if base:
        import demi
        start = Image.open(base).convert("RGB").resize((832, 1216))
    ref = None
    if ref_scale > 0:
        ref = reference_image(ident)
        if ref is not None:
            people.use_reference()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    names = []
    for k in range(count):
        args = dict(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                    width=832, height=1216, num_inference_steps=24, guidance_scale=6.0,
                    generator=torch.Generator().manual_seed(seed + k))
        if ref is not None:
            pipe.set_ip_adapter_scale(ref_scale)
            args["ip_adapter_image"] = ref
        if start is not None and depth:
            i2i = people.depth_img2img()
            del args["width"], args["height"]
            if ref is not None:
                i2i.set_ip_adapter_scale(ref_scale)
            from PIL import ImageFilter
            # 奥行きの細かい凹凸（胸や膝の起伏）を、模型が暗い影の塊として描いた。ぼかして大きな形だけを渡す
            control = Image.open(depth).convert("RGB").resize((832, 1216)).filter(ImageFilter.GaussianBlur(6))
            im = i2i(image=start, control_image=control, strength=strength,
                     controlnet_conditioning_scale=depth_scale, control_guidance_end=depth_end, **args).images[0]
        elif start is not None:
            i2i = demi.img2img()
            del args["width"], args["height"]
            if ref is not None:
                i2i.set_ip_adapter_scale(ref_scale)
            im = i2i(image=start, strength=strength, **args).images[0]
        else:
            im = pipe(**args).images[0]
        name = f"{ident}-{seed + k}.png"
        im.save(out / name)
        names.append(name)
    (out / f"{ident}-prompt.txt").write_text(pos + "\n\nnegative: " + neg + "\n", encoding="utf-8")
    return names


# 三面図の向きごとの言葉と描き換えの強さ。向きは下絵で決め、言葉は補うだけ（言葉だけでは横が斜め前、後ろが振り返った）。
# 正面は 0.8 だと顔が描かれなかった（下絵の顔をそのまま残した）ので、正面だけ強める
VIEWS = {
    "front": ("front view, facing viewer, detailed face", 0.85),
    "side": ("side view, profile, facing left", 0.8),
    "back": ("back view, from behind, facing away, head facing away", 0.8),
    "right": ("side view, profile, facing right", 0.8),
}
# 下絵の色の既定。設定に turnaround が無いキャラクターに使う
BASE_COLORS = {"skin": "240,200,170", "top": "175,175,185", "bottom": "40,40,45"}


GENRES = ROOT / "styles" / "genres.json"


def genre(ident: str) -> dict:
    """人物のジャンル（設定の genre、無ければ既定）の頭身・塗り・線の決まり。heads は範囲の中ほど。
    写実の人形にアニメの顔を描かせると、体と顔の釣り合いが崩れた。頭身は人形の側で作る"""
    d = json.loads(GENRES.read_text(encoding="utf-8"))
    key = load("characters", ident).get("genre") or d["default"]
    g = dict(d["genres"][key], id=key)
    gender = load("characters", ident).get("gender") or ("female" if "1girl" in load("characters", ident).get("look", "") else None)
    lo, hi = g.get("heads_by_gender", {}).get(gender, g["heads_tall"])
    g["heads"] = round((lo + hi) / 2, 2)
    return g


def turnaround_plan(ident: str, outdir: str, seed: int = 0) -> dict:
    """三面図の段取り: 下絵を写す命令と、向きごとに描く引数。描かずに中身だけ返す（試験と、描く前の確かめに使う）。
    下絵に無い物（マント）は絵に出なかったので、色の設定に cape・boots があれば下絵に置く"""
    c = load("characters", ident)
    colors = {**BASE_COLORS, **c.get("turnaround", {})}
    base = str(Path(outdir) / "base")
    cmd = [sys.executable, str(ROOT / "tools/engine/turnaround.py"), base]
    for k in ("skin", "top", "bottom", "cape", "boots"):
        if colors.get(k):
            cmd += [f"--{k}", colors[k]]
    for k in ("clothes", "hair", "hair_color", "split", "boots_height"):
        if colors.get(k):
            cmd += [f"--{k.replace('_', '-')}", colors[k]]
    for k in colors.get("keep", []):
        cmd += ["--keep", k]
    g = genre(ident)
    if "--heads" not in cmd and colors.get("heads", g.get("heads")):
        cmd += ["--heads", str(colors.get("heads", g.get("heads")))]
    if colors.get("long_sleeves"):
        cmd.append("--long-sleeves")
    views = {}
    for v, (words, strength) in VIEWS.items():
        # 三面図では持ち物を持たせない（人形の手は空で、持たせると手と持ち物が崩れた）
        # 下絵で正面から隠れる物（背中のマント）は言葉で補う。補わないと、正面と横で襟巻きの端がマントの代わりに垂れた
        extra = colors.get("words", "")
        views[v] = dict(base=f"{base}-{v}.png", strength=strength, seed=seed, items=[],
                        pose=", ".join(x for x in ("standing straight, arms at sides, open empty hands, hands visible",
                                                   extra, words, "character turnaround") if x))
    return {"base_cmd": cmd, "views": views}


def turnaround(ident: str, outdir: str, count: int = 2, seed: int = 0) -> dict:
    """三面図を描く: 人形の下絵を3方向から写し、向きごとに count 枚描く。検品はしない（検品担当に回す）"""
    import os
    import subprocess
    plan = turnaround_plan(ident, outdir, seed)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(ROOT / ".cache/engine/bpy"), os.environ.get("PYTHONPATH"))))}
    subprocess.run(plan["base_cmd"], check=True, env=env, cwd=ROOT)
    files = {}
    for v, kw in plan["views"].items():
        base, strength, s = kw.pop("base"), kw.pop("strength"), kw.pop("seed")
        names = draw(ident, str(Path(outdir) / v), count, s, base=base, strength=strength, designing=True, **kw)
        files[v] = [str(Path(outdir) / v / n) for n in names]
    return files


# 笑う表情。これ以外では、見た目と目の言葉から笑みの言葉を外す。外さないと、怒り・悲しみ・ふだんも
# 見た目の「gentle smile」に引かれて微笑みになった（羊娘の表情 11 種で 4 種）
SMILING = {"smile", "laugh", "tender", "blush", "embarrassed"}
_SMILE_WORDS = ("gentle smile", "smile", "smiling", "soft half-lidded eyes", "half-lidded eyes")
# 表情ごとの打ち消し。言葉で頼むだけでは隣の表情（微笑み、片目つぶり）に寄ったので、寄った先を打ち消す
EXPR_AVOID = {
    "neutral": "(smile, smiling, happy, blush, open mouth:1.3)",
    "angry": "(smile, smiling, happy, blush, sad, teary eyes:1.3)",
    "sad": "(smile, smiling, happy, angry, v-shaped eyebrows:1.3)",
    "laugh": "(one eye closed, wink, closed mouth:1.3)",
    "determined": "(smile, blush, sad:1.2)",
    "surprised": "(smile, closed mouth:1.2)",
}


def _drop_smile(text: str) -> str:
    parts = [p.strip() for p in text.split(",")]
    return ", ".join(p for p in parts if p and p.strip("() ").split(":")[0] not in _SMILE_WORDS)


def expressions_plan(ident: str, only: list[str] | None = None) -> list[dict]:
    """表情差分の段取り: 表情ごとの描く言葉。顔だけを描き直すので、言葉は顔に関わるもの（見た目・目・表情）に絞る。
    服や持ち物の言葉を入れると、顔の枠の中に服の柄や持ち物が描き込まれやすい"""
    c = load("characters", ident)
    eyes = c.get("eyes", {}).get("tags", "")
    out = []
    for e in expressions_of(ident):
        if only and e["id"] not in only:
            continue
        smiling = e["id"] in SMILING
        look, eye = (c["look"], eyes) if smiling else (_drop_smile(c["look"]), _drop_smile(eyes))
        # 表情の言葉を先頭の区切りに置く。後ろの区切りほど効きにくく、見た目の言葉の後ろに置くと表情が消えた
        words = ", ".join(x for x in (e["tags"], look, eye, "portrait, face focus, detailed eyes") if x)
        avoid = e.get("avoid") or EXPR_AVOID.get(e["id"], "")
        out.append({"id": e["id"], "name": e["name"], "prompt": words,
                    "negative": ", ".join(x for x in (avoid, c.get("negative", ""), "extra eyes, asymmetrical eyes, different eye colors") if x)})
    return out


def expressions(ident: str, outdir: str, base: str | None = None, seed: int = 0, strength: float = 0.85,
                only: list[str] | None = None, ref_scale: float = 0.0) -> dict:
    """表情差分を描く。顔の基準の絵（無ければ胸から上を1枚描く）の顔の枠だけを、表情ごとに描き直す。
    髪・服・体は基準の絵のまま残るので、表情を変えても同じ人物に見えやすい。並べた図 expressions.png も書く"""
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).parent))
    import imgproc
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    if base is None:
        name = draw(ident, str(out / "base"), 1, seed, designing=True, items=[], framing="upper body, portrait",
                    pose="looking at viewer, facing viewer, " + DEFAULT_EXPRESSIONS[0]["tags"])[0]
        base = str(out / "base" / name)
    im = Image.open(base).convert("RGB")
    # 描き直すのは顔の枠（顔の 0.8 倍の余白）を拡大した絵だが、貼り戻すのは顔の範囲だけ。髪・襟巻き・鎧は基準の絵のまま
    box = imgproc.face_box(base, im, margin=0.8)
    if box is None:
        raise SystemExit(f"顔が見つからない: {base}")
    mask = imgproc.face_mask(base, im)
    # 手本の色の絵があれば、顔の描き直しにも読ませる（表情を変えても顔つきを保つ）
    c = load("characters", ident)
    ref = Image.open(ROOT / c["images"]["color"]).convert("RGB") if c["images"].get("color") and ref_scale > 0 else None
    if ref is not None:
        import people
        people.use_reference()
    files = {}
    for k, e in enumerate(expressions_plan(ident, only)):
        res = imgproc.face_redraw(im, box, e["prompt"], e["negative"], strength=strength, seed=seed + k, ref=ref, ref_scale=ref_scale, mask=mask)
        p = out / f"expr-{e['id']}.png"
        res.save(p)
        files[e["id"]] = str(p)
    # 並べた図: 顔の範囲の外接枠を同じ大きさで4列に並べる（顔の位置がそろっている方が差が分かる。
    # 描き直しの枠のまま並べると胸まで入り、顔が小さくて表情の差が見えなかった）
    fy, fx = np.nonzero(np.asarray(mask) > 128)
    pad = int((fy.max() - fy.min()) * 0.1)
    fbox = (max(fx.min() - pad, 0), max(fy.min() - pad, 0), min(fx.max() + pad, im.width), min(fy.max() + pad, im.height))
    side = 256
    faces = [Image.open(f).crop(fbox).resize((side, side)) for f in files.values()]
    cols = 4
    sheet = Image.new("RGB", (side * cols, side * ((len(faces) + cols - 1) // cols)), "white")
    for i, f in enumerate(faces):
        sheet.paste(f, (side * (i % cols), side * (i // cols)))
    sheet.save(out / "expressions.png")
    return {"base": base, "box": [int(v) for v in box], "files": files, "sheet": str(out / "expressions.png")}


SHEET_CSS = """
:root { --paper:#fbfaf7; --ink:#141313; --sub:#5d5853; --rule:#d9d4cd; --accent:#d23a26;
  --display:"Dela Gothic One","Hiragino Sans","Yu Gothic",sans-serif; --body:"Zen Kaku Gothic New","Hiragino Sans","Yu Gothic",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace; color-scheme: light; }
html,body { background:var(--paper); color:var(--ink); }
body { font-family:var(--body); font-size:14px; line-height:1.75; padding-inline:16px; padding-block:32px; }
.sheet { max-width:1100px; margin:0 auto; display:grid; gap:28px; }
header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:end; gap:12px; border-bottom:3px solid var(--ink); padding-bottom:10px; }
h1 { font-family:var(--display); font-weight:400; font-size:clamp(28px,5vw,44px); margin:0; }
.id { font-family:var(--mono); color:var(--sub); }
h2 { font-size:13px; letter-spacing:.2em; color:var(--accent); margin:0 0 8px; }
.cols { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:28px; }
dl { margin:0; display:grid; gap:8px; } dl div { display:grid; grid-template-columns:7em minmax(0,1fr); gap:8px; border-top:1px solid var(--rule); padding-top:8px; }
dt { color:var(--sub); } dd { margin:0; } code { font-family:var(--mono); font-size:12.5px; }
.swatches { display:flex; flex-wrap:wrap; gap:8px; } .sw { width:64px; } .sw i { display:block; height:40px; border:1px solid var(--rule); }
.sw span { font-family:var(--mono); font-size:11px; color:var(--sub); }
.imgs { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }
figure { margin:0; } figure img { width:100%; height:auto; display:block; border:1px solid var(--rule); background:#fff; }
figcaption { font-size:12px; color:var(--sub); margin-top:4px; }
.items { list-style:none; margin:0; padding:0; display:grid; gap:8px; } .items li { border-top:1px solid var(--rule); padding-top:8px; }
@media (max-width:760px) { .cols { grid-template-columns:minmax(0,1fr); } }
"""

ROLE_JA = {"color": "色の手本", "lineart": "線画", "colored-lineart": "線画に色を置いたもの", "sheet": "設定画"}


# 設定資料の「ポーズ」と「髪型差分」。設定資料集に poses / hairstyles が無ければ既定を使う。
# 既定のポーズは資料の決まり（立ち・歩き・役どころの動作・持ち物を使う）に合わせる
DEFAULT_POSES = [
    {"id": "stand", "name": "立ち", "tags": "standing, relaxed pose, arms at sides"},
    {"id": "walk", "name": "歩き", "tags": "walking, mid-stride, one foot forward"},
    {"id": "work", "name": "役どころの動作", "tags": "doing her job, three-quarter view"},
]


def variants_plan(ident: str, kind: str) -> list[dict]:
    """描く差分の一覧。kind は pose か hairstyle。髪型は設定資料集の hairstyles にしか無い（既定を作らない。髪型は人物ごとの設計）"""
    c = load("characters", ident)
    if kind == "pose":
        return c.get("poses") or DEFAULT_POSES
    if kind == "hairstyle":
        return c.get("hairstyles", [])
    raise ValueError(kind)


def variants(ident: str, outdir: str, kind: str, seed: int = 0, ref_scale: float = 0.5) -> dict:
    """ポーズは全身、髪型は胸から上で描く。色の手本（color）を読ませ、服と顔を保つ。役割の名前 pose-<id> / hairstyle-<id> で出す"""
    out = {}
    for v in variants_plan(ident, kind):
        sub = Path(outdir) / f"{kind}-{v['id']}"
        if kind == "pose":
            names = draw(ident, str(sub), seed=seed, ref_scale=ref_scale, designing=True, pose=v["tags"])
        else:
            # 髪型の言葉は見た目の後ろに入る。いつもの髪型の言葉に負けたら、hairstyles の tags を強める
            names = draw(ident, str(sub), seed=seed, ref_scale=ref_scale, designing=True,
                         pose=v["tags"], framing="upper body, portrait, bust shot")
        out[f"{kind}-{v['id']}"] = str(sub / names[0])
    return out


def sheet(ident: str, out: str) -> dict:
    """保存した設定から、キャラクターの設定資料のページを1つの HTML に組む（絵は埋め込む）。
    文字は絵に焼き込まない（手元の日本語の書体が中国語用で、字形が崩れるため）"""
    import base64
    import html
    c = load("characters", ident)

    def img(rel):
        return "data:image/jpeg;base64," + base64.b64encode((ROOT / rel).read_bytes()).decode()

    e = html.escape
    rows = [("変えない見た目", c["look"]), ("いつもの服", c["outfit"]), ("描かせない言葉", c.get("negative") or "（無し）")]
    # 場面の絵（scene-<場所の id>）の見出しは、世界観に保存した場所の名前にする
    places = {}
    for w in sorted((BIBLE / "worlds").glob("*.json")) if (BIBLE / "worlds").exists() else []:
        wd = json.loads(w.read_text(encoding="utf-8"))
        places.update({x["id"]: f'{wd["name"]}の{x["name"]}' for x in wd["locations"]})

    def caption(k):
        if k.startswith("scene-"):
            return "場面: " + places.get(k[6:], k[6:])
        return ROLE_JA.get(k, k)
    figs = "".join(f'<figure><img src="{img(v)}" alt="{e(c["name"])}の{e(caption(k))}"><figcaption>{e(caption(k))}</figcaption></figure>'
                   for k, v in c["images"].items())
    items = "".join(f'<li><b>{e(i["name"])}</b> <code>{e(i["tags"])}</code><br>{e(i.get("desc", ""))}'
                    + (f'<br>持ち方: <code>{e(i["hold"])}</code>' if i.get("hold") else "")
                    + (f'<br>大きさ: <code>{e(i["size"])}</code>' if i.get("size") else "")
                    + ''
                    + (f'<img src="{img(i["image"])}" alt="{e(i["name"])}" style="max-width:160px;display:block;margin-top:6px">' if i.get("image") else "")
                    + "</li>" for i in c["items"]) or "<li>（まだ無い）</li>"
    sw = "".join(f'<div class="sw"><i style="background:{e(h)}"></i><span>{e(h)}</span></div>' for h in c.get("palette", []))
    body = f"""<title>{e(c["name"])}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@400;700&family=JetBrains+Mono&display=swap">
<style>{SHEET_CSS}</style>
<div class="sheet">
<header><h1>{e(c["name"])}</h1><span class="id">{e(c["id"])}</span></header>
<p>{e(c.get("notes", ""))}</p>
<div class="cols">
<section><h2>設定</h2><dl>{"".join(f"<div><dt>{e(k)}</dt><dd><code>{e(v)}</code></dd></div>" for k, v in rows)}</dl></section>
<section><h2>色見本</h2><div class="swatches">{sw or "（まだ無い）"}</div><h2 style="margin-top:20px">装飾・持ち物</h2><ul class="items">{items}</ul></section>
</div>
<section><h2>手本と場面</h2><div class="imgs">{figs}</div></section>
</div>
"""
    Path(out).write_text(body, encoding="utf-8")
    return {"out": out, "images": len(c["images"]), "bytes": len(body.encode())}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new-character"); s.add_argument("id"); s.add_argument("--name", required=True)
    s.add_argument("--look", required=True); s.add_argument("--outfit", default=""); s.add_argument("--negative", default="")
    s.add_argument("--notes", default="")
    s = sub.add_parser("add-item"); s.add_argument("id"); s.add_argument("item"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True); s.add_argument("--desc", default=""); s.add_argument("--image")
    s.add_argument("--hold", default="", help="持ち方・付け方（例: gripping the handle with both hands）"); s.add_argument("--size", default="")
    s.add_argument("--avoid", default="", help="この持ち物で描かせないもの（例: small wrench, wrench on belt）")
    s = sub.add_parser("add-image"); s.add_argument("id"); s.add_argument("role"); s.add_argument("src")
    s = sub.add_parser("palette"); s.add_argument("id")
    s = sub.add_parser("new-world"); s.add_argument("id"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True); s.add_argument("--desc", default="")
    s = sub.add_parser("add-location"); s.add_argument("id"); s.add_argument("loc"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True); s.add_argument("--desc", default=""); s.add_argument("--image")
    s.add_argument("--avoid", default="", help="この場所で描かせないもの（例: barrels, crates）")
    for name in ("prompt", "draw"):
        s = sub.add_parser(name); s.add_argument("id")
        if name == "draw":
            s.add_argument("out"); s.add_argument("--count", type=int, default=1); s.add_argument("--seed", type=int, default=0)
            s.add_argument("--ref-scale", type=float, default=0.6)
            s.add_argument("--base", help="下絵の画像（tools/engine/pose_prop.py の出力）"); s.add_argument("--strength", type=float, default=0.8)
            s.add_argument("--reference", help="人が渡した参考資料の画像。渡すとイラストレーターモードで、設計がそろっていなくても描く")
        s.add_argument("--scene", default=""); s.add_argument("--pose", default=""); s.add_argument("--outfit")
        s.add_argument("--items", help="持ち物の id をカンマ区切りで。省くと全部"); s.add_argument("--world"); s.add_argument("--location")
        s.add_argument("--framing", default="full body")
    s = sub.add_parser("show"); s.add_argument("id")
    s = sub.add_parser("sheet"); s.add_argument("id"); s.add_argument("out")
    s = sub.add_parser("settei", help="設定画 1 枚（三面図・頭身の目盛り・表情・部位の拡大・色指定）を PNG に組む（tools/gen/settei.py）")
    s.add_argument("id"); s.add_argument("out"); s.add_argument("--expressions"); s.add_argument("--details"); s.add_argument("--views")
    s = sub.add_parser("set-body"); s.add_argument("id"); s.add_argument("plan")
    s = sub.add_parser("body"); s.add_argument("id")
    s = sub.add_parser("set-eyes"); s.add_argument("id"); s.add_argument("--tags", required=True); s.add_argument("--notes", default="")
    s = sub.add_parser("add-expression"); s.add_argument("id"); s.add_argument("expr"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True)
    s = sub.add_parser("expressions", help="表情差分: 顔の基準の絵の顔だけを、表情ごとに描き直す")
    s.add_argument("id"); s.add_argument("out"); s.add_argument("--base"); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--strength", type=float, default=0.85); s.add_argument("--only", help="表情の id をカンマ区切りで")
    s.add_argument("--ref-scale", type=float, default=0.0, help="手本の顔に寄せる強さ。既定は 0（使わない）。0.4 では手本の開いた目に引っ張られ、目が表情ごとに動かなかった")
    s = sub.add_parser("design-status", help="キャラデザモードで、まだそろっていないもの"); s.add_argument("id")
    s = sub.add_parser("variants", help="設定資料のポーズ（pose）・髪型差分（hairstyle）を描く")
    s.add_argument("id"); s.add_argument("out"); s.add_argument("--kind", choices=["pose", "hairstyle"], required=True)
    s.add_argument("--seed", type=int, default=0); s.add_argument("--ref-scale", type=float, default=0.5)
    s = sub.add_parser("turnaround", help="三面図: 人形の下絵を3方向から写し、向きごとに描く")
    s.add_argument("id"); s.add_argument("out"); s.add_argument("--count", type=int, default=2); s.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    kw = {}
    if a.cmd in ("prompt", "draw"):
        kw = dict(scene=a.scene, pose=a.pose, outfit=a.outfit, world=a.world, location=a.location, framing=a.framing,
                  items=a.items.split(",") if a.items else None)
    r = {
        "new-character": lambda: new_character(a.id, a.name, a.look, a.outfit, a.negative, a.notes),
        "add-item": lambda: add_item(a.id, a.item, a.name, a.tags, a.desc, a.image, a.hold, a.size, a.avoid),
        "add-image": lambda: add_image(a.id, a.role, a.src),
        "palette": lambda: palette(a.id),
        "new-world": lambda: new_world(a.id, a.name, a.tags, a.desc),
        "add-location": lambda: add_location(a.id, a.loc, a.name, a.tags, a.desc, a.image, a.avoid),
        "prompt": lambda: dict(zip(("prompt", "negative"), prompt(a.id, **kw))),
        "draw": lambda: draw(a.id, a.out, a.count, a.seed, a.ref_scale, a.base, a.strength, a.reference, **kw),
        "design-status": lambda: design_status(a.id),
        "show": lambda: load("characters", a.id),
        "sheet": lambda: sheet(a.id, a.out),
        "settei": lambda: __import__("settei").compose(a.id, a.out, a.views.split(",") if a.views else None, a.expressions, a.details),
        "turnaround": lambda: turnaround(a.id, a.out, a.count, a.seed),
        "variants": lambda: variants(a.id, a.out, a.kind, a.seed, a.ref_scale),
        "set-eyes": lambda: set_eyes(a.id, a.tags, a.notes),
        "set-body": lambda: set_body(a.id, a.plan),
        "body": lambda: body_plan(a.id),
        "add-expression": lambda: add_expression(a.id, a.expr, a.name, a.tags),
        "expressions": lambda: expressions(a.id, a.out, a.base, a.seed, a.strength, a.only.split(",") if a.only else None, a.ref_scale),
    }[a.cmd]()
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
