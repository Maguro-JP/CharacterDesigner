"""ロゴ・マークとスタンプを作る部品（画面は app.py の「ロゴ・スタンプ」メニュー）。

- ロゴ・マーク: 頼み（名前、雰囲気、色）からロゴ向けの言葉と禁止ワードを組み、絵の模型（engine.Painter）に描かせる。
  描いた絵の背景を抜き、正方形と横長に整え、色を減らした版と白黒の版を作る。
  文字は模型に描かせない（模型の文字は崩れて読めない字になる）。ロゴの文字はフォントで後から重ねる。
- スタンプ: 決まった大きさ・透明の背景・余白・白い縁取りに整える。大きさの決まりは SPECS（出典は docs/references.md）。
- 書き出しは PNG（透明）と SVG。SVG は色を減らした絵の同じ色の横の並びを長方形にまとめた物で、拡大しても色の境がにじまない。
  曲線の輪郭を引き直す物ではない（曲線にするには輪郭の追跡の部品が要る。今は入れていない）。
どれも模型の要らない処理は PIL だけで動く。描く所だけ時間がかかるので、画面からは裏の糸（app.py の _run_task）で呼ぶ。
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

# ロゴ向けの言葉。平らな塗り・はっきりした形・白い地は、背景を抜きやすく、色を減らしても形が残る
LOGO_WORDS = "logo mark, simple flat vector emblem, bold clean shapes, centered, single icon, solid plain white background, " \
             "minimal, high contrast, crisp edges, no text"
# 禁止ワード。文字（崩れた字になる）、写真、細かすぎる背景、影の多い立体
LOGO_AVOID = "text, letters, words, typography, watermark, signature, garbled text, photo, photorealistic, realistic, " \
             "detailed background, busy background, scenery, texture, noise, gradient background, 3d render, drop shadow, blurry, " \
             "multiple logos, frame, border"
# 日本語の頼みは模型に渡さない（模型は日本語を読めず、別の物を描く元になる）。言葉の模型が無いときに使う小さな表
MOOD_EN = {"かわいい": "cute", "可愛い": "cute", "かっこいい": "cool", "格好いい": "cool", "やさしい": "gentle", "優しい": "gentle",
           "元気": "energetic", "シンプル": "simple", "高級": "luxury", "上品": "elegant", "和風": "japanese style",
           "レトロ": "retro", "未来": "futuristic", "自然": "natural", "ポップ": "pop", "力強い": "powerful", "楽しい": "playful",
           "落ち着いた": "calm", "丸い": "rounded", "動物": "animal", "猫": "cat", "犬": "dog", "鳥": "bird", "花": "flower",
           "星": "star", "筆": "brush", "ペン": "pen", "絵": "painting", "キャラクター": "character"}
COLOR_EN = {"赤": "red", "青": "blue", "緑": "green", "黄": "yellow", "黄色": "yellow", "橙": "orange", "オレンジ": "orange",
            "紫": "purple", "ピンク": "pink", "桃色": "pink", "黒": "black", "白": "white", "灰": "gray", "金": "gold",
            "銀": "silver", "茶": "brown", "水色": "light blue", "紺": "navy"}

# スタンプの大きさの決まり。size は書き出す大きさ、margin は縁から絵までの余白（画素）
# 出典: LINE Creators Market の制作ガイドライン、Telegram の Stickers の文書（docs/references.md の「スタンプの大きさ」）
SPECS = {
    "line": dict(name="LINE スタンプ", size=(370, 320), margin=10),
    "line_main": dict(name="LINE メイン画像", size=(240, 240), margin=10),
    "line_tab": dict(name="LINE トークルームタブ", size=(96, 74), margin=2),
    "telegram": dict(name="Telegram ステッカー", size=(512, 512), margin=8),
}
LINE_COUNTS = (8, 16, 24, 32, 40)   # LINE で選べるスタンプの個数
MAX_BYTES = 1024 * 1024              # LINE の 1 個あたりの容量の上限


def _translate(text: str, table: dict) -> str:
    out = text
    for ja in sorted(table, key=len, reverse=True):
        out = out.replace(ja, f" {table[ja]} ")
    return out


def logo_prompt(name: str = "", mood: str = "", colors: str = "", words=None) -> tuple[str, str]:
    """ロゴを描かせる言葉と禁止ワード。名前は描かせない（文字は後からフォントで重ねる）。名前の意味だけを題材として渡す"""
    from chatdraw.engine import english_only
    parts = []
    for text, table in ((mood, MOOD_EN), (colors, COLOR_EN)):
        text = (text or "").strip()
        if not text:
            continue
        if words is not None and re.search(r"[぀-ヿ一-鿿]", text):
            try:
                text = words.to_prompt(text, tags=True)
            except Exception:   # 言葉の模型が使えないときは表で置き換える
                text = _translate(text, table)
        else:
            text = _translate(text, table)
        text = re.sub(r"\s+", " ", english_only(text)).strip(" ,")
        if text:
            parts.append(text + (" color scheme" if table is COLOR_EN else ""))
    subject = re.sub(r"\s+", " ", english_only(_translate(name or "", MOOD_EN))).strip(" ,")
    if subject:
        parts.insert(0, f"symbol inspired by {subject}")
    return ", ".join([LOGO_WORDS] + parts), LOGO_AVOID


def draw_logo(painter, name: str = "", mood: str = "", colors: str = "", seed: int = 7, words=None, size=(1024, 1024), say=None):
    """絵の模型にロゴのマークを 1 枚描かせ、背景を抜いた RGBA を返す。painter は engine.Painter（試験では偽の模型）"""
    prompt, avoid = logo_prompt(name, mood, colors, words)
    if say:
        say("ロゴのマークを描いています")
    old = getattr(painter, "avoid", "")
    painter.avoid = ", ".join(a for a in (old, avoid) if a)
    try:
        im = painter.paint(prompt, seed, size=size)
    finally:
        painter.avoid = old
    return remove_background(im)


def remove_background(img: Image.Image, tol: int = 40) -> Image.Image:
    """四隅からつながった地の色だけを透明にする（ロゴの中の同じ色は残す）。もう透明があればそのまま"""
    img = img.convert("RGBA")
    if img.getchannel("A").getextrema()[0] < 250:
        return img
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))
    near = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L").point(lambda d: 255 if d <= tol else 0)
    # 四隅から塗りつぶして、外とつながった地だけを取る
    flood = near.convert("RGB")
    for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if near.getpixel(p) == 255:
            ImageDraw.floodfill(flood, p, (128, 0, 0), thresh=0)
    outside = flood.getchannel("R").point(lambda v: 255 if v == 128 else 0)
    alpha = ImageOps.invert(outside).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    img.putalpha(alpha)
    return img


def trim(img: Image.Image) -> Image.Image:
    """透明でない所の外枠で切る"""
    box = img.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return img.crop(box) if box else img


def fit(img: Image.Image, size: tuple[int, int], margin: int = 0) -> Image.Image:
    """透明の地の size の中に、余白を残して縦横比のまま収め、真ん中に置く"""
    img = trim(img.convert("RGBA"))
    w, h = size[0] - 2 * margin, size[1] - 2 * margin
    s = min(w / img.width, h / img.height)
    small = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.alpha_composite(small, ((size[0] - small.width) // 2, (size[1] - small.height) // 2))
    return out


def square(img: Image.Image, size: int = 1024, margin: int = 64) -> Image.Image:
    return fit(img, (size, size), margin)


def fonts() -> list[Path]:
    """文字に使えるフォント。アプリに同梱するのは chatdraw/fonts の自由に配れる物（OFL など。ライセンスの文と一緒に置く）だけ。
    OS に入っているフォントはその PC の上で使うだけで、アプリには入れない（配る許しが無いため）"""
    found = sorted((Path(__file__).parent / "fonts").glob("*.[ot]tf"))
    for d in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/System/Library/Fonts")):
        if d.exists():
            for name in ("meiryo.ttc", "YuGothB.ttc", "msgothic.ttc", "ipag.ttf", "NotoSansCJK-Bold.ttc", "DejaVuSans-Bold.ttf",
                         "ヒラギノ角ゴシック W6.ttc", "arialbd.ttf"):
                found += list(d.rglob(name))[:1]
    return found


def _font(path, px: int):
    try:
        return ImageFont.truetype(str(path), px) if path else ImageFont.load_default(px)
    except (OSError, TypeError):
        return ImageFont.load_default()


def wide(mark: Image.Image, text: str = "", size=(1600, 600), color=(30, 30, 30, 255), font=None) -> Image.Image:
    """横長のロゴ。左にマーク、右に文字（フォントで書く）。文字が無ければマークを真ん中に置く"""
    W, H = size
    pad = H // 10
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    if not text:
        return fit(mark, size, pad)
    m = fit(mark, (H - 2 * pad, H - 2 * pad))
    out.alpha_composite(m, (pad, pad))
    room = W - H - pad
    px = int(H * 0.42)
    f = _font(font or (fonts() or [None])[0], px)
    d = ImageDraw.Draw(out)
    while px > 8:
        box = d.textbbox((0, 0), text, font=f)
        if box[2] - box[0] <= room and box[3] - box[1] <= H - 2 * pad:
            break
        px = int(px * 0.9)
        f = _font(font or (fonts() or [None])[0], px)
    box = d.textbbox((0, 0), text, font=f)
    x = H + (room - (box[2] - box[0])) // 2 - box[0]
    y = (H - (box[3] - box[1])) // 2 - box[1]
    d.text((x, y), text, font=f, fill=color)
    return out


def reduce_colors(img: Image.Image, n: int = 4) -> Image.Image:
    """色を n 色に減らした版（透明は残す）。半透明の縁は透けるか透けないかの 2 つにする"""
    img = img.convert("RGBA")
    alpha = img.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    flat = Image.new("RGB", img.size, (255, 255, 255))
    flat.paste(img.convert("RGB"), mask=alpha)
    q = flat.quantize(n, method=Image.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB").convert("RGBA")
    q.putalpha(alpha)
    return q


def mono(img: Image.Image, threshold: int = 160) -> Image.Image:
    """白黒の版。濃い所を黒、薄い所を透明にする（白い紙に 1 色で刷る形）"""
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    dark = img.convert("L").point(lambda v: 255 if v < threshold else 0)
    ink = ImageChops.multiply(dark, alpha.point(lambda a: 255 if a >= 128 else 0))
    if not ink.getbbox():   # 全部が薄い色のマークは、形（透明でない所）をそのまま黒にする
        ink = alpha.point(lambda a: 255 if a >= 128 else 0)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste((0, 0, 0, 255), mask=ink)
    return out


def to_svg(img: Image.Image, n: int = 6, max_side: int = 256) -> str:
    """色を n 色に減らし、同じ色の横の並びを長方形にまとめた SVG。透明は書かない"""
    q = reduce_colors(img, n)
    if max(q.size) > max_side:
        s = max_side / max(q.size)
        q = q.resize((max(1, round(q.width * s)), max(1, round(q.height * s))), Image.NEAREST)
    w, h = q.size
    px = q.load()
    paths: dict[str, list[str]] = {}
    for y in range(h):
        x = 0
        while x < w:
            c = px[x, y]
            if c[3] < 128:
                x += 1
                continue
            x0 = x
            while x < w and px[x, y] == c:
                x += 1
            paths.setdefault("#%02x%02x%02x" % c[:3], []).append(f"M{x0} {y}h{x - x0}v1h{x0 - x}z")
    body = "".join(f'<path fill="{k}" d="{"".join(v)}"/>' for k, v in paths.items())
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" shape-rendering="crispEdges">{body}</svg>'


def logo_set(mark: Image.Image, text: str = "", font=None, colors: int = 4) -> dict[str, Image.Image]:
    """1 つのマークから、正方形・横長・色を減らした版・白黒の版をそろえる"""
    sq = square(mark)
    wd = wide(mark, text, font=font)
    return {"square": sq, "wide": wd, "square-colors": reduce_colors(sq, colors), "square-mono": mono(sq),
            "wide-colors": reduce_colors(wd, colors), "wide-mono": mono(wd)}


def export_logo(mark: Image.Image, folder, stem: str = "logo", text: str = "", font=None, svg: bool = True) -> list[Path]:
    """logo_set を PNG（透明）で書き、色を減らした版は SVG でも書く。書いた道を返す"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for key, im in logo_set(mark, text, font).items():
        p = folder / f"{stem}-{key}.png"
        im.save(p)
        out.append(p)
        if svg and key.endswith("-colors"):
            s = folder / f"{stem}-{key}.svg"
            s.write_text(to_svg(im), encoding="utf-8")
            out.append(s)
    return out


# ---- スタンプ ----

def outline(img: Image.Image, width: int = 6, color=(255, 255, 255, 255)) -> Image.Image:
    """形の外に白い縁取りを付ける（透明でない所を width 画素ふくらませた所を白で塗り、絵をその上に重ねる）"""
    img = img.convert("RGBA")
    if width <= 0:
        return img
    pad = width + 2
    big = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(img, (pad, pad))
    a = big.getchannel("A").point(lambda v: 255 if v >= 64 else 0)
    grown = a.filter(ImageFilter.MaxFilter(2 * width + 1)).filter(ImageFilter.GaussianBlur(0.6))
    out = Image.new("RGBA", big.size, (0, 0, 0, 0))
    out.paste(color, mask=grown)
    out.alpha_composite(big)
    return out


def stamp(img: Image.Image, spec: str = "line", border: int = 6) -> Image.Image:
    """1 枚をスタンプの形にする。背景を抜き、白い縁取りを付け、決まった大きさの透明の地に余白を残して収める"""
    s = SPECS[spec]
    cut = remove_background(img)
    edge = max(1, round(border * min(s["size"]) / 320)) if border else 0
    return fit(outline(trim(cut), edge), s["size"], s["margin"])


def export_stamps(images, folder, spec: str = "line", stem: str = "stamp", main_index: int = 0) -> list[Path]:
    """複数枚をまとめてスタンプにして書く。LINE の形ならメイン画像とタブ画像も 1 枚目（main_index）から作り、zip にまとめる。
    容量が上限を超えた 1 枚は、色を減らして書き直す"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    images = list(images)
    out = []
    for i, im in enumerate(images, 1):
        if isinstance(im, (str, Path)):
            im = Image.open(im)
        out.append(_save_small(stamp(im, spec), folder / f"{i:02d}.png"))
    if spec == "line" and images:
        first = images[main_index]
        first = Image.open(first) if isinstance(first, (str, Path)) else first
        out.append(_save_small(stamp(first, "line_main"), folder / "main.png"))
        out.append(_save_small(stamp(first, "line_tab", border=2), folder / "tab.png"))
    z = folder / f"{stem}-{spec}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        for p in out:
            f.write(p, p.name)
    return out + [z]


def _save_small(im: Image.Image, path: Path) -> Path:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    if buf.tell() > MAX_BYTES:
        buf = io.BytesIO()
        reduce_colors(im, 64).save(buf, "PNG", optimize=True)
    path.write_bytes(buf.getvalue())
    return path


def expressions(ident: str, home=None) -> list[Path]:
    """キャラクターデザインで描いた表情差分の絵（設定資料の images の expr-*）。表情の名前の順"""
    import json
    from chatdraw.charadesign import _home
    root = _home(home)
    f = root / "bible" / "characters" / f"{ident}.json"
    try:
        images = json.loads(f.read_text(encoding="utf-8")).get("images", {})
    except (OSError, ValueError):
        return []
    return [root / v for k, v in sorted(images.items()) if k.startswith("expr-") and (root / v).exists()]


# ---- アプリのアイコン ----

ICON_DIR = Path(__file__).parent / "icon"     # 選ばれたアイコンの絵（app.png）を置く所。無い間は今のアイコンのまま
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def icon_png() -> Path | None:
    p = ICON_DIR / "app.png"
    return p if p.exists() else None


def make_ico(png, ico) -> Path:
    """選ばれた絵（PNG）から Windows の .ico（16〜256 画素の組）を作る。窓のアイコンとインストーラーが使う"""
    im = square(Image.open(png), 256, 8)
    ico = Path(ico)
    ico.parent.mkdir(parents=True, exist_ok=True)
    im.save(ico, format="ICO", sizes=ICO_SIZES)
    return ico


# ---- 右クリック ----

def menu_items(window) -> list[tuple[str, object, str]]:
    """「ロゴ・スタンプ」の項目（名前、押したときの関数、ツールチップ）。メニューバーと右クリックで同じ物を使う。
    右クリックへの足し方は docs/knowledge/decisions.md の 2026-11-01 ロゴ・スタンプの行"""
    return [
        ("ロゴ・マークを作る…", window.logo_make,
         "名前・雰囲気・色を書くと、AI がロゴのマークを描きます。文字はフォントで重ね、正方形・横長・色を減らした版・白黒の版を書き出します"),
        ("今の絵をロゴに整える…", window.logo_from_canvas,
         "今の絵の背景を抜き、正方形・横長・色を減らした版・白黒の版を PNG と SVG で書き出します"),
        ("今の絵をスタンプにする…", window.stamp_from_canvas,
         "今の絵の背景を抜き、白い縁取りと余白を付けて、スタンプの大きさで書き出します"),
        ("表情差分をまとめてスタンプにする…", window.stamp_from_expressions,
         "キャラクターデザインで描いた表情差分を、まとめてスタンプにして zip で書き出します"),
    ]
