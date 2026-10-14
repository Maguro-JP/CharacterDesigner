"""検品の下ごしらえ: 検品担当（.claude/agents/checker.md）が目で見る前に、機械で拡大図と事実をそろえる。

検品担当が自分で切り出すと、座標がずれて顔や手が写らない回があり、画像の枚数を絞った回は指や足元が
「見ていない」のまま残った。宙に浮いた布や、設定で描かせないものも、毎回目だけで探していた。
ここでは、決まった形の検品図を1枚作り、数えられる事実を先に出す。判断（通す・戻す）はしない。

  python3 tools/gen/qc.py sheet   絵.png OUT.png               全体と顔の拡大（OUT）、人物を分けた2倍前後の拡大（OUT-detail）の検品図
  python3 tools/gen/qc.py facts   絵.png [--character knight]   端で切れていないか・部位の棚卸し・浮いた塊・肌の割合・描かせないもの・設定の言葉の欠け
  python3 tools/gen/qc.py compare 絵1.png 絵2.png ...           組（三面図・表情差分）で、部位ごとの色がずれていないか
  python3 tools/gen/qc.py scars   前.png 後.png 範囲.png         部分を描き直した範囲の縁で、前より輪郭が鈍った所（にじみの跡）
  python3 tools/gen/qc.py expr    基準.png OUT.jpg 表情1.png ...  表情差分の見比べ図（顔・眉と目・口を「ふだん」と並べる）

検品図は JPEG で書く（PNG だと1枚 数 MB になり、ディスクの空きが少ないとき検品担当が図を作れなかった）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
# 部位分けの番号（tools/gen/edit.py の parts。ATR の並び）
HAIR, UPPER, SKIRT, PANTS, DRESS, LSHOE, RSHOE, FACE, LLEG, RLEG, LARM, RARM, SCARF = 2, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 17
SKIN = (FACE, LLEG, RLEG, LARM, RARM)
PART_JA = {HAIR: "髪", UPPER: "上着", SKIRT: "スカート", PANTS: "ズボン", DRESS: "ワンピース", FACE: "顔", SCARF: "襟巻き"}


# ---- 模型を使わない計算（試験はここを見る） ----

def figure_mask(rgb: np.ndarray, paper: int = 30) -> np.ndarray:
    """白地の絵で、地と違う画素（人物と物）。四隅の色を地とみなし、そこから paper 以上離れた画素"""
    corners = np.concatenate([rgb[:8, :8], rgb[:8, -8:], rgb[-8:, :8], rgb[-8:, -8:]]).reshape(-1, 3).astype(float)
    bg = np.median(corners, 0)
    return np.abs(rgb.astype(float) - bg).max(-1) > paper


def background_seams(rgb: np.ndarray, gap: int = 4, band: int = 12, flat: float = 4.0, least: float = 0.2,
                     agree: float = 0.7, step: float = 5.0, cap: float = 25.0, sharp: float = 3.0,
                     near: float = 20.0) -> list[dict]:
    """背景の色が、まっすぐな横線・縦線を境に急に変わる所。部分の描き直しの範囲の縁に出る継ぎ目。

    アラクネの下半身を描き直した絵で、範囲の上の縁（430 行目）を境に背景の青が 7 上がり、細かな粒が消えた。
    明るさだけを見ると差は 1 未満で拾えなかったので、3 色それぞれの差を見る。
    線の上下（左右）の帯（band 行、境から gap 行あける）が、どちらも平ら（ばらつき flat 未満）で
    四隅の色（背景）から near 以内の列だけを数える。翼の中の平らな羽の帯や人物の輪郭を拾わないため。
    差が step を超えて cap 未満、帯の中の変化の sharp 倍より大きい（なだらかな光のむらでない）、
    agree 以上の列で同じ向きに変わる、をすべて満たす行を継ぎ目とし、近い行は 1 本にまとめる。
    手元の 8 枚で、継ぎ目のある 1 枚だけを拾い、残り 7 枚は拾わなかった"""
    X = rgb.astype(float)
    corners = np.concatenate([X[:8, :8], X[:8, -8:], X[-8:, :8], X[-8:, -8:]]).reshape(-1, 3)
    bgc = np.median(corners, 0)
    out = []
    for name, M in (("row", X), ("col", X.transpose(1, 0, 2))):
        H, W, _ = M.shape
        hits = []
        for i in range(gap + band, H - gap - band):
            a, b = M[i - gap - band:i - gap], M[i + gap:i + gap + band]
            ok = ((a.std(0).max(-1) < flat) & (b.std(0).max(-1) < flat)
                  & (np.abs(a.mean(0) - bgc).max(-1) < near) & (np.abs(b.mean(0) - bgc).max(-1) < near))
            if ok.sum() < least * W:
                continue
            d = (b.mean(0) - a.mean(0))[ok]
            med = np.median(d, 0)
            c = int(np.abs(med).argmax())
            h = band // 2
            inner = (abs(np.median((a[h:].mean(0) - a[:h].mean(0))[ok][:, c]))
                     + abs(np.median((b[h:].mean(0) - b[:h].mean(0))[ok][:, c])))
            if (step < abs(med[c]) < cap and abs(med[c]) > sharp * inner
                    and (np.sign(d[:, c]) == np.sign(med[c])).mean() > agree):
                hits.append((i, float(abs(med[c])), float(ok.mean())))
        groups = []
        for r in hits:
            if groups and r[0] - groups[-1][-1][0] <= gap + band:
                groups[-1].append(r)
            else:
                groups.append([r])
        for g in groups:
            top = max(g, key=lambda r: r[1])
            out.append({"at": name, "pos": top[0], "step": round(top[1], 1), "width": round(top[2], 2)})
    return out

def repaint_scars(before: Image.Image, after: Image.Image, mask: Image.Image, width: int = 10, cell: int = 32,
                  drop: float = 0.5, contrast: float = 20.0) -> list[dict]:
    """部分を描き直した範囲（mask の白）の縁の帯で、描き直す前より輪郭が鈍った所（にじみ・ぼやけの跡）。

    絵全体から鈍い所を探すと、革の柔らかい光やしっぽのなだらかな塗りなど、わざと柔らかく描いた所も拾い、
    本物のにじみと分けられなかった（8 か所のうち本物 3）。描き直した範囲は分かっているので、その縁だけを前後で比べる。
    セルごとに「一番鋭い 1 画素の変化 ÷ 明暗の差」を測り、描き直した後が前（0.6 未満なら 0.6）の drop 倍を下回れば拾う。
    絵の外は範囲の内とみなす（範囲が絵の端に接すると、端の帯を縁と取り違えた）"""
    from scipy import ndimage
    m = np.asarray(mask.convert("L")) > 127
    ring = (ndimage.binary_dilation(m, iterations=width)
            & ~ndimage.binary_erosion(m, iterations=width, border_value=1))

    def gradient(im):
        lum = np.asarray(im.convert("RGB")).astype(float) @ np.array([0.299, 0.587, 0.114])
        return lum, np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8.0

    lb, gb = gradient(before)
    la, ga = gradient(after)
    h, w = m.shape
    out = []
    for y in range(0, h - cell + 1, cell // 2):
        for x in range(0, w - cell + 1, cell // 2):
            r = ring[y:y + cell, x:x + cell]
            if r.mean() < 0.2:
                continue
            ca = la[y:y + cell, x:x + cell][r]
            spread = np.percentile(ca, 95) - np.percentile(ca, 5)
            if spread < contrast:
                continue
            sa = ga[y:y + cell, x:x + cell][r].max() / spread
            cb = lb[y:y + cell, x:x + cell][r]
            sb = gb[y:y + cell, x:x + cell][r].max() / max(np.percentile(cb, 95) - np.percentile(cb, 5), contrast)
            if sa < drop * max(sb, 0.6):
                out.append({"x": x, "y": y, "size": cell, "sharp": round(float(sa), 2), "before": round(float(sb), 2)})
    return out

def floating_blobs(rgb: np.ndarray, least: float = 0.0015) -> dict:
    """人物の塊から離れた塊（宙に浮いた布・煙・物）。地が平らでない絵（背景つき）は数えない。
    小さすぎる点（絵全体の least 未満）は、髪の跳ねや影の粒なので数えない"""
    from scipy import ndimage
    corners = np.concatenate([rgb[:8, :8], rgb[:8, -8:], rgb[-8:, :8], rgb[-8:, -8:]]).reshape(-1, 3).astype(float)
    if corners.std(0).max() > 12:
        return {"plain_background": False, "blobs": []}
    m = ndimage.binary_closing(figure_mask(rgb), iterations=2)
    lab, n = ndimage.label(m)
    if n == 0:
        return {"plain_background": True, "blobs": []}
    sizes = np.bincount(lab.ravel())[1:]
    main = int(sizes.argmax()) + 1
    total = rgb.shape[0] * rgb.shape[1]
    out = []
    for i, s in enumerate(sizes, 1):
        if i == main or s < least * total:
            continue
        ys, xs = np.nonzero(lab == i)
        out.append({"box": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "area": round(s / total, 4)})
    return {"plain_background": True, "blobs": sorted(out, key=lambda b: -b["area"])}


def part_colors(rgb: np.ndarray, parts: np.ndarray, least: int = 400) -> dict:
    """部位ごとの色の真ん中（画素が least 未満の部位は数えない）"""
    out = {}
    for k in PART_JA:
        m = parts == k
        if m.sum() >= least:
            out[k] = np.median(rgb[m].reshape(-1, 3).astype(float), 0)
    return out


def color_gaps(colors: list[dict], limit: float = 40.0) -> list[dict]:
    """組の中で、同じ部位の色がどれだけ離れたか（RGB の距離の最大）。limit を超えたものだけ返す。
    部位分けが取れなかった絵はその部位を比べない"""
    out = []
    for k, ja in PART_JA.items():
        got = [(i, c[k]) for i, c in enumerate(colors) if k in c]
        if len(got) < 2:
            continue
        worst = max(((float(np.linalg.norm(a - b)), i, j) for x, (i, a) in enumerate(got) for (j, b) in got[x + 1:]), default=None)
        if worst and worst[0] > limit:
            out.append({"part": ja, "distance": round(worst[0], 1), "between": [worst[1], worst[2]]})
    return out


# 顔の外接枠の中での帯（上からの割合）。アニメ絵の顔の部位分けは前髪の下から顎までで、眉と目・口はおおむねこの位置
BANDS = {"眉と目": (0.10, 0.58), "口": (0.60, 0.92)}


def edge_cut(rgb: np.ndarray, margin: int = 2) -> list[str]:
    """人物が絵の端で切れているか。地と違う画素が端の帯にあれば、その辺の名前を返す（全身の絵で足先や頭が切れる欠損）"""
    fig = figure_mask(rgb)
    out = []
    for name, band in (("上", fig[:margin]), ("下", fig[-margin:]), ("左", fig[:, :margin]), ("右", fig[:, -margin:])):
        if band.mean() > 0.02:
            out.append(name)
    return out


# 欠損の棚卸しで数える部位（部位分けの番号）。服で覆われた腕や脚は部位分けで取れないことがあるので、
# 「取れない」は欠損の証拠ではなく、目で確かめる所の印として出す
INVENTORY = {"髪": (HAIR,), "顔": (FACE,), "右腕（素肌）": (RARM,), "左腕（素肌）": (LARM,), "右脚（素肌）": (RLEG,),
             "左脚（素肌）": (LLEG,), "右の靴": (RSHOE,), "左の靴": (LSHOE,)}


def inventory(parts: np.ndarray, least: int = 150) -> dict:
    """部位ごとに、取れた画素の数と塊の数。塊が2つ以上ある部位は、途中で切れているか、別の物が重なっている印"""
    from scipy import ndimage
    out = {}
    for name, ks in INVENTORY.items():
        m = np.isin(parts, ks)
        n = int(m.sum())
        lab, k = ndimage.label(m)
        big = int((np.bincount(lab.ravel())[1:] >= least).sum()) if k else 0
        out[name] = {"pixels": n, "pieces": big, "found": n >= least}
    return out


def nouns_missing(words: str, got: dict, vocab: set, least: float = 0.2) -> list[str]:
    """読む模型の一覧に無い言い方（dark red cape）は、最後の名詞（cape）が一覧にあればそれで比べる。
    一覧に無い言い方を比べずに外すと、騎士の正面にマントが無いことを拾えなかった"""
    out = []
    for t in (x.strip().lower() for x in words.split(",")):
        if not t or t in vocab or " " not in t:
            continue
        # 前置詞より後ろは付け足し（long black skirt to the knees の knees は物ではない）。前で切って最後の名詞を取る
        head = re.split(r" (?:up to|to|with|behind|on|around|under|over|in|at|from) ", t)[0]
        if " " not in head and head in vocab:
            continue
        noun = head.rsplit(" ", 1)[-1]
        if noun in vocab and got.get(noun, 0.0) < least and not any(k.endswith(noun) and v >= least for k, v in got.items()):
            out.append(f"{t}（{noun} が読めない）")
    return out


# ---- 絵から ----

def _parts(path: str, im: Image.Image) -> np.ndarray:
    import edit
    return np.asarray(edit.parts(path).resize(im.size, Image.NEAREST))


def _largest(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage
    lab, n = ndimage.label(mask)
    if n == 0:
        return mask
    return lab == (int(np.bincount(lab.ravel())[1:].argmax()) + 1)


def _box(mask: np.ndarray, pad: float, shape) -> tuple | None:
    if mask.sum() < 50:
        return None
    ys, xs = np.nonzero(mask)
    h, w = ys.max() - ys.min(), xs.max() - xs.min()
    p = int(max(h, w) * pad) + 8
    return (max(xs.min() - p, 0), max(ys.min() - p, 0), min(xs.max() + p, shape[1]), min(ys.max() + p, shape[0]))


def tiles(box, rows: int = 3, cols: int = 2, overlap: float = 0.12) -> list[tuple]:
    """人物の外接枠を rows×cols に分けた枠（少し重ねる。境目にある手や持ち物が切れて見えないように）"""
    x0, y0, x1, y1 = box
    w, h = (x1 - x0) / cols, (y1 - y0) / rows
    ox, oy = w * overlap, h * overlap
    return [(int(max(x0 + c * w - ox, x0)), int(max(y0 + r * h - oy, y0)), int(min(x0 + (c + 1) * w + ox, x1)),
             int(min(y0 + (r + 1) * h + oy, y1))) for r in range(rows) for c in range(cols)]


def sheet(src: str, out: str, zoom: float = 2.0, cell: int = 380) -> dict:
    """検品図を2枚書く。out は全体と顔の拡大、out の -detail は人物を分けた拡大（どの枚も zoom 倍前後）。
    どこも「見ていない」にならないよう、人物の全部をどれかの拡大に入れる。
    部位分けで手と足を探すと、籠手や鎧靴を手足と取らず見つからなかった。6つに分けるだけでは 0.8 倍にしかならなかった"""
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im)
    fig = figure_mask(rgb)
    fbox = _box(_largest(fig), 0.02, fig.shape) or (0, 0, im.width, im.height)
    try:
        face = _largest(_parts(src, im) == FACE)
        face_box = _box(face, 0.3, fig.shape) if face.sum() >= 200 else None
    except Exception:          # 部位分けの模型が無くても検品図は作る
        face_box = None
    note = []
    if face_box is None:       # 顔が取れなければ、人物の上端の正方形を顔の候補にする
        side = int((fbox[2] - fbox[0]) * 0.5)
        cx = (fbox[0] + fbox[2]) // 2
        face_box = (max(cx - side // 2, 0), fbox[1], min(cx + side // 2, im.width), fbox[1] + side)
        note.append("顔は部位分けで取れず、人物の上端を使った")
    font = ImageFont.truetype(FONT, 20) if Path(FONT).exists() else ImageFont.load_default()
    # 1枚目: 全体と顔
    full_h = 900
    full = im.resize((int(im.width * full_h / im.height), full_h))
    face_img = im.crop(face_box).resize((full_h, full_h), Image.LANCZOS)
    a = Image.new("RGB", (full.width + 20 + full_h, full_h + 30), "white")
    d = ImageDraw.Draw(a)
    a.paste(full, (0, 30))
    sx = full.width / im.width
    d.rectangle([face_box[0] * sx, 30 + face_box[1] * sx, face_box[2] * sx, 30 + face_box[3] * sx], outline="blue", width=2)
    d.text((4, 4), "全体（青い枠が右の顔）", fill="black", font=font)
    d.text((full.width + 24, 4), f"顔（{full_h / max(face_box[2] - face_box[0], 1):.1f} 倍）", fill="black", font=font)
    a.paste(face_img, (full.width + 20, 30))
    a.save(out, quality=88)
    # 2枚目: 人物を分けた拡大。1枚の範囲が cell/zoom 以下になる数に分ける
    span = cell / zoom
    cols = max(1, int(np.ceil((fbox[2] - fbox[0]) / span)))
    rows = max(1, int(np.ceil((fbox[3] - fbox[1]) / span)))
    boxes = tiles(fbox, rows, cols)
    detail = str(Path(out).with_name(Path(out).stem + "-detail.jpg"))
    b = Image.new("RGB", (cols * (cell + 10), rows * (cell + 34)), "white")
    d = ImageDraw.Draw(b)
    for i, bx in enumerate(boxes):
        r, c = divmod(i, cols)
        x, y = c * (cell + 10), r * (cell + 34)
        t = im.crop(bx)
        scale = min(cell / t.width, cell / t.height)
        b.paste(t.resize((max(int(t.width * scale), 1), max(int(t.height * scale), 1)), Image.LANCZOS), (x, y + 26))
        d.text((x, y + 2), f"{r + 1}段{c + 1}列（{scale:.1f} 倍、x{bx[0]}-{bx[2]} y{bx[1]}-{bx[3]}）", fill="black", font=font)
    b.save(detail, quality=88)
    return {"out": out, "detail": detail, "figure": [int(v) for v in fbox], "face": [int(v) for v in face_box],
            "grid": [rows, cols], "notes": note}


def facts(src: str, character: str | None = None) -> dict:
    """数えられる事実。判断はしない（検品担当が、この数字を手がかりに目で確かめる）"""
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im)
    parts = _parts(src, im)
    person = parts > 0
    res = {"edge_cut": edge_cut(rgb), "inventory": inventory(parts),
           "floating": floating_blobs(rgb), "seams": background_seams(rgb),
           "skin_ratio": round(float(np.isin(parts, SKIN).sum() / max(person.sum(), 1)), 3)}
    import tagger
    got = tagger.read(src)
    res["tags"] = dict(sorted(got.items(), key=lambda x: -x[1])[:40])
    if character:
        import bible
        c = bible.load("characters", character)
        avoid = {w.strip().lower() for w in c.get("negative", "").split(",") if w.strip()}
        for it in c.get("items", []):
            avoid |= {w.strip().lower() for w in it.get("avoid", "").split(",") if w.strip()}
        res["avoided_but_seen"] = {t: p for t, p in got.items() if t in avoid}
        words = ", ".join(x for x in (c["look"], c.get("eyes", {}).get("tags", ""), c["outfit"]) if x)
        res["asked_but_missing"] = tagger.missing(words, got) + nouns_missing(words, got, tagger.vocabulary())
    return res


def expr(base: str, out: str, srcs: list[str]) -> dict:
    """表情差分の見比べ図: 1行に1表情、左から顔・眉と目の帯（3倍）・口の帯（3倍）。先頭の行は「ふだん」（無ければ基準の絵）。
    どの絵も基準の絵の同じ枠で切るので、行ごとに位置がそろい、動いた所が目で追える。
    動きを数字で出すのはやめた: 画素の差は前髪の毛先の揺れでどの表情も目の帯が 21〜23 動いて見え、
    暗い画素を数えるやり方は部位分けの顔の広さが絵ごとに 2万7千〜3万5千画素と揺れ、照れの頬の赤みも口と数えた"""
    bi = Image.open(base).convert("RGB")
    face = _largest(_parts(base, bi) == FACE)
    box = _box(face, 0.0, face.shape) if face.sum() >= 200 else None
    if box is None:
        raise SystemExit("基準の絵で顔が見つからない")
    srcs = [s for s in srcs if ".parts." not in s]   # 部位分けの控え（絵の隣に置かれる）は表情の絵ではない
    ref = next((s for s in srcs if "neutral" in Path(s).stem), None)
    order = ([ref] if ref else [base]) + [s for s in srcs if s != ref]
    x0, y0, x1, y1 = box
    h = y1 - y0
    font = ImageFont.truetype(FONT, 18) if Path(FONT).exists() else ImageFont.load_default()
    face_w, zoom = 240, 3
    strips = {k: (y0 + int(h * t), y0 + int(h * u)) for k, (t, u) in BANDS.items()}
    widths = [face_w] + [(x1 - x0) * zoom for _ in strips]
    row_h = max(int(face_w * h / (x1 - x0)), max((b - a) * zoom for a, b in strips.values())) + 26
    sheet_ = Image.new("RGB", (sum(widths) + 10 * len(widths), row_h * len(order)), "white")
    d = ImageDraw.Draw(sheet_)
    for r, s in enumerate(order):
        im = Image.open(s).convert("RGB")
        y = r * row_h
        d.text((4, y + 2), Path(s).stem + ("（比べる相手）" if r == 0 else ""), fill="black", font=font)
        x = 0
        f = im.crop(box)
        sheet_.paste(f.resize((face_w, int(face_w * f.height / f.width))), (x, y + 24))
        x += face_w + 10
        for k, (a, b) in strips.items():
            st = im.crop((x0, a, x1, b))
            sheet_.paste(st.resize((st.width * zoom, st.height * zoom), Image.LANCZOS), (x, y + 24))
            if r == 0:
                d.text((x + 4, y + 2), f"{k}（{zoom}倍）", fill="red", font=font)
            x += st.width * zoom + 10
    sheet_.save(out, quality=85)
    return {"out": out, "face": [int(v) for v in box], "rows": [Path(s).name for s in order],
            "note": "動いたかは数字で決めない。行を上下に見比べて、眉・目・口のどれが動いたかを目で決める"}


def compare(srcs: list[str], limit: float = 40.0) -> dict:
    colors = []
    for s in srcs:
        im = Image.open(s).convert("RGB")
        colors.append(part_colors(np.asarray(im), _parts(s, im)))
    return {"files": srcs, "gaps": color_gaps(colors, limit),
            "parts_found": [[PART_JA[k] for k in c] for c in colors]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet"); s.add_argument("src"); s.add_argument("out")
    f = sub.add_parser("facts"); f.add_argument("src"); f.add_argument("--character")
    c = sub.add_parser("compare"); c.add_argument("srcs", nargs="+"); c.add_argument("--limit", type=float, default=40.0)
    sc = sub.add_parser("scars"); sc.add_argument("before"); sc.add_argument("after"); sc.add_argument("mask")
    e = sub.add_parser("expr"); e.add_argument("base"); e.add_argument("out"); e.add_argument("srcs", nargs="+")
    a = ap.parse_args()
    r = {"sheet": lambda: sheet(a.src, a.out), "facts": lambda: facts(a.src, a.character),
         "compare": lambda: compare(a.srcs, a.limit), "expr": lambda: expr(a.base, a.out, a.srcs),
         "scars": lambda: repaint_scars(*(Image.open(p) for p in (a.before, a.after, a.mask)))}[a.cmd]()
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
