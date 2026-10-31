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
  python3 tools/gen/charsheet.py sheet <id> [<出力.html>] <出力.png> --format <版>   版を選んで1枚を出す
  python3 tools/gen/charsheet.py formats   版の一覧（名前・用途・比率・見本の画像）

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
FORMATS_DIR = bible.ROOT / "styles" / "sheet-formats"
INK, SUB, RULE, RED, PAPER = (20, 19, 19), (93, 88, 83), (217, 212, 205), (210, 58, 38), (251, 250, 247)
PANEL_KINDS = {"header", "turnaround", "poses", "expressions", "swatches", "notes", "slots", "callouts", "figure", "sharebar", "strip"}


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
                    "default": bool(fm.get("default")), "sample": f"library/sheets/formats/{fm['name']}.png"})
    return sorted(out, key=lambda f: (not f["default"], f["name"]))


class _Page:
    """描いた物の矩形を欄ごとに記録する。欄からのはみ出しを試験で数えるため"""

    def __init__(self, W, H):
        from PIL import Image, ImageDraw
        self.im = Image.new("RGB", (W, H), PAPER)
        self.d = ImageDraw.Draw(self.im)
        self.W, self.H = W, H
        self.drawn: list[tuple[str, tuple, tuple]] = []   # (欄, 欄の矩形, 描いた矩形)
        self.panel, self.pbox = "", (0, 0, W, H)
        self.anchors: dict = {}

    def font(self, n):
        from PIL import ImageFont
        return ImageFont.truetype(FONT, max(8, int(n)))

    def mark(self, r):
        self.drawn.append((self.panel, self.pbox, tuple(int(v) for v in r)))

    def text(self, xy, t, size, fill=INK, maxw=None):
        """1行の文字。幅を超える分は「…」で切る（欄から出さない）"""
        f = self.font(size)
        if maxw is not None and self.d.textlength(t, font=f) > maxw:
            while t and self.d.textlength(t + "…", font=f) > maxw:
                t = t[:-1]
            t += "…"
        self.d.text(xy, t, fill=fill, font=f)
        b = self.d.textbbox(xy, t, font=f)
        self.mark(b)
        return b

    def wrap(self, x, y, t, size, maxw, maxy, fill=INK, gap=1.4):
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

    def paste(self, img, box, align="center"):
        """枠に収まる最大の大きさで貼る（縦横比を保つ）。返り値は貼った矩形"""
        from PIL import Image
        x, y, w, h = box
        k = min(w / img.width, h / img.height)
        im = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
        px = x + (w - im.width) // 2
        py = y + (h - im.height) if align == "bottom" else y + (h - im.height) // 2
        self.im.paste(im, (int(px), int(py)))
        r = (int(px), int(py), int(px) + im.width, int(py) + im.height)
        self.mark(r)
        return r, k

    def empty(self, box, label):
        x, y, w, h = box
        self.d.rectangle([x, y, x + w - 1, y + h - 1], outline=RULE, width=2)
        for i in range(0, int(w + h), 28):   # 斜線で「空いている」ことを見せる
            a, b = (x + max(0, i - h), y + min(h, i)), (x + min(w, i), y + max(0, i - w))
            self.d.line([a, b], fill=(236, 232, 226), width=1)
        self.mark((x, y, x + w, y + h))
        size = max(14, min(28, int(min(w, h) / 6)))
        f = self.font(size)
        t = "未作成"
        tw = self.d.textlength(t, font=f)
        self.text((x + (w - tw) / 2, y + h / 2 - size), t, size, SUB)
        if label:
            self.text((x + 8, y + h - size - 10), label, int(size * 0.8), SUB, maxw=w - 16)


def _crop_face(im):
    fx = FACE_CROP
    return im.crop((int(fx[0] * im.width), int(fx[1] * im.height), int(fx[2] * im.width), int(fx[3] * im.height)))


def _trim(im):
    from PIL import ImageOps
    box = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 12 else 0).getbbox()
    return im.crop(box) if box else im


def _expr_list(ident, c):
    imgs = c.get("images", {})
    names = {e["id"]: e["name"] for e in bible.expressions_of(ident)}
    order = [e["id"] for e in bible.expressions_of(ident)]
    have = sorted((r for r in imgs if r.startswith("expr-")), key=lambda r: order.index(r[5:]) if r[5:] in order else 99)
    out = [(names.get(r[5:], r[5:]), imgs[r]) for r in have]
    # 名前が重なる表情（照れが2つ）は id を添える。同じ名前が並ぶと別の表情に見えなかった
    dup = [n for n, _ in out]
    out = [((n + f"{dup[:i].count(n) + 1}") if dup.count(n) > 1 else n, p) for i, (n, p) in enumerate(out)]
    # 設定にあって絵の無い表情は空欄で並べる（何が足りないかを版の上で見せる）
    out += [(names[i], None) for i in order if f"expr-{i}" not in imgs]
    return out


def _panel(pg, pn, ident, c, sw, notes):
    from PIL import Image
    W, H = pg.W, pg.H
    x, y, w, h = int(pn["box"][0] * W), int(pn["box"][1] * H), int(pn["box"][2] * W), int(pn["box"][3] * H)
    pg.panel, pg.pbox = pn["kind"], (x, y, x + w, y + h)
    imgs = c.get("images", {})
    title = pn.get("title", "")
    ts = max(18, int(H * 0.018))
    if title:
        pg.text((x, y), title, ts, INK, maxw=w)
        y += int(ts * 1.6)
        h -= int(ts * 1.6)
    k = pn["kind"]
    if k == "header":
        big = pn.get("big")
        s1 = int(h * (0.55 if big else 0.7))
        pg.text((x, y), c["name"], s1, INK, maxw=w)
        sub = f"{ident}  設定資料" if not big else "  ".join(i["name"] for i in c.get("items", [])[:3])
        pg.text((x, y + int(s1 * 1.25)), sub, max(14, int(s1 * 0.4)), SUB, maxw=w) if big else \
            pg.text((x + min(w * 0.5, pg.d.textlength(c["name"], font=pg.font(s1)) + 30), y + s1 * 0.45), sub, int(s1 * 0.42), SUB, maxw=w * 0.45)
        if not big:
            pg.d.line([(x, y + h - 2), (x + w, y + h - 2)], fill=INK, width=3)
    elif k == "turnaround":
        if not imgs.get("turnaround"):
            return pg.empty((x, y, w, h), "四面図")
        t = Image.open(bible.ROOT / imgs["turnaround"]).convert("RGB")
        spans, top, bot = _figures(t)
        lab = int(ts * 0.9)
        left = int(w * 0.09) if pn.get("guides") else 0
        crop = t.crop((spans[0][0] - 10, top, spans[-1][1] + 10, bot + 1)) if spans else t
        # 元の四面図は高さ 304 画素なので 2.5 倍を超えて伸ばさない（線がぼやけた）
        area = (x + left, y, w - left, h - lab * 2)
        kk = min(area[2] / crop.width, area[3] / crop.height, 2.5)
        cw, ch = int(crop.width * kk), int(crop.height * kk)
        # 横長の四面図は欄の高さが余るので上下の中央に置く（下に寄せると上に大きな空白が出た）
        r, kk = pg.paste(crop, (x + left + (area[2] - cw) // 2, y + (area[3] - ch) // 2, cw, ch))
        x0 = r[0] - int((spans[0][0] - 10) * kk) if spans else r[0]
        pg.anchors["figures"] = [(x0 + int((a + b) / 2 * kk), r[1], r[3]) for a, b in spans]
        if pn.get("guides"):
            for frac, label in ((0.0, "頭の上"), (0.5, "半分"), (1.0, "足の下")):
                yy = r[1] + int(frac * (r[3] - r[1] - 1))
                pg.d.line([(x, yy), (x + w, yy)], fill=RED, width=1)
                pg.text((x, yy - lab - 4 if frac else yy + 3), label, lab * 0.85, RED, maxw=left - 4)
        n = pn.get("ruler")
        if n:   # 全身を n 等分する目盛り。頭の高さを測る処理が無いので頭身とは書かない
            rx = r[2] + 16 if r[2] + 60 < x + w else x + left - 30
            for i in range(n + 1):
                yy = r[1] + (r[3] - r[1]) * i / n
                pg.d.line([(rx, yy), (rx + (14 if i % 2 == 0 else 8), yy)], fill=RED, width=2)
            pg.d.line([(rx, r[1]), (rx, r[3])], fill=RED, width=2)
            pg.mark((rx, r[1], rx + 14, r[3]))
            pg.text((max(x, rx - 60), r[1] - lab * 1.8), f"全身の{n}等分", lab * 0.8, RED, maxw=x + w - max(x, rx - 60))
        names = ["正面", "横（右向き）", "横（左向き）", "背面"] if len(spans) == 4 else [""] * len(spans)
        for (cx, _, b), nm in zip(pg.anchors["figures"], names):
            tw = pg.d.textlength(nm, font=pg.font(lab))
            pg.text((max(x, cx - tw / 2), b + 6), nm, lab, SUB)
    elif k in ("poses", "figure"):
        roles = sorted(r for r in imgs if r.startswith("pose-")) if k == "poses" else []
        n = pn.get("count", 1)
        names = {p.get("id"): p.get("name", p.get("id")) for p in c.get("poses", []) if isinstance(p, dict)}
        cells = [(names.get(r[5:], r[5:]), imgs[r]) for r in roles][:n]
        cells += [(p.get("name"), None) for p in c.get("poses", []) if f"pose-{p.get('id')}" not in imgs][:n - len(cells)]
        if k == "figure":
            cells = [("正面", None)]
        cells += [("", None)] * (n - len(cells))
        gap = 24
        cw = (w - gap * (n - 1)) // n
        lab = int(ts * 0.85)
        for i, (nm, path) in enumerate(cells):
            box = (x + i * (cw + gap), y, cw, h - lab * 2)
            if k == "figure" and imgs.get("turnaround"):
                t = Image.open(bible.ROOT / imgs["turnaround"]).convert("RGB")
                spans, top, bot = _figures(t)
                a, b = spans[0]
                pg.paste(t.crop((a - 4, top, b + 4, bot + 1)), box, "bottom")
            elif path:
                r, _ = pg.paste(_trim(Image.open(bible.ROOT / path).convert("RGB")), box, "bottom")
                if nm:   # 名前は絵の真下に置く（ますの左端に置くと絵から離れた）
                    tw = min(cw, pg.d.textlength(nm, font=pg.font(lab)))
                    pg.text((max(box[0], (r[0] + r[2] - tw) / 2), box[1] + box[3] + 6), nm, lab, SUB, maxw=cw)
            else:
                pg.empty(box, nm)
    elif k == "expressions":
        cols, rows = pn.get("cols", 4), pn.get("rows", 2)
        ex = _expr_list(ident, c)[:cols * rows]
        gap = 18
        lab = int(ts * (1.0 if pn.get("large") else 0.8))
        cell = min((w - gap * (cols - 1)) // cols, (h - rows * (lab * 1.6) - gap * (rows - 1)) // rows)
        cell = int(cell)
        ox = x + (w - (cell * cols + gap * (cols - 1))) // 2
        for i, (nm, path) in enumerate(ex):
            cx, cy = ox + (i % cols) * (cell + gap), y + (i // cols) * (cell + int(lab * 1.6) + gap)
            if path:
                pg.paste(_crop_face(Image.open(bible.ROOT / path).convert("RGB")), (cx, cy, cell, cell))
                pg.d.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], outline=RULE)
                pg.text((cx, cy + cell + 4), nm, lab, SUB, maxw=cell)
            else:
                pg.empty((cx, cy, cell, cell), nm)
    elif k == "swatches":
        style = pn.get("style", "list")
        if not sw:
            return pg.empty((x, y, w, h), "色見本")
        if style == "table":
            heads = ["", "名前・役", "ふつう", "影", "ハイライト"]
            colx = [0, 0.12, 0.42, 0.64, 0.82]
            rh = min(int(h / (len(sw) + 1)), 110)
            fs = int(min(rh * 0.3, 30))
            for hx, t in zip(colx, heads):
                pg.text((x + int(hx * w), y), t, fs, SUB, maxw=w * 0.2)
            for i, s in enumerate(sw):
                yy = y + rh * (i + 1)
                rgb = tuple(int(s["hex"][j:j + 2], 16) for j in (1, 3, 5))
                q = int(rh * 0.8)
                pg.d.rectangle([x, yy, x + q, yy + q], fill=rgb, outline=RULE)
                pg.mark((x, yy, x + q, yy + q))
                pg.text((x + int(0.12 * w), yy + 4), s["name"], fs, INK, maxw=w * 0.28)
                pg.text((x + int(0.12 * w), yy + fs * 1.4), s["role"], int(fs * 0.8), SUB, maxw=w * 0.28)
                pg.text((x + int(0.42 * w), yy + 4), s["hex"], fs, INK, maxw=w * 0.2)
                pg.text((x + int(0.42 * w), yy + fs * 1.4), f"{s['share'] * 100:.0f}%", int(fs * 0.8), SUB, maxw=w * 0.2)
                # 影とハイライトの色は描いた絵から決めていない。色を作って埋めると決まりに見えるので空欄にする
                for cx in (0.64, 0.82):
                    pg.empty((x + int(cx * w), yy, int(0.16 * w), q), "")
                pg.d.line([(x, yy + rh - 6), (x + w, yy + rh - 6)], fill=RULE)
        else:
            cols = 2 if style == "grid" else 1
            rows = (len(sw) + cols - 1) // cols
            rh = min(int(h / rows), 80)
            q = int(rh * 0.75)
            fs = int(min(q * 0.42, 26))
            cw = w // cols
            for i, s in enumerate(sw):
                cx, cy = x + (i // rows) * cw, y + (i % rows) * rh
                rgb = tuple(int(s["hex"][j:j + 2], 16) for j in (1, 3, 5))
                pg.d.rectangle([cx, cy, cx + q, cy + q], fill=rgb, outline=RULE)
                pg.mark((cx, cy, cx + q, cy + q))
                pg.text((cx + q + 12, cy), f"{s['name']}  {s['role']}", fs, INK, maxw=cw - q - 16)
                pg.text((cx + q + 12, cy + fs * 1.3), f"{s['hex']}  {s['share'] * 100:.0f}%", int(fs * 0.85), SUB, maxw=cw - q - 16)
    elif k in ("sharebar", "strip"):
        if not sw:
            return pg.empty((x, y, w, h), "色見本")
        tot = sum(s["share"] for s in sw) or 1
        bh = int(h * (0.45 if k == "sharebar" else 0.7))
        xx = x
        for i, s in enumerate(sw):
            ww = int(w * s["share"] / tot) if i < len(sw) - 1 else x + w - xx
            rgb = tuple(int(s["hex"][j:j + 2], 16) for j in (1, 3, 5))
            pg.d.rectangle([xx, y, xx + ww - 1, y + bh], fill=rgb)
            pg.mark((xx, y, xx + ww, y + bh))
            if k == "sharebar" and ww > 40:
                fs = int(min(h * 0.12, 24))
                pg.text((xx + 4, y + bh + 8), s["name"], fs, INK, maxw=ww - 6)
                pg.text((xx + 4, y + bh + 8 + fs * 1.4), f"{s['share'] * 100:.0f}%", fs, SUB, maxw=ww - 6)
            xx += ww
        pg.d.rectangle([x, y, x + w - 1, y + bh], outline=RULE)
    elif k == "notes":
        fs = max(14, int(ts * 0.85))
        yy = y
        for n in notes:
            yy, ok = pg.wrap(x, yy, "・" + n, fs, w, y + h)
            yy += fs * 0.5
            if not ok or yy > y + h - fs * 1.4:
                break
    elif k == "slots":
        ss = pn["slots"]
        gap = 20
        cw = (w - gap * (len(ss) - 1)) // len(ss)
        for i, (role, nm) in enumerate(ss):
            box = (x + i * (cw + gap), y, cw, h)
            if imgs.get(role):
                pg.paste(_trim(Image.open(bible.ROOT / imgs[role]).convert("RGB")), box, "bottom")
            else:
                pg.empty(box, nm)
    elif k == "callouts":
        items = []
        if pn.get("face"):
            src = imgs.get("expr-neutral") or next((imgs[r] for r in sorted(imgs) if r.startswith("expr-")), None)
            items.append(("顔・角・耳", src, "face", 0.07))
        if pn.get("items"):
            items += [(i["name"], imgs.get(f"detail-item-{i['id']}"), "item", None) for i in c.get("items", [])]
        items = items[:pn.get("max", 4)]
        gap = 20
        n = max(1, len(items))
        cw = (w - gap * (n - 1)) // n
        lab = int(ts * 0.8)
        for i, (nm, path, kind, ty) in enumerate(items):
            box = (x + i * (cw + gap), y + lab * 2, cw, min(h - lab * 2, cw))   # 正方形のます。縦に伸ばすと絵と空欄の高さがそろわなかった
            pg.text((box[0], y), f"{i + 1}. {nm}", lab, INK, maxw=cw)
            if path:
                im = Image.open(bible.ROOT / path).convert("RGB")
                r, _ = pg.paste(_crop_face(im) if kind == "face" else _trim(im), box)
                pg.d.rectangle([r[0], r[1], r[2] - 1, r[3] - 1], outline=RED, width=2)
                figs = pg.anchors.get("figures")
                if figs and ty is not None:   # 引き出し線: 拡大の枠の上辺から、正面の該当する高さへ
                    fx, ft, fb = figs[0]
                    ax, ay = fx, int(ft + (fb - ft) * ty)
                    pg.d.line([((r[0] + r[2]) // 2, r[1]), (ax, ay)], fill=RED, width=2)
                    pg.d.ellipse([ax - 6, ay - 6, ax + 6, ay + 6], outline=RED, width=2)
                    # 引き出し線は欄をまたぐのが役目なので、版面の中に収まるかだけを見る
                    saved = pg.panel, pg.pbox
                    pg.panel, pg.pbox = "leader", (0, 0, pg.W, pg.H)
                    pg.text((ax + 10, ay - lab), str(i + 1), lab, RED)
                    pg.panel, pg.pbox = saved
            else:
                pg.empty(box, "")


def sheet_format(ident: str, name: str, out_png: str, out_html: str | None = None) -> dict:
    """版（styles/sheet-formats/<名前>.json）の欄の並びで1枚を書き出す。返り値の drawn は欄ごとの描いた矩形（はみ出しの試験に使う）"""
    fm = load_format(name)
    if fm.get("engine") == "classic":
        h = out_html or str(Path(out_png).with_suffix(".html"))
        r = sheet(ident, h, out_png)
        r["format"] = name
        return r
    c = bible.load("characters", ident)
    W, H = fm["size"]
    pg = _Page(W, H)
    sw, notes = _swatches(c), _notes(c)
    # 四面図を先に描く（引き出し線の行き先の位置を決めるため）
    order = sorted(fm["panels"], key=lambda p: p["kind"] != "turnaround")
    for pn in order:
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
    return {"format": name, "png": out_png, "size": [W, H], "panels": len(fm["panels"]), "elements": len(pg.drawn),
            "outside_panel": len(over), "drawn": pg.drawn}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "formats":
        for f in formats():
            print(f"{f['name']:<11} {f['title']}{'（既定）' if f['default'] else ''}  {f['ratio']}  {f['sample']}\n            {f['purpose']}")
        return
    if len(sys.argv) >= 5 and sys.argv[1] == "sheet" and "--format" in sys.argv:
        a = [v for v in sys.argv[2:]]
        i = a.index("--format")
        name = a[i + 1]
        rest = a[:i] + a[i + 2:]
        out_png = next(v for v in rest[1:] if v.endswith(".png"))
        out_html = next((v for v in rest[1:] if v.endswith(".html")), None)
        r = sheet_format(rest[0], name, out_png, out_html)
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
