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
  python3 tools/gen/charsheet.py sheet <id> <出力.html> <出力.png>   見せる1枚（四面図・表情・色見本・注記）

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
    """見せる1枚を、同じ並べ方で HTML と PNG に書き出す。載せるのは images にある turnaround と expr-*（検品を通した絵だけを登録する）"""
    from PIL import Image, ImageDraw, ImageFont
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
    canvas = Image.new("RGB", (W, 4000), (251, 250, 247))
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
    # 3段目: 色見本（左）と注記（右）
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
    return {"html": out_html, "png": out_png, "size": list(canvas.size), "expressions": len(expr_roles),
            "swatches": {s["name"]: [s["role"], s["share"]] for s in sw}, "bytes": len(page.encode())}


def main():
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
