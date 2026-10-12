"""検品の下ごしらえ: 検品担当（.claude/agents/checker.md）が目で見る前に、機械で拡大図と事実をそろえる。

検品担当が自分で切り出すと、座標がずれて顔や手が写らない回があり、画像の枚数を絞った回は指や足元が
「見ていない」のまま残った。宙に浮いた布や、設定で描かせないものも、毎回目だけで探していた。
ここでは、決まった形の検品図を1枚作り、数えられる事実を先に出す。判断（通す・戻す）はしない。

  python3 tools/gen/qc.py sheet   絵.png OUT.png               全体と顔の拡大（OUT）、人物を分けた2倍前後の拡大（OUT-detail）の検品図
  python3 tools/gen/qc.py facts   絵.png [--character knight]   浮いた塊・肌の割合・描かせないものが読めたか・設定の言葉の欠け
  python3 tools/gen/qc.py compare 絵1.png 絵2.png ...           組（三面図・表情差分）で、部位ごとの色がずれていないか
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
    res = {"floating": floating_blobs(rgb),
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
    e = sub.add_parser("expr"); e.add_argument("base"); e.add_argument("out"); e.add_argument("srcs", nargs="+")
    a = ap.parse_args()
    r = {"sheet": lambda: sheet(a.src, a.out), "facts": lambda: facts(a.src, a.character),
         "compare": lambda: compare(a.srcs, a.limit), "expr": lambda: expr(a.base, a.out, a.srcs)}[a.cmd]()
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
