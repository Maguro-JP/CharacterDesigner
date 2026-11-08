"""キャラクターデザインの流れ（設定資料集・三面図・表情差分）を、アプリから使うための部品。

設定資料集の形と表情・向きの言葉は tools/gen/bible.py の物をそのまま使う（同じ人物を、リポジトリの道具でもアプリでも
同じ資料から描けるように）。違うのは描き方だけで、アプリでは Blender の人形を使わず、今の絵の模型（engine.Painter）で描く。
- 三面図: 設定の「変えない見た目」と「いつもの服」に向きの言葉を足し、同じ種で向きごとに 1 枚描く
- 表情差分: 基準の絵の顔の囲みの中だけを、表情ごとに描き直す。囲みの外（髪・服・体）は 1 画素も変えない
  （finishers.keep_outside で合わせる。顔を切り出して貼り戻すと継ぎ目が出た）
- 設定資料の置き場はデータの置き場（paths.HOME）の bible/。リポジトリの bible/ には書かない
どれも時間がかかるので、画面からは裏の糸（app.py の _run_task）で呼ぶ。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 向きの名前は資料の決まり（tools/gen/charsheet.py の view-front・view-back・view-left・view-right）にそろえる。
# 前は turn-front・turn-side と別の名前で置いていて、三面図を描いても design_status の「足りない物」から消えなかった
TURN_VIEWS = ("front", "left", "back")             # 三面図
FOUR_VIEWS = ("front", "left", "back", "right")    # 四面図（左右は持ち物や髪の結び方が違うので、片方を裏返して作らない）
VIEW_WORDS = {"front": "front", "left": "side", "back": "back", "right": "right"}   # 向き → bible.VIEWS の鍵
VIEW_JA = {"front": "正面", "left": "左", "back": "背面", "right": "右", "side": "左"}
OLD_ROLE = {"turn-front": "view-front", "turn-side": "view-left", "turn-back": "view-back"}   # 前の版の名前
TURN_POSE = "standing straight, arms at sides, open empty hands, hands visible, full body, simple background, character turnaround"
EXPR_STRENGTH = 0.55   # 表情差分の描き直しの強さ。顔の形を残したまま表情だけを変える強さ


class NotReady(RuntimeError):
    """流れを進められない（部品が無い、設定資料がまだ無い）。理由は利用者に見せる日本語で持つ"""


def _home(home=None) -> Path:
    if home is not None:
        return Path(home)
    from chatdraw.paths import HOME
    return HOME


def bible(home=None):
    """tools/gen/bible.py を、置き場をデータの置き場に向けて読む。無ければ NotReady"""
    d = str(Path(__file__).resolve().parents[1] / "tools" / "gen")
    if d not in sys.path:
        sys.path.append(d)
    try:
        import bible as b
    except ImportError as e:
        raise NotReady("キャラクターデザインの部品（tools/gen/bible.py）が入っていません。アプリを入れ直してください") from e
    root = _home(home)
    b.ROOT = root            # 手本の絵の道は ROOT からの相対で持つ（_copy、sheet）
    b.BIBLE = root / "bible"
    return b


def slug(name: str, home=None) -> str:
    """設定資料の id。英数字はそのまま、それ以外（日本語の名前）は番号にする。同じ id があれば後ろに番号を足す"""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "chara"
    folder = _home(home) / "bible" / "characters"
    ident, n = base, 2
    while (folder / f"{ident}.json").exists():
        ident, n = f"{base}-{n}", n + 1
    return ident


def characters(home=None) -> list[dict]:
    """保存した設定資料（id と名前）。新しい順"""
    import json
    folder = _home(home) / "bible" / "characters"
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    out = []
    for p in files:
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            out.append(dict(id=c["id"], name=c.get("name", c["id"])))
        except (OSError, ValueError, KeyError):
            continue
    return out


def palette(image, n: int = 8) -> list[str]:
    """絵の中の多い色を n 色。白い地（明るく色の薄い所）は数えない"""
    from PIL import Image
    small = image.convert("RGB").copy()
    small.thumbnail((256, 256))
    q = small.quantize(n + 4, method=Image.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors(), reverse=True)
    out = []
    for _count, i in counts:
        r, g, b = pal[i * 3:i * 3 + 3]
        if min(r, g, b) > 235:
            continue
        out.append(f"#{r:02x}{g:02x}{b:02x}")
        if len(out) == n:
            break
    return out


def save_character(name: str, look: str, image, outfit: str = "", notes: str = "", home=None) -> dict:
    """描いた人物を設定資料に保存する。絵は色の手本（color）として置き、色見本も取る"""
    import tempfile
    b = bible(home)
    ident = slug(name, home)
    b.new_character(ident, name, look, outfit, notes=notes)
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "color.png"
        image.convert("RGB").save(src)
        b.add_image(ident, "color", str(src))
    c = b.load("characters", ident)
    c["palette"] = palette(image)
    b.save("characters", c)
    return c


def turnaround_plan(ident: str, home=None, views=TURN_VIEWS) -> list[dict]:
    """三面図の向きごとの描く言葉。持ち物は持たせない（三面図で持たせると手と持ち物が崩れた）"""
    b = bible(home)
    c = b.load("characters", ident)
    out = []
    for v in views:
        words = b.VIEWS[VIEW_WORDS[v]][0]
        prompt = ", ".join(x for x in (c["look"], c.get("outfit", ""), TURN_POSE, words) if x)
        out.append(dict(view=v, name=VIEW_JA[v], prompt=prompt, negative=c.get("negative", "")))
    return out


def _add(b, ident: str, role: str, image) -> str:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"{role}.png"
        image.convert("RGB").save(src)
        return b.add_image(ident, role, str(src))


def draw_turnaround(painter, ident: str, seed: int = 0, size=None, say=lambda msg: None, home=None, views=TURN_VIEWS) -> dict:
    """三面図（views を FOUR_VIEWS にすると四面図）を描いて設定資料に置く。返すのは向き → 置き場（データの置き場からの相対）。
    同じ種で描く（向きごとに種を替えると、服と髪の形が向きごとに変わった）"""
    _need(painter, "三面図" if len(views) == 3 else "四面図")
    b = bible(home)
    title = "三面図" if len(views) == 3 else "四面図"
    out = {}
    for i, v in enumerate(turnaround_plan(ident, home, views), 1):
        say(f"{title}: {v['name']}を描いています（{i}/{len(views)}）")
        im = painter.paint(v["prompt"], seed, size=size)
        out[v["view"]] = _add(b, ident, f"view-{v['view']}", im)
    _drop_old(b, ident)
    return out


def _need(painter, what: str):
    if painter is None or not getattr(painter, "ready", lambda: False)():
        raise NotReady(f"{what}を描くには絵の模型が要ります。AI のメニューで模型を取ってください")


def _drop_old(b, ident: str):
    """新しい名前（view-*）で描き直したら、前の版の名前（turn-*）の絵を資料から外す（同じ向きが 2 枚並ばないように）"""
    c = b.load("characters", ident)
    imgs = c.get("images", {})
    old = [k for k, new in OLD_ROLE.items() if k in imgs and new in imgs]
    if old:
        for k in old:
            imgs.pop(k)
        b.save("characters", c)


def images_of(ident: str, home=None) -> dict:
    """資料の絵（役割 → 置き場）。前の版の turn-* は今の名前（view-*）に読み替える"""
    imgs = dict(bible(home).load("characters", ident).get("images", {}))
    for old, new in OLD_ROLE.items():
        if old in imgs:
            imgs.setdefault(new, imgs[old])
            imgs.pop(old)
    return imgs


def face_mask(image, boxes):
    """顔の枠（x0, y0, x1, y1 の並び）から、表情差分で描き直す囲みを作る（枠を少し広げた楕円）"""
    from PIL import Image, ImageDraw
    m = Image.new("L", image.size, 0)
    d = ImageDraw.Draw(m)
    for x0, y0, x1, y1 in boxes:
        px, py = (x1 - x0) * 0.08, (y1 - y0) * 0.08
        d.ellipse((x0 - px, y0 - py, x1 + px, y1 + py), fill=255)
    return m


def draw_expressions(painter, ident: str, base, mask, seed: int = 0, only=None, say=lambda msg: None,
                     strength: float = EXPR_STRENGTH, home=None) -> dict:
    """表情差分を描いて設定資料に置く。base（PIL）の mask（白が顔）の中だけを表情ごとに描き直し、外は base のまま"""
    from chatdraw.finishers import keep_outside
    _need(painter, "表情差分")
    if mask is None or mask.convert("L").getbbox() is None:
        raise NotReady("顔が見つかりませんでした。顔を選択範囲か赤ペンで囲んでから、もう一度選んでください")
    b = bible(home)
    plan = b.expressions_plan(ident, only)
    src = base.convert("RGB")
    out = {}
    for k, e in enumerate(plan, 1):
        say(f"表情差分: {e['name']}を描いています（{k}/{len(plan)}）")
        res = painter.redraw(e["prompt"], seed + k, src, mask, strength=strength)
        out[e["id"]] = _add(b, ident, f"expr-{e['id']}", keep_outside(src, res, mask))
    return out


def write_sheet(ident: str, home=None) -> Path:
    """設定資料のページ（絵を埋め込んだ 1 つの HTML）を設定資料の隣に書く"""
    b = bible(home)
    out = b.BIBLE / "characters" / f"{ident}.html"
    b.sheet(ident, str(out))
    return out


# ---- キャラクターシート（1 枚に名前と設定・三面図・表情差分・色の見本・持ち物・目の拡大を並べる） ----

SHEET_W = 2400        # シートの幅。段ごとに絵を縮めてこの幅に収める
SHEET_GAP = 24
SHEET_PAD = 16        # 区画の中の余白
CAPTION_PX = 26       # 絵の下の名前の字の大きさ
# 並びの型: 名前 → 段の並び（段 = 区画の鍵の並び）。区画は blocks の鍵。中身の無い区画は飛ばす
SHEET_LAYOUTS = {
    "横長": [["profile", "colors"], ["views", "eyes"], ["expressions"], ["items", "extras"]],
    "縦長": [["profile"], ["views"], ["expressions"], ["eyes", "colors"], ["items"], ["extras"]],
    "絵を大きく": [["views"], ["expressions"], ["profile", "eyes", "colors"], ["items", "extras"]],
}
SHEET_LAYOUT = "横長"
SHEET_LAYOUT_W = {"横長": 2400, "縦長": 1600, "絵を大きく": 2400}
# 日本語の字が出る書体。上から探す（DejaVu などの欧文の書体では日本語が豆腐になる。
# 中国語の書体（WenQuanYi など）は日本語の字形と違う字があるので使わない）
JA_FONTS = ("meiryo.ttc", "YuGothM.ttc", "YuGothR.ttc", "msgothic.ttc", "ipag.ttf", "ipagp.ttf", "fonts-japanese-gothic.ttf",
            "NotoSansCJKjp-Regular.otf", "NotoSansCJK-Regular.ttc", "NotoSansJP-Regular.otf", "ヒラギノ角ゴシック W3.ttc")
# 色の名前（近い色の名前を付ける。値は sRGB）
COLOR_NAMES = (("黒", (20, 20, 20)), ("灰", (128, 128, 128)), ("白", (245, 245, 245)), ("赤", (200, 30, 40)),
               ("朱", (230, 80, 40)), ("橙", (240, 150, 40)), ("黄", (240, 210, 60)), ("黄緑", (150, 200, 60)),
               ("緑", (40, 150, 70)), ("青緑", (30, 150, 150)), ("水色", (120, 190, 230)), ("青", (40, 80, 200)),
               ("紺", (30, 40, 100)), ("紫", (120, 60, 160)), ("桃", (240, 150, 180)), ("肌", (245, 205, 175)),
               ("茶", (130, 80, 40)), ("焦げ茶", (70, 40, 25)), ("金", (200, 160, 60)), ("銀", (190, 190, 200)))


def ja_font_path() -> Path | None:
    """日本語の字が出る書体の置き場。同梱の chatdraw/fonts を先に、無ければ OS の物を探す"""
    own = sorted((Path(__file__).parent / "fonts").glob("*.[ot]t[fc]"))
    if own:
        return own[0]
    for d in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/System/Library/Fonts"), Path("/Library/Fonts")):
        if not d.exists():
            continue
        for name in JA_FONTS:
            hit = next(iter(d.rglob(name)), None)
            if hit:
                return hit
    return None


def _font(px: int):
    from PIL import ImageFont
    p = ja_font_path()
    try:
        return ImageFont.truetype(str(p), px) if p else ImageFont.load_default(px)
    except (OSError, TypeError):
        return ImageFont.load_default()


def color_name(value: str) -> str:
    v = value.lstrip("#")
    rgb = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    return min(COLOR_NAMES, key=lambda c: sum((a - b) ** 2 for a, b in zip(rgb, c[1])))[0]


def named_colors(values) -> list[dict]:
    """色の値の並びに名前を付ける。同じ名前が続くときは番号を足す（赤 1、赤 2）"""
    out, seen = [], {}
    for v in values:
        n = color_name(v)
        seen[n] = seen.get(n, 0) + 1
        out.append({"name": n if seen[n] == 1 else f"{n} {seen[n]}", "value": v, "part": ""})
    return out


def _wrap(draw, text: str, font, width: int) -> list[str]:
    """字の幅で折り返す（日本語は語の切れ目が空白ではないので、1 字ずつ測る）"""
    lines = []
    for para in str(text).split("\n"):
        line = ""
        for ch in para:
            if line and draw.textlength(line + ch, font=font) > width:
                lines.append(line)
                line = ch
            else:
                line += ch
        lines.append(line)
    return lines


def _text_block(title: str, rows: list[tuple[str, str]], width: int = 760, swatches=None):
    """文字の区画（白地に見出しと行）。swatches は [(色の値, 文)]: 色の四角と文を並べる"""
    from PIL import Image, ImageDraw
    big, small = _font(44), _font(28)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines: list[tuple[str, object, str | None]] = [(title, big, None)]
    for k, v in rows:
        if not v:
            continue
        for i, line in enumerate(_wrap(probe, f"{k}: {v}" if k else str(v), small, width - SHEET_PAD * 2)):
            lines.append((line, small, None))
    for value, text in swatches or []:
        lines.append((text, small, value))
    h = SHEET_PAD * 2 + sum((60 if f is big else 40) for _l, f, _s in lines)
    im = Image.new("RGBA", (width, h), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    y = SHEET_PAD
    for line, f, sw in lines:
        x = SHEET_PAD
        if sw:
            d.rectangle((x, y + 4, x + 48, y + 34), fill=sw, outline=(60, 60, 60))
            x += 60
        d.text((x, y), line, font=f, fill=(25, 25, 25))
        y += 60 if f is big else 40
    return im


def _captioned(im, caption: str, h: int):
    """絵を高さ h に縮め、下に名前を書いた 1 枚"""
    from PIL import Image, ImageDraw
    im = im.convert("RGBA")
    w = max(1, round(im.width * h / im.height))
    px = max(CAPTION_PX, h // 22)   # 高い段は縮めて並べるので、字も段の高さに合わせて大きくする（小さすぎて読めなかった）
    out = Image.new("RGBA", (w, h + px + 12), (255, 255, 255, 0))
    out.paste(im.resize((w, h), Image.LANCZOS), (0, 0))
    d = ImageDraw.Draw(out)
    f = _font(px)
    tw = d.textlength(caption, font=f)
    d.text(((w - tw) / 2, h + 4), caption, font=f, fill=(40, 40, 40, 255))
    return out


def _strip(pics, h: int):
    """名前付きの絵を横に並べた 1 枚（区画の中の並び）と、並べた位置"""
    from PIL import Image
    tiles = [(n, _captioned(im, n, h)) for n, im in pics]
    w = sum(t.width for _n, t in tiles) + SHEET_PAD * (len(tiles) + 1)
    out = Image.new("RGBA", (w, max(t.height for _n, t in tiles) + SHEET_PAD * 2), (0, 0, 0, 0))
    x = SHEET_PAD
    for _n, t in tiles:
        out.alpha_composite(t, (x, SHEET_PAD))
        x += t.width + SHEET_PAD
    return out


def eye_crop(image, faces=None):
    """正面の絵から目のあたりを切り出す（目の拡大の絵が無いときにシートに置く物）。顔の枠が無ければ全身の頭の位置から"""
    w, h = image.size
    if faces:
        x0, y0, x1, y1 = faces[0]
    else:
        x0, y0, x1, y1 = w * 0.36, h * 0.04, w * 0.64, h * 0.22
    fh = y1 - y0
    return image.crop((int(x0), int(y0 + fh * 0.25), int(x1), int(y0 + fh * 0.65)))


def sheet_blocks(ident: str, home=None) -> dict:
    """シートの区画（鍵 → (レイヤーの名前, 絵)）。中身の無い区画は入れない"""
    from PIL import Image
    b = bible(home)
    root = _home(home)
    c = b.load("characters", ident)
    imgs = images_of(ident, home)

    def opened(rel):
        with Image.open(root / rel) as im:
            return im.convert("RGBA")
    out = {}
    prof = [("年齢", c.get("age", "")), ("身長・頭身", c.get("height", "")), ("役割", c.get("role", "")),
            ("性格", c.get("personality", "")), ("背景設定", c.get("backstory", "")), ("見た目", c.get("look", "")),
            ("いつもの服", c.get("outfit", "")), ("目", (c.get("eyes") or {}).get("tags", "")), ("決まり", c.get("rules", "")),
            ("描かない物", c.get("negative", ""))]
    out["profile"] = ("名前と設定", _text_block(c.get("name", ident), prof))
    views = [(VIEW_JA[v], opened(imgs[f"view-{v}"])) for v in FOUR_VIEWS if f"view-{v}" in imgs]
    if not views and "color" in imgs:
        views = [("色の手本", opened(imgs["color"]))]
    if views:
        out["views"] = ("三面図" if len(views) <= 3 else "四面図", _strip(views, 900))
    names = {e["id"]: e["name"] for e in b.expressions_of(ident)}
    expr = [(names.get(k[5:], k[5:]), opened(v)) for k, v in imgs.items() if k.startswith("expr-")]
    if expr:
        out["expressions"] = ("表情差分", _strip(expr, 420))
    if "detail-eyes" in imgs:
        out["eyes"] = ("目の拡大", _strip([("目の拡大", opened(imgs["detail-eyes"]))], 320))
    elif "view-front" in imgs:
        out["eyes"] = ("目の拡大", _strip([("目の拡大（正面から切り出し）", eye_crop(opened(imgs["view-front"])))], 320))
    colors = c.get("colors") or named_colors(c.get("palette", []))
    if colors:
        sw = [(x["value"], f"{x['name']}  {x['value']}" + (f"  {x['part']}" if x.get("part") else "")) for x in colors]
        out["colors"] = ("色の見本", _text_block("色の見本", [], 560, sw))
    items = c.get("items", [])
    if items:
        rows = [(i.get("name", i["id"]), "、".join(x for x in (i.get("desc", ""), i.get("hold", ""), i.get("size", "")) if x)
                 or i.get("tags", "")) for i in items]
        block = _text_block("持ち物", rows, 760)
        pics = [(i.get("name", i["id"]), opened(imgs[f"detail-item-{i['id']}"])) for i in items if f"detail-item-{i['id']}" in imgs]
        if pics:
            strip = _strip(pics, 320)
            both = Image.new("RGBA", (block.width + strip.width, max(block.height, strip.height)), (0, 0, 0, 0))
            both.alpha_composite(block, (0, 0))
            both.alpha_composite(strip, (block.width, 0))
            block = both
        out["items"] = ("持ち物", block)
    extra = []
    for prefix, label in (("pose-", "ポーズ"), ("hairstyle-", "髪型"), ("outfit-", "服"), ("detail-outfit-", "服の部位"),
                          ("detail-hair", "髪の拡大"), ("detail-height", "身長の比較")):
        for k, v in sorted(imgs.items()):
            if k.startswith(prefix) and not (prefix == "outfit-" and k.startswith("detail-")):
                extra.append((f"{label} {k[len(prefix):]}".strip(), opened(v)))
    if extra:
        out["extras"] = ("追加資料", _strip(extra, 360))
    return out


def compose_sheet(ident: str, home=None, layout: str = SHEET_LAYOUT) -> dict:
    """キャラクターシートを 1 枚に組む。区画ごとに 1 枚のレイヤー（project.write_psd に渡す形）と、まとめた 1 枚。
    段の区画は同じ高さにそろえ、段の幅をシートの幅に合わせて縮める"""
    from types import SimpleNamespace
    from PIL import Image
    if layout not in SHEET_LAYOUTS:
        raise NotReady(f"並びの型「{layout}」はありません。選べる型: {'、'.join(SHEET_LAYOUTS)}")
    blocks = sheet_blocks(ident, home)
    if not any(k in blocks for k in ("views", "expressions")):
        raise NotReady("この人物にはまだ絵がありません。三面図か表情差分を描いてから作ってください")
    width = SHEET_LAYOUT_W[layout]
    rows = []
    for keys in SHEET_LAYOUTS[layout]:
        row = [blocks[k] for k in keys if k in blocks]
        if not row:
            continue
        h = max(im.height for _n, im in row)
        scaled = [(n, im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)) for n, im in row]
        total = sum(im.width for _n, im in scaled) + SHEET_GAP * (len(scaled) - 1)
        k = min(1.0, (width - SHEET_GAP * 2) / total)
        if k < 1.0:
            scaled = [(n, im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)) for n, im in scaled]
        rows.append(scaled)
    h = sum(r[0][1].height for r in rows) + SHEET_GAP * (len(rows) + 1)
    layers = [SimpleNamespace(name="背景", visible=True, opacity=1.0, image=Image.new("RGBA", (width, h), (236, 236, 240, 255)))]
    y = SHEET_GAP
    for r in rows:
        x = SHEET_GAP
        for n, im in r:
            layer = Image.new("RGBA", (width, h), (0, 0, 0, 0))
            layer.paste(im, (x, y))
            layers.append(SimpleNamespace(name=n, visible=True, opacity=1.0, image=layer))
            x += im.width + SHEET_GAP
        y += r[0][1].height + SHEET_GAP
    merged = layers[0].image.copy()
    for l in layers[1:]:
        merged.alpha_composite(l.image)
    return {"size": (width, h), "layers": layers, "merged": merged, "layout": layout}


def write_sheet_psd(ident: str, out=None, home=None, layout: str = SHEET_LAYOUT) -> Path:
    """キャラクターシートをレイヤーの PSD で書き、まとめた PNG を隣に置く（既定は設定資料の隣の <id>-sheet.psd と .png）"""
    from chatdraw.project import write_psd
    from PySide6.QtGui import QImage
    snap = compose_sheet(ident, home, layout)
    out = Path(out) if out else bible(home).BIBLE / "characters" / f"{ident}-sheet.psd"
    out.parent.mkdir(parents=True, exist_ok=True)
    snap["merged"].convert("RGB").save(out.with_suffix(".png"))

    def q(im):
        im = im.convert("RGBA")
        return QImage(im.tobytes(), im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()
    for l in snap["layers"]:
        box = l.image.getchannel("A").getbbox() if l.name != "背景" else None
        if box:   # 区画の所だけを書く（全面の透明を 8 枚書くと 1 枚のシートが 150MB を超えた）
            l.left, l.top = box[0], box[1]
            l.image = l.image.crop(box)
        l.image = q(l.image)
    snap["merged"] = q(snap["merged"])
    write_psd(snap, out)
    return out


# ---- 追加資料（キャラクターデザイナーのメニューの項目）。名前は design_status の「足りない物」と同じ ----

POSE_FRAME = "full body, simple background, white background"
BUST_FRAME = "upper body, portrait, bust shot, simple background, white background"
CLOSE_STRENGTH = 0.35   # 拡大の描き直しの強さ。元の絵の形と色を残し、細部だけを足す


def _base_words(c: dict) -> str:
    return ", ".join(x for x in (c.get("look", ""), (c.get("eyes") or {}).get("tags", "")) if x)


def draw_poses(painter, ident: str, seed: int = 0, size=None, say=lambda m: None, home=None) -> dict:
    """ポーズ差分（pose-<id>）。設定に poses が無ければ既定の 4 種（立ち・歩き・役どころの動作・持ち物を使う）"""
    _need(painter, "ポーズ差分")
    b = bible(home)
    c = b.load("characters", ident)
    plan = b.variants_plan(ident, "pose")
    out = {}
    for i, v in enumerate(plan, 1):
        say(f"ポーズ差分: {v['name']}を描いています（{i}/{len(plan)}）")
        prompt = ", ".join(x for x in (_base_words(c), c.get("outfit", ""), v["tags"], POSE_FRAME) if x)
        out[v["id"]] = _add(b, ident, f"pose-{v['id']}", painter.paint(prompt, seed, size=size))
    return out


def _put_list(b, ident: str, key: str, entries: list[dict]):
    c = b.load("characters", ident)
    have = {e["id"]: e for e in c.get(key, [])}
    have.update({e["id"]: e for e in entries})
    c[key] = list(have.values())
    b.save("characters", c)


def draw_hairstyles(painter, ident: str, seed: int = 0, styles=None, size=None, say=lambda m: None, home=None) -> dict:
    """髪型差分（hairstyle-<id>）。styles は [{"id", "name", "tags"}]。渡せば設定資料の hairstyles に足す。
    髪型は人物ごとの設計なので、既定の髪型は作らない（無ければ NotReady）"""
    _need(painter, "髪型差分")
    b = bible(home)
    if styles:
        _put_list(b, ident, "hairstyles", styles)
    plan = b.variants_plan(ident, "hairstyle")
    if not plan:
        raise NotReady("髪型がまだありません。髪型の名前と描く言葉を書いてから選んでください")
    c = b.load("characters", ident)
    out = {}
    for i, v in enumerate(plan, 1):
        say(f"髪型差分: {v['name']}を描いています（{i}/{len(plan)}）")
        prompt = ", ".join(x for x in (_base_words(c), c.get("outfit", ""), v["tags"], BUST_FRAME) if x)
        out[v["id"]] = _add(b, ident, f"hairstyle-{v['id']}", painter.paint(prompt, seed, size=size))
    return out


def draw_outfits(painter, ident: str, seed: int = 0, outfits=None, size=None, say=lambda m: None, home=None) -> dict:
    """服の差分（outfit-<id>）と服の部位の拡大（detail-outfit-<n>）。outfits は [{"id", "name", "tags"}] で、
    渡せば設定資料の outfits に足す。部位はいつもの服の言葉を読点で分けた物（最大 3 か所）"""
    _need(painter, "服の差分")
    b = bible(home)
    if outfits:
        _put_list(b, ident, "outfits", outfits)
    c = b.load("characters", ident)
    out = {}
    plan = c.get("outfits", [])
    for i, v in enumerate(plan, 1):
        say(f"服の差分: {v['name']}を描いています（{i}/{len(plan)}）")
        prompt = ", ".join(x for x in (_base_words(c), v["tags"], "standing, " + POSE_FRAME) if x)
        out[v["id"]] = _add(b, ident, f"outfit-{v['id']}", painter.paint(prompt, seed, size=size))
    parts = c.get("outfit_parts") or [p.strip() for p in re.split(r"[,、]", c.get("outfit", "")) if p.strip()][:3]
    if parts and not c.get("outfit_parts"):
        c = b.load("characters", ident)   # 読み直す（上で足した絵を、前に読んだ中身で上書きしない）
        c["outfit_parts"] = parts
        b.save("characters", c)
    for i, part in enumerate(parts, 1):
        say(f"服の部位の拡大: {part}（{i}/{len(parts)}）")
        prompt = f"{part}, clothing detail, close-up, no humans, simple background, white background"
        out[f"part-{i}"] = _add(b, ident, f"detail-outfit-{i}", painter.paint(prompt, seed + i, size=size))
    if not out:
        raise NotReady("服の言葉がありません。設定の「いつもの服」か、服の差分の言葉を書いてください")
    return out


def draw_items(painter, ident: str, seed: int = 0, items=None, size=None, say=lambda m: None, home=None) -> dict:
    """持ち物の設定（detail-item-<id>）。items は [{"id", "name", "tags", "desc", "hold", "size"}] で、渡せば設定資料に足す。
    持ち物は人を描かずに物だけを描く（人に持たせると手と持ち物が崩れた）"""
    _need(painter, "持ち物の設定")
    b = bible(home)
    for it in items or []:
        b.add_item(ident, it["id"], it.get("name", it["id"]), it.get("tags", ""), it.get("desc", ""),
                   hold=it.get("hold", ""), size=it.get("size", ""))
    plan = b.load("characters", ident).get("items", [])
    if not plan:
        raise NotReady("持ち物がまだありません。持ち物の名前と描く言葉を書いてから選んでください")
    out = {}
    for i, it in enumerate(plan, 1):
        say(f"持ち物の設定: {it['name']}を描いています（{i}/{len(plan)}）")
        prompt = ", ".join(x for x in (it.get("tags", ""), it.get("size", ""),
                                       "item design, object only, no humans, simple background, white background") if x)
        out[it["id"]] = _add(b, ident, f"detail-item-{it['id']}", painter.paint(prompt, seed + i, size=size))
    return out


def set_colors(ident: str, colors=None, home=None) -> list[dict]:
    """色の指定（設定資料の colors）。colors は [{"name", "value", "part"}]。無ければ正面か色の手本の絵から 8 色取って名前を付ける"""
    from PIL import Image
    b = bible(home)
    c = b.load("characters", ident)
    if not colors:
        imgs = images_of(ident, home)
        rel = imgs.get("view-front") or imgs.get("color")
        if not rel:
            raise NotReady("色を取る絵がありません。三面図か色の手本を先に置いてください")
        with Image.open(_home(home) / rel) as im:
            vals = palette(im)
        colors = named_colors(vals)
        c["palette"] = vals
    c["colors"] = list(colors)
    b.save("characters", c)
    return c["colors"]


def _closeup(painter, ident: str, role: str, region, prompt: str, seed: int, home=None) -> dict:
    """正面の絵の region（x0, y0, x1, y1 の割合）を切り出して大きくし、模型に細部を描き直させる（弱い強さ）"""
    from PIL import Image
    b = bible(home)
    imgs = images_of(ident, home)
    if "view-front" not in imgs:
        raise NotReady("正面の絵がありません。三面図を先に描いてください")
    with Image.open(_home(home) / imgs["view-front"]) as im:
        src = im.convert("RGB")
    w, h = src.size
    crop = src.crop(tuple(int(v * (w if i % 2 == 0 else h)) for i, v in enumerate(region)))
    scale = 1024 / max(crop.size)
    crop = crop.resize((max(8, round(crop.width * scale)) // 8 * 8, max(8, round(crop.height * scale)) // 8 * 8), Image.LANCZOS)
    mask = Image.new("L", crop.size, 255)
    res = painter.redraw(prompt, seed, crop, mask, strength=CLOSE_STRENGTH)
    return {role: _add(b, ident, role, res)}


def draw_eyes(painter, ident: str, seed: int = 0, say=lambda m: None, home=None) -> dict:
    """目の拡大（detail-eyes）。正面の絵の目のあたりを大きくして細部を描かせる"""
    _need(painter, "目の拡大")
    c = bible(home).load("characters", ident)
    say("目の拡大を描いています")
    words = ", ".join(x for x in ((c.get("eyes") or {}).get("tags", ""), "close-up of eyes, detailed eyes, eyelashes") if x)
    return _closeup(painter, ident, "detail-eyes", (0.36, 0.08, 0.64, 0.18), words, seed, home)


def draw_hair(painter, ident: str, seed: int = 0, say=lambda m: None, home=None) -> dict:
    """髪の拡大（detail-hair）。正面の絵の頭のあたりを大きくして細部を描かせる"""
    _need(painter, "髪の拡大")
    c = bible(home).load("characters", ident)
    say("髪の拡大を描いています")
    return _closeup(painter, ident, "detail-hair", (0.3, 0.0, 0.7, 0.2),
                    ", ".join(x for x in (c.get("look", ""), "close-up of hair, detailed hair strands") if x), seed, home)


def _cm(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(cm|センチ)", str(text or ""))
    return float(m.group(1)) if m else None


def height_compare(ident: str, others=(), home=None) -> dict:
    """身長の比較（detail-height）。この人物とほかの人物の正面の絵を、設定の身長（〜cm）の比で並べ、目盛りを引く。
    絵は描かない（並べるだけ）。身長の書いていない人物は 160cm として並べ、名前の横に「身長未設定」と書く"""
    from PIL import Image, ImageDraw
    b = bible(home)
    root = _home(home)
    people = []
    for i in (ident, *others):
        imgs = images_of(i, home)
        rel = imgs.get("view-front") or imgs.get("color")
        if not rel:
            continue
        c = b.load("characters", i)
        with Image.open(root / rel) as im:
            people.append((c.get("name", i), _cm(c.get("height", "")), im.convert("RGBA")))
    if not people:
        raise NotReady("並べる絵がありません。三面図を先に描いてください")
    tallest = max(p[1] or 160 for p in people)
    H, top, f = 1000, 80, _font(28)
    tiles = []
    for name, cm, im in people:
        h = round(H * (cm or 160) / tallest)
        tiles.append((name + ("" if cm else "（身長未設定）"), cm, im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)))
    W = 120 + sum(t[2].width + 40 for t in tiles)
    out = Image.new("RGBA", (W, H + top + 60), (255, 255, 255, 255))
    d = ImageDraw.Draw(out)
    for k in range(0, int(tallest) + 1, 10):   # 10cm ごとの目盛り
        y = top + H - round(H * k / tallest)
        d.line((80, y, W, y), fill=(220, 220, 225) if k % 50 else (170, 170, 180), width=1)
        if k % 50 == 0:
            d.text((8, y - 14), f"{k}cm", font=f, fill=(90, 90, 90))
    x = 120
    for name, cm, im in tiles:
        out.alpha_composite(im, (x, top + H - im.height))
        d.text((x, top + H + 10), name + (f" {cm:g}cm" if cm else ""), font=f, fill=(30, 30, 30))
        x += im.width + 40
    return {"detail-height": _add(b, ident, "detail-height", out)}


# 追加資料の項目: (鍵, メニューの名前, ツールチップ, 満たす design_status の項目)。順はメニューの並び
EXTRAS = [
    ("turnaround", "三面図", "正面・左・背面を同じ種で描きます", "全身の四面図: 正面・背面・左"),
    ("fourview", "四面図", "正面・左・背面・右を同じ種で描きます（左右は裏返さずに描きます）", "全身の四面図"),
    ("expressions", "表情差分", "正面の絵の顔の中だけを、表情ごとに描き直します。顔の外は変えません", "胸から上: 表情差分"),
    ("poses", "ポーズ差分", "立ち・歩き・役どころの動作・持ち物を使う、を全身で描きます", "ポーズ"),
    ("hairstyles", "髪型差分", "書いた髪型ごとに胸から上を描きます", "胸から上: 髪型差分"),
    ("outfits", "服の差分", "書いた服ごとに全身を描き、いつもの服の部位を拡大で描きます", "服・装飾・武装: 服の部位の拡大"),
    ("items", "持ち物の設定", "持ち物ごとに、人を描かずに物だけを描きます", "服・装飾・武装: 持ち物の拡大"),
    ("colors", "色の指定", "正面の絵から色を取り、色の名前と値を設定資料に書きます", "色見本"),
    ("height", "身長の比較", "ほかの人物と、設定の身長の比で並べます", ""),
    ("eyes", "目の拡大", "正面の絵の目のあたりを大きくして、細部を描かせます", "目と髪の詳細: 目の拡大"),
    ("hair", "髪の拡大", "正面の絵の頭のあたりを大きくして、細部を描かせます", "目と髪の詳細: 髪の拡大"),
]


def front_face(ident: str, home=None):
    """表情差分の基準の絵（正面）と顔の囲み。顔の枠は検品から、取れなければ頭の位置から"""
    from PIL import Image
    imgs = images_of(ident, home)
    rel = imgs.get("view-front") or imgs.get("color")
    if not rel:
        raise NotReady("正面の絵がありません。三面図を先に描いてください")
    path = _home(home) / rel
    base = Image.open(path).convert("RGB")
    faces = check_image(path)["faces"]
    return base, (face_mask(base, faces) if faces else guess_face(base))


def run_extra(key: str, painter, ident: str, seed: int = 0, say=lambda m: None, home=None, size=None, **kw) -> dict:
    """追加資料を 1 つ作って設定資料に置く。返すのは役割 → 置き場"""
    if key == "turnaround":
        return draw_turnaround(painter, ident, seed, size=size, say=say, home=home)
    if key == "fourview":
        return draw_turnaround(painter, ident, seed, size=size, say=say, home=home, views=FOUR_VIEWS)
    if key == "expressions":
        _need(painter, "表情差分")
        base, mask = front_face(ident, home)
        return draw_expressions(painter, ident, base, mask, seed, kw.get("only"), say=say, home=home)
    if key == "poses":
        return draw_poses(painter, ident, seed, size=size, say=say, home=home)
    if key == "hairstyles":
        return draw_hairstyles(painter, ident, seed, kw.get("styles"), size=size, say=say, home=home)
    if key == "outfits":
        return draw_outfits(painter, ident, seed, kw.get("outfits"), size=size, say=say, home=home)
    if key == "items":
        return draw_items(painter, ident, seed, kw.get("items"), size=size, say=say, home=home)
    if key == "colors":
        return {"colors": set_colors(ident, kw.get("colors"), home)}
    if key == "height":
        return height_compare(ident, kw.get("others", ()), home)
    if key == "eyes":
        return draw_eyes(painter, ident, seed, say=say, home=home)
    if key == "hair":
        return draw_hair(painter, ident, seed, say=say, home=home)
    raise NotReady(f"追加資料「{key}」はありません")


def sync_chara(ident: str, path=None, home=None) -> Path:
    """設定資料の今の中身で .chara を書き直す（追加資料を足したあとに呼ぶ）。path が無ければライブラリーの <id>.chara"""
    from chatdraw import charafile
    ch = charafile.from_bible(ident, home)
    return charafile.save(ch, path or charafile.library_dir(home) / f"{ident}{charafile.SUFFIX}")



# ---- キャラデザを作る（キャラデザモードの流れを最後まで通す） ----

DESIGN_STEPS = ("設定を書く", "目と表情を決める", "三面図を描く", "表情差分を描く", "検品する", "キャラクターシートに並べる",
                "キャラクターファイルに保存する")
PROFILE_KEYS = ("age", "height", "role", "personality", "backstory", "negative", "rules", "colors", "outfit_parts")


def guess_face(image):
    """顔の枠が見つからないときの顔の囲み。三面図の正面（立ち姿の全身）の上の真ん中を頭とみなす。
    検品の顔の枠が取れた絵では使わない"""
    w, h = image.size
    return face_mask(image, [(w * 0.36, h * 0.04, w * 0.64, h * 0.22)])


def check_image(path) -> dict:
    """1 枚を作画監督（handcheck）に通す。読めなかった絵は崩れとして数える（読めない手・顔を「崩れ無し」にしない）"""
    from chatdraw import handcheck
    try:
        r = handcheck.check(str(path), fetch=False)
    except Exception as e:   # noqa: BLE001  検品が落ちても流れは止めず、読めなかったことを残す
        r = {"readable": False, "bad": [], "reason": f"検品できませんでした（{e}）"}
    bad = list(r.get("bad", []))
    if not r.get("readable"):
        bad.append("検品できなかった: " + str(r.get("reason", "手・顔を読めませんでした")))
    return {"bad": bad, "faces": [f["box"] for f in r.get("faces", []) if "box" in f]}


def make_design(painter, spec: dict, seed: int = 0, say=lambda msg: None, home=None, expressions=None,
                size=None, loras=None, out=None) -> dict:
    """キャラデザモードの流れを順に通す: 設定 → 目と表情 → 三面図 → 表情差分 → 検品 → シート → .chara。
    spec は name・look・outfit・eyes・eyes_notes・notes と PROFILE_KEYS の欄。expressions は描く表情の id（既定は全部）。
    返すのは id・.chara の置き場・工程ごとの記録・検品の崩れ・design_status と同じ判定の足りない物"""
    from chatdraw import charafile
    if painter is None or not getattr(painter, "ready", lambda: False)():
        raise NotReady("キャラデザを作るには絵の模型が要ります。AI のメニューで模型を取ってください")
    if not (spec.get("look") or "").strip():
        raise NotReady("見た目（髪・目・体つき）の言葉を書いてください。三面図はこの言葉で描きます")
    b = bible(home)
    root = _home(home)
    log = []

    def step(i, msg=""):
        log.append(DESIGN_STEPS[i] + (f": {msg}" if msg else ""))
        say(f"キャラデザ {i + 1}/{len(DESIGN_STEPS)}: {DESIGN_STEPS[i]}" + (f"（{msg}）" if msg else ""))

    # 1. 設定を書く
    ident = spec.get("id") or slug(spec.get("name", ""), home)
    b.new_character(ident, spec.get("name", "") or ident, spec["look"], spec.get("outfit", ""),
                    negative=spec.get("negative", ""), notes=spec.get("notes", ""))
    c = b.load("characters", ident)
    c.update({k: spec[k] for k in PROFILE_KEYS if spec.get(k)})
    b.save("characters", c)
    step(0, ident)
    # 2. 目と表情を決める（表情は既定の 8 種に、spec の固有の表情を重ねる）
    if spec.get("eyes"):
        b.set_eyes(ident, spec["eyes"], spec.get("eyes_notes", ""))
    for e in spec.get("own_expressions", []):
        b.add_expression(ident, e["id"], e["name"], e["tags"])
    step(1, f"表情 {len(b.expressions_of(ident))} 種")
    # 3. 三面図
    step(2)
    turn = draw_turnaround(painter, ident, seed, size=size, say=say, home=home)
    # 4. 表情差分（三面図の正面の顔の中だけを描き直す）
    front = root / turn["front"]
    from PIL import Image
    base = Image.open(front).convert("RGB")
    qc_front = check_image(front)
    mask = face_mask(base, qc_front["faces"]) if qc_front["faces"] else guess_face(base)
    step(3, "顔の枠は検品から" if qc_front["faces"] else "顔の枠が取れず、頭の位置から囲みました")
    expr = draw_expressions(painter, ident, base, mask, seed, only=expressions, say=say, home=home)
    # 5. 検品（三面図と表情差分を 1 枚ずつ）
    faults = {}
    for role, rel in [(f"view-{k}", v) for k, v in turn.items()] + [(f"expr-{k}", v) for k, v in expr.items()]:
        r = qc_front if role == "view-front" else check_image(root / rel)
        if r["bad"]:
            faults[role] = r["bad"]
    step(4, f"崩れのある絵 {len(faults)} 枚" if faults else "崩れは見つかりませんでした")
    c = b.load("characters", ident)
    c["palette"] = palette(base)
    c["qc"] = faults
    if loras is not None:
        c["loras"] = loras
    b.save("characters", c)
    # 6. シート
    psd = write_sheet_psd(ident, home=home)
    step(5, psd.name)
    # 7. .chara
    status = b.design_status(ident)
    ch = charafile.from_bible(ident, home)
    path = charafile.save(ch, out or charafile.library_dir(home) / f"{ident}{charafile.SUFFIX}")
    step(6, path.name)
    return {"id": ident, "path": str(path), "sheet": str(psd), "turn": turn, "expressions": expr,
            "faults": faults, "missing": status["missing"], "ready": status["ready"], "log": log}
