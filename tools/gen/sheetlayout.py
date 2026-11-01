"""設定画集の1枚を HTML と CSS で組み、Chromium で PNG に書き出す。

版（styles/sheet-formats/<名前>.json）は 12 列の格子の区画（grid-template-areas）と、区画に入れる欄を持つ。
テーマ（styles/sheet-themes/<名前>.json）は 3〜4 色と地の模様と書体を持つ。

PIL で直接描いていたときは、字間・行間・書体の太さと、欄の間隔をそろえる調整が描画の処理ごとに分かれ、
見出しの帯や台紙の枠で区切るしかなかった。CSS grid なら格子と余白を数字で決められ、文字組みもブラウザに任せられる。
数字の根拠は docs/knowledge/learning/design-sheet-layout.md の実例の表。

  CSS の大きさは出力の半分で組み、device_scale_factor 2 で書き出す（文字と細い線を2倍の解像度で描くため）。
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
import tempfile
from pathlib import Path

import bible
import cdhome
import charsheet as cs

FONTS = cdhome.HOME / "fonts"
CHROME = os.environ.get("SHEET_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
# 横の向きの名前。四面図の絵は 正面・右向き・左向き・背面 の順に描いてある
VIEW_NAMES = {4: ["正面", "右向き", "左向き", "背面"], 2: ["正面", "背面"], 1: ["正面"]}
TILE_CROP = (0.10, 0.0, 0.90, 0.50)   # 表情の絵から頭と肩を切る割合。顔だけ（FACE_CROP）だと髪型と襟が切れて別人に見えた
# 顔の大写し: 額と顎を枠で切る。実例の紹介頁は顔を大胆に切って目を大きく見せていた。表情の差は目と口に出るので、そこを残す
TIGHT_CROP = (0.22, 0.09, 0.79, 0.38)   # 角や髪飾りのある頭で、角が切れて頭の形が読めないほどには寄らない


def _uri(im, fmt="PNG") -> str:
    buf = io.BytesIO()
    im.save(buf, fmt, quality=92) if fmt == "JPEG" else im.save(buf, fmt, optimize=False)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def _cut_rgba(im, src=None):
    im = im.convert("RGB")
    from PIL import ImageFilter
    # 縁を2画素削る。白い背景の縁取りが残ると、暗い地のテーマで人物の周りに白い線が出た
    m = cs._cutout(im, src).point(lambda v: 255 if v > 200 else 0).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    out = im.convert("RGBA")
    out.putalpha(m)
    return out


def _figures(c):
    """四面図の人物を1人ずつ透かして切り出す。返り値は (名前, 画像) の並び。全員を同じ上端・下端で切るので縮尺がそろう"""
    from PIL import Image
    p = c.get("images", {}).get("turnaround")
    if not p:
        return []
    im = Image.open(bible.ROOT / p).convert("RGB")
    spans, top, bot = cs._figures(im)
    cut = _cut_rgba(im)
    names = VIEW_NAMES.get(len(spans), [""] * len(spans))
    # 切る幅は隣の人物との間の真ん中まで広げる。人物の列の幅で切ると、外套や襟巻の端が縦にまっすぐ欠けた
    out = []
    for i, (n, (a, b)) in enumerate(zip(names, spans)):
        lo = 0 if i == 0 else (spans[i - 1][1] + a) // 2
        hi = im.width if i == len(spans) - 1 else (b + spans[i + 1][0]) // 2
        piece = cut.crop((lo, max(0, top - 6), hi, min(im.height, bot + 6)))
        bb = piece.getchannel("A").getbbox() or (0, 0, piece.width, piece.height)
        out.append((n, piece.crop((bb[0], 0, bb[2], piece.height))))
    return out


def _sharp(c, fig):
    """小さい四面図の人物を AI の拡大（Real-ESRGAN のアニメ絵用）で4倍にする。そのまま引き伸ばすと、
    騎士（幅220画素）でぼけて縁がぎざぎざになった。拡大した絵は四面図の隣に置き、2回目からは読む"""
    from PIL import Image
    p = bible.ROOT / c["images"]["turnaround"]
    out = Path(str(p) + ".hero.png")
    if out.exists() and out.stat().st_mtime >= p.stat().st_mtime:
        return Image.open(out)
    try:
        import upscale
        bg = Image.new("RGB", fig.size, "white")
        bg.paste(fig, mask=fig.getchannel("A"))
        big = upscale.x4(bg).convert("RGBA")
        big.putalpha(fig.getchannel("A").resize(big.size, Image.LANCZOS))
    except Exception:
        return fig
    big.save(out)
    return big


def _hero(c, figs):
    """主役の立ち姿: 背景を透かせるポーズの絵で最も大きいもの、無ければ四面図の正面。
    場面つきの絵（背景を透かせない）は地の上に立たせられないので使わない"""
    from PIL import Image
    for _, p in cs._pose_list(c):
        im = Image.open(bible.ROOT / p).convert("RGB")
        cut = _cut_rgba(im)
        if cut.getchannel("A").getextrema()[0] == 0:   # 透けた所がある = 背景を外せた
            return cut.crop(cut.getchannel("A").getbbox()), "立ち姿"
    # 四面図の正面は小さく（騎士で幅220画素ほど）、大きく置くとぼけて縁がぎざぎざになった。
    # 1人だけを大きく描いた色の絵があり、そちらの人物が大きければ先に使う
    p = c.get("images", {}).get("color")
    if p and (bible.ROOT / p).exists():
        cut = _cut_rgba(Image.open(bible.ROOT / p), bible.ROOT / p)
        bb = cut.getchannel("A").getbbox()
        scene = (cut.getchannel("A").point(lambda v: v > 127 and 255).histogram()[255] / (cut.width * cut.height)) > 0.6
        # 場面ごと描いた絵（城の中など）は抜けず、服も四面図と違うことがあるので主役にしない
        if bb and not scene and (not figs or (bb[3] - bb[1]) > figs[0][1].height * 1.2):
            return cut.crop(bb), "色の基準"
    if figs and figs[0][1].height < 1200:
        return _sharp(c, figs[0][1]), "基準の正面"
    if figs:
        return figs[0][1], "基準の正面"
    return None, ""


def _faces(ident, c, n, crop="bust"):
    from PIL import Image
    out = []
    for name, p in cs._expr_list(ident, c)[:n]:
        im = Image.open(bible.ROOT / p).convert("RGB")
        x0, y0, x1, y1 = TILE_CROP if crop == "bust" else TIGHT_CROP
        out.append((name, im.crop((int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height)))))
    return out


def _callouts(ident, c):
    from PIL import Image
    ex = cs._expr_list(ident, c)
    if not ex:
        return []
    im = Image.open(bible.ROOT / ex[0][1]).convert("RGB")
    def crop(r):
        return im.crop((int(r[0] * im.width), int(r[1] * im.height), int(r[2] * im.width), int(r[3] * im.height)))
    f = cs.FACE_CROP
    # 目は顔の切り抜きの中の割合で取る。胸から上の絵の割合（EYE_CROP）は絵によって顔の高さが違い、騎士では鼻と口を切り出した
    fw, fh = f[2] - f[0], f[3] - f[1]
    eye = (f[0] + fw * 0.08, f[1] + fh * 0.30, f[0] + fw * 0.92, f[1] + fh * 0.58)
    return [("顔", crop(f)), ("目", crop(eye))]


def _font_css():
    faces = []
    for fam, files in (("Noto Sans JP", ("noto-sans-jp", (400, 500, 700, 900))), ("Noto Serif JP", ("noto-serif-jp", (400, 600, 700, 900)))):
        stem, ws = files
        for w in ws:
            for sub in (f"{stem}-latin-{w}", f"{stem}-{w}"):
                f = FONTS / f"{sub}.woff2"
                if f.exists():
                    faces.append(f"@font-face{{font-family:'{fam}';font-weight:{w};src:url('{f.as_uri()}') format('woff2');}}")
    return "\n".join(faces)


PATTERNS = {
    "none": "none",
    "dots": "radial-gradient(color-mix(in srgb, var(--ink) 9%, transparent) 1px, transparent 1.4px) 0 0 / 18px 18px",
    "lines": "repeating-linear-gradient(0deg, color-mix(in srgb, var(--ink) 5%, transparent) 0 1px, transparent 1px 28px)",
    "grid": "linear-gradient(color-mix(in srgb, var(--ink) 5%, transparent) 1px, transparent 1px) 0 0 / 32px 32px,"
            " linear-gradient(90deg, color-mix(in srgb, var(--ink) 5%, transparent) 1px, transparent 1px) 0 0 / 32px 32px",
}

SPARSE = {
    "areas": ["hero hero hero hero hero head head head head head head head",
              "hero hero hero hero hero line line line sw sw sw sw",
              "hero hero hero hero hero line line line note note note note"],
    "rows": ["auto", "auto", "1fr"],
    "panels": [{"kind": "lineart", "area": "line", "title": "線画", "grow": True},
               {"kind": "swatches", "area": "sw", "style": "chips"},
               {"kind": "notes", "area": "note", "title": "注記"}],
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:var(--W);height:var(--H);overflow:hidden}
body{background:var(--page);color:var(--ink);font-family:var(--font);font-weight:400;
  -webkit-font-smoothing:antialiased;font-feature-settings:"palt";word-break:auto-phrase;line-break:strict}
.bg{position:absolute;inset:0;background:var(--pattern);pointer-events:none}
.page{position:absolute;inset:var(--m);display:grid;grid-template-columns:repeat(12,1fr);
  column-gap:var(--g);row-gap:var(--rg);grid-template-areas:var(--areas);grid-template-rows:var(--rows)}
.cell{min-width:0;min-height:0;display:flex;flex-direction:column;gap:calc(var(--rg) * .75)}
.panel{flex:none;display:flex;flex-direction:column}
.panel.grow{flex:1;min-height:0}
.panel.fill{flex:1;min-height:0}
.panel.fill .swt{flex:1}
.lab{font-size:var(--t-head);font-weight:700;letter-spacing:.12em;color:var(--accent);
  display:flex;align-items:baseline;gap:.6em;margin-bottom:calc(var(--t-head) * .6);line-height:1}
.lab small{font-size:var(--t-note);font-weight:400;letter-spacing:.06em;color:var(--sub)}
.lab::after{content:"";flex:1;height:1px;background:color-mix(in srgb, var(--sub) 35%, transparent);align-self:center}
.name{font-family:var(--title-font);font-size:var(--t-name);font-weight:var(--name-w);line-height:1.05;letter-spacing:.04em}
.kana{font-size:var(--t-note);letter-spacing:.32em;color:var(--sub);margin-top:calc(var(--t-note) * .9);text-transform:uppercase}
.meta{font-size:var(--t-body);color:var(--sub);margin-top:calc(var(--t-body) * .6);line-height:1.6}
.meta b{color:var(--ink);font-weight:500}
.fit{flex:1;position:relative;min-height:0}
.fit img{position:absolute;display:block;z-index:1}
.fit{container-type:size}
.wm{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;writing-mode:vertical-rl;font-family:var(--title-font);font-weight:900;
  font-size:min(var(--t-wm), 92cqw, calc(96cqh / var(--wmn)));line-height:1;letter-spacing:.02em;color:color-mix(in srgb, var(--accent) 13%, transparent);white-space:nowrap;z-index:0}
.name.huge{font-size:var(--t-huge);line-height:.95;letter-spacing:-.01em;position:relative;z-index:0}
.shadow{position:absolute;border-radius:50%;background:radial-gradient(closest-side, color-mix(in srgb, var(--ink) 18%, transparent), transparent)}
.guide{position:absolute;height:0;border-top:1px dashed color-mix(in srgb, var(--accent) 45%, transparent)}
.guide.up span{top:auto;bottom:4px}
.guide span{position:absolute;left:0;top:4px;font-size:var(--t-note);color:var(--sub);letter-spacing:.06em}
.cap{position:absolute;font-size:var(--t-note);color:var(--sub);letter-spacing:.12em;transform:translateX(-50%);white-space:nowrap}
.faces{flex:1;display:grid;gap:var(--fg);min-height:0}
.face{display:flex;flex-direction:column;min-height:0}
.face .im{flex:1;min-height:0;background:var(--tile);border-radius:var(--radius);overflow:hidden;position:relative}
.face img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 25%;mix-blend-mode:multiply}
.face p{font-size:calc(var(--t-note) * 1.15);color:color-mix(in srgb, var(--ink) 70%, var(--page)) !important;letter-spacing:.14em;color:var(--sub);text-align:center;margin-top:.55em;line-height:1}
.notes{list-style:none;font-size:var(--t-body);line-height:1.75;counter-reset:n}
.notes li{counter-increment:n;display:grid;grid-template-columns:1.8em 1fr;margin-bottom:.55em}
.notes li::before{content:counter(n,decimal-leading-zero);color:var(--accent);font-weight:700;font-size:var(--t-note);padding-top:.25em;letter-spacing:.04em}
.notes b{font-weight:700}
.notes li.wide{grid-column:1 / -1}
.chips{display:flex;flex-wrap:wrap;gap:calc(var(--t-body) * .7) calc(var(--t-body) * 1.4)}
.chip{display:flex;align-items:center;gap:.55em;font-size:var(--t-note);color:color-mix(in srgb, var(--ink) 68%, var(--page));line-height:1.3}
.chip i{width:calc(var(--t-body) * 1.6);height:calc(var(--t-body) * 1.6);border-radius:50%;flex:none;
  box-shadow:inset 0 0 0 1px color-mix(in srgb, var(--ink) 14%, transparent)}
.chip b{display:block;color:var(--ink);font-weight:500;font-size:var(--t-body)}
.swl{display:grid;grid-template-columns:repeat(var(--swc,1),1fr);column-gap:var(--g);row-gap:calc(var(--t-body) * .8)}
.swt{width:100%;border-collapse:collapse;font-size:var(--t-body)}
.swt td{padding:calc(var(--t-body) * .42) 0;border-bottom:1px solid color-mix(in srgb, var(--sub) 25%, transparent);vertical-align:middle}
.swt td.k{width:calc(var(--t-body) * 3.4)}
.swt i{display:block;width:calc(var(--t-body) * 2.6);height:calc(var(--t-body) * 2.6);border-radius:var(--radius);
  box-shadow:inset 0 0 0 1px color-mix(in srgb, var(--ink) 14%, transparent)}
.swt .r{color:var(--sub);font-size:var(--t-note);letter-spacing:.08em}
.swt .h{font-family:ui-monospace,"DejaVu Sans Mono",monospace;font-size:var(--t-note);color:var(--sub)}
.swt .bar{width:30%}
.swt .bar div{height:6px;background:color-mix(in srgb, var(--sub) 18%, transparent);border-radius:3px;overflow:hidden}
.swt .bar span{display:block;height:100%;background:var(--accent)}
.swt .p{text-align:right;font-size:var(--t-note);color:var(--sub);width:4em}
.sbar{display:flex;height:calc(var(--t-body) * 2.2);border-radius:var(--radius);overflow:hidden}
.sleg{margin-top:calc(var(--t-body) * .8);gap:calc(var(--t-body) * .5) calc(var(--t-body) * 1.1)}
.sleg .chip i{width:calc(var(--t-note) * 1.1);height:calc(var(--t-note) * 1.1)}
.strip{display:flex;height:calc(var(--t-body) * 0.9);border-radius:99px;overflow:hidden}
.calls{display:grid;grid-template-columns:1fr 1.6fr;gap:var(--fg)}
.calls{grid-template-columns:auto 1fr !important}
.call:first-child .im{aspect-ratio:1}
.call .im{height:var(--callh);background:var(--tile);border-radius:var(--radius);overflow:hidden}
.call img{width:100%;height:100%;object-fit:cover;mix-blend-mode:multiply;display:block}
.call p{font-size:var(--t-note);color:var(--sub);margin-top:.5em;letter-spacing:.1em}
.call p b{color:var(--accent);margin-right:.5em}
"""

# 寸法を決めたあとに、絵を区画に収める（縦横の比を保ち、足を下にそろえる）。四面図の高さの線と名前もここで置く
JS = r"""
() => {
  for (const box of document.querySelectorAll('.fit')) {
    const img = box.querySelector('img'); if (!img) continue;
    const W = box.clientWidth, H = box.clientHeight - (box.dataset.cap ? parseFloat(getComputedStyle(document.body).getPropertyValue('--t-note')) * 2.8 : 0);
    const L = box.dataset.guides ? 56 : 0;   // 高さの線の名前を置く幅。人物と重ならないよう左に空けておく
    const k = parseFloat(box.dataset.scale || 1), top = box.dataset.anchor === 'top';
    const s = Math.min((W - L) / img.naturalWidth, H / img.naturalHeight) * k;
    // 拡大した主役は頭を区画の上にそろえ、はみ出した下（足）は版面の端で切る
    const w = img.naturalWidth * s, h = img.naturalHeight * s, x = L + (W - L - w) / 2, y = top ? H * 0.02 : H - h;
    Object.assign(img.style, {left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px'});
    // 版はひな形で、欄の位置は人物に合わせてずらす。主役の右の輪郭から一定の間を空けて、右の欄の左端を決める。
    // 細い人物なら欄を寄せて余白を詰め、腕や杖が広がる人物なら欄を押し出す
    if (box.closest('[data-kind="hero"]') && box.dataset.prof) {
      const prof = JSON.parse(box.dataset.prof), ib = img.getBoundingClientRect(), gap = W * 0.06;
      const heroCell = box.closest('.cell');
      for (const cell of document.querySelectorAll('.cell')) {
        if (cell === heroCell) continue;
        const cb = cell.getBoundingClientRect();
        // 主役の区画のすぐ右の欄だけを動かす。離れた列まで動かすと、隣の列に重なった
        const hb = heroCell.getBoundingClientRect();
        if (cb.left < hb.right - 2 || cb.left - hb.right > W * 0.08) continue;
        let right = -1;
        for (let i = 0; i < prof.length; i++) {
          const y0 = ib.top + ib.height * i / prof.length, y1 = ib.top + ib.height * (i + 1) / prof.length;
          if (y1 < cb.top || y0 > cb.bottom || !prof[i]) continue;
          right = Math.max(right, ib.left + ib.width * prof[i]);
        }
        if (right < 0) continue;
        const dx = Math.max(-cb.width * 0.25, Math.min(cb.width * 0.45, right + gap - cb.left));
        cell.style.marginLeft = (parseFloat(cell.style.marginLeft || 0) + dx) + 'px';
      }
    }
    // 主役は人物ごとに幅が違う（腕を上げる、外套が広がる）。隣の欄の文字にかぶるときは、かぶらなくなるまで縮め、
    // それでも足りなければ版面の端の側へ寄せる。区画の線で切ると腕や髪が直線で欠けるので、切らずに大きさで合わせる
    if (box.closest('[data-kind="hero"]')) {
      const texts = [...document.querySelectorAll('.name, .kana, .meta, .lab, .guide span, .cap, .chip, .notes li, .face, .swt, .strip, .sbar, .call')]
        .filter(t => !box.contains(t) && !t.matches('.name.huge'));
      const hit = () => { const a = img.getBoundingClientRect();
        return texts.some(t => { const b = t.getBoundingClientRect(); return a.left < b.right - 2 && a.right > b.left + 2 && a.top < b.bottom - 2 && a.bottom > b.top + 2; }); };
      let ss = s, xx = x;
      for (let i = 0; i < 24 && hit(); i++) {
        if (i % 2 === 0 && ss > s * 0.62) ss *= 0.94; else xx -= W * 0.03;
        const ww = img.naturalWidth * ss, hh = img.naturalHeight * ss;
        Object.assign(img.style, {left: xx + 'px', top: (top ? H * 0.02 : H - hh) + 'px', width: ww + 'px', height: hh + 'px'});
      }
      box.dataset.fit = (ss / s).toFixed(2);
    }
    if (box.dataset.shadow) {
      const sh = document.createElement('div'); sh.className = 'shadow';
      Object.assign(sh.style, {left: (x + w * 0.5 - w * 0.36) + 'px', width: (w * 0.72) + 'px', top: (y + h - h * 0.032) + 'px', height: (h * 0.036) + 'px'});
      box.insertBefore(sh, img);
    }
    if (box.dataset.caps) {
      for (const [name, cx] of JSON.parse(box.dataset.caps)) {
        const p = document.createElement('div'); p.className = 'cap'; p.textContent = name;
        Object.assign(p.style, {left: (x + w * cx) + 'px', top: (y + h + 10) + 'px'}); box.appendChild(p);
      }
    }
    if (box.dataset.guides) {
      for (const [name, t] of [['頭の上', 0], ['半分', 0.5], ['足の下', 1]]) {
        // 線は人物の左右に少し出すだけにする。区画の幅いっぱいに引くと、2人だけの図で左右の空きが目立った
        const g = document.createElement('div'); g.className = t === 1 ? 'guide up' : 'guide'; g.style.top = (y + h * t) + 'px';
        g.style.left = Math.max(0, x - 64) + 'px'; g.style.right = Math.max(0, W - x - w - 24) + 'px';
        g.innerHTML = `<span>${name}</span>`; box.insertBefore(g, img);
      }
    }
  }
  const out = {drawn: [], over: [], empty: []};
  const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom].map(v => Math.round(v * 2)); };
  for (const cell of document.querySelectorAll('.cell')) {
    const cb = r(cell), area = cell.dataset.area, free = !!(cell.dataset.bleed || cell.dataset.overlap);
    const items = cell.querySelectorAll('img, .name, .meta, .notes li, .chip, .face p, .cap, .guide span, .swt tr, .sbar, .strip, .lab, .call p');
    if (!items.length) out.empty.push(area);
    for (const it of items) {
      const b = r(it); out.drawn.push([area, cb, b, free]);
      if (free) { out.free = (out.free || 0) + ((b[0] < cb[0] - 2 || b[1] < cb[1] - 2 || b[2] > cb[2] + 2 || b[3] > cb[3] + 2) ? 1 : 0); continue; }
      if (b[0] < cb[0] - 2 || b[1] < cb[1] - 2 || b[2] > cb[2] + 2 || b[3] > cb[3] + 2) out.over.push([area, it.className || it.tagName, cb, b]);
    }
  }
  return out;
}
"""


def _swatch_html(sw, style):
    e = html.escape
    if style == "table":
        rows = "".join(
            f'<tr><td class="k"><i style="background:{s["hex"]}"></i></td><td><b>{e(s["name"])}</b><br><span class="r">{e(s["role"])}</span></td>'
            f'<td class="h">{s["hex"]}</td><td class="bar"><div><span style="width:{min(100, s["share"] * 250):.0f}%"></span></div></td>'
            f'<td class="p">{s["share"] * 100:.0f}%</td></tr>' for s in sw)
        return f'<table class="swt">{rows}</table>'
    cls = "chips" if style == "chips" else "swl"
    return f'<div class="{cls}">' + "".join(
        f'<div class="chip"><i style="background:{s["hex"]}"></i><div><b>{e(s["name"])}</b>{e(s["role"])} · {s["hex"]}</div></div>'
        for s in sw) + "</div>"


def _wm(c):
    """人物の後ろに敷く名前の大きな文字（縦書き）。区画の高さに字数が収まる大きさにする"""
    n = c["name"]
    return f'<div class="wm" style="--wmn:{len(n)}">{html.escape(n)}</div>'


def _panel_html(pn, ctx):
    e = html.escape
    k, c = pn["kind"], ctx["c"]
    lab = lambda t, sub="": (f'<div class="lab">{e(t)}{f"<small>{e(sub)}</small>" if sub else ""}</div>' if t else "")
    if k == "header":
        items = "・".join(i["name"] for i in c.get("items", [])[:3])
        meta = f'<div class="meta">持ち物 <b>{e(items)}</b></div>' if items and pn.get("meta", True) else ""
        pull = f' style="margin-left:calc(-{pn["pull"] * 100:.1f}vw)"' if pn.get("pull") else ""   # 名前を主役の下へ引き込み、人物が文字にかぶさるようにする
        return (f'<div class="name{" huge" if pn.get("huge") else ""}"{pull}>{e(c["name"])}</div><div class="kana">{e(ctx["ident"])} — {e(ctx["fm"]["title"])}</div>{meta}')
    if k == "hero":
        im, cap = ctx["hero"]
        if not im:
            return ""
        sc, anchor = pn.get("scale", 1), pn.get("anchor", "bottom")
        shadow = ' data-shadow="1"' if sc <= 1 and anchor == "bottom" else ""   # 足が切れるときは影を置かない
        # 名前の大きな文字を人物の後ろに敷く（実例では人物が名前や大きな文字にかぶさる作りがあった）
        wm = _wm(c) if pn.get("watermark") else ""
        # clip の辺は区画の線で切る。拡大した人物が隣の図の文字（高さの線の名前など）にかぶるのを防ぐ
        ins = " ".join("0" if sd in pn.get("clip", []) else "-100vw" for sd in ("top", "right", "bottom", "left"))
        clip = f' style="clip-path:inset({ins})"' if pn.get("clip") else ""
        # 人物の右の輪郭（高さ2%ごとの右端の位置）。右の欄をこの輪郭に沿って寄せたり離したりする
        import numpy as np
        al = np.asarray(im.getchannel("A")) > 40
        prof = []
        for i in range(50):
            band = al[int(i * al.shape[0] / 50):int((i + 1) * al.shape[0] / 50)]
            cols = np.nonzero(band.any(axis=0))[0]
            prof.append(round(float(cols.max() + 1) / al.shape[1], 3) if len(cols) else 0)
        return (f'<div class="fit" data-scale="{sc}" data-anchor="{anchor}" data-prof="{json.dumps(prof)}"{shadow}{clip}>'
                f'{wm}<img src="{_uri(im)}"></div>')
    if k == "lineart":
        p = c.get("images", {}).get("lineart")
        if not p or not (bible.ROOT / p).exists():
            return ""
        from PIL import Image
        cut = _cut_rgba(Image.open(bible.ROOT / p), bible.ROOT / p)
        bb = cut.getchannel("A").getbbox()
        img = f'<img src="{_uri(cut.crop(bb))}">' if bb else ""
        return lab(pn.get("title", "線画"), "") + f'<div class="fit">{img}</div>'
    if k == "turnaround":
        figs = ctx["figs"]
        if not figs:
            return ""
        im, centers = ctx["turn"]
        title = pn.get("title", "四面図")
        if "四面図" in title and len(figs) == 2:   # 2人だけの絵に「四面図」と書くと、足りない向きが読めない
            title = title.replace("四面図", "正面・背面図")
        caps = html.escape(json.dumps([[n, x] for (n, _), x in zip(figs, centers)], ensure_ascii=False))
        g = ' data-guides="1"' if pn.get("guides") else ""
        wm = _wm(c) if pn.get("watermark") else ""
        return lab(title, pn.get("sub", "")) + f'<div class="fit" data-cap="1" data-caps="{caps}"{g}>{wm}<img src="{_uri(im)}"></div>'
    if k == "expressions":
        faces = _faces(ctx["ident"], c, pn.get("max", 6), pn.get("crop", "bust"))
        if not faces:
            return ""
        cols = pn.get("cols", 3)
        # 最後の行が欠けると空いたますが目立つので、指定の列数の前後で余りの少ない列数を選ぶ
        cols = min((cols, cols + 1, cols - 1), key=lambda k: (-len(faces) % k if k > 0 else 99, abs(k - pn.get("cols", 3))))
        tiles = "".join(f'<div class="face"><div class="im"><img src="{_uri(f, "JPEG")}"></div><p>{e(n)}</p></div>' for n, f in faces)
        rows = -(-len(faces) // cols)
        return lab(pn.get("title", "")) + f'<div class="faces" style="grid-template-columns:repeat({cols},1fr);grid-template-rows:repeat({rows},1fr)">{tiles}</div>'
    if k == "poses":
        cells = [(n, _cut_rgba(__import__("PIL.Image", fromlist=["Image"]).open(bible.ROOT / p))) for n, p in cs._pose_list(c)]
        cells = [(n, im.crop(im.getchannel("A").getbbox())) for n, im in cells]
        if len(cells) < 2:   # ポーズの絵が足りない所は四面図の正面と背面で埋める（欄の半分が空くより、基準の立ち姿がある方が使える）
            cells += [f for f in ctx["figs"] if f[0] in ("正面", "背面")][:2 - len(cells) + 1]
        im, centers = _row(cells)
        caps = html.escape(json.dumps([[n, x] for (n, _), x in zip(cells, centers)], ensure_ascii=False))
        return lab(pn.get("title", "")) + f'<div class="fit" data-cap="1" data-caps="{caps}"><img src="{_uri(im)}"></div>'
    if k == "swatches":
        return lab(pn.get("title", "")) + _swatch_html(ctx["sw"], pn.get("style", "list"))
    if k == "notes":
        if not ctx["notes"]:
            return ""
        notes = ctx["notes"]
        if pn.get("brief"):   # 総覧では各注記の最初の一文だけにする。全文は作画用の版に載せる（狭い欄に全文を詰めると欄からあふれた）
            notes = [t.split("。")[0] for t in notes]
            # 長い文は最初の読点までにする（「…」で切ると文の途中で切れて見え、項目名だけにすると見出しの羅列に見えた）
            def cut(t):
                k, _, v = t.partition(": ")
                if len(v) <= 24:
                    return t
                head = v.split("、")[0]
                return f"{k}: {head}"
            notes = [cut(t) for t in notes]
        lis = "".join(f'<li><span><b>{e(t.split(": ", 1)[0])}</b>　{e(t.split(": ", 1)[1] if ": " in t else "")}</span></li>' for t in notes)
        if pn.get("columns"):
            # 2段に組み、長い注記（40字より長い）と、2項目以下のときは全幅の1段にする。段組みに流すと左右の段の行数が偏った
            lis = "".join(f'<li{" class=wide" if len(t) > 40 or len(notes) <= 2 else ""}><span><b>{e(t.split(": ", 1)[0])}</b>　{e(t.split(": ", 1)[1] if ": " in t else "")}</span></li>'
                          for t in notes)
            return lab(pn.get("title", "")) + f'<ol class="notes" style="display:grid;grid-template-columns:repeat({pn["columns"]},1fr);column-gap:var(--g)">{lis}</ol>'
        return lab(pn.get("title", "")) + f'<ol class="notes">{lis}</ol>'
    if k in ("sharebar", "strip"):
        sw = sorted(ctx["sw"], key=lambda s: -s["share"])
        tot = sum(s["share"] for s in sw) or 1
        segs = "".join(f'<div style="flex:{s["share"] / tot:.4f};background:{s["hex"]}"></div>' for s in sw)
        # 帯の中に名前を書くと細い区画で名前がぶつかったので、名前と割合は帯の下に並べる
        leg = "".join(f'<div class="chip"><i style="background:{s["hex"]}"></i><div>{e(s["name"])} {s["share"] / tot * 100:.0f}%</div></div>' for s in sw)
        bar = "strip" if k == "strip" else "sbar"
        per = len(sw) if len(sw) <= 6 or k == "strip" else -(-len(sw) // 2)   # 2行になるときは行ごとの数をそろえる（2行目が1つだけになった）
        return lab(pn.get("title", ""), pn.get("sub", "")) + f'<div class="{bar}">{segs}</div><div class="chips sleg" style="display:grid;grid-template-columns:repeat({per},auto);justify-content:start">{leg}</div>'
    if k == "callouts":
        cl = _callouts(ctx["ident"], c)
        if not cl:
            return ""
        t = "".join(f'<div class="call"><div class="im"><img src="{_uri(im, "JPEG")}"></div><p><b>{i + 1:02d}</b>{e(n)}</p></div>' for i, (n, im) in enumerate(cl))
        return lab(pn.get("title", "")) + f'<div class="calls">{t}</div>'
    raise ValueError(f"欄の種類 {k} は組めません")


def _row(figs, gap=0.5):
    """人物を同じ縮尺のまま横一列に並べた1枚と、各人物の中心の横位置（幅に対する割合）を返す。
    1枚にまとめるのは、区画に収めるときに全員を同じ倍率で縮めるため（別々に収めると縮尺がずれた）"""
    from PIL import Image
    H = max(im.height for _, im in figs)
    same = all(n in ("正面", "背面", "右向き", "左向き") for n, _ in figs)   # 四面図の人物は元の縮尺のまま、ポーズと混ぜるときは高さをそろえる
    figs = [(n, im.crop(im.getchannel("A").point(lambda v: 255 if v > 60 else 0).getbbox())) for n, im in figs]   # 薄い縁で足の位置がずれた
    H = max(im.height for _, im in figs)
    scaled = [im if same or im.height == H else im.resize((round(im.width * H / im.height), H)) for _, im in figs]
    sp = int(sum(im.width for im in scaled) / len(scaled) * gap)
    W = sum(im.width for im in scaled) + sp * (len(scaled) - 1)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x, centers = 0, []
    for im in scaled:
        out.paste(im, (x, H - im.height), im)
        centers.append((x + im.width / 2) / W)
        x += im.width + sp
    return out, centers


def _theme_vars(th, c, W, H, fm):
    col = dict(th["colors"])
    if col.get("accent") == "character":
        col["accent"] = "#%02x%02x%02x" % cs._char_accent(c)
    u = W / 2 / 1200   # 文字と余白の段は CSS 幅 1200 を基準に決め、版の幅に合わせて伸ばす
    t = {**{"name": 56, "head": 17, "body": 15, "note": 11.5}, **fm.get("type", {})}
    m = fm.get("margin", 0.045) * W / 2
    serif = "'Noto Serif JP','IPAPMincho',serif"
    sans = "'Noto Sans JP','IPAPGothic',sans-serif"
    v = {
        "--W": f"{W / 2}px", "--H": f"{H / 2}px", "--m": f"{m:.1f}px",
        "--g": f"{fm.get('gutter', 0.02) * W / 2:.1f}px", "--rg": f"{fm.get('row_gap', 0.028) * W / 2:.1f}px",
        "--fg": f"{fm.get('face_gap', 0.012) * W / 2:.1f}px", "--callh": f"{fm.get('callout_h', 0.09) * W / 2:.1f}px",
        "--page": col["page"], "--ink": col["ink"], "--sub": col["sub"], "--accent": col["accent"], "--tile": col["card"],
        "--pattern": PATTERNS.get(th.get("motif", "none"), "none"),
        "--font": serif if th.get("font") == "serif" else sans,
        "--title-font": serif if th.get("title_font", th.get("font")) == "serif" else sans,
        "--name-w": str(th.get("name_weight", 700)), "--radius": f"{th.get('card_radius', 4)}px",
    }
    t.setdefault("wm", t["name"] * 3.2)
    t.setdefault("huge", t["name"] * 1.9)
    for k, px in t.items():
        v[f"--t-{k}"] = f"{px * u:.2f}px"
    return v


def render(ident: str, fm: dict, th: dict, out_png: str, out_html: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright
    c = bible.load("characters", ident)
    W, H = fm["size"]
    if W % 2 or H % 2:
        raise ValueError(f"{fm['name']}: 大きさは偶数にする（半分の CSS 寸法を 2 倍で書き出すため）")
    figs = _figures(c)
    # 四面図も表情も無い人物は、版の区画の半分以上が空いた。主役を大きくし、線画・色・注記で組む版に替える
    if not figs and not cs._expr_list(ident, c) and fm["name"] != "color":
        fm = {**fm, "areas": SPARSE["areas"], "rows": SPARSE["rows"],
              "panels": [{"kind": "hero"}] + [p for p in fm["panels"] if p["kind"] == "header"] + SPARSE["panels"]}
        if fm["size"][1] > fm["size"][0]:   # 縦長の版は素材が少ないと下半分が空いたので、横長にする
            fm["size"] = [2400, 1350]
        W, H = fm["size"]
        for p in fm["panels"]:
            if p["kind"] == "hero":
                p.update(area="hero", scale=1, anchor="bottom", overlap=True)   # 全身像は頭から足まで見せる
            if p["kind"] == "header":
                p.update(area="head", huge=False, pull=0)
    ctx = {"c": c, "ident": ident, "fm": fm, "figs": figs, "hero": _hero(c, figs), "sw": cs._swatches(c), "notes": cs._notes(c),
           "turn": _row(figs) if figs else (None, [])}
    # 区画ごとに欄を積む。素材の無い欄は外し、区画が空になったら absorb の区画に面積を渡して格子を組み直す
    cells, used, free = {}, [], {}
    for pn in fm["panels"]:
        body = _panel_html(pn, ctx)
        if body:
            # 印（bleed: 版面の端で切ってよい辺、overlap: 隣の区画に重ねてよい）は区画ごとに集める。印の無い区画のはみ出しだけを崩れとして数える
            f = free.setdefault(pn["area"], {"bleed": set(), "overlap": False})
            f["bleed"] |= set(pn.get("bleed", []))
            f["overlap"] |= bool(pn.get("overlap"))
            grow = " grow" if pn["kind"] in ("hero", "turnaround", "expressions", "poses", "lineart") else (" fill" if pn.get("style") == "table" else "")
            cells.setdefault(pn["area"], []).append(f'<div class="panel{grow}" data-kind="{pn["kind"]}">{body}</div>')
            used.append(pn["kind"])
    rows = [r.split() for r in fm["areas"]]
    for pn in fm["panels"]:
        if pn["area"] not in cells:
            to = pn.get("absorb") or "."
            rows = [[to if a == pn["area"] else a for a in r] for r in rows]
    for r in rows:
        if len(r) != 12:
            raise ValueError(f"{fm['name']}: 区画の行は 12 列にする: {r}")
    v = _theme_vars(th, c, W, H, fm)
    v["--areas"] = " ".join(f'"{" ".join(r)}"' for r in rows)
    v["--rows"] = " ".join(fm["rows"])
    style = ":root{" + ";".join(f"{k}:{val}" for k, val in v.items()) + "}"
    hero_areas = {pn["area"] for pn in fm["panels"] if pn["kind"] == "hero"}

    def cell(a, p):
        f = free.get(a, {"bleed": set(), "overlap": False})
        st = f"grid-area:{a}" + "".join(f";margin-{side}:calc(-1 * var(--m))" for side in sorted(f["bleed"]))
        mark = (" data-bleed=\"" + " ".join(sorted(f["bleed"])) + "\"" if f["bleed"] else "") + (" data-overlap=\"1\"" if f["overlap"] else "")
        # 主役の区画を最も手前に置く。名前に重ねるときは、名前（overlap の印だけの区画）より人物を上にする
        z = ";z-index:3" if a in hero_areas else (";z-index:1" if f["overlap"] or f["bleed"] else "")
        return f'<div class="cell" data-area="{a}"{mark} style="{st}{z}">{"".join(p)}</div>'
    body = "".join(cell(a, p) for a, p in cells.items())
    doc = (f'<!doctype html><html lang="ja"><meta charset="utf-8"><title>{html.escape(c["name"])} {html.escape(fm["title"])}</title>'
           f'<style>{_font_css()}\n{style}\n{CSS}</style><body><div class="bg"></div><div class="page">{body}</div></body></html>')
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "sheet.html"
        src.write_text(doc, encoding="utf-8")
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=CHROME if Path(CHROME).exists() else None,
                                   args=["--allow-file-access-from-files"])
            pg = b.new_page(viewport={"width": W // 2, "height": H // 2}, device_scale_factor=2)
            pg.goto(src.as_uri())
            pg.evaluate("document.fonts.ready")
            res = pg.evaluate(JS)
            Path(out_png).parent.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=out_png, full_page=False)
            b.close()
    if out_html:
        Path(out_html).write_text(doc, encoding="utf-8")
    return {"size": [W, H], "panels": used, "drawn": res["drawn"], "outside_panel": len(res["over"]), "over": res["over"], "intended": res.get("free", 0),
            "empty": res["empty"]}
