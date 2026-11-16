"""模型で描いた絵から、人が描いている途中に見える工程の絵と、筆が動くタイムラプスを作る。

工程に分けて描いても、模型は 1 回で色も影も背景も付いた絵を出す。その絵を工程ごとにそのまま見せると、
サムネイルの時点で完成の絵になり、あとの工程は完成の絵に少し手を入れるだけに見えた。人が描くときは、
白い紙にラフの薄い線 → 清書した線画 → 部位ごとの平らな下塗り → 影 1 段 → 影 2 段 → 光 → 背景 → ディテール → 仕上げ、
の順にキャンバスに物が増えていく（docs/knowledge/drawing-phases.md）。そこで、模型の絵から線と平らな色と影と光を取り出し、
その順に重ねた絵を作る。最後の絵は模型の絵そのもの（質を落とさない）で、仕上げではゴミ（孤立した点、色の継ぎ目）を検品して直す。

線の取り出しは、外の模型（lineart の注釈器など）を使わず、明るさの谷（周りより暗く細い所）を numpy と scipy で取る
（取りに行く部品と許諾の確かめが要らず、1 枚 1 秒ほどで済む）。
しきい値はどれも私の推測の値で、Actions の phase-bench の絵で見直す。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

STAGES = ["白紙", "アタリ", "ラフ", "線画", "下塗り", "影 1 段", "影 2 段", "光", "背景", "ディテール", "仕上げ"]
# 工程（chatdraw/phases.PHASES の順）ごとに、キャンバスに見せる人の工程
PHASE_STAGE = ["白紙", "サムネイル", "アタリ", "ラフ", "ラフ", "ラフ", "線画", "下塗り", "影 1 段", "影 2 段", "光", "仕上げ"]
PAPER = (255, 255, 255)
PENCIL = np.array([96, 108, 140], np.float32)   # ラフの鉛筆の色（青みの灰色）
LINE_DARK = 14       # 線: 周りの明るさよりこれだけ暗い所を線とする（0〜255）
ROUGH_DARK = 10      # ラフ: 同じ。粗く縮めた絵で測る
SHADE1, SHADE2, LIGHT = 12, 45, 15   # 下塗りの色よりこれだけ暗い・明るい所を、影 1 段・影 2 段・光とする
SPECK_DIFF, SPECK_MOST = 90, 6       # 周りの中央の色から RGB の差の和がこれ以上離れ、塊がこの画素数以下なら孤立した点
FIG_GROW = 6         # 部位分けの人物の所を広げる画素
SEAM_JUMP = 70       # 1 つの部位の中で、上下の帯の明るさがこれだけ跳んだら色の継ぎ目
FRAME_SIDE = 480     # タイムラプスの 1 枚の長い辺
REGION_COLORS = 10   # 塗りの所を分ける色の数（私の推測）
BASE_COLORS = 12     # 下塗りに使う色の数。人の下塗りは部位ごとに 1 色なので、色を絞って平らにする（私の推測）


def _lum(a):
    a = a.astype(np.float32)
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def figure(image, parts=None):
    """人物の所の真偽の配列。部位分けがあればそれを使い、無ければ四隅の色から分ける。分けられなければ None（全部を人物として扱う）"""
    from scipy import ndimage
    if parts is not None:
        m = ndimage.binary_dilation(np.asarray(parts) > 0, iterations=FIG_GROW)   # 部位分けは指先を落とすので、少し広げる
    else:
        from chatdraw import phasetools
        m = phasetools.silhouette(image)
    m = ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=2))
    share = m.mean()
    return m if 0.03 < share < 0.85 else None


def dark_lines(image, sigma=1.0, dark=LINE_DARK):
    """明るさの谷の深さ（0〜255 の float）。大きいほど濃い線"""
    from scipy import ndimage
    L = _lum(np.asarray(image.convert("RGB")))
    fine = ndimage.gaussian_filter(L, sigma * 0.6)
    around = ndimage.gaussian_filter(L, sigma * 3.0)
    d = np.clip(around - fine - dark, 0, None)
    return np.clip(d * 4.0, 0, 255)


def blank(size):
    return Image.new("RGB", size, PAPER)


_blank = blank


def rough(image, fig=None, scale=3, alpha=0.55):
    """白い紙に薄い鉛筆の線。縮めた絵で線を取るので細部が落ち、2 本ずらして重ねて下描きの揺れを出す"""
    from scipy import ndimage
    w, h = image.size
    small = image.convert("RGB").resize((max(8, w // scale), max(8, h // scale)), Image.BILINEAR)
    d = dark_lines(small, sigma=1.0, dark=ROUGH_DARK)
    d = np.asarray(Image.fromarray(d.astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255.0
    d2 = ndimage.shift(d, (2, -2), order=0)
    a = np.clip(np.maximum(d * alpha, d2 * alpha * 0.6), 0, 1)
    if fig is not None:
        a *= ndimage.binary_dilation(fig, iterations=6)
    paper = np.full((h, w, 3), 255, np.float32)
    out = paper * (1 - a[..., None]) + PENCIL * a[..., None]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


ATARI = (70, 130, 220)   # アタリの線の色（薄い青）
LIMBS = [("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"), ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
         ("left_hip", "left_knee"), ("left_knee", "left_ankle"), ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
         ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip")]


def atari(size, points, base=None):
    """丸と棒のアタリ。最後の絵の体の点（頭・肩・腰・関節）の位置にそのまま置く（前は粗いラフを縮めて代わりにしていて、
    あとの絵の体の位置と合わなかった）。体の点が読めなければ None"""
    pts = {k: tuple(v) for k, v in (points or {}).items()}
    need = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    if not all(k in pts for k in need):
        return None
    out = base.copy() if base is not None else _blank(size)
    d = ImageDraw.Draw(out)
    w = max(2, round(min(size) / 300))
    sw = abs(pts["left_shoulder"][0] - pts["right_shoulder"][0]) or min(size) / 8
    face = [pts[k] for k in ("nose", "left_eye", "right_eye", "left_ear", "right_ear") if k in pts]
    sh = ((pts["left_shoulder"][0] + pts["right_shoulder"][0]) / 2, (pts["left_shoulder"][1] + pts["right_shoulder"][1]) / 2)
    hip = ((pts["left_hip"][0] + pts["right_hip"][0]) / 2, (pts["left_hip"][1] + pts["right_hip"][1]) / 2)
    if face:
        cx, cy = sum(p[0] for p in face) / len(face), sum(p[1] for p in face) / len(face)
    else:
        cx, cy = sh[0], sh[1] - sw * 0.7
    r = sw * 0.42
    d.ellipse([cx - r, cy - r * 1.15, cx + r, cy + r * 1.05], outline=ATARI, width=w)   # 頭の丸
    d.line([cx - r, cy, cx + r, cy], fill=ATARI, width=1)                             # 目の高さの十字
    d.line([cx, cy - r * 1.15, cx, cy + r * 1.05], fill=ATARI, width=1)
    d.line([(cx, cy + r), sh], fill=ATARI, width=w)                                    # 首
    d.line([sh, hip], fill=ATARI, width=w)                                             # 背骨
    for a, b in LIMBS:
        if a in pts and b in pts:
            d.line([pts[a], pts[b]], fill=ATARI, width=w)
    for k, p in pts.items():
        if k in ("nose", "left_eye", "right_eye", "left_ear", "right_ear"):
            continue
        rr = w * 3
        d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], outline=ATARI, width=w)   # 関節の丸
    return out


def thumbnail(image, fig=None):
    """白い紙の真ん中に、小さく縮めた粗いラフ（構図だけを見るサムネイル）"""
    w, h = image.size
    r = rough(image, fig, scale=6, alpha=0.7).resize((w // 3, h // 3), Image.LANCZOS)
    out = _blank((w, h))
    out.paste(r, ((w - r.width) // 2, (h - r.height) // 2))
    ImageDraw.Draw(out).rectangle([(w - r.width) // 2 - 2, (h - r.height) // 2 - 2, (w + r.width) // 2 + 1, (h + r.height) // 2 + 1],
                                  outline=(150, 150, 150))
    return out


def ink(image, fig=None):
    """清書した線の濃さ（0〜1）。人物の所だけ（人物を分けられなければ全体）"""
    from scipy import ndimage
    a = np.clip(dark_lines(image, sigma=1.0) / 255.0 * 1.6, 0, 1)
    if fig is not None:
        a *= ndimage.binary_dilation(fig, iterations=2)
    return a


def lineart(image, fig=None):
    a = ink(image, fig)
    return Image.fromarray((255 * (1 - a)).clip(0, 255).astype(np.uint8)).convert("RGB")


def regions(image, fig=None, colors=REGION_COLORS):
    """塗りの所の番号（0 は人物の外）。色の近い塊（影の濃さは縮めて、同じ物の明るい所と暗い所を 1 つにする）を線で切って番号にする。
    線だけで閉じた所にすると、線が途切れた所から全体が 1 つにつながり、マフラーの赤まで壁の色になった。
    小さすぎる所と線の上は、近い所の番号に寄せる（塗り残しを作らない）"""
    from scipy import ndimage
    rgb = image.convert("RGB")
    a = np.asarray(rgb.filter(ImageFilter.MedianFilter(5))).astype(np.float32)
    L = _lum(a)
    lift = a * ((255.0 * (np.clip(L, 1, 255) / 255.0) ** 0.3) / np.clip(L, 1, 255))[..., None]
    q = np.asarray(Image.fromarray(lift.clip(0, 255).astype(np.uint8)).quantize(colors=colors, method=Image.MEDIANCUT)
                   .filter(ImageFilter.ModeFilter(7)))
    line = ink(rgb, None) > 0.35
    area = np.ones(line.shape, bool) if fig is None else fig
    lab = np.zeros(line.shape, np.int32)
    top = 0
    for c in np.unique(q):
        l, n = ndimage.label(area & ~line & (q == c))
        lab[l > 0] = l[l > 0] + top
        top += n
    if top:
        sizes = np.bincount(lab.ravel(), minlength=top + 1)
        small = sizes < max(30, line.size // 8000)
        small[0] = True
        lab[small[lab]] = 0
    holes = area & (lab == 0)
    if holes.any() and (lab > 0).any():
        _d, idx = ndimage.distance_transform_edt(lab == 0, return_indices=True)
        lab[holes] = lab[idx[0][holes], idx[1][holes]]
    return lab


def _means(src, lab, take):
    """番号ごとに、take の画素の色の平均（take が無い番号は nan）"""
    n = int(lab.max()) + 1
    key = lab[take]
    cnt = np.bincount(key, minlength=n).astype(np.float32)
    out = np.full((n, 3), np.nan, np.float32)
    for c in range(3):
        s = np.bincount(key, weights=src[..., c][take], minlength=n)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, c] = s / cnt
    out[cnt == 0] = np.nan
    return out


def layers(image, fig=None, lab=None):
    """下塗り・影 1 段・影 2 段・光の色の絵（numpy の float の RGB）と、塗る所の真偽の配列"""
    a = np.asarray(image.convert("RGB")).astype(np.float32)
    if lab is None:
        lab = regions(image, fig)
    area = lab > 0
    L = _lum(a)
    n = int(lab.max()) + 1
    lmean = np.bincount(lab.ravel(), weights=L.ravel(), minlength=n) / np.maximum(np.bincount(lab.ravel(), minlength=n), 1)
    base_c = _means(a, lab, area & (L >= lmean[lab]))   # 部位の明るい側の平均を固有の色にする（影の色を下塗りに混ぜない）
    base_c = np.where(np.isnan(base_c), _means(a, lab, area), base_c)
    base = np.where(area[..., None], np.nan_to_num(base_c[lab], nan=255.0), 255.0)
    # 塗りの所ごとの色のままでは、背景のぼかしや服のしわの明暗が段になって残り、下塗りの時点で完成に近く見えた。色を絞って平らにする
    flat = np.asarray(Image.fromarray(base.clip(0, 255).astype(np.uint8)).quantize(colors=BASE_COLORS, method=Image.MEDIANCUT)
                      .convert("RGB")).astype(np.float32)
    base = np.where(area[..., None], flat, 255.0)
    bl = _lum(base)
    out = {"base": base, "area": area, "lab": lab}
    prev = base
    for name, sel in (("shade1", area & (L < bl - SHADE1)), ("shade2", area & (L < bl - SHADE2)), ("light", area & (L > bl + LIGHT))):
        c = _means(a, lab, sel)
        layer = prev.copy()
        layer[sel] = np.nan_to_num(c[lab][sel], nan=0) if sel.any() else layer[sel]
        out[name], out[name + "_m"] = layer, sel
        prev = layer
    return out


def _with_lines(rgb, a):
    return Image.fromarray((rgb * (1 - a[..., None] * 0.92)).clip(0, 255).astype(np.uint8))


def stages(final, parts=None, points=None) -> list[tuple[str, Image.Image]]:
    """人の工程の順の絵。最後は仕上げ（模型の絵。clean を通した物を渡す）。人物を背景から分けられないときは「背景」を省く"""
    from scipy import ndimage
    final = final.convert("RGB")
    fig = figure(final, parts)
    a = ink(final, fig)
    ly = layers(final, fig)
    w, h = final.size
    fa = np.asarray(final).astype(np.float32)
    out = [("白紙", _blank((w, h)))]
    at = atari((w, h), points)
    if at is not None:
        out.append(("アタリ", at))
        out.append(("ラフ", Image.blend(at, rough(final, fig), 0.75)))   # ラフはアタリの上に描く
    else:
        out.append(("ラフ", rough(final, fig)))
    out.append(("線画", lineart(final, fig)))   # 線画は白い紙の上の黒い線だけ（色の絵に色調を掛けない）
    for key, name in (("base", "下塗り"), ("shade1", "影 1 段"), ("shade2", "影 2 段"), ("light", "光")):
        out.append((name, _with_lines(ly[key], a)))
    lit = ly["light"]
    if fig is not None:
        core = fig if parts is None else ndimage.binary_erosion(np.asarray(parts) > 0, iterations=4)
        # 背景を入れたら、人物の縁は広げる前の部位分けで切る（部位分けは人物より数画素外まで取るので、少し削る。削らないと人物のまわりに明るい輪が残った）
        soft = ndimage.gaussian_filter(core.astype(np.float32), 1.5)[..., None]
        lit = np.where(ly["area"][..., None], lit, fa)   # 塗る所の外の白で縁をぼかすと、人物のまわりに白い光の輪が出た
        bg = lit * soft + fa * (1 - soft)
        out.append(("背景", _with_lines(bg, a)))
        detail = bg * 0.35 + fa * 0.65
    else:
        detail = lit * 0.35 + fa * 0.65
    out.append(("ディテール", _with_lines(detail, a * 0.5)))
    out.append(("仕上げ", final))
    return out


def for_phase(i: int, image, parts=None, points=None):
    """工程 i（0 から）の途中にキャンバスに見せる絵。模型の絵をそのまま見せない（完成の絵を先に見せない）"""
    name = PHASE_STAGE[min(i, len(PHASE_STAGE) - 1)]
    if image is None or name == "白紙":
        return _blank(image.size if image is not None else (832, 1216))
    fig = figure(image, parts)
    if name == "サムネイル":
        return thumbnail(image, fig)
    if name == "アタリ":
        at = atari(image.size, points)
        return at if at is not None else rough(image, fig, scale=8, alpha=0.45)
    if name == "ラフ":
        r = rough(image, fig, scale={3: 5, 4: 3}.get(i, 2))
        at = atari(image.size, points)
        return Image.blend(at, r, 0.75) if at is not None else r
    if name == "線画":
        return lineart(image, fig)
    if name == "仕上げ":
        return image
    ly = layers(image, fig)
    key = {"下塗り": "base", "影 1 段": "shade1", "影 2 段": "shade2", "光": "light"}[name]
    return _with_lines(ly[key], ink(image, fig))


# ここから仕上げのゴミの検品と直し

def specks(image, protect=None):
    """孤立した点（周りの中央の色から大きく外れた、ごく小さな塊）の真偽の配列"""
    from scipy import ndimage
    a = np.asarray(image.convert("RGB")).astype(np.int16)
    med = np.stack([ndimage.median_filter(a[..., c], size=5) for c in range(3)], -1)
    off = np.abs(a - med).sum(-1) > SPECK_DIFF
    lab, n = ndimage.label(off)
    if not n:
        return off & False, med
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    m = (sizes <= SPECK_MOST)[lab] & off
    if protect is not None:
        m &= ~protect
    return m, med


PART_NAMES = {1: "帽子", 2: "髪", 4: "上の服", 5: "スカート", 6: "ズボン", 7: "ワンピース", 8: "ベルト", 9: "左の靴", 10: "右の靴",
              11: "顔", 12: "左脚", 13: "右脚", 14: "左腕", 15: "右腕", 16: "鞄", 17: "マフラー"}


def seams(image, parts) -> list[dict]:
    """1 つの部位の中で、上下の帯の明るさが急に跳ぶ所（靴下が上は白・下は黒に分かれる、など）。部位分けが無ければ測れない"""
    if parts is None:
        return []
    p = np.asarray(parts)
    L = _lum(np.asarray(image.convert("RGB")))
    found = []
    for k in np.unique(p):
        if k == 0:
            continue
        m = p == k
        rows = np.where(m.sum(1) >= 6)[0]
        if len(rows) < 30:
            continue
        prof = np.array([L[r][m[r]].mean() for r in rows])
        step = max(3, len(rows) // 20)   # 継ぎ目はぼけて数十画素にわたるので、部位の高さに合わせた幅で比べる
        jump = np.abs(prof[step:] - prof[:-step])
        j = int(jump.argmax())
        if jump[j] < SEAM_JUMP:
            continue
        top, bot = j + step, len(rows) - j - step
        if min(top, bot) < 0.15 * len(rows):
            continue
        y = int(rows[j + step // 2])
        xs = np.where(m[y])[0]
        found.append({"part": PART_NAMES.get(int(k), f"部位 {int(k)}"), "jump": round(float(jump[j]), 1),
                      "box": (int(xs.min()) - 8, y - 24, int(xs.max()) + 8, y + 24)})
    return found


def clean(image, parts=None) -> tuple[Image.Image, dict]:
    """孤立した点を周りの色で埋め、色の継ぎ目を測る。返りは (直した絵, {"specks": 埋めた画素, "seams": 継ぎ目の一覧})。
    線の上の点は線の一部なので触らない"""
    from scipy import ndimage
    line = ink(image) > 0.5
    lab, n = ndimage.label(line, structure=np.ones((3, 3)))
    if n:   # 線（つながった長い塊）だけを守る。線と同じ暗さの点まで守ると、黒い点のゴミが残った
        line = (np.bincount(lab.ravel(), minlength=n + 1) > SPECK_MOST * 3)[lab] & line
    m, med = specks(image, protect=line)
    a = np.asarray(image.convert("RGB")).copy()
    a[m] = med[m].astype(np.uint8)
    out = Image.fromarray(a)
    return out, {"specks": int(m.sum()), "seams": seams(out, parts), "seams_readable": parts is not None}


# ここからタイムラプス（筆が動く）

def strokes(mask, most=4000) -> list[list[tuple[int, int]]]:
    """線の画素を、隣へ隣へとたどって筆の線（点の並び）にする。上から順に並べる（人は頭から描く）"""
    ys, xs = np.nonzero(mask)
    left = set(zip(xs.tolist(), ys.tolist()))
    order = sorted(left, key=lambda p: (p[1] // 24, p[0]))
    out = []
    near = [(dx, dy) for r in (1, 2) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if max(abs(dx), abs(dy)) == r]
    for start in order:
        if start not in left:
            continue
        left.discard(start)
        line, (x, y) = [start], start
        while True:
            for dx, dy in near:
                q = (x + dx, y + dy)
                if q in left:
                    left.discard(q)
                    line.append(q)
                    x, y = q
                    break
            else:
                break
        if len(line) >= 3:
            out.append(line)
        if len(out) >= most:
            break
    return out


def _pen(img, xy, r=5, color=(40, 40, 40)):
    """筆先の印（今どこを描いているか）"""
    f = img.copy()
    d = ImageDraw.Draw(f)
    x, y = xy
    d.line([x, y, x + 22, y - 30], fill=(120, 90, 60), width=4)
    d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=2)
    return f


def _draw_lines(base, target, frames, width, per):
    """target の線を、筆の線の順に base の上へ描き足していく"""
    t = np.asarray(target.convert("L")) < 235
    lines = strokes(t)
    acc = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(acc)
    cur = base
    for k, s in enumerate(lines):
        d.line(s, fill=255, width=width) if len(s) > 1 else None
        if (k + 1) % per == 0 or k == len(lines) - 1:
            cur = Image.composite(target, base, acc)
            frames.append(_pen(cur, s[-1]))
    return Image.composite(target, base, acc) if lines else target


def _brush(base, target, frames, r, n_frames, order_lab=None):
    """base と違う所を、筆の丸い跡（筆の幅 r）で行ったり来たりしながら塗り広げる。塗る所ごと（大きい所から）に塗る"""
    a, b = np.asarray(base).astype(np.int16), np.asarray(target).astype(np.int16)
    diff = np.abs(a - b).sum(-1) > 12
    if not diff.any():
        return target
    groups = []
    if order_lab is not None:
        lab = order_lab
        ids, cnt = np.unique(lab[diff], return_counts=True)
        for i in ids[np.argsort(-cnt)]:
            groups.append(diff & (lab == i))
        rest = diff & ~(np.isin(lab, ids))
        if rest.any():
            groups.append(rest)
    else:
        groups = [diff]
    dabs = []
    for g in groups:
        ys, xs = np.nonzero(g)
        if len(ys) < 4:
            continue
        for row, y in enumerate(range(int(ys.min()), int(ys.max()) + 1, r)):
            band = xs[(ys >= y) & (ys < y + r)]
            if not len(band):
                continue
            rng = range(int(band.min()), int(band.max()) + 1, r)
            for x in (rng if row % 2 == 0 else reversed(list(rng))):
                if g[min(y + r // 2, g.shape[0] - 1), min(x, g.shape[1] - 1)] or g[y, min(x, g.shape[1] - 1)]:
                    dabs.append((x, y + r // 2))
    if not dabs:
        return target
    acc = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(acc)
    per = max(1, len(dabs) // n_frames)
    for k, (x, y) in enumerate(dabs):
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        if (k + 1) % per == 0:
            frames.append(_pen(Image.composite(target, base, acc), (x, y), r))
    # 筆の跡の外に残った所（細い隙間）は、最後の 1 枚で埋める
    frames.append(target)
    return target


def timelapse(stage_list, side=FRAME_SIDE, parts=None) -> list[Image.Image]:
    """人の工程の絵から、筆が動くタイムラプスの絵の並びを作る"""
    small = []
    for name, im in stage_list:
        s = im.convert("RGB").copy()
        s.thumbnail((side, side), Image.LANCZOS)
        small.append((name, s))
    frames = [small[0][1]] * 6
    cur = small[0][1]
    lab = None
    for name, im in small[1:]:
        if name in ("アタリ", "ラフ"):
            cur = _draw_lines(cur, im, frames, width=2, per=4 if name == "アタリ" else 12)
        elif name == "線画":
            # 人は線画を清書するとき、ラフを薄くしてその上をなぞり、最後にラフを消す
            faint = Image.blend(cur, _blank(cur.size), 0.7)
            frames.append(faint)
            cur = _draw_lines(faint, Image.composite(im, faint, Image.fromarray(((np.asarray(im.convert("L")) < 235) * 255).astype(np.uint8))),
                              frames, width=2, per=10)
            cur = im
            frames.extend([cur] * 3)
            lab = regions(stage_list[-1][1].convert("RGB").resize(cur.size, Image.LANCZOS))
        elif name == "仕上げ":
            for t in (0.25, 0.5, 0.75):
                frames.append(Image.blend(cur, im, t))
            cur = im
        else:
            r = {"下塗り": 9, "影 1 段": 6, "影 2 段": 4, "光": 3, "背景": 12, "ディテール": 3}.get(name, 6)
            cur = _brush(cur, im, frames, r, 40, lab if name in ("下塗り", "影 1 段", "影 2 段", "光") else None)
        frames.extend([cur] * 4)   # 工程の区切りで少し止める
    frames.extend([small[-1][1]] * 12)
    return frames


def save_gif(frames, path: Path, ms=60) -> Path:
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0, optimize=True)
    return path


def transition(prev, new, n=10, side=FRAME_SIDE) -> list[Image.Image]:
    """前の工程の絵の上に、次の工程を筆で描き重ねていく途中の絵（窓に順に出す）。線の工程は線を引き、色の工程は筆で塗り広げる"""
    size = new.size
    a, b = prev.convert("RGB").copy(), new.convert("RGB").copy()
    a.thumbnail((side, side), Image.LANCZOS)
    b = b.resize(a.size, Image.LANCZOS)
    frames: list[Image.Image] = []
    if sat(b) < 12:
        per = max(1, len(strokes(np.asarray(b.convert("L")) < 235)) // n)
        _draw_lines(a, b, frames, width=2, per=per)
    else:
        _brush(a, b, frames, 8, n)
    step = max(1, len(frames) // n)
    return [f.resize(size, Image.BILINEAR) for f in frames[::step][:n]] + [new]


def sat(im) -> float:
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    return float((a.max(-1) - a.min(-1)).mean())


def build(final, keep: Path, parts=None, points=None) -> dict:
    """仕上げのゴミを直し、人の工程の絵を keep/human/ に、タイムラプスを keep/timelapse.gif に残す"""
    import time
    t0 = time.time()
    cleaned, report = clean(final, parts)
    st = stages(cleaned, parts, points)
    d = keep / "human"
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, (name, im) in enumerate(st, 1):
        p = d / f"{k:02d}-{name.replace(' ', '')}.png"
        im.save(p)
        paths.append((name, str(p)))
    t1 = time.time()
    frames = timelapse(st, parts=parts)
    gif = save_gif(frames, keep / "timelapse.gif")
    return {"image": cleaned, "stages": paths, "timelapse": str(gif), "frames": len(frames), "frame_list": frames, "clean": report,
            "seconds": {"stages": round(t1 - t0, 2), "timelapse": round(time.time() - t1, 2)}}
