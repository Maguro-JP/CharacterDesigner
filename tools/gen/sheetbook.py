"""設定画集を頁に分けて組む。頁ごとに読む人と役割を分ける。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/sheetbook.py <人物の id> [--out library/sheets/book/<id>]

  01 扉: 見て楽しむ人に向けて、一枚絵と名前を大きく見せる
  02 デザインの作り: 描く人に向けて、全身の正面を中央に置き、服・装備・持ち物の拡大を引き出し線と注釈で囲む
  03 四面図と色: 同じ縮尺の向きの図と高さの線、色指定の表
  04 表情と線画: 表情の差分と線画

1枚の版に全部を詰めると、どの欄も小さくなり、姿の設計（服の作り、持ち物の付け方）が読めなかった。
設定資料は描く人が同じ人物を描き直すための資料なので、作りの頁を中心に置き、扉と表情はそれを挟む。
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import bible
import cdhome
import charsheet as cs
import sheetlayout as sl

ROOT = Path(__file__).resolve().parents[2]
W, H = 1200, 800   # CSS の寸法。2倍で書き出して 2400x1600
CACHE = cdhome.HOME / "sheet"

# 部位分けの番号 → 見出しと、服の言葉から注釈を拾う手がかり
PARTS = [
    ("hair", [2], "髪", ("hair", "ponytail", "bangs", "horn", "ear")),
    ("hat", [1], "帽子", ("hat", "helmet", "goggles", "horn", "ribbon")),
    ("upper", [4, 7], "上半身", ("armor", "breastplate", "pauldron", "cardigan", "shirt", "jacket", "blouse", "robe",
                                "overall", "cloak", "cape", "coat", "vest")),
    ("scarf", [17], "襟巻", ("scarf",)),
    ("belt", [8], "帯・ベルト", ("belt", "sash", "obi")),
    ("lower", [5, 6], "下半身", ("skirt", "pants", "trousers", "tights", "hakama", "overall")),
    ("arms", [14, 15], "腕・手", ("gauntlet", "glove", "sleeve", "bracer")),
    ("shoes", [9, 10], "足元", ("boot", "shoe", "loafer", "sandal", "sock")),
]


# 服の言葉（英語の描画用の言葉）を注釈の日本語にする。訳せない言葉は載せない（英語を混ぜると読めない人が出る）
JA = {"silver": "銀の", "plate": "板金の", "armor": "鎧", "breastplate": "胸当て", "pauldrons": "肩当て", "pauldron": "肩当て",
      "gauntlets": "籠手", "gauntlet": "籠手", "red": "赤い", "dark red": "暗い赤の", "scarf": "襟巻", "cape": "外套",
      "long": "長い", "black": "黒い", "skirt": "スカート", "to the knees": "膝丈", "tights": "タイツ", "armored": "装甲の",
      "boots": "ブーツ", "up to the knees": "膝まで", "white": "白い", "shirt": "シャツ", "orange": "橙の", "overalls": "つなぎ",
      "gloves": "手袋", "brown": "茶色の", "goggles": "ゴーグル", "work": "作業用の", "belt": "ベルト", "pants": "ズボン",
      "trousers": "ズボン", "hat": "帽子", "witch": "魔女の", "robe": "ローブ", "purple": "紫の", "sash": "帯",
      "cardigan": "カーディガン", "yellow": "黄色の", "blouse": "ブラウス", "loafers": "ローファー", "hakama": "袴",
      "ponytail": "ポニーテール", "short": "短い", "hair": "髪", "wavy": "波打つ", "cloak": "マント", "hood": "フード",
      "sleeves": "袖", "wide": "幅広の", "pleated": "ひだのある", "grey": "灰色の", "gray": "灰色の", "leather": "革の"}


def ja_note(w: str) -> str:
    import re
    s = re.sub(r"[()]|:\d+(\.\d+)?", "", w).lower().strip()
    for k in sorted(JA, key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(k)}\b", JA[k], s)
    return "" if re.search(r"[a-z]{3,}", s) else s.replace(" ", "")


def _font():
    return sl._font_css()


def _hero_file(ident, c):
    """主役の透かした全身を保存して返す（部位分けは絵のファイルを読むため）"""
    figs = sl._figures(c)
    im, _ = sl._hero(c, figs)
    if im is None:
        return None, None, figs
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{ident}-hero.png"
    bg = __import__("PIL.Image", fromlist=["Image"]).new("RGB", im.size, "white")
    bg.paste(im, mask=im.getchannel("A"))
    bg.save(p)
    return im, p, figs


def _callouts(c, im, src):
    """全身を高さで4つに分け、それぞれを拡大して服の言葉を注釈に付ける。
    部位分けの模型で範囲を取ると、騎士では鎧と外套が1つの「服」になり、拡大が全身に広がった。
    頭身の割合で切るほうが、どの人物でも頭・胸・腰・足の作りが確実に入る"""
    import numpy as np
    alpha = np.asarray(im.getchannel("A")) > 40
    words = [w.strip() for w in (str(c.get("outfit", "")) + "," + str(c.get("look", ""))).replace(";", ",").split(",") if w.strip()]
    bands = [("頭・髪", 0.0, 0.17, ("hair", "eye", "ear", "horn", "hat", "goggles", "ribbon", "helmet", "ponytail", "bangs")),
             ("胸・肩", 0.14, 0.40, ("armor", "breastplate", "pauldron", "scarf", "cardigan", "shirt", "blouse", "jacket", "robe",
                                    "overall", "cape", "cloak", "vest", "collar", "sleeve", "gauntlet", "glove")),
             ("腰・裾", 0.38, 0.64, ("belt", "sash", "obi", "skirt", "pants", "trousers", "hakama", "tights", "pocket")),
             ("脚・足元", 0.62, 1.0, ("boot", "shoe", "loafer", "sock", "sandal", "tights"))]
    out, used = [], set()
    for ja, a, b, keys in bands:
        y0, y1 = int(im.height * a), int(im.height * b)
        cols = np.nonzero(alpha[y0:y1].any(axis=0))[0]
        if not len(cols):
            continue
        rows = alpha[y0:y1]
        ys, xs = np.nonzero(rows)
        import re as _re
        en = [w for w in words if w not in used and any(_re.search(rf"\b{k}s?\b", w.lower()) for k in keys)]
        if ja == "胸・肩":   # 「装甲のブーツ」を鎧の言葉と取り違えないよう、足元の言葉は足元に回す
            en = [w for w in en if not _re.search(r"\b(boot|shoe)s?\b", w.lower())]
        used.update(en)
        notes = [n for n in (ja_note(w) for w in en) if n]
        cy = int(np.median(ys))
        row = np.nonzero(rows[cy])[0]
        cx = float(row[np.argmin(np.abs(row - np.median(xs)))]) if len(row) else float(np.median(xs))   # 脚の間など透けた所に点を打たない
        out.append({"ja": ja, "box": [int(cols.min()), y0, int(cols.max()) + 1, y1],
                    "c": [cx, y0 + cy], "notes": notes[:3]})
    for it in c.get("items", [])[:1]:
        out.append({"ja": it["name"], "box": None, "c": None, "notes": [it.get("desc", "")], "item": True})
    return out


def _render(doc, out_png):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=sl.CHROME if Path(sl.CHROME).exists() else None)
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        pg.set_content(doc)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(200)
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(out_png))
        b.close()


def _page(th, body, extra_css=""):
    ink, page, accent, sub = th.get("ink", "#241a16"), th.get("page", "#f2efe8"), th.get("accent", "#8e1b1f"), th.get("sub", "#6b5a50")
    return f"""<!doctype html><html lang=ja><meta charset=utf-8><style>{_font()}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{W}px;height:{H}px;overflow:hidden;position:relative;background:{page};color:{ink};font-family:'Noto Sans JP';
  -webkit-font-smoothing:antialiased;font-feature-settings:"palt"}}
.folio{{position:absolute;right:36px;bottom:22px;font-size:11px;letter-spacing:.3em;color:{sub}}}
.h{{position:absolute;left:48px;top:36px}}
.h b{{display:block;font-size:12px;letter-spacing:.35em;color:{accent}}}
.h span{{display:block;font-family:'Noto Serif JP';font-weight:700;font-size:28px;margin-top:6px}}
{extra_css}</style><body>{body}</body></html>""".replace("ACCENT", accent).replace("SUBC", sub)


def _theme(c):
    """テーマの色（地・墨・補助・差し色）。人物の指定が無ければ既定の studio"""
    try:
        t = json.loads((ROOT / "styles" / "sheet-themes" / f"{c.get('theme') or 'studio'}.json").read_text(encoding="utf-8"))
        col = dict(t.get("colors", t))
        if col.get("accent") == "character":
            # 差し色を人物の持ち色から借りる版。最も鮮やかな色を使う（"character" のまま渡すと線が描かれなかった）
            import colorsys
            sw = cs._swatches(c)
            def sat(h):
                r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
                hh, l, s = colorsys.rgb_to_hls(r, g, b)
                return s if 0.22 <= l <= 0.55 else -1   # 明るすぎる色は地に溶けて見出しが読めなかった
            best = max((s["hex"] for s in sw), key=sat) if sw else None
            col["accent"] = best if best and sat(best) > 0.15 else col.get("ink", "#1e1d1f")
        return {k: col[k] for k in ("ink", "page", "accent", "sub") if col.get(k)}
    except Exception:
        return {}


def page_cover(ident, c, th, hero, out):
    """扉: 一枚絵（場面つきの色の絵があればそれ）を版面いっぱいに、名前を大きく"""
    from PIL import Image
    # 扉の一枚絵は、検品を通ったポーズの絵を先に使う。色の絵は設定と違う服で描かれていることがある（羊娘で黒いシャツ）
    poses = cs._pose_list(c)
    p = poses[0][1] if poses else c.get("images", {}).get("color")
    art = Image.open(bible.ROOT / p).convert("RGB") if p else None
    name = html.escape(c["name"])
    items = "・".join(i["name"] for i in c.get("items", [])[:3])
    if art is not None:
        pic = f'<img class=art src="{sl._uri(art, "JPEG")}">'
    else:
        pic = f'<img class=art src="{sl._uri(hero)}" style="object-fit:contain">'
    body = f"""{pic}<div class=veil></div>
<div class=t><b>CHARACTER DESIGN</b><h1>{name}</h1><i>{html.escape(ident.upper())}</i>
<p>持ち物 {html.escape(items)}</p></div><div class=folio>01 — 扉</div>"""
    css = """.art{position:absolute;right:0;top:0;height:100%;width:62%;object-fit:cover;object-position:50% 20%}
.veil{position:absolute;left:0;top:0;width:44%;height:100%;background:linear-gradient(90deg,var(--p) 70%,transparent)}
.t{position:absolute;left:64px;top:50%;transform:translateY(-50%);width:460px}
.t b{font-size:12px;letter-spacing:.45em;color:ACCENT}
.t h1{font-family:'Noto Serif JP';font-weight:900;font-size:76px;line-height:1.1;margin:14px 0 10px}
.t i{font-style:normal;font-size:13px;letter-spacing:.6em;color:SUBC}
.t p{margin-top:28px;font-size:15px;line-height:1.9}"""
    doc = _page(th, body, css).replace("var(--p)", th.get("page", "#f2efe8"))
    _render(doc, out)


def page_design(ident, c, th, hero, src, out):
    """デザインの作り: 正面の全身を中央に、部位の拡大を左右に並べ、引き出し線で結ぶ"""
    calls = _callouts(c, hero, src)
    # 剣や杖で横に広い人物は、高さで合わせると左右の拡大の列に重なったので、幅でも縮める
    maxw = W - 2 * (40 + 300 + 30)
    s = min((H - 120) / hero.height, maxw / hero.width)
    fh, fw = hero.height * s, hero.width * s
    fx, fy = (W - fw) / 2, 70
    calls = [k for k in calls if not k.get("item")] 
    left, right = calls[0::2], calls[1::2]
    boxes, lines = [], []
    colw, gap = 300, 22
    for side, lst in (("l", left), ("r", right)):
        n = max(1, len(lst))
        ch = (H - 160 - gap * (n - 1)) / n
        x = 40 if side == "l" else W - 40 - colw
        for i, k in enumerate(lst):
            y = 100 + i * (ch + gap)
            x0, y0, x1, y1 = k["box"]
            crop = hero.crop((x0, y0, x1, y1))
            cw, chh = crop.size
            tx_h = 30 + 19 * len(k["notes"])
            sc = min(colw / cw, (ch - tx_h) / chh)
            iw, ih = cw * sc, chh * sc
            ix = x if side == "l" else x + colw - iw
            notes = "".join(f"<li>{html.escape(t)}</li>" for t in k["notes"])
            num = (i * 2 + (1 if side == "l" else 2))
            # 絵の大きさを数字で決めて置く。欄の中で絵が縮んだ位置を知らないと、引き出し線が絵に届かなかった
            boxes.append(f'<img class=ci src="{sl._uri(crop)}" style="left:{ix:.0f}px;top:{y:.0f}px;width:{iw:.0f}px;height:{ih:.0f}px">'
                         f'<div class="ct {side}" style="left:{x}px;top:{y + ih + 8:.0f}px;width:{colw}px">'
                         f'<b>{num:02d}　{html.escape(k["ja"])}</b><ul>{notes}</ul></div>')
            px, py = fx + k["c"][0] * s, fy + (H - 120 - fh) + k["c"][1] * s
            ax = ix + iw + 6 if side == "l" else ix - 6
            ay = y + ih / 2
            lines.append(f'<path d="M{ax:.0f},{ay:.0f} L{(ax + px) / 2:.0f},{ay:.0f} L{px:.0f},{py:.0f}"/><circle cx="{px:.0f}" cy="{py:.0f}" r="3.5"/><circle cx="{ax:.0f}" cy="{ay:.0f}" r="2"/>')
    accent = th.get("accent", "#8e1b1f")
    body = (f'<div class=h><b>02 — DESIGN</b><span>デザインの作り</span></div>'
            f'<img class=fig src="{sl._uri(hero)}" style="left:{fx:.0f}px;top:{fy + (H - 120 - fh):.0f}px;height:{fh:.0f}px">'
            f'<svg width="{W}" height="{H}" style="position:absolute;inset:0;z-index:3" fill="none" stroke="{accent}" stroke-width="1.2">'
            f'{"".join(lines)}</svg>{"".join(boxes)}<div class=folio>02 — デザインの作り</div>')
    css = """.fig{position:absolute;z-index:2}
.ci{position:absolute;z-index:4}
.ct{position:absolute;z-index:4;font-size:11.5px;line-height:1.6}
.ct.r{text-align:right}
.ct b{display:block;font-size:13px;color:ACCENT;margin-bottom:2px}
.ct ul{list-style:none;color:SUBC}
svg circle{fill:ACCENT}"""
    _render(_page(th, body, css), out)


def page_turn(ident, c, th, figs, out):
    """四面図と色: 同じ縮尺の向きの図を高さの線とともに大きく、色指定の表を右に"""
    im, centers = sl._row(figs)
    sw = cs._swatches(c)
    rows = "".join(f'<tr><td><i style="background:{s["hex"]}"></i></td><td><b>{html.escape(s["name"])}</b><br>'
                   f'<small>{html.escape(s["role"])}　{s["hex"]}</small></td><td class=p>{s["share"] * 100:.0f}%</td></tr>' for s in sw)
    fh = H - 190
    s = fh / im.height
    fw = im.width * s
    fx = 60 + (790 - fw) / 2
    caps = "".join(f'<div class=cap style="left:{fx + fw * cx:.0f}px;top:{110 + fh + 10}px">{html.escape(n)}</div>'
                   for (n, _), cx in zip(figs, centers))
    guides = "".join(f'<div class=g style="top:{110 + fh * t:.0f}px"><span>{n}</span></div>' for n, t in (("頭の上", 0), ("半分", .5), ("足の下", 1)))
    title = "四面図" if len(figs) >= 4 else "正面・背面図"
    body = (f'<div class=h><b>03 — TURNAROUND</b><span>{title}と色</span></div>{guides}'
            f'<img class=t src="{sl._uri(im)}" style="left:{fx:.0f}px;top:110px;height:{fh}px">{caps}'
            f'<table>{rows}</table><div class=folio>03 — {title}と色</div>')
    css = """.t{position:absolute}
.g{position:absolute;left:60px;width:790px;border-top:1px dashed ACCENT;opacity:.6}
.g span{position:absolute;left:0;top:4px;font-size:10.5px;color:SUBC}
.cap{position:absolute;transform:translateX(-50%);font-size:11px;letter-spacing:.2em;color:SUBC}
table{position:absolute;right:48px;top:120px;width:320px;table-layout:fixed;border-collapse:collapse;font-size:12.5px}
td{padding:7px 4px;border-bottom:1px solid rgba(0,0,0,.08);vertical-align:middle}
td:nth-child(1){width:44px}td:nth-child(3){width:48px}
td i{display:block;width:30px;height:30px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.2)}
td small{color:SUBC}
td.h{font-family:monospace;font-size:11px;color:SUBC}
td.p{text-align:right;color:SUBC}"""
    _render(_page(th, body, css), out)


def page_faces(ident, c, th, out):
    """表情と線画"""
    from PIL import Image
    faces = sl._faces(ident, c, 6, crop="bust")
    tiles = "".join(f'<figure><img src="{sl._uri(im, "JPEG")}"><figcaption>{html.escape(n)}</figcaption></figure>' for n, im in faces)
    p = c.get("images", {}).get("lineart")
    line = ""
    if p:
        la = sl._cut_rgba(Image.open(bible.ROOT / p), bible.ROOT / p)
        bb = la.getchannel("A").getbbox()
        if bb:
            line = f'<img class=la src="{sl._uri(la.crop(bb))}">'
    cols = 3 if len(faces) > 4 else max(1, len(faces))
    body = (f'<div class=h><b>04 — EXPRESSION</b><span>表情と線画</span></div>'
            f'<div class=g style="grid-template-columns:repeat({cols},1fr)">{tiles}</div>{line}<div class=folio>04 — 表情と線画</div>')
    css = """.g{position:absolute;left:48px;top:110px;width:760px;display:grid;gap:14px}
figure{background:#fff}
figure img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;object-position:50% 20%}
figcaption{font-size:11.5px;letter-spacing:.2em;padding:6px 8px;color:SUBC}
.la{position:absolute;right:60px;top:90px;height:660px;max-width:320px;object-fit:contain}"""
    _render(_page(th, body, css), out)


def build(ident, out_dir):
    c = bible.load("characters", ident)
    th = _theme(c)
    hero, src, figs = _hero_file(ident, c)
    out_dir = Path(out_dir)
    made = []
    page_cover(ident, c, th, hero, out_dir / "01-cover.png"); made.append("01-cover.png")
    if hero is not None:
        page_design(ident, c, th, hero, src, out_dir / "02-design.png"); made.append("02-design.png")
    if figs:
        page_turn(ident, c, th, figs, out_dir / "03-turnaround.png"); made.append("03-turnaround.png")
    if cs._expr_list(ident, c) or c.get("images", {}).get("lineart"):
        page_faces(ident, c, th, out_dir / "04-expressions.png"); made.append("04-expressions.png")
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ident")
    ap.add_argument("--out")
    a = ap.parse_args()
    out = a.out or ROOT / "library" / "sheets" / "book" / a.ident
    print("\n".join(build(a.ident, out)))


if __name__ == "__main__":
    main()
