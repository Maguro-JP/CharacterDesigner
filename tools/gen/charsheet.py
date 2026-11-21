"""キャラクターデザインの資料（設定画）に載せるものの決まりと、1 冊の資料への書き出し。

資料は 8 つの区分で作る。区分ごとに、設定資料集（bible/characters/<id>.json）の文字の欄と、絵の役割（images のキー）を決める。
全部そろうまで、キャラデザモードは終わらない（bible.design_status がここを見る）。

  1. 基本情報     名前・年齢・身長と頭身・役割・性格・背景設定
  2. 全身の四面図  正面・背面・左・右（左右は持ち物や髪の結び方が違うので、片方を裏返して作らない）
  3. ポーズ       立ち・歩き・役どころの動作・持ち物を使う、の 3 種以上
  4. 胸から上     表情差分 8 種以上、髪型差分 2 種以上
  5. 詳細         目の拡大、髪の拡大
  6. 服・装飾・武装 部位ごとの拡大（1 つ以上）と、持ち物ごとの拡大
  7. 色見本       色の名前・色の値・使う部位
  8. 補足         描くときの決まり、描いてはいけないもの

  python3 tools/gen/charsheet.py status <id>        足りないものを区分ごとに出す
  python3 tools/gen/charsheet.py render <id> <出力.html>   資料を書き出す（無い所は「未作成」）
  python3 tools/gen/charsheet.py sheet <id> <出力.html> <出力.png>   見せる1枚（四面図・表情・色見本・注記）。既定の版 classic
  python3 tools/gen/charsheet.py sheet <id> [<出力.html>] <出力.png> [--format <版>] [--theme <テーマ>]   版とテーマを選んで1枚を出す
  python3 tools/gen/charsheet.py formats   版の一覧（名前・用途・比率）
  python3 tools/gen/charsheet.py themes [<id>]   テーマの一覧。id を付けると、そのキャラクターに合う候補を並べる
テーマを付けないときは、キャラクターの設定の theme、それも無ければ既定のテーマ（studio）を使う。

見せる1枚の並べ方は docs/knowledge/learning/design-sheet-layout.md の決まりに合わせる。
四面図は横一列で足をそろえて高さの線を引き、表情は名前つきの均等なます、色見本は役と面積の割合、注記は数と位置を書く。
"""
from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402
import design  # noqa: E402,F401  SAM を読む前に模型の置き場所の既定を効かせる

# 区分: (キー, 見出し, 文字の欄, 絵の役割の決まり)。絵の役割の決まりは (接頭辞, 最少の枚数, 説明)
SECTIONS = [
    ("profile", "基本情報", ["name", "age", "height", "role", "personality", "backstory"], []),
    # 向きの回る順（正面→左→背面→右）。斜め前（3/4）は現場で最も使う向きなので枠を置くが、必須にはしない
    ("views", "全身の四面図", [], [("view-front", 1, "正面"), ("view-34", 0, "斜め前"), ("view-left", 1, "左"), ("view-back", 1, "背面"), ("view-right", 1, "右")]),
    ("poses", "ポーズ", [], [("pose-", 3, "立ち・歩き・役どころの動作・持ち物を使う")]),
    ("bust", "胸から上（表情・髪型）", ["expressions"], [("expr-", 8, "表情差分"), ("hairstyle-", 2, "髪型差分")]),
    ("details", "目と髪の詳細", ["eyes"], [("detail-eyes", 1, "目の拡大"), ("detail-hair", 1, "髪の拡大")]),
    ("outfit", "服・装飾・武装", ["outfit_parts"], [("detail-outfit-", 1, "服の部位の拡大"), ("detail-item-", 0, "持ち物の拡大（持ち物の数だけ）")]),
    ("colors", "色見本", ["colors"], []),
    ("notes", "補足", ["rules", "negative"], []),
]
# 文字の欄の見出し
FIELD_JA = {"name": "名前", "age": "年齢", "height": "身長・頭身", "role": "役割", "personality": "性格", "backstory": "背景設定",
            "expressions": "表情の一覧", "eyes": "目の設計", "outfit_parts": "服の部位", "colors": "色", "rules": "描くときの決まり",
            "negative": "描いてはいけないもの"}


def _roles(c: dict, prefix: str) -> list[str]:
    return sorted(k for k in c.get("images", {}) if k == prefix or (prefix.endswith("-") and k.startswith(prefix)))


def status(ident: str) -> dict:
    """区分ごとに、そろっていない文字の欄と絵を返す。missing が全部空なら資料は完成"""
    c = bible.load("characters", ident)
    out = {}
    for key, title, fields, roles in SECTIONS:
        miss = [FIELD_JA.get(f, f) for f in fields if not c.get(f)]
        for prefix, least, what in roles:
            need = len(c.get("items", [])) if prefix == "detail-item-" else least
            have = len(_roles(c, prefix))
            if have < need:
                miss.append(f"{what}の絵（{prefix}…、{have}/{need}）")
        out[key] = {"title": title, "missing": miss}
    return {"id": ident, "ready": not any(v["missing"] for v in out.values()), "sections": out}


CSS = """
:root { --paper:#fbfaf7; --ink:#141313; --sub:#5d5853; --rule:#d9d4cd; --accent:#d23a26; --todo:#9a9087;
  --display:"Dela Gothic One","Hiragino Sans","Yu Gothic",sans-serif; --body:"Zen Kaku Gothic New","Hiragino Sans","Yu Gothic",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace; color-scheme: light; }
html,body { background:var(--paper); color:var(--ink); margin:0; }
body { font-family:var(--body); font-size:14px; line-height:1.75; padding:32px 16px; }
.sheet { max-width:1200px; margin:0 auto; display:grid; gap:32px; }
header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:end; gap:12px; border-bottom:3px solid var(--ink); padding-bottom:10px; }
h1 { font-family:var(--display); font-weight:400; font-size:clamp(28px,5vw,48px); margin:0; }
h2 { font-family:var(--display); font-weight:400; font-size:20px; margin:0 0 12px; display:flex; gap:10px; align-items:baseline; }
h2 small { font-family:var(--mono); font-size:12px; color:var(--accent); }
.id { font-family:var(--mono); color:var(--sub); }
section { border-top:1px solid var(--rule); padding-top:16px; }
dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; margin:0; }
dt { color:var(--sub); } dd { margin:0; }
.imgs { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:14px; }
.imgs.wide { grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); }
figure { margin:0; } figure img { width:100%; height:auto; display:block; background:#fff; border:1px solid var(--rule); }
figcaption { font-size:12px; color:var(--sub); margin-top:4px; }
.todo { color:var(--todo); border:1px dashed var(--rule); padding:10px 12px; font-size:13px; }
.sw { display:flex; gap:10px; align-items:center; } .sw i { width:44px; height:44px; border:1px solid var(--rule); display:block; flex:none; }
.sw code { font-family:var(--mono); font-size:12px; }
.swatches { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
code { font-family:var(--mono); font-size:12px; }
"""


def _img(rel: str) -> str:
    p = bible.ROOT / rel
    kind = "png" if p.suffix == ".png" else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(p.read_bytes()).decode()


def render(ident: str, out: str) -> dict:
    """資料を 1 つの HTML に書き出す（絵は埋め込む）。文字は絵に焼き込まない（手元の日本語の書体が中国語用で、字形が崩れる）"""
    c = bible.load("characters", ident)
    st = status(ident)
    e = html.escape

    def val(v):
        if isinstance(v, list):
            return "<br>".join(e(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x)) for x in v)
        if isinstance(v, dict):
            return "<br>".join(f"{e(str(k))}: {e(json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x))}" for k, x in v.items())
        return e(str(v))

    def figs(prefix, cls=""):
        roles = _roles(c, prefix)
        if not roles:
            return ""
        return f'<div class="imgs {cls}">' + "".join(
            f'<figure><img src="{_img(c["images"][r])}" alt="{e(c["name"])}の{e(r)}"><figcaption>{e(r)}</figcaption></figure>'
            for r in roles) + "</div>"

    parts = []
    for key, title, fields, roles in SECTIONS:
        miss = st["sections"][key]["missing"]
        body = ""
        if key == "colors" and c.get("colors"):
            cols = c["colors"]
            items = cols.items() if isinstance(cols, dict) else enumerate(cols)
            body += '<div class="swatches">' + "".join(
                f'<div class="sw"><i style="background:{e(str(v if isinstance(v, str) else v.get("hex", "")))}"></i>'
                f'<span>{e(str(k))}<br><code>{e(str(v if isinstance(v, str) else v.get("hex", "")))}</code></span></div>'
                for k, v in items) + "</div>"
        else:
            rows = [(FIELD_JA.get(f, f), c[f]) for f in fields if c.get(f)]
            if rows:
                body += "<dl>" + "".join(f"<dt>{e(k)}</dt><dd>{val(v)}</dd>" for k, v in rows) + "</dl>"
        for prefix, _, _ in roles:
            body += figs(prefix, "wide" if prefix in ("expr-", "hairstyle-") else "")
        if key == "outfit" and c.get("items"):
            body += "<dl>" + "".join(f'<dt>{e(i["name"])}</dt><dd>{e(i.get("desc", ""))}'
                                     + (f'<br>持ち方: {e(i["hold"])}' if i.get("hold") else "")
                                     + (f'<br>大きさ: {e(i["size"])}' if i.get("size") else "") + "</dd>" for i in c["items"]) + "</dl>"
        if miss:
            body += '<div class="todo">未作成: ' + "、".join(e(m) for m in miss) + "</div>"
        done = "完成" if not miss else f"未作成 {len(miss)}"
        parts.append(f'<section><h2>{e(title)}<small>{done}</small></h2>{body}</section>')
    page = (f'<title>{e(c["name"])} 設定資料</title>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@400;700&family=JetBrains+Mono&display=swap">'
            f'<style>{CSS}</style><div class="sheet"><header><h1>{e(c["name"])}</h1><span class="id">{e(c["id"])}</span></header>'
            + "".join(parts) + "</div>")
    Path(out).write_text(page, encoding="utf-8")
    return {"out": out, "ready": st["ready"], "missing": sum(len(v["missing"]) for v in st["sections"].values()),
            "bytes": len(page.encode())}


# 胸から上の表情の絵（832x1216）から顔と角を切り出す枠（幅・高さに対する割合）。表情差分は同じ基準の絵から
# 描き直すので顔の位置がそろっており、割合の固定で足りる。切り出さずに並べると顔が小さく、表情の差が見えなかった
FACE_CROP = (0.24, 0.05, 0.77, 0.41)
EYE_CROP = (0.30, 0.20, 0.71, 0.31)   # 目の拡大（同じ胸から上の絵での割合）
FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"   # 日本語の字形の書体（中国語用の書体は字形が崩れた）


def _fg_mask(im):
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(int)
    return (a.min(axis=2) < 235)


def _figures(im):
    """四面図の1枚の絵から、人物ごとの左右の範囲と、全員の上端・下端を返す（白い背景の列の切れ目で分ける）"""
    import numpy as np
    m = _fg_mask(im)
    cols = m.sum(axis=0) > 2
    spans, start = [], None
    for x, on in enumerate(list(cols) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start > im.width * 0.04:
                spans.append((start, x))
            start = None
    rows = np.nonzero(m.sum(axis=1) > 2)[0]
    return spans, int(rows.min()), int(rows.max())


def color_shares(im, named: dict) -> dict:
    """人物の画素を、名前つきの色の最も近いものに割り当てて、面積の割合を返す（白い背景は除く）"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(int)[_fg_mask(im)]
    names = list(named)
    ref = np.array([named[n] for n in names])
    d = ((a[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)
    idx = d.argmin(axis=1)
    total = len(idx)
    return {n: round(float((idx == i).sum()) / total, 3) for i, n in enumerate(names)}


SWATCH_JA = {"top": "カーディガン", "bottom": "ズボン", "boots": "靴", "hair_color": "髪", "blouse": "ブラウス", "skin": "肌",
             "horn": "角", "eyes": "目"}


def _swatches(c: dict) -> list[dict]:
    """色見本: 設定資料の swatches（名前 → "r,g,b"、描いた絵から測った色）か、無ければ四面図の決まりの色（turnaround の値）。
    四面図の人物の画素を最も近い色に割り当てて面積の割合を測る。決まりの色は塗りの明るい面より暗く、測ると
    カーディガンが 6% になるなど実際とずれたので、描いた絵から測った色を持たせる。
    役は面積の順に、髪と肌を除いて 主・副・アクセント（docs/knowledge/learning/character-design-basics.md の 6:3:1）"""
    from PIL import Image
    src = c.get("swatches") or {SWATCH_JA.get(k, k): c.get("turnaround", {})[k] for k in ("top", "bottom", "boots", "hair_color")
                                 if isinstance(c.get("turnaround", {}).get(k), str)}
    named = {k: tuple(int(v) for v in str(x).split(",")) for k, x in src.items()}
    shares = {}
    if not named and c.get("images", {}).get("color"):
        named, shares = _measure_parts(bible.ROOT / c["images"]["color"])
    elif c.get("images", {}).get("turnaround"):
        shares = color_shares(Image.open(bible.ROOT / c["images"]["turnaround"]), named)
    base = ("髪", "肌")
    order = [k for k in sorted(named, key=lambda k: -shares.get(k, 0)) if k not in base]
    roles = {k: r for k, r in zip(order, ("主", "副", "アクセント"))}
    return [{"key": k, "name": k, "hex": "#%02x%02x%02x" % named[k], "share": shares.get(k, 0.0),
             "role": roles.get(k, "髪・肌" if k in base else "その他")} for k in named]


PART_JA = {"hat": "帽子", "hair": "髪", "upper": "上着", "skirt": "スカート", "pants": "ズボン", "dress": "服", "belt": "ベルト",
           "left_shoe": "靴", "right_shoe": "靴", "face": "肌", "bag": "鞄", "scarf": "襟巻"}


def _measure_parts(src) -> tuple[dict, dict]:
    """決まりの色を持たない人物は、色の絵を部位分けし、部位ごとの中央の色と面積を測る。
    色見本が空だと、その欄が抜けて版の半分が空いた"""
    import numpy as np
    from PIL import Image
    import edit
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).reshape(-1, 3)
    seg = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST)).reshape(-1)
    inv = {v: k for k, v in edit.LABELS.items()}
    person = seg > 0
    named, shares = {}, {}
    for v in np.unique(seg[person]):
        ja = PART_JA.get(inv.get(int(v), ""))
        if not ja:
            continue
        px = a[seg == v]
        n = shares.get(ja, 0) + len(px) / max(1, person.sum())
        if n < 0.02:
            continue
        named[ja] = tuple(int(x) for x in np.median(px, axis=0))
        shares[ja] = n
    return named, shares


def _notes(c: dict) -> list[str]:
    out = []
    for i in c.get("items", []):
        out.append(f"{i['name']}: {i.get('desc', '')}")
    if c.get("eyes", {}).get("notes"):
        out.append("目: " + c["eyes"]["notes"])
    return out


def sheet(ident: str, out_html: str, out_png: str, width: int = 2400) -> dict:
    """見せる1枚を、同じ並べ方で HTML と PNG に書き出す。載せるのは images にある turnaround と expr-* と pose-*（検品を通した絵だけを登録する）"""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    c = bible.load("characters", ident)
    imgs = c.get("images", {})
    exprs = {e["id"]: e["name"] for e in bible.expressions_of(ident)}
    # 表情は設定の並び（ふだん→笑い→怒り…）の順に置く。名前が重なる表情（照れが2つ）は id を添える
    order = [e["id"] for e in bible.expressions_of(ident)]
    expr_roles = sorted((r for r in imgs if r.startswith("expr-")), key=lambda r: order.index(r[5:]) if r[5:] in order else 99)
    seen = [exprs.get(r[5:], r[5:]) for r in expr_roles]
    exprs = {r[5:]: (exprs.get(r[5:], r[5:]) + (f"（{r[5:]}）" if seen.count(exprs.get(r[5:], r[5:])) > 1 else "")) for r in expr_roles}
    sw = _swatches(c)
    notes = _notes(c)
    f = lambda n: ImageFont.truetype(FONT, n)
    pad, gap = 60, 40
    W = width
    # 下の段まで入る高さで作り、最後に使った所まで切る（足りないと切った所が黒くなった）
    canvas = Image.new("RGB", (W, 12000), (251, 250, 247))
    d = ImageDraw.Draw(canvas)
    d.text((pad, pad), c["name"], fill=(20, 19, 19), font=f(64))
    d.text((pad + 520, pad + 28), f"{ident}  設定資料", fill=(93, 88, 83), font=f(28))
    y = pad + 100
    d.line([(pad, y), (W - pad, y)], fill=(20, 19, 19), width=4)
    y += gap
    # 1段目: 四面図。足の位置をそろえ、上端・半分・下端に線を引く
    if imgs.get("turnaround"):
        t = Image.open(bible.ROOT / imgs["turnaround"]).convert("RGB")
        spans, top, bot = _figures(t)
        # 元の四面図が小さい（羊娘は高さ 304 画素）ので、2 倍を超えて引き伸ばさない。ぼやけて線が読めなくなった
        h = min(900, (bot - top) * 2)
        k = h / (bot - top)
        crop = t.crop((0, top, t.width, bot + 1))
        crop = crop.resize((int(crop.width * k), h), Image.LANCZOS)
        x0 = max((W - crop.width) // 2, pad + 140)   # 左の余白に高さの線の名前を置く
        d.text((pad, y), "全身の四面図", fill=(20, 19, 19), font=f(36))
        y += 60
        canvas.paste(crop, (x0, y))
        for frac, label in ((0.0, "頭の上"), (0.5, "全身の半分"), (1.0, "足の下")):
            yy = y + int(frac * (h - 1))
            d.line([(pad, yy), (W - pad, yy)], fill=(210, 58, 38), width=1)
            d.text((pad, yy - 26 if frac else yy + 4), label, fill=(210, 58, 38), font=f(20))
        names = ["正面", "横（右向き）", "横（左向き）", "背面"] if len(spans) == 4 else [""] * len(spans)
        for (a, b), nm in zip(spans, names):
            d.text((x0 + int((a + b) / 2 * k) - 20, y + h + 10), nm, fill=(93, 88, 83), font=f(26))
        y += h + 60 + gap
    # 2段目: 表情。顔の枠で切り、名前つきの均等なます
    if expr_roles:
        d.line([(pad, y), (W - pad, y)], fill=(217, 212, 205), width=1)
        y += 20
        d.text((pad, y), f"表情（{len(expr_roles)}種）", fill=(20, 19, 19), font=f(36))
        y += 60
        cols = 6 if len(expr_roles) > 8 else 4
        cell = (W - 2 * pad - (cols - 1) * 24) // cols
        for i, r in enumerate(expr_roles):
            im = Image.open(bible.ROOT / imgs[r]).convert("RGB")
            fx = FACE_CROP
            face = im.crop((int(fx[0] * im.width), int(fx[1] * im.height), int(fx[2] * im.width), int(fx[3] * im.height)))
            face = face.resize((cell, cell), Image.LANCZOS)
            cx, cy = pad + (i % cols) * (cell + 24), y + (i // cols) * (cell + 60)
            canvas.paste(face, (cx, cy))
            d.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], outline=(217, 212, 205))
            d.text((cx, cy + cell + 8), exprs.get(r[5:], r[5:]), fill=(93, 88, 83), font=f(26))
        y += ((len(expr_roles) + cols - 1) // cols) * (cell + 60) + gap
    # 3段目: ポーズ。全身を人物の範囲で切り、足の位置をそろえて横に並べる（検品を通した pose-* だけを登録する）
    pose_roles = sorted(r for r in imgs if r.startswith("pose-"))
    if pose_roles:
        d.line([(pad, y), (W - pad, y)], fill=(217, 212, 205), width=1)
        y += 20
        d.text((pad, y), f"ポーズ（{len(pose_roles)}種）", fill=(20, 19, 19), font=f(36))
        y += 60
        # 枚数が少なくても 4 列のますの大きさにする。1 枚を幅いっぱいにすると縦に伸び、1 枚の絵の高さを超えた
        cols = 4
        cell = (W - 2 * pad - (cols - 1) * 24) // cols
        ph = int(cell * 1.6)
        names = {p.get("id"): p.get("name", p.get("id")) for p in c.get("poses", []) if isinstance(p, dict)}
        for i, r in enumerate(pose_roles):
            im = Image.open(bible.ROOT / imgs[r]).convert("RGB")
            box = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 12 else 0).getbbox() or (0, 0, im.width, im.height)
            fig = im.crop(box)
            k = min(cell / fig.width, ph / fig.height)
            fig = fig.resize((max(1, int(fig.width * k)), max(1, int(fig.height * k))), Image.LANCZOS)
            cx, cy = pad + (i % cols) * (cell + 24), y + (i // cols) * (ph + 60)
            canvas.paste(fig, (cx + (cell - fig.width) // 2, cy + ph - fig.height))
            d.text((cx, cy + ph + 8), names.get(r[5:], r[5:]), fill=(93, 88, 83), font=f(26))
        y += ((len(pose_roles) + cols - 1) // cols) * (ph + 60) + gap
    # 4段目: 色見本（左）と注記（右）
    d.line([(pad, y), (W - pad, y)], fill=(217, 212, 205), width=1)
    y += 20
    d.text((pad, y), "色見本（四面図での面積）", fill=(20, 19, 19), font=f(36))
    nx = W // 2
    d.text((nx, y), "注記", fill=(20, 19, 19), font=f(36))
    y += 60
    yy = y
    for s in sw:
        rgb = tuple(int(s["hex"][i:i + 2], 16) for i in (1, 3, 5))
        d.rectangle([pad, yy, pad + 64, yy + 64], fill=rgb, outline=(217, 212, 205))
        d.text((pad + 84, yy + 4), f"{s['name']}  {s['role']}", fill=(20, 19, 19), font=f(26))
        d.text((pad + 84, yy + 36), f"{s['hex']}  {s['share'] * 100:.0f}%", fill=(93, 88, 83), font=f(22))
        yy += 84
    ny = y
    for n in notes:
        line, lines = "", []
        for ch in n:
            if d.textlength(line + ch, font=f(24)) > W - nx - pad:
                lines.append(line)
                line = ""
            line += ch
        lines.append(line)
        for ln in lines:
            d.text((nx, ny), ln, fill=(20, 19, 19), font=f(24))
            ny += 34
        ny += 14
    y = max(yy, ny) + pad
    canvas = canvas.crop((0, 0, W, y))
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png, optimize=True)
    # HTML は同じ1枚の絵を埋め込み、注記と色見本は文字でも持つ（検索と写しのため）
    e = html.escape
    rows = "".join(f'<tr><td><i style="background:{s["hex"]}"></i></td><td>{e(s["name"])}</td><td>{e(s["role"])}</td>'
                   f'<td><code>{s["hex"]}</code></td><td>{s["share"] * 100:.0f}%</td></tr>' for s in sw)
    page = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(c["name"])} 設定資料</title><style>{CSS}'
            'table{border-collapse:collapse} td{padding:4px 10px;border-bottom:1px solid var(--rule)} td i{display:block;width:28px;height:28px;border:1px solid var(--rule)}'
            '.one img{width:100%;height:auto;display:block}</style>'
            f'<div class="sheet"><header><h1>{e(c["name"])}</h1><span class="id">{e(ident)}</span></header>'
            f'<section class="one"><img src="data:image/png;base64,{base64.b64encode(Path(out_png).read_bytes()).decode()}" alt="{e(c["name"])}の設定資料"></section>'
            f'<section><h2>色見本</h2><table>{rows}</table></section>'
            f'<section><h2>注記</h2><ul>' + "".join(f"<li>{e(n)}</li>" for n in notes) + '</ul></section></div>')
    Path(out_html).write_text(page, encoding="utf-8")
    return {"html": out_html, "png": out_png, "size": list(canvas.size), "expressions": len(expr_roles), "poses": len(pose_roles),
            "swatches": {s["name"]: [s["role"], s["share"]] for s in sw}, "bytes": len(page.encode())}


# 設定画集の版（フォーマット）とテーマ。版はデータ（styles/sheet-formats/<名前>.json）に持ち、12 列の格子の区画と、
# 区画に入れる欄だけを決める。同じ素材から目的の違う1枚を出し分けるため。並べ方をコードに書くと、版を足すたびに描画の処理が分かれた。
# テーマは 3〜4 色・地の模様・書体だけを決める。
# 二つを分けたのは、同じ「総覧型」でも騎士なら羊皮紙、整備士なら真鍮のように、人物ごとに見せ方を替えたいから。
# 版は styles/sheet-formats/<名前>.json、テーマは styles/sheet-themes/<名前>.json に持つ。
FORMATS_DIR = bible.ROOT / "styles" / "sheet-formats"
THEMES_DIR = bible.ROOT / "styles" / "sheet-themes"
PANEL_KINDS = {"header", "hero", "turnaround", "poses", "expressions", "swatches", "notes", "callouts", "sharebar", "strip"}
THEME_KEYS = {"name", "title", "mood", "fits", "colors", "motif", "font"}


def load_format(name: str) -> dict:
    path = FORMATS_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"版 {name} がありません。一覧: python3 tools/gen/charsheet.py formats")
    fm = json.loads(path.read_text(encoding="utf-8"))
    for pn in fm.get("panels", []):
        if pn["kind"] not in PANEL_KINDS:
            raise ValueError(f"{name}: 欄の種類 {pn['kind']} は描けません")
    return fm


def formats() -> list[dict]:
    out = []
    for path in sorted(FORMATS_DIR.glob("*.json")):
        fm = json.loads(path.read_text(encoding="utf-8"))
        out.append({"name": fm["name"], "title": fm["title"], "purpose": fm["purpose"], "ratio": fm["ratio"],
                    "default": bool(fm.get("default")), "sample": f"library/sheets/formats/<キャラクター>/{fm['name']}.png"})
    return sorted(out, key=lambda f: (not f["default"], f["name"]))


def load_theme(name: str) -> dict:
    path = THEMES_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"テーマ {name} がありません。一覧: python3 tools/gen/charsheet.py themes")
    th = json.loads(path.read_text(encoding="utf-8"))
    miss = THEME_KEYS - set(th)
    if miss:
        raise ValueError(f"テーマ {name} に {sorted(miss)} がありません")
    return th


def themes() -> list[dict]:
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(THEMES_DIR.glob("*.json"))]
    return sorted(out, key=lambda t: (not t.get("default"), t["name"]))


def _char_text(c: dict) -> str:
    parts = [c.get(k, "") for k in ("look", "outfit", "notes", "personality", "role", "world", "backstory")]
    parts += [i.get("name", "") + " " + i.get("tags", "") for i in c.get("items", [])]
    return " ".join(str(p) for p in parts).lower()


def suggest_themes(c: dict) -> list[tuple[str, int]]:
    """キャラクターの設定（見た目・服・持ち物・注記）の言葉と、テーマの fits の言葉が重なる数で並べる。
    選ぶのは人か監督で、これは候補を出すだけ（言葉の一致は作風の判断の代わりにならない）"""
    text = _char_text(c)
    scored = [(t["name"], sum(1 for w in t.get("fits", []) if w.lower() in text)) for t in themes()]
    return sorted(scored, key=lambda s: -s[1])


def pick_theme(c: dict, name: str | None = None) -> str:
    """使うテーマ: 指定 → キャラクターの theme → 既定（default: true のもの）"""
    if name:
        return name
    if c.get("theme"):
        return c["theme"]
    return next(t["name"] for t in themes() if t.get("default"))


def _hex(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _char_accent(c: dict):
    """キャラクターの持ち色で、最も鮮やかで暗すぎない色。地の色の帯や模様に使う"""
    import colorsys
    best, score = (140, 42, 42), -1
    for h in c.get("palette", []):
        rgb = _hex(h)
        _, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
        sc = s * (1 - abs(l - 0.45) * 1.6)
        if sc > score:
            best, score = rgb, sc
    return best


_SAM = None


def _person_mask(src, size):
    """人の形の覆い。服の部位分けの外形を枠にして SAM で切り出す（2回目からは絵の隣の .sam.png を読む）。
    部位分けだけでは、人の縁がぎざぎざになり、腕を背景の機械と取り違えた。SAM が背景の側を選んだときは反転する"""
    import numpy as np
    from pathlib import Path
    from PIL import Image
    import edit
    out = Path(str(src) + ".sam.png")
    if out.exists() and out.stat().st_mtime >= Path(src).stat().st_mtime:
        return np.asarray(Image.open(out).resize(size, Image.NEAREST)) > 127
    im = Image.open(src).convert("RGB")
    seg = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST)) > 0
    ys, xs = np.nonzero(seg)
    if not len(xs):
        return seg
    try:
        import torch
        from transformers import SamModel, SamProcessor
        global _SAM
        if _SAM is None:
            _SAM = (SamModel.from_pretrained("facebook/sam-vit-base"), SamProcessor.from_pretrained("facebook/sam-vit-base"))
        model, proc = _SAM
        box = [[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]]
        inp = proc(im, input_boxes=[box], return_tensors="pt")
        with torch.no_grad():
            o = model(**inp, multimask_output=True)
        masks = proc.image_processor.post_process_masks(o.pred_masks, inp["original_sizes"], inp["reshaped_input_sizes"])[0][0].numpy()
        # 部位分けと最も重なる面を選ぶ（点数の最大は、魔女で背景の側を選んだ）
        best = None
        for mk in masks:
            border = np.concatenate([mk[0], mk[-1], mk[:, 0], mk[:, -1]]).mean()
            if border > 0.5:
                mk = ~mk
            iou = (mk & seg).sum() / max(1, (mk | seg).sum())
            if best is None or iou > best[0]:
                best = (iou, mk)
        mask = best[1] | seg
    except Exception:
        mask = seg
    Image.fromarray((mask * 255).astype("uint8")).save(out)
    return np.asarray(Image.fromarray((mask * 255).astype("uint8")).resize(size, Image.NEAREST)) > 127


def _cutout(im, src=None):
    """背景を透かす覆いを作る。囲まれた所（白い服、目の光）は残す。覆い無しで貼ると、色の付いた地の上に四角が出た。
    縁の色（白に限らない）を背景とし、src があれば人の部位分けで、人に付いていない塊（機械、背景の模様）を外す。
    手に持つ物（スパナ、杖、剣）は人の部位に入らないので、人に触れていて細長い塊は残す"""
    import numpy as np
    from PIL import Image, ImageFilter
    from scipy import ndimage
    a = np.asarray(im.convert("RGB")).astype(int)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    ref = np.median(border, axis=0)
    near = np.abs(a - ref).max(axis=2) < 30
    lab, _ = ndimage.label(near)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    fg = ~np.isin(lab, list(edge))
    if src is not None:
        person = _person_mask(src, im.size)
        if person.sum() > 500:
            # 持ち物は手に触れている。腕の部位（14, 15）の近くに触れない塊は、人の後ろの物（機械）として外す
            import edit
            seg = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
            arms = np.isin(seg, [14, 15])
            touch = ndimage.binary_dilation(person, iterations=8)
            ys, xs = np.nonzero(person)
            pad = int((xs.max() - xs.min()) * 0.25)
            box = np.zeros_like(person)
            box[:, max(0, xs.min() - pad):xs.max() + pad] = True
            rest, n = ndimage.label(fg & ~person)
            keep = person.copy()
            for k, sl in enumerate(ndimage.find_objects(rest), 1):
                comp = rest[sl] == k
                area = comp.sum()
                if not (touch[sl] & comp).any():
                    continue   # 人に触れていない塊は背景
                solid = area / comp.size
                # 大きく詰まった塊（機械の車輪）は背景、細長い・まばらな塊（持ち物）は残す
                # 人の横幅から大きく外れて広がる塊（背後の機械）は背景。持ち物は人の幅の近くに収まる
                if (box[sl] & comp).sum() < 0.7 * area:
                    continue
                keep[sl] |= comp
            fg = ndimage.binary_fill_holes(keep) & (fg | person)
            # 髪と腕の間など、人の形に囲まれた白い背景は縁につながらず残った。人の形の外の白は背景として抜く
            # 白に近い（明るく色の薄い）画素。生成の地は真っ白でなく、薄い灰や黄みがかった白で残った
            # SAM の人の形は粗く、髪の間の白い隙間まで人に含めた。地の色に近い白の塊は、服・顔・腕の部位
            # （白いブラウス、肌の明るい所）に入っていなければ、人の形の内でも背景として抜く
            mx, mn = a.max(axis=2), a.min(axis=2)
            white = ((mn > 222) & (mx - mn < 14)) | (np.abs(a - ref).max(axis=2) < 26)   # 地の色そのものに近い薄い黄みの縁も含める
            import edit
            seg = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
            keepw = ndimage.binary_erosion(np.isin(seg, [4, 5, 6, 7, 11, 14, 15, 17]), iterations=2)
            wl, wn = ndimage.label(white & ~keepw)
            if wn:
                ws = ndimage.sum(white, wl, range(1, wn + 1))
                fg &= ~np.isin(wl, [i + 1 for i, v in enumerate(ws) if v >= 25])
            # 本体から離れた小さな欠片（抜け残りの赤い点）は外す
            lab2, n2 = ndimage.label(fg)
            if n2 > 1:
                sizes = ndimage.sum(fg, lab2, range(1, n2 + 1))
                fg = np.isin(lab2, [i + 1 for i, v in enumerate(sizes) if v >= 0.004 * person.sum()])
    elif (~fg).mean() < 0.15:
        return Image.new("L", im.size, 255)
    m = Image.fromarray((fg * 255).astype("uint8"))
    if src is not None:
        mt = _matte(im, fg, a, src)
        if mt is not None:
            return mt
    return m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))


_VM = None


def _matte(im, fg, a, src):
    """覆いの縁を ViTMatte（覆いの内・外・保留の3値から、縁の透け具合を絵から推す模型）で抜き直す。
    覆いを広げてぼかすだけでは、髪の毛先の間に地の白が残り、白い縁や白い塊に見えた。
    白っぽい所は保留にして模型に判定させ、0.3 より不透明な所は完全に不透明にそろえる（顔や手が薄く透けた）"""
    import numpy as np
    from pathlib import Path
    from PIL import Image
    from scipy import ndimage
    out = Path(str(src) + ".matte.png")
    if out.exists() and out.stat().st_mtime >= Path(src).stat().st_mtime:
        mt = Image.open(out)
        return mt if mt.size == im.size else None
    try:
        import torch
        from transformers import VitMatteImageProcessor, VitMatteForImageMatting
        global _VM
        if _VM is None:
            name = "hustvl/vitmatte-small-composition-1k"
            _VM = (VitMatteImageProcessor.from_pretrained(name), VitMatteForImageMatting.from_pretrained(name))
        proc, model = _VM
        whiteish = (a.min(axis=2) > 215) & ((a.max(axis=2) - a.min(axis=2)) < 30)
        core = ndimage.binary_erosion(fg, iterations=6) & ~ndimage.binary_dilation(whiteish, iterations=3)
        unk = ndimage.binary_dilation(fg, iterations=8)
        tri = np.where(core, 255, np.where(unk, 128, 0)).astype("uint8")
        inp = proc(images=im.convert("RGB"), trimaps=Image.fromarray(tri), return_tensors="pt")
        with torch.no_grad():
            al = model(**inp).alphas[0, 0].numpy()[:im.height, :im.width]
        al = np.clip((al - 0.05) / 0.25, 0, 1)   # 顔・手・白い服は模型が半分ほどの透けと見たので、0.3 より上は不透明にする
    except Exception:
        return None
    mt = Image.fromarray((al * 255).astype("uint8"))
    mt.save(out)
    return mt


def _crop_face(im):
    fx = FACE_CROP
    return im.crop((int(fx[0] * im.width), int(fx[1] * im.height), int(fx[2] * im.width), int(fx[3] * im.height)))


def _trim(im):
    from PIL import ImageOps
    box = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 12 else 0).getbbox()
    return im.crop(box) if box else im


def _expr_list(ident, c, with_missing=False):
    imgs = c.get("images", {})
    names = {e["id"]: e["name"] for e in bible.expressions_of(ident)}
    order = [e["id"] for e in bible.expressions_of(ident)]
    have = sorted((r for r in imgs if r.startswith("expr-")), key=lambda r: order.index(r[5:]) if r[5:] in order else 99)
    out = [(names.get(r[5:], r[5:]), imgs[r]) for r in have]
    # 名前が重なる表情（照れが2つ）は番号を添える。同じ名前が並ぶと別の表情に見えなかった
    dup = [n for n, _ in out]
    out = [((n + f"{dup[:i].count(n) + 1}") if dup.count(n) > 1 else n, p) for i, (n, p) in enumerate(out)]
    if with_missing:
        out += [(names[i], None) for i in order if f"expr-{i}" not in imgs]
    return out


def _pose_list(c):
    imgs = c.get("images", {})
    names = {p.get("id"): p.get("name", p.get("id")) for p in c.get("poses", []) if isinstance(p, dict)}
    return [(names.get(r[5:], r[5:]), imgs[r]) for r in sorted(r for r in imgs if r.startswith("pose-"))]


def _has_material(pn, ident, c):
    imgs = c.get("images", {})
    k = pn["kind"]
    if k in ("turnaround", "figure"):
        return bool(imgs.get("turnaround"))
    if k == "poses":
        return bool(_pose_list(c))
    if k == "expressions":
        return bool(_expr_list(ident, c))
    if k == "slots":
        return any(imgs.get(r) for r, _ in pn["slots"])
    return True


def sheet_format(ident: str, name: str, out_png: str, out_html: str | None = None, theme: str | None = None) -> dict:
    """版（styles/sheet-formats/<名前>.json）の区画と、テーマ（styles/sheet-themes/）の色と書体で1枚を組み、PNG に書き出す。
    組むのは sheetlayout（HTML と CSS を Chromium で描く）。テーマは 指定 → キャラクターの theme → 既定。
    返り値の drawn は区画ごとの描いた矩形、outside_panel は区画からはみ出した数、empty は中身の無い区画"""
    import sheetlayout
    fm = load_format(name)
    c = bible.load("characters", ident)
    tname = pick_theme(c, theme)
    r = sheetlayout.render(ident, fm, load_theme(tname), out_png, out_html)
    return {"format": name, "theme": tname, "png": out_png, **r}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "formats":
        for f in formats():
            print(f"{f['name']:<11} {f['title']}{'（既定）' if f['default'] else ''}  {f['ratio']}  {f['sample']}\n            {f['purpose']}")
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "themes":
        if len(sys.argv) >= 3:   # キャラクターに合うテーマの候補（設定の言葉との重なりの数）
            c = bible.load("characters", sys.argv[2])
            print(f"指定: {c.get('theme') or 'なし'}  使うテーマ: {pick_theme(c)}")
            for n, s in suggest_themes(c):
                print(f"  {n:<10} 重なり {s}")
            return
        for t in themes():
            print(f"{t['name']:<10} {t['title']}{'（既定）' if t.get('default') else ''}\n           {t['mood']}")
        return
    if len(sys.argv) >= 4 and sys.argv[1] == "sheet" and ("--format" in sys.argv or "--theme" in sys.argv):
        a = list(sys.argv[2:])
        opt = {}
        for key in ("--format", "--theme"):
            if key in a:
                i = a.index(key)
                opt[key] = a[i + 1]
                a = a[:i] + a[i + 2:]
        name = opt.get("--format") or next(f["name"] for f in formats() if f["default"])
        out_png = next(v for v in a[1:] if v.endswith(".png"))
        out_html = next((v for v in a[1:] if v.endswith(".html")), None)
        r = sheet_format(a[0], name, out_png, out_html, opt.get("--theme"))
        r.pop("drawn", None)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    if len(sys.argv) >= 5 and sys.argv[1] == "sheet":
        print(json.dumps(sheet(sys.argv[2], sys.argv[3], sys.argv[4]), ensure_ascii=False, indent=1))
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "status":
        r = status(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "render":
        r = render(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
