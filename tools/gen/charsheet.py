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
    if c.get("images", {}).get("turnaround"):
        shares = color_shares(Image.open(bible.ROOT / c["images"]["turnaround"]), named)
    base = ("髪", "肌")
    order = [k for k in sorted(named, key=lambda k: -shares.get(k, 0)) if k not in base]
    roles = {k: r for k, r in zip(order, ("主", "副", "アクセント"))}
    return [{"key": k, "name": k, "hex": "#%02x%02x%02x" % named[k], "share": shares.get(k, 0.0),
             "role": roles.get(k, "髪・肌" if k in base else "その他")} for k in named]


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


# 設定画集の版（フォーマット）。版はデータ（styles/sheet-formats/<名前>.json）に持ち、欄の種類と位置（版面に対する割合）だけを決める。
# 同じ素材から目的の違う1枚を出し分けるため。並べ方をコードに書くと、版を足すたびに描画の処理が分かれた
# 設定画集の版（フォーマット）とテーマ。
# 版は欄の種類と位置（版面に対する割合）だけを決め、テーマは配色・地の質感・地の模様・飾りの罫・見出しの様式・書体を決める。
# 二つを分けたのは、同じ「総覧型」でも騎士なら羊皮紙、整備士なら真鍮のように、人物ごとに見せ方を替えたいから。
# 版は styles/sheet-formats/<名前>.json、テーマは styles/sheet-themes/<名前>.json に持つ。
FORMATS_DIR = bible.ROOT / "styles" / "sheet-formats"
THEMES_DIR = bible.ROOT / "styles" / "sheet-themes"
PIXEL_FONT = "/usr/share/fonts/opentype/unifont/unifont_jp.otf"   # 角ばった点の書体。レトロSF の見出しに使う
PANEL_KINDS = {"header", "turnaround", "poses", "expressions", "swatches", "notes", "slots", "callouts", "figure", "sharebar", "strip"}
THEME_KEYS = {"name", "title", "mood", "fits", "colors", "texture", "motif", "frame", "heading"}


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


def _cutout(im):
    """白い背景（縁につながる白）を透かす覆いを作る。囲まれた白（白い服、目の光）は残す。
    覆い無しで貼ると、色の付いた地の上に白い四角が出た"""
    import numpy as np
    from PIL import Image, ImageFilter
    from scipy import ndimage
    a = np.asarray(im.convert("RGB")).astype(int)
    white = a.min(axis=2) > 232
    lab, _ = ndimage.label(white)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge))
    if bg.mean() < 0.15:   # 背景が白くない絵（場面つき）は四角のまま貼る
        return Image.new("L", im.size, 255)
    m = Image.fromarray(((~bg) * 255).astype("uint8"))
    return m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))


class _Page:
    """版面。テーマで地を作り、描いた物の矩形を欄ごとに記録する（欄からのはみ出しを試験で数えるため）"""

    def __init__(self, W, H, theme: dict | None = None, c: dict | None = None):
        from PIL import ImageDraw
        self.th = theme or load_theme("studio")
        c = c or {}
        col = {k: (_char_accent(c) if v == "character" else _hex(v)) for k, v in self.th["colors"].items()}
        col.setdefault("page_ink", col["ink"])
        col.setdefault("page_sub", col["sub"])
        self.col = col
        self.W, self.H = W, H
        self.im = self._ground(W, H)
        self.d = ImageDraw.Draw(self.im)
        self.drawn: list[tuple[str, tuple, tuple]] = []   # (欄, 欄の矩形, 描いた矩形)
        self.panel, self.pbox = "", (0, 0, W, H)
        self.anchors: dict = {}
        self.section = 0
        self.scale = 1.0
        self._frame()

    # ---- 地 ----
    def _ground(self, W, H):
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter
        th, col = self.th, self.col
        rng = np.random.default_rng(7)
        t = np.linspace(0, 1, H)[:, None, None]
        a = np.array(col["page"])[None, None, :] * (1 - t) + np.array(col["page2"])[None, None, :] * t
        a = np.broadcast_to(a, (H, W, 3)).copy()
        s = float(th.get("texture_strength", 0.3))
        tex = th.get("texture", "none")
        if tex in ("grain", "parchment", "washi"):
            # 粒は 1 画素ごとの雑音にせず、6 画素角の粒を滑らかに広げる。1 画素ごとの雑音は PNG で縮まず、1 枚が 2MB を超えた
            g = Image.fromarray(np.clip(rng.normal(128, 40, (H // 6 + 1, W // 6 + 1)), 0, 255).astype("uint8")).resize((W, H), Image.BICUBIC)
            a += ((np.asarray(g)[:, :, None] - 128) / 40) * 3 * s
        if tex == "parchment":   # むら（低い周波数の濃淡）と、縁を暗くする焼け
            low = Image.fromarray((rng.random((H // 60 + 2, W // 60 + 2)) * 255).astype("uint8")).resize((W, H), Image.BICUBIC)
            a += (np.asarray(low)[:, :, None] / 255 - 0.5) * 34 * s
            yy, xx = np.mgrid[0:H, 0:W]
            r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
            a *= (1 - np.clip(r - 0.75, 0, 1) * 0.35 * s)[:, :, None]
        im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if tex == "washi":   # 和紙の繊維: 短い曲がった筋を、地より少し明るく・暗く
            for _ in range(int(W * H / 2500)):
                x, y = rng.random() * W, rng.random() * H
                L, ang = 20 + rng.random() * 60, rng.random() * 6.28
                pts = [(x + np.cos(ang + k * 0.15) * L * k / 4, y + np.sin(ang + k * 0.15) * L * k / 4) for k in range(5)]
                v = 255 if rng.random() < 0.6 else 120
                d.line(pts, fill=(v, v, v, int(60 * s)), width=1)
        elif tex == "grid":
            g = (*col["page_sub"], int(60 * s))
            for x in range(0, W, 48):
                d.line([(x, 0), (x, H)], fill=g, width=1)
            for y in range(0, H, 48):
                d.line([(0, y), (W, y)], fill=g, width=1)
        elif tex == "scan":
            for y in range(0, H, 5):
                d.line([(0, y), (W, y)], fill=(0, 0, 0, int(70 * s)), width=2)
        im = Image.alpha_composite(im.convert("RGBA"), layer)
        im = Image.alpha_composite(im, self._motif(W, H, rng))
        return im.convert("RGB")

    def _motif(self, W, H, rng):
        """地の模様。キャラクターの持ち色や世界の手がかり（菱・歯車・葉・波・星）を薄く敷く"""
        import math
        from PIL import Image, ImageDraw
        th, col = self.th, self.col
        al = int(255 * float(th.get("motif_alpha", 0.1)))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        m = th.get("motif", "none")
        c1, c2 = (*col["accent"], al), (*col["accent2"], al)
        if m == "dots":
            for y in range(0, H, 36):
                for x in range(0, W, 36):
                    r = 2 + 3 * (x / W)   # 右へ行くほど大きくなる網点
                    d.ellipse([x - r, y - r, x + r, y + r], fill=c1)
        elif m == "diamonds":
            s = 90
            for j, y in enumerate(range(-s, H + s, s // 2)):
                for x in range(-s + (j % 2) * s // 2, W + s, s):
                    d.polygon([(x, y - s // 2), (x + s // 2, y), (x, y + s // 2), (x - s // 2, y)], outline=c2, width=2)
                    d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=c1)
        elif m == "waves":   # 青海波: 重ねた半円
            s = 70
            for j, y in enumerate(range(0, H + s, s // 2)):
                for x in range(-s + (j % 2) * s, W + s, 2 * s):
                    for k in (1.0, 0.72, 0.44):
                        d.arc([x - s * k, y - s * k, x + s * k, y + s * k], 180, 360, fill=(*col["accent2"], al), width=3)
        elif m == "stars":
            for _ in range(int(W * H / 9000)):
                x, y, r = rng.random() * W, rng.random() * H, 1 + rng.random() * 2.5
                d.ellipse([x - r, y - r, x + r, y + r], fill=(*col["page_ink"], int(al * rng.random())))
            for _ in range(12):
                x, y, r = rng.random() * W, rng.random() * H, 8 + rng.random() * 10
                d.line([(x - r, y), (x + r, y)], fill=(*col["accent"], al), width=2)
                d.line([(x, y - r), (x, y + r)], fill=(*col["accent"], al), width=2)
        elif m == "gears":
            for _ in range(7):
                cx, cy, R = rng.random() * W, rng.random() * H, 90 + rng.random() * 220
                n = int(R / 14)
                pts = []
                for k in range(n * 2):
                    a0 = k * math.pi / n
                    rr = R if k % 2 == 0 else R * 0.86
                    pts += [(cx + rr * math.cos(a0 - 0.12), cy + rr * math.sin(a0 - 0.12)), (cx + rr * math.cos(a0 + 0.12), cy + rr * math.sin(a0 + 0.12))]
                d.polygon(pts, outline=c1, width=4)
                d.ellipse([cx - R * 0.3, cy - R * 0.3, cx + R * 0.3, cy + R * 0.3], outline=c1, width=4)
        elif m == "leaves":
            for _ in range(int(W * H / 60000)):
                cx, cy, L = rng.random() * W, rng.random() * H, 30 + rng.random() * 40
                ang = rng.random() * math.pi
                leaf = Image.new("RGBA", (int(L * 2), int(L * 2)), (0, 0, 0, 0))
                ImageDraw.Draw(leaf).ellipse([L * 0.5, L * 0.75, L * 1.5, L * 1.25], fill=c1 if rng.random() < 0.75 else c2)
                leaf = leaf.rotate(math.degrees(ang), resample=Image.BICUBIC)
                layer.alpha_composite(leaf, (int(cx - L), int(cy - L)))
        elif m == "diagonal":
            for x in range(-H, W, 60):
                d.line([(x, H), (x + H, 0)], fill=c2, width=2)
        return layer

    def _frame(self):
        """版面の縁の飾り。描いた物の矩形には数えない（欄の外に置く飾りなので）"""
        from PIL import Image, ImageFilter
        fr, col, W, H, d = self.th.get("frame", "none"), self.col, self.W, self.H, self.d
        if fr == "double":
            d.rectangle([14, 14, W - 15, H - 15], outline=col["accent2"], width=4)
            d.rectangle([24, 24, W - 25, H - 25], outline=col["accent2"], width=1)
            for x, y in ((14, 14), (W - 15, 14), (14, H - 15), (W - 15, H - 15)):
                d.polygon([(x, y - 16), (x + 16, y), (x, y + 16), (x - 16, y)], fill=col["accent"], outline=col["accent2"])
        elif fr == "corners":
            L = int(min(W, H) * 0.05)
            for x, y, sx, sy in ((16, 16, 1, 1), (W - 17, 16, -1, 1), (16, H - 17, 1, -1), (W - 17, H - 17, -1, -1)):
                d.line([(x, y), (x + sx * L, y)], fill=col["accent"], width=5)
                d.line([(x, y), (x, y + sy * L)], fill=col["accent"], width=5)
        elif fr == "neon":
            glow = Image.new("RGB", (W, H), (0, 0, 0))
            from PIL import ImageDraw
            ImageDraw.Draw(glow).rectangle([16, 16, W - 17, H - 17], outline=col["accent"], width=6)
            glow = glow.filter(ImageFilter.GaussianBlur(10))
            from PIL import ImageChops
            self.im.paste(ImageChops.add(self.im, glow))
            d.rectangle([16, 16, W - 17, H - 17], outline=col["accent"], width=2)

    # ---- 部品 ----
    def font(self, n, kind="gothic"):
        from PIL import ImageFont
        return ImageFont.truetype(PIXEL_FONT if kind == "pixel" else FONT, max(8, int(n)))

    def mark(self, r):
        self.drawn.append((self.panel, self.pbox, tuple(int(v) for v in r)))

    def text(self, xy, t, size, fill=None, maxw=None, kind="gothic"):
        """1行の文字。幅を超える分は「…」で切る（欄から出さない）"""
        fill = self.col["ink"] if fill is None else fill
        f = self.font(size, kind)
        if maxw is not None and self.d.textlength(t, font=f) > maxw:
            while t and self.d.textlength(t + "…", font=f) > maxw:
                t = t[:-1]
            t += "…"
        self.d.text(xy, t, fill=fill, font=f)
        b = self.d.textbbox(xy, t, font=f)
        self.mark(b)
        return b

    def wrap(self, x, y, t, size, maxw, maxy, fill=None, gap=1.45):
        """折り返す文字。下端を超える行は書かず、書けなかったことを「…」で示す"""
        f = self.font(size)
        lines, line = [], ""
        for ch in t:
            if self.d.textlength(line + ch, font=f) > maxw:
                lines.append(line)
                line = ""
            line += ch
        lines.append(line)
        for i, ln in enumerate(lines):
            if y + size * gap * 2 > maxy and i < len(lines) - 1:
                self.text((x, y), ln[:-1] + "…", size, fill)
                return y + size * gap, False
            self.text((x, y), ln, size, fill)
            y += size * gap
        return y, True

    def card(self, box, pad=0):
        """欄の台紙。絵と文字はこの上に置く（地の模様の上に直に置くと読めなかった）"""
        from PIL import Image, ImageDraw, ImageFilter
        x0, y0, x1, y1 = box
        th, col = self.th, self.col
        r = int(th.get("card_radius", 12))
        if th.get("card_shadow"):
            sh = Image.new("L", (self.W, self.H), 0)
            ImageDraw.Draw(sh).rounded_rectangle([x0 + 6, y0 + 8, x1, y1], r, fill=90)
            sh = sh.filter(ImageFilter.GaussianBlur(9))
            dark = Image.new("RGB", (self.W, self.H), _mix(col["page2"], (0, 0, 0), 0.55))
            self.im.paste(dark, (0, 0), sh)
            x1, y1 = x1 - 6, y1 - 8
        self.d.rounded_rectangle([x0, y0, x1, y1], r, fill=col["card"], outline=col["rule"], width=2)
        fr = th.get("frame")
        if fr == "rivets":
            for x, y in ((x0 + 14, y0 + 14), (x1 - 14, y0 + 14), (x0 + 14, y1 - 14), (x1 - 14, y1 - 14)):
                self.d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=col["accent"], outline=col["accent2"], width=2)
        elif fr == "neon":
            self.d.rounded_rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], r + 3, outline=col["accent2"], width=2)
        elif fr == "double":
            self.d.rounded_rectangle([x0 + 7, y0 + 7, x1 - 7, y1 - 7], max(0, r - 4), outline=col["rule"], width=1)
        return (x0, y0, x1, y1)

    def heading(self, x, y, w, title, size):
        """欄の見出し: 番号と題。様式（帯・札・筆・下線）はテーマで決める。返り値は使った高さ"""
        th, col = self.th, self.col
        hd = th.get("heading", {})
        self.section += 1
        n = self.section
        num = {"roman": ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][min(n, 10) - 1],
               "kanji": "一二三四五六七八九十"[min(n, 10) - 1], "none": ""}.get(hd.get("number", "arabic"), f"{n:02d}")
        kind = th.get("title_font", "gothic")
        style = hd.get("style", "tab")
        bh = int(size * 1.7)
        if style == "band":
            self.d.rectangle([x, y, x + w, y + bh], fill=col["accent"])
            self.d.rectangle([x, y, x + bh, y + bh], fill=col["accent2"])
            nf = self.font(size * 0.8, kind)
            tw = self.d.textlength(num, font=nf)
            self.text((x + (bh - tw) / 2, y + bh * 0.2), num, size * 0.8, col["band_text"], kind=kind)
            self.text((x + bh + size * 0.6, y + bh * 0.18), title, size, col["band_text"], maxw=w - bh - size, kind=kind)
            self.mark((x, y, x + w, y + bh))
            return bh + int(size * 0.5)
        if style == "pill":
            label = f"{num}  {title}"
            tw = min(self.d.textlength(label, font=self.font(size, kind)) + size * 1.6, w)
            self.d.rounded_rectangle([x, y, x + tw, y + bh], bh // 2, fill=col["accent"])
            self.text((x + size * 0.8, y + bh * 0.18), label, size, col["band_text"], maxw=tw - size * 1.2, kind=kind)
            if tw + 20 < w:
                self.d.line([(x + tw + 16, y + bh // 2), (x + w, y + bh // 2)], fill=col["accent2"], width=3)
            self.mark((x, y, x + tw, y + bh))
            return bh + int(size * 0.5)
        if style == "brush":   # 太い払いの筆の線を題の下に敷く
            self.d.polygon([(x, y + bh * 0.62), (x + w * 0.55, y + bh * 0.48), (x + w * 0.6, y + bh * 0.78), (x + 6, y + bh * 0.95)],
                           fill=_mix(col["accent"], col["page"], 0.55))
            self.text((x, y), num, size * 1.15, col["accent"], kind=kind)
            nw = self.d.textlength(num, font=self.font(size * 1.15, kind))
            self.text((x + nw + size * 0.5, y + size * 0.1), title, size, col["page_ink"], maxw=w - nw - size, kind=kind)
            return bh + int(size * 0.3)
        # tab: 色の札に番号、続けて題、細い罫
        self.d.rounded_rectangle([x, y, x + bh, y + bh], 8, fill=col["accent"])
        nf = self.font(size * 0.75, kind)
        tw = self.d.textlength(num, font=nf)
        self.text((x + (bh - tw) / 2, y + bh * 0.22), num, size * 0.75, col["band_text"], kind=kind)
        tb = self.text((x + bh + size * 0.5, y + bh * 0.15), title, size, col["page_ink"], maxw=w - bh - size, kind=kind)
        self.d.line([(tb[2] + size * 0.6, y + bh // 2), (x + w, y + bh // 2)], fill=col["rule"], width=2)
        self.mark((x, y, x + bh, y + bh))
        return bh + int(size * 0.5)

    def paste(self, img, box, align="center", cut=True, limit=None):
        """枠に収まる最大の大きさで貼る（縦横比を保つ）。白い背景は透かす。返り値は貼った矩形と倍率"""
        from PIL import Image
        x, y, w, h = box
        k = min(w / img.width, h / img.height, limit or 99)
        size = (max(1, int(img.width * k)), max(1, int(img.height * k)))
        im = img.resize(size, Image.LANCZOS)
        mask = _cutout(img).resize(size, Image.LANCZOS) if cut else None
        px = x + (w - im.width) // 2
        py = y + (h - im.height) if align == "bottom" else y + (h - im.height) // 2
        self.im.paste(im, (int(px), int(py)), mask)
        r = (int(px), int(py), int(px) + im.width, int(py) + im.height)
        self.mark(r)
        return r, k

    def empty(self, box, label):
        """素材の無い欄。点線の枠と小さな文字だけにする（斜線と大きな「未作成」は版の中で目立ちすぎた）"""
        x, y, w, h = [int(v) for v in box]
        col = self.col
        step = 14
        for xx in range(x, x + w, step * 2):
            self.d.line([(xx, y), (min(xx + step, x + w), y)], fill=col["rule"], width=2)
            self.d.line([(xx, y + h - 1), (min(xx + step, x + w), y + h - 1)], fill=col["rule"], width=2)
        for yy in range(y, y + h, step * 2):
            self.d.line([(x, yy), (x, min(yy + step, y + h))], fill=col["rule"], width=2)
            self.d.line([(x + w - 1, yy), (x + w - 1, min(yy + step, y + h))], fill=col["rule"], width=2)
        self.mark((x, y, x + w, y + h))
        size = max(12, min(22, int(min(w, h) / 7)))
        t = f"未作成 {label}" if label else "—"
        f = self.font(size)
        tw = min(self.d.textlength(t, font=f), w - 8)
        self.text((x + (w - tw) / 2, y + (h - size) / 2), t, size, col["sub"], maxw=w - 8)


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


def _panel(pg, pn, ident, c, sw, notes):
    from PIL import Image
    W, H = pg.W, pg.H
    col = pg.col
    x, y, w, h = int(pn["box"][0] * W), int(pn["box"][1] * H), int(pn["box"][2] * W), int(pn["box"][3] * H)
    pg.panel, pg.pbox = pn["kind"], (x, y, x + w, y + h)
    imgs = c.get("images", {})
    k = pn["kind"]
    # 素材の無い欄: optional なら版から外す。そうでなければ小さな空欄だけを置く
    if not _has_material(pn, ident, c) and pn.get("optional"):
        return
    title = pn.get("title", "")
    ts = max(18, int(min(W, H) * 0.024 * pg.scale))   # 小さく表示される版（紹介型）は text_scale で文字を大きくする
    if title:
        used = pg.heading(x, y, w, title, ts)
        y += used
        h -= used
    if k == "header":
        return _header(pg, pn, ident, c, x, y, w, h)
    hero = pn.get("hero") and k in ("poses", "figure")
    # 主役の絵は台紙の上端を下げ、頭を台紙の外へ出す（枠から少しはみ出させると手前に見える）
    lift = int(h * 0.16) if hero else 0
    cx0, cy0, cx1, cy1 = pg.card((x, y + lift, x + w, y + h))
    pad = int(min(w, h) * 0.04) + 8
    ix, iy, iw, ih = x + pad, y + pad, w - 2 * pad, h - 2 * pad
    if hero:
        iy, ih = y, h - pad
    lab = max(14, int(ts * 0.8))
    if k == "turnaround":
        if not imgs.get("turnaround"):
            return pg.empty((ix, iy, iw, ih), "四面図")
        t = Image.open(bible.ROOT / imgs["turnaround"]).convert("RGB")
        spans, top, bot = _figures(t)
        left = max(int(iw * 0.09), lab * 4) if pn.get("guides") else 0
        crop = t.crop((spans[0][0] - 10, top, spans[-1][1] + 10, bot + 1)) if spans else t
        area = (ix + left, iy, iw - left, ih - lab * 2)
        # 元の四面図が小さい（羊娘は高さ 304 画素）ので 3 倍を超えて伸ばさない（線がぼやけた）
        r, kk = pg.paste(crop, area, limit=3.0)
        x0 = r[0] - int((spans[0][0] - 10) * kk) if spans else r[0]
        pg.anchors["figures"] = [(x0 + int((a + b) / 2 * kk), r[1], r[3]) for a, b in spans]
        if pn.get("guides"):
            for frac, label in ((0.0, "頭の上"), (0.5, "半分"), (1.0, "足の下")):
                yy = r[1] + int(frac * (r[3] - r[1] - 1))
                pg.d.line([(ix, yy), (ix + iw, yy)], fill=col["guide"], width=1)
                pg.text((ix, yy - lab - 4 if frac else yy + 3), label, lab * 0.85, col["guide"], maxw=left - 4)
        n = pn.get("ruler")
        if n:   # 全身を n 等分する目盛り。頭の高さを測る処理が無いので頭身とは書かない
            rx = r[2] + 16 if r[2] + 60 < ix + iw else ix + left - 30
            for i in range(n + 1):
                yy = r[1] + (r[3] - r[1]) * i / n
                pg.d.line([(rx, yy), (rx + (14 if i % 2 == 0 else 8), yy)], fill=col["guide"], width=2)
            pg.d.line([(rx, r[1]), (rx, r[3])], fill=col["guide"], width=2)
            pg.mark((rx, r[1], rx + 14, r[3]))
        names = ["正面", "横（右向き）", "横（左向き）", "背面"] if len(spans) == 4 else [""] * len(spans)
        for (cx, _, b), nm in zip(pg.anchors["figures"], names):
            tw = pg.d.textlength(nm, font=pg.font(lab))
            pg.text((max(ix, cx - tw / 2), b + 6), nm, lab, col["sub"])
    elif k in ("poses", "figure"):
        n = pn.get("count", 1)
        if k == "figure":
            cells = [("正面", None)]
        else:
            # 絵のあるポーズだけを並べる。空のますを並べると、版の半分が「未作成」になった
            cells = _pose_list(c)[:n]
            # ポーズの絵が足りないときは四面図の正面で埋める（欄の半分が空くより、基準の立ち姿がある方が使える）
            if pn.get("fill_front") and len(cells) < n and imgs.get("turnaround"):
                cells.append(("基準の正面", "__front__"))
            cells = cells or [("ポーズ", None)]
        n = len(cells)
        gap = 24
        cw = (iw - gap * (n - 1)) // n
        for i, (nm, path) in enumerate(cells):
            box = (ix + i * (cw + gap), iy, cw, ih - (lab * 2 if nm and k == "poses" else 0))
            if (k == "figure" or path == "__front__") and imgs.get("turnaround"):
                t = Image.open(bible.ROOT / imgs["turnaround"]).convert("RGB")
                spans, top, bot = _figures(t)
                a, b = spans[0]
                r, _ = pg.paste(t.crop((a - 4, top, b + 4, bot + 1)), box, "bottom")
                if path == "__front__":
                    tw = min(cw, pg.d.textlength(nm, font=pg.font(lab)))
                    pg.text((max(box[0], (r[0] + r[2] - tw) / 2), box[1] + box[3] + 6), nm, lab, col["sub"], maxw=cw)
            elif path:
                r, _ = pg.paste(_trim(Image.open(bible.ROOT / path).convert("RGB")), box, "bottom")
                if nm and not hero:   # 名前は絵の真下に置く（ますの左端に置くと絵から離れた）
                    tw = min(cw, pg.d.textlength(nm, font=pg.font(lab)))
                    pg.text((max(box[0], (r[0] + r[2] - tw) / 2), box[1] + box[3] + 6), nm, lab, col["sub"], maxw=cw)
            else:
                pg.empty((box[0], max(box[1], cy0 + pad), box[2], box[3] - max(0, cy0 + pad - box[1])), nm)
    elif k == "expressions":
        cols, rows = pn.get("cols", 4), pn.get("rows", 2)
        ex = _expr_list(ident, c)[:cols * rows]
        if not ex:
            return pg.empty((ix, iy, iw, ih), "表情")
        # 枚数が少なければ列を詰める（空のますを並べない）
        rows = min(rows, (len(ex) + cols - 1) // cols)
        cols = min(cols, len(ex)) if rows == 1 else cols
        gap = 18
        lb = int(lab * (1.15 if pn.get("large") else 1.0))
        cell = int(min((iw - gap * (cols - 1)) // cols, (ih - rows * (lb * 1.7) - gap * (rows - 1)) // rows))
        ox = ix + (iw - (cell * cols + gap * (cols - 1))) // 2
        oy = iy + (ih - (rows * (cell + int(lb * 1.7)) + gap * (rows - 1))) // 2
        tint = _mix(col["card"], col["accent"], 0.12)
        for i, (nm, path) in enumerate(ex):
            cx, cy = ox + (i % cols) * (cell + gap), oy + (i // cols) * (cell + int(lb * 1.7) + gap)
            pg.d.rounded_rectangle([cx, cy, cx + cell - 1, cy + cell - 1], int(cell * 0.12), fill=tint)
            pg.paste(_crop_face(Image.open(bible.ROOT / path).convert("RGB")), (cx, cy, cell, cell))
            tw = pg.d.textlength(nm, font=pg.font(lb))
            pg.text((cx + max(0, (cell - tw) / 2), cy + cell + 6), nm, lb, col["ink"], maxw=cell)
    elif k == "swatches":
        style = pn.get("style", "list")
        if not sw:
            return pg.empty((ix, iy, iw, ih), "色見本")
        if style == "table":
            heads = ["", "名前・役", "ふつう", "影", "ハイライト"]
            colx = [0, 0.12, 0.42, 0.64, 0.82]
            rh = min(int(ih / (len(sw) + 1)), 110)
            fs = int(min(rh * 0.3, 30))
            for hx, t in zip(colx, heads):
                pg.text((ix + int(hx * iw), iy), t, fs, col["sub"], maxw=iw * 0.2)
            for i, s in enumerate(sw):
                yy = iy + rh * (i + 1)
                q = int(rh * 0.8)
                pg.d.rounded_rectangle([ix, yy, ix + q, yy + q], 8, fill=_hex(s["hex"]), outline=col["rule"])
                pg.mark((ix, yy, ix + q, yy + q))
                pg.text((ix + int(0.12 * iw), yy + 4), s["name"], fs, col["ink"], maxw=iw * 0.28)
                pg.text((ix + int(0.12 * iw), yy + fs * 1.4), s["role"], int(fs * 0.8), col["sub"], maxw=iw * 0.28)
                pg.text((ix + int(0.42 * iw), yy + 4), s["hex"], fs, col["ink"], maxw=iw * 0.2)
                pg.text((ix + int(0.42 * iw), yy + fs * 1.4), f"{s['share'] * 100:.0f}%", int(fs * 0.8), col["sub"], maxw=iw * 0.2)
                # 影とハイライトの色は描いた絵から決めていない。色を作って埋めると決まりに見えるので空欄にする
                for cx in (0.64, 0.82):
                    pg.empty((ix + int(cx * iw), yy, int(0.16 * iw), q), "")
                pg.d.line([(ix, yy + rh - 6), (ix + iw, yy + rh - 6)], fill=col["rule"])
        else:
            cols = 2 if style == "grid" else 1
            rows = (len(sw) + cols - 1) // cols
            rh = min(int(ih / rows), 120)
            q = int(rh * 0.75)
            fs = int(min(q * 0.45, 34, (iw // cols) / 13))
            cw = iw // cols
            for i, s in enumerate(sw):
                cx, cy = ix + (i // rows) * cw, iy + (i % rows) * rh
                pg.d.ellipse([cx, cy, cx + q, cy + q], fill=_hex(s["hex"]), outline=col["rule"], width=2)
                pg.mark((cx, cy, cx + q, cy + q))
                pg.text((cx + q + 12, cy), f"{s['name']}  {s['role']}", fs, col["ink"], maxw=cw - q - 16)
                pg.text((cx + q + 12, cy + fs * 1.3), f"{s['hex']}  {s['share'] * 100:.0f}%", int(fs * 0.85), col["sub"], maxw=cw - q - 16)
    elif k in ("sharebar", "strip"):
        if not sw:
            return pg.empty((ix, iy, iw, ih), "色見本")
        tot = sum(s["share"] for s in sw) or 1
        bh = int(ih * 0.62)
        xx = ix
        for i, s in enumerate(sw):
            ww = int(iw * s["share"] / tot) if i < len(sw) - 1 else ix + iw - xx
            pg.d.rectangle([xx, iy, xx + ww - 1, iy + bh], fill=_hex(s["hex"]))
            pg.mark((xx, iy, xx + ww, iy + bh))
            if ww > 40:
                fs = int(min(ih * 0.12, 24))
                pg.text((xx + 4, iy + bh + 8), s["name"], fs, col["ink"], maxw=ww - 6)
                if k == "sharebar":
                    pg.text((xx + 4, iy + bh + 8 + fs * 1.4), f"{s['share'] * 100:.0f}%", fs, col["sub"], maxw=ww - 6)
            xx += ww
        pg.d.rectangle([ix, iy, ix + iw - 1, iy + bh], outline=col["rule"])
    elif k == "notes":
        fs = max(14, int(ts * 0.8))
        yy = iy
        for n in notes:
            pg.d.ellipse([ix, yy + fs * 0.35, ix + fs * 0.5, yy + fs * 0.85], fill=col["accent"])
            yy, ok = pg.wrap(ix + fs * 0.9, yy, n, fs, iw - fs, iy + ih, col["ink"])
            yy += fs * 0.6
            if not ok or yy > iy + ih - fs * 1.4:
                break
    elif k == "slots":
        ss = [s for s in pn["slots"] if imgs.get(s[0])] if pn.get("optional") else pn["slots"]
        gap = 20
        cw = (iw - gap * (len(ss) - 1)) // len(ss)
        for i, (role, nm) in enumerate(ss):
            box = (ix + i * (cw + gap), iy, cw, ih)
            if imgs.get(role):
                pg.paste(_trim(Image.open(bible.ROOT / imgs[role]).convert("RGB")), box, "bottom")
            else:
                pg.empty(box, nm)
    elif k == "callouts":
        items = []
        if pn.get("face"):
            src = imgs.get("expr-neutral") or next((imgs[r] for r in sorted(imgs) if r.startswith("expr-")), None)
            items.append(("顔", src, "face", 0.07))
            if pn.get("eyes", True):
                items.append(("目", src, "eyes", 0.075))
        if pn.get("items"):
            # 拡大の絵が無い持ち物は外す（全部が空のますだった）
            items += [(i["name"], imgs.get(f"detail-item-{i['id']}"), "item", None) for i in c.get("items", [])
                      if imgs.get(f"detail-item-{i['id']}") or not pn.get("optional_items", True)]
        items = items[:pn.get("max", 4)]
        if not items:
            return pg.empty((ix, iy, iw, ih), "部位の拡大")
        gap = 24
        n = len(items)
        cw = min((iw - gap * (n - 1)) // n, ih - lab * 2)
        ox = ix   # 左に寄せる。中央に置くと、正面の人物への引き出し線が四面図を斜めに横切った
        for i, (nm, path, kind, ty) in enumerate(items):
            box = (ox + i * (cw + gap), iy + lab * 2, cw, cw)
            rr = int(lab * 0.75)
            pg.d.ellipse([box[0], iy, box[0] + 2 * rr, iy + 2 * rr], fill=col["guide"])
            pg.text((box[0] + rr - pg.d.textlength(str(i + 1), font=pg.font(lab)) / 2, iy + rr - lab * 0.6), str(i + 1), lab, col["card"])
            pg.text((box[0] + 2 * rr + 10, iy), nm, lab, col["ink"], maxw=cw - 2 * rr - 10)
            if path:
                im = Image.open(bible.ROOT / path).convert("RGB")
                pg.d.rounded_rectangle([box[0], box[1], box[0] + cw, box[1] + cw], 12, fill=_mix(col["card"], col["accent"], 0.1))
                part = _crop_face(im) if kind == "face" else im.crop(tuple(int(v * s) for v, s in zip(EYE_CROP, im.size * 2))) if kind == "eyes" else _trim(im)
                r, _ = pg.paste(part, box)
                pg.d.rounded_rectangle([box[0], box[1], box[0] + cw, box[1] + cw], 12, outline=col["guide"], width=3)
                figs = pg.anchors.get("figures")
                if figs and ty is not None:   # 正面の人物の該当する高さに番号の印を置く
                    # 線で結ぶと、拡大の枠から正面の人物までの線が四面図を斜めに横切って絵を読みにくくした
                    fx, ft, fb = figs[0]
                    ax, ay = fx - int((fb - ft) * 0.12) - int(lab * 1.8) * i, int(ft + (fb - ft) * ty)
                    saved = pg.panel, pg.pbox
                    pg.panel, pg.pbox = "leader", (0, 0, pg.W, pg.H)
                    rr = int(lab * 0.75)
                    pg.d.line([(ax, ay), (fx, ay)], fill=col["guide"], width=2)
                    pg.d.ellipse([ax - rr, ay - rr, ax + rr, ay + rr], fill=col["guide"])
                    tw = pg.d.textlength(str(i + 1), font=pg.font(lab))
                    pg.text((ax - tw / 2, ay - lab * 0.6), str(i + 1), lab, col["card"])
                    pg.panel, pg.pbox = saved
            else:
                pg.empty(box, "")


def _header(pg, pn, ident, c, x, y, w, h):
    """名前の見出し。名前を最も大きく、その下に小さく英字の id と版の題。名前と本文の大きさの差で階層を見せる"""
    col, th = pg.col, pg.th
    kind = th.get("title_font", "gothic")
    big = pn.get("big")
    s1 = int(h * (0.48 if big else 0.62))
    bar = max(8, int(s1 * 0.14))
    pg.d.rectangle([x, y + int(s1 * 0.08), x + bar, y + int(s1 * 1.1)], fill=col["accent"])
    pg.mark((x, y, x + bar, y + int(s1 * 1.1)))
    nb = pg.text((x + bar * 2.5, y), c["name"], s1, col["page_ink"], maxw=w - bar * 3, kind=kind)
    sub = f"{ident.upper()}  ·  {pn.get('label', '設定資料')}"
    if big:
        pg.text((x + bar * 2.5, nb[3] + s1 * 0.25), sub, max(14, int(s1 * 0.32)), col["page_sub"], maxw=w - bar * 3, kind=kind)
        its = "  ".join(i["name"] for i in c.get("items", [])[:3])
        if its and nb[3] + s1 * 0.9 < y + h - s1 * 0.3:
            pg.text((x + bar * 2.5, nb[3] + s1 * 0.8), its, max(14, int(s1 * 0.3)), col["page_sub"], maxw=w - bar * 3)
        return
    sx = min(nb[2] + s1 * 0.6, x + w * 0.6)
    pg.text((sx, y + s1 * 0.5), sub, max(14, int(s1 * 0.36)), col["page_sub"], maxw=x + w - sx, kind=kind)
    pg.d.line([(x, y + h - 3), (x + w, y + h - 3)], fill=col["accent"], width=4)
    pg.d.line([(x, y + h + 4), (x + w * 0.3, y + h + 4)], fill=col["accent2"], width=2)


def sheet_format(ident: str, name: str, out_png: str, out_html: str | None = None, theme: str | None = None) -> dict:
    """版（styles/sheet-formats/<名前>.json）の欄の並びと、テーマ（styles/sheet-themes/）の見せ方で1枚を書き出す。
    テーマは 指定 → キャラクターの theme → 既定。返り値の drawn は欄ごとの描いた矩形（はみ出しの試験に使う）"""
    fm = load_format(name)
    c = bible.load("characters", ident)
    tname = pick_theme(c, theme)
    th = load_theme(tname)
    W, H = fm["size"]
    pg = _Page(W, H, th, c)
    pg.scale = float(fm.get("text_scale", 1.0))
    sw, notes = _swatches(c), _notes(c)
    # 見出しの番号は版に書いた順に振る。四面図は先に描く（引き出し線の行き先の位置を決めるため）ので、番号を先に決めておく
    numbered = [pn for pn in fm["panels"] if pn.get("title") and (_has_material(pn, ident, c) or not pn.get("optional"))]
    order = sorted(fm["panels"], key=lambda p: p["kind"] != "turnaround")
    for pn in order:
        pg.section = numbered.index(pn) if pn in numbered else pg.section
        pn = {**pn, "label": fm["title"]} if pn["kind"] == "header" else pn
        _panel(pg, pn, ident, c, sw, notes)
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    pg.im.save(out_png, optimize=True)
    over = [(p, d) for p, b, d in pg.drawn if d[0] < b[0] - 1 or d[1] < b[1] - 1 or d[2] > b[2] + 1 or d[3] > b[3] + 1]
    if out_html:
        e = html.escape
        Path(out_html).write_text(
            f'<!doctype html><meta charset="utf-8"><title>{e(c["name"])} {e(fm["title"])}</title>'
            f'<img style="width:100%" src="data:image/png;base64,{base64.b64encode(Path(out_png).read_bytes()).decode()}">',
            encoding="utf-8")
    return {"format": name, "theme": tname, "png": out_png, "size": [W, H], "panels": len(fm["panels"]), "elements": len(pg.drawn),
            "outside_panel": len(over), "drawn": pg.drawn}


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
