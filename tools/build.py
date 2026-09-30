"""部品で組んだキャラクター（parts.json）を、光を当てて高い解像度で描き、ドット絵に落とす。

1ドットずつ文字で打つ描き方は、陰影の密度で頭打ちになる。そこで形は部品（楕円、多角形、
太さのある線）で組み、光で陰影を付けてから、縮小・減色・輪郭付け・孤立ドットの掃除で
ドットにする。最後だけ touchups で1ドット単位に直す。手本にした作風の作品が 3D の
モデルからドットを起こしているのと同じ順序にしている。

座標は仕上がりのドット単位（小数可）で書く。内部では SS 倍の解像度で描く。
依存は Pillow だけにしている（重い道具を足す前に、自前の描画で届くかを試すため）。

使い方: python3 tools/build.py characters/<name>/parts.json [--preview out/]
出力: 同じフォルダの sprite.json（tools/check.py と tools/render.py がそのまま読める形）
"""
import argparse
import copy
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SS = 8  # 1ドットを何倍で描くか。8 あれば 1px 幅の剣も形が崩れない

# 光は左上・手前から。styles/diorama.json の light.direction に合わせている
LIGHT = (-0.55, -0.65, 0.52)


def _norm(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def _data(img):
    """画素の並び。Pillow 12 で getdata が非推奨になったので、あれば新しい方を使う。"""
    f = getattr(img, "get_flattened_data", None)
    return f() if f else img.getdata()


# ---------------------------------------------------------------- 形を描く

def draw_shape(draw, shape, shift=(0, 0)):
    """shape を SS 倍の座標で draw に塗る。shift は全体をずらす量（ドット単位）。"""
    kind = shape["type"]
    s = SS
    shape = _shifted(shape, shift)
    if kind == "ellipse":
        cx, cy, rx, ry = shape["at"]
        draw.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s], fill=255)
    elif kind == "poly":
        draw.polygon([(x * s, y * s) for x, y in shape["points"]], fill=255)
    elif kind == "rect":
        x0, y0, x1, y1 = shape["at"]
        draw.rectangle([x0 * s, y0 * s, x1 * s - 1, y1 * s - 1], fill=255)
    elif kind == "capsule":
        # 太さのある線。腕や脚のように、両端が丸い筒
        pts = shape["points"]
        r = shape["r"]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            dx, dy = x1 - x0, y1 - y0
            n = math.hypot(dx, dy) or 1.0
            ox, oy = -dy / n * r, dx / n * r
            draw.polygon([((x0 + ox) * s, (y0 + oy) * s), ((x1 + ox) * s, (y1 + oy) * s),
                          ((x1 - ox) * s, (y1 - oy) * s), ((x0 - ox) * s, (y0 - oy) * s)], fill=255)
        for x, y in pts:
            draw.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill=255)
    elif kind == "pixline":
        # ドット単位の線。細い斜めの剣や槍は、縮小に任せると段がそろわず鎖のように途切れる。
        # 仕上がりの格子で Bresenham の線を引き、そのドットを丸ごと塗る
        (x0, y0), (x1, y1) = [(int(round(x)), int(round(y))) for x, y in shape["points"]]
        for x, y in _bresenham(x0, y0, x1, y1):
            for k in range(shape.get("width", 1)):
                draw.rectangle([(x + k) * s, y * s, (x + k + 1) * s - 1, (y + 1) * s - 1], fill=255)
    else:
        raise ValueError(f"知らない形: {kind}")


def _bresenham(x0, y0, x1, y1):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _shifted(shape, shift):
    dx, dy = shift
    if not (dx or dy):
        return shape
    shape = dict(shape)
    if "points" in shape:
        shape["points"] = [[x + dx, y + dy] for x, y in shape["points"]]
    if shape["type"] == "ellipse":
        cx, cy, rx, ry = shape["at"]
        shape["at"] = [cx + dx, cy + dy, rx, ry]
    elif shape["type"] == "rect":
        x0, y0, x1, y1 = shape["at"]
        shape["at"] = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
    return shape


def part_mask(part, size, shift=(0, 0)):
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    for shape in part["shapes"]:
        draw_shape(d, shape, shift)
    for shape in part.get("cut", []):
        # cut は形をくり抜く。兜の覗き穴や、腕の間の隙間に使う
        m = Image.new("L", size, 0)
        draw_shape(ImageDraw.Draw(m), shape, shift)
        mask.paste(0, (0, 0), m)
    return mask


# ---------------------------------------------------------------- 光を当てる

def shade_part(part, mask, material):
    """部品ごとの明るさ（0〜1）を SS 倍の解像度で返す。

    形の厚みは、マスクをぼかして作る膨らみで近似する。部品の中心が盛り上がり、縁が落ちる。
    これで法線を取り、左上の光との内積で明るさを決める。金属は鋭い反射を足す。
    """
    w, h = mask.size
    bbox = mask.getbbox()
    if not bbox:
        return [0.0] * (w * h)
    thin = min(bbox[2] - bbox[0], bbox[3] - bbox[1])
    radius = max(1.0, thin * part.get("round", 0.35))
    height = list(_data(mask.filter(ImageFilter.GaussianBlur(radius))))
    mdata = _data(mask)
    # 膨らみの高さを部品の太さに比例させる。細い腕も太い胴も同じ丸みに見えるように
    relief = part.get("relief", 1.4) * radius / 2.0 / 255.0
    L = _norm(LIGHT)
    spec_power = material.get("spec_power", 0)
    spec_gain = material.get("spec_gain", 0.0)
    ambient = material.get("ambient", 0.32)
    bias = part.get("bias", 0.0)
    # 房（strands）: 流れに直交する向きに明暗の縞を足す。髪や毛皮を面ではなく束に見せる
    strands = part.get("strands")
    if strands:
        a = math.radians(strands.get("angle", 0))
        ca, sa = math.cos(a), math.sin(a)
        k = 2 * math.pi / (strands.get("period", 2.5) * SS)
        amp = strands.get("amp", 0.15)
    # 反射の向き: 視線 (0,0,1) と光の中間
    Hv = _norm((L[0], L[1], L[2] + 1.0))
    out = [0.0] * (w * h)
    # 部品の範囲だけを走る。全画面を走ると、小さな部品でも 7 万画素を見ることになる
    for y in range(bbox[1], bbox[3]):
        row = y * w
        for x in range(bbox[0], bbox[2]):
            i = row + x
            if mdata[i] < 128:
                continue
            hx = (height[i + 1] if x + 1 < w else 0) - (height[i - 1] if x > 0 else 0)
            hy = (height[i + w] if y + 1 < h else 0) - (height[i - w] if y > 0 else 0)
            # _norm を画素ごとに呼ぶと遅いので、同じ計算をその場で行う（足す順も同じにして結果を変えない）
            nx, ny = -hx * relief, -hy * relief
            nn = math.sqrt(nx * nx + ny * ny + 1.0) or 1.0
            n = (nx / nn, ny / nn, 1.0 / nn)
            diff = max(0.0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2])
            v = ambient + (1 - ambient) * diff
            if spec_power:
                sp = max(0.0, n[0] * Hv[0] + n[1] * Hv[1] + n[2] * Hv[2]) ** spec_power
                v += spec_gain * sp
            if strands:
                v += amp * math.sin((x * ca + y * sa) * k)
            out[i] = v + bias
    return out


# ---------------------------------------------------------------- 組み立て

def render_hi(spec):
    """全部品を奥から順に重ね、SS 倍の (部品番号, 明るさ) の格子を返す。"""
    W, H = spec["canvas"]
    size = (W * SS, H * SS)
    parts = spec["parts"]
    mats = spec["materials"]
    top = [-1] * (size[0] * size[1])
    light = [0.0] * (size[0] * size[1])
    for idx, part in enumerate(parts):
        sx0, sy0 = spec.get("shift", (0, 0))
        ox, oy = part.get("offset", (0, 0))
        mask = part_mask(part, size, (sx0 + ox, sy0 + oy))
        box = mask.getbbox()
        if not box:
            continue
        sh = shade_part(part, mask, mats[part["material"]])
        md = _data(mask)
        w0 = size[0]
        for y in range(box[1], box[3]):
            for i in range(y * w0 + box[0], y * w0 + box[2]):
                if md[i] >= 128:
                    top[i] = idx
                    light[i] = sh[i]
    # 落ち影: 光の来る側（左上）に手前の部品があれば暗くする。部品の重なりに奥行きを出す
    ox, oy = spec.get("cast_shadow", {}).get("offset", [0.6, 0.9])
    dim = spec.get("cast_shadow", {}).get("strength", 0.28)
    sx, sy = round(ox * SS), round(oy * SS)
    w, h = size
    groups = [p.get("group", p["name"]) for p in parts]
    shaded = light[:]
    for y in range(h):
        for x in range(w):
            i = y * w + x
            p = top[i]
            if p < 0:
                continue
            qx, qy = x - sx, y - sy
            if 0 <= qx < w and 0 <= qy < h:
                q = top[qy * w + qx]
                if q > p and groups[q] != groups[p] and not parts[q].get("no_cast"):
                    shaded[i] = light[i] - dim
    return top, shaded, size


def downscale(spec, top, light, size):
    """SS×SS の塊ごとに、いちばん広く見えている部品とその平均の明るさを1ドットにする。"""
    W, H = spec["canvas"]
    w = size[0]
    parts = spec["parts"]
    cells = [[None] * W for _ in range(H)]
    area = SS * SS
    for Y in range(H):
        for X in range(W):
            count, total = {}, {}
            for y in range(Y * SS, (Y + 1) * SS):
                for x in range(X * SS, (X + 1) * SS):
                    p = top[y * w + x]
                    if p < 0:
                        continue
                    count[p] = count.get(p, 0) + 1
                    total[p] = total.get(p, 0.0) + light[y * w + x]
            if not count:
                continue
            filled = sum(count.values())
            # 細い部品（剣、指）は weight で面積を底上げし、縮小で消えないようにする
            best = max(count, key=lambda p: (count[p] * parts[p].get("weight", 1.0), p))
            score = count[best] * parts[best].get("weight", 1.0)
            if filled < area * 0.5 and score < area * 0.5:
                continue
            cells[Y][X] = (best, total[best] / count[best])
    return cells


def _noise(x, y):
    """座標で決まる -0.5〜0.5 の揺らぎ。毎回同じ値なので、描き直しても絵が変わらない。"""
    n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 0xFFFF - 0.5


def _mix(a, b, t=0.5):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3)))


def levels(spec, m):
    """素材の (色段, 段の境) を返す。texture の設定で段を足す。

    deep: 最も暗い段の下に、輪郭の色と混ぜた深い影の段を足す。実機の立ち絵は影の奥を
    輪郭に近い暗さまで落としていて、暗いドットが全体の半分を超える。
    expand: 隣の段の中間色を挟んで段を増やす。手打ちのドット絵は素材ごとに5〜7段を持ち
    （実機の立ち絵で1体 28〜40 色）、3〜4段のままだと面が広く平らに残る。
    """
    ramp = list(m["ramp"])
    steps = list(m.get("steps") or [(i + 1) / len(ramp) for i in range(len(ramp) - 1)])
    tex = spec.get("texture", {})
    if tex.get("deep"):
        ramp = [_mix(m["outline"], ramp[0], 0.5)] + ramp
        steps = [(steps[0] if steps else 0.5) * tex["deep"]] + steps
    return ramp, steps


def ramp_of(spec, m):
    """描くときに使う色段。expand では段の間に中間色を挟む（番号 2k が元の段、奇数が中間色）。"""
    ramp, _ = levels(spec, m)
    if not spec.get("texture", {}).get("expand"):
        return ramp
    out = [ramp[0]]
    for a, b in zip(ramp, ramp[1:]):
        out += [_mix(a, b), b]
    return out


def quantize(spec, cells):
    """明るさを素材の色段に落とす。段の境は素材の steps（無ければ等分）。

    texture があれば、明暗の幅を contrast 倍に広げ、座標ごとの揺らぎ（amp）を足してから
    段に落とす。段の境が1ドット単位でほぐれ、面の中に情報量が出る。expand では、境から
    band 以内のドットを中間色にする。
    """
    mats = spec["materials"]
    parts = spec["parts"]
    tex = spec.get("texture", {})
    out = [[None] * len(cells[0]) for _ in cells]
    for y, row in enumerate(cells):
        for x, c in enumerate(row):
            if c is None:
                continue
            p, v = c
            m = mats[parts[p]["material"]]
            _, steps = levels(spec, m)
            amp = m.get("texture", parts[p].get("texture", tex.get("amp", 0.0)))
            # contrast: 影の側を深く落とし、光の側を立てて立体に見せる
            pv = tex.get("pivot", 0.5)
            # 肌は顔の目鼻が乗る面なので、素材の contrast で幅を抑えられるようにする
            v = pv + (v - pv) * m.get("contrast", tex.get("contrast", 1.0)) + amp * _noise(x, y)
            k = sum(1 for t in steps if v >= t)
            if tex.get("expand"):
                band = tex.get("band", 0.05)
                e = 2 * k
                if k < len(steps) and steps[k] - v < band:
                    e += 1
                elif k > 0 and v - steps[k - 1] < band:
                    e -= 1
                k = e
            out[y][x] = (p, k)
    return out


def outline(spec, grid):
    """輪郭は形の外側に1ドット足す。部品の境目は奥の部品側に線を引く。

    純黒の一律の線ではなく素材ごとの最暗色で縁取る（16ビット機のの決まり、styles/diorama.json）。
    外周のドットを塗り替えるのではなく外に足すのは、剣のような2ドット幅の部品が
    輪郭だけになって中身が消えるのを防ぐため。
    境目の線は、手前の部品を浮かせるために奥の部品にだけ引く。同じ素材どうしには引かないが、
    手前の部品に line_same があれば引く（素肌の腕が素肌の胴に溶けるのを防ぐ）。
    """
    parts = spec["parts"]
    mats = spec["materials"]
    H, W = len(grid), len(grid[0])
    colors = [[None] * W for _ in range(H)]
    owner = [[None] * W for _ in range(H)]
    at = lambda x, y: grid[y][x] if 0 <= x < W and 0 <= y < H else None  # noqa: E731
    groups = [p.get("group", p["name"]) for p in parts]
    four = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for y in range(H):
        for x in range(W):
            c = grid[y][x]
            if c is None:
                # 外に足す輪郭: 隣の不透明なドットのうち、いちばん手前の部品の色
                nb = [n for n in (at(x + dx, y + dy) for dx, dy in four) if n is not None]
                nb = [n for n in nb if not parts[n[0]].get("no_outline")]
                if nb:
                    q = max(n[0] for n in nb)
                    colors[y][x] = mats[parts[q]["material"]]["outline"]
                    # 輪郭は接している部品すべてのもの。頭と体の実測で使う
                    owner[y][x] = frozenset(n[0] for n in nb)
                continue
            p, k = c
            m = mats[parts[p]["material"]]
            color = ramp_of(spec, m)[k]
            if parts[p].get("inner_line", True):
                for n in (at(x + dx, y + dy) for dx, dy in four):
                    if n is None:
                        continue
                    q = n[0]
                    if q > p and groups[q] != groups[p] and (parts[q]["material"] != parts[p]["material"] or parts[q].get("line_same")) \
                            and not parts[q].get("no_line_behind"):
                        color = m.get("line", m["outline"])
                        break
            colors[y][x] = color
            owner[y][x] = p
    return colors, owner


def fill_pinholes(colors):
    """上下左右を塞がれた1ドットの透明の穴を、周りで最も暗い色で埋める。

    脚を曲げたコマで、膝の間に背景が1ドットだけ覗いた。形の穴ではなく傷に見えるので埋める。
    """
    H, W = len(colors), len(colors[0])
    filled = 0
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            if colors[y][x] is not None:
                continue
            nb = [colors[y - 1][x], colors[y + 1][x], colors[y][x - 1], colors[y][x + 1]]
            if all(n is not None for n in nb):
                colors[y][x] = min(nb, key=lambda c: sum(hex_to_rgb(c)))
                filled += 1
    return filled


def clean_orphans(colors, protect=(), keep_within=None):
    """周り8方向に同じ色が無いドットを、周りで最も多い色に替える。ノイズに見えるため。

    keep_within を渡すと、周りに明るさの差がその値以下の色があるドットは残す。
    手打ちのドット絵は孤立ドットが2割ほどあり、面の質感はそこで出ている。
    消すのは、周りから明るさが大きく外れた傷のようなドットだけにする。
    """
    H, W = len(colors), len(colors[0])
    changed = 0
    for _ in range(3):
        snap = [row[:] for row in colors]
        n_changed = 0
        for y in range(H):
            for x in range(W):
                c = snap[y][x]
                if c is None or (x, y) in protect:
                    continue
                nb = [snap[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      if (dx or dy) and 0 <= x + dx < W and 0 <= y + dy < H]
                if c in nb:
                    continue
                opaque = [n for n in nb if n is not None]
                if not opaque:
                    continue
                if keep_within is not None and min(_luma_dist(n, c) for n in opaque) <= keep_within:
                    continue
                # 周りの色のうち、明るさが最も近いものを選ぶ。形の明暗を崩さないため
                # 並べてから選ぶ。集合の順番はプロセスごとに変わり、同点のとき描き上がりが揺れる
                best = min(sorted(set(opaque)), key=lambda n: (_luma_dist(n, c), -opaque.count(n)))
                colors[y][x] = best
                n_changed += 1
        changed += n_changed
        if not n_changed:
            break
    return changed


def flatten_crown(colors):
    """頭頂の3ドット幅のこぶを1段下げて平らにする。

    丸い頭頂を縮小すると、いちばん上の2行が3ドット幅になり、こぶのように飛び出す。
    手で打つドット絵は頭頂を平らに切るので、上の行の輪郭を1段下へ移す。
    """
    rows = [y for y, row in enumerate(colors) if any(c is not None for c in row)]
    if len(rows) < 3:
        return 0
    y0 = rows[0]
    run = [x for x, c in enumerate(colors[y0]) if c is not None]
    below = [x for x, c in enumerate(colors[y0 + 1]) if c is not None]
    if len(run) > 3 or len(below) < len(run) + 3:
        return 0
    for x in run:
        colors[y0 + 1][x] = colors[y0][x]
        colors[y0][x] = None
    return len(run)


def _luma_dist(a, b):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return abs((0.2126 * ra[0] + 0.7152 * ra[1] + 0.0722 * ra[2])
               - (0.2126 * rb[0] + 0.7152 * rb[1] + 0.0722 * rb[2]))


def style_max_colors(spec):
    """作風の色数の上限。spec の max_colors、無ければ styles/<style>.json の palette.max_colors。"""
    if "max_colors" in spec:
        return spec["max_colors"]
    path = Path(__file__).resolve().parent.parent / "styles" / f"{spec.get('style', '')}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("palette", {}).get("max_colors")
    return None


def reduce_colors(colors, limit, protect=()):
    """色数が上限を超えたら、使うドットが最も少ない色から、いちばん近い色に寄せる。

    コマによって明るさの段が1つだけ余分に出ることがある（右向きの呼吸で、外套の明るい段が2ドットだけ出た）。
    素材の段を手で削るとほかのコマの陰影まで減るので、そのコマで数ドットの色だけを寄せる。
    """
    merged = 0
    while True:
        count = {}
        for y, row in enumerate(colors):
            for x, c in enumerate(row):
                if c is not None and (x, y) not in protect:
                    count[c] = count.get(c, 0) + 1
        used = {c for row in colors for c in row if c is not None}
        if not limit or len(used) <= limit or len(count) < 2:
            return merged
        rare = min(count, key=lambda c: (count[c], c))
        ra = hex_to_rgb(rare)
        near = min((c for c in used if c != rare),
                   key=lambda c: (sum((a - b) ** 2 for a, b in zip(hex_to_rgb(c), ra)), c))
        # 仕上げのドット（目や眼鏡の光）は、同じ色がほかにあって寄せられても残す。
        # 襟の白と眼鏡の光が同じ色で、右向きの呼吸のコマで光が消えた
        for y, row in enumerate(colors):
            for x, c in enumerate(row):
                if c == rare and (x, y) not in protect:
                    row[x] = near
        merged += 1


def apply_touchups(spec, colors):
    """最後の1ドット単位の仕上げ。色は '#hex' か '素材名:段'（段は ramp の番号か outline）。"""
    mats = spec["materials"]
    done = set()
    for t in spec.get("touchups", []):
        c = t["c"]
        if c is not None and not c.startswith("#"):
            name, k = c.split(":")
            c = mats[name]["outline"] if k == "outline" else mats[name]["ramp"][int(k)]
        for x, y in t["at"]:
            # 作風の変換で絵の外へ出た仕上げは置かない（負の添字で反対側に描かれるのも防ぐ）
            if not (0 <= y < len(colors) and 0 <= x < len(colors[0])):
                continue
            colors[y][x] = c
            done.add((x, y))
    return done


def measure(spec, colors, owner):
    """頭の高さと体の芯の枠を、描き上がったドットから数える（輪郭を含む）。

    手で書いた数字は形を直すたびにずれる。check.py の頭身と大きさの判定を
    実物に対して行うため、ここで数える。頭は head: true の部品、体の芯は
    prop: true（武器、外套など、はみ出してよいもの）を除いた部品。
    """
    parts = spec["parts"]
    head_rows, xs, ys = set(), [], []
    for y, row in enumerate(owner):
        for x, p in enumerate(row):
            if p is None or colors[y][x] is None:
                continue
            ps = p if isinstance(p, frozenset) else (p,)
            if any(parts[q].get("head") for q in ps):
                head_rows.add(y)
            if not all(parts[q].get("prop") for q in ps):
                xs.append(x)
                ys.append(y)
    head = (max(head_rows) - min(head_rows) + 1) if head_rows else spec.get("head_height")
    box = [min(xs), min(ys), max(xs) + 1, max(ys) + 1] if xs else spec.get("body_box")
    return head, box


def to_sprite(spec, colors, owner=None):
    """sprite.json の形（記号の格子とパレット）にする。記号は色の明るさ順に振る。"""
    used = sorted({c for row in colors for c in row if c}, key=lambda c: hex_to_rgb(c))
    symbols = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    if len(used) > len(symbols):
        raise ValueError(f"色が多すぎる: {len(used)}")
    sym = {c: symbols[i] for i, c in enumerate(used)}
    head, box = measure(spec, colors, owner) if owner else (spec.get("head_height"), spec.get("body_box"))
    rows = ["".join(sym[c] if c else "." for c in row) for row in colors]
    return {
        "name": spec["name"],
        "style": spec["style"],
        "brief": spec.get("brief", ""),
        "generated_from": "parts.json（tools/build.py が書き出す。手で直さない）",
        **({"frame": spec["frame"]} if spec.get("frame") else {}),
        "head_height": head,
        "body_box": box,
        "palette": {sym[c]: c for c in used},
        "rows": rows,
        # 仕上げで意図して置いた1ドット（目、鼻、口）。check.py の孤立ドットの数から除く
        "intended": [list(p) for p in sorted({(x, y) for t in spec.get("touchups", []) for x, y in t["at"]
                                              if 0 <= y < len(colors) and 0 <= x < len(colors[0]) and colors[y][x]})],
    }


def apply_transforms(spec):
    """部品を拡大縮小する。体格の枠（子供など）を、既存の職業から作るため。

    transforms: [{parts: "*" か名前の並び, scale: [sx, sy], origin: [x, y], touchups: true/false}]
    上から順にかける。子供は全体を縮めてから、頭だけを少し戻す（頭の比率が大きくなる）。
    touchups: true の規則は、目や鼻の仕上げのドットも同じ位置へ動かす。
    """
    rules = spec.get("transforms")
    if not rules:
        return spec
    spec = copy.deepcopy(spec)
    for rule in rules:
        sx, sy = rule["scale"]
        ox, oy = rule["origin"]
        pick = rule.get("parts", "*")
        if pick == "head":
            # 頭の部品（head: true）と、頭と一緒に動く髪。作風ごとの変換で名前を並べずに済むように
            pick = [p["name"] for p in spec["parts"] if p.get("head") or p["name"] in ("hair_back", "neck")]
        tx = lambda x: ox + (x - ox) * sx  # noqa: E731
        ty = lambda y: oy + (y - oy) * sy  # noqa: E731
        for part in spec["parts"]:
            if pick != "*" and part["name"] not in pick:
                continue
            for key in ("shapes", "cut"):
                for sh in part.get(key, []):
                    if "points" in sh:
                        sh["points"] = [[tx(x), ty(y)] for x, y in sh["points"]]
                    if "r" in sh:
                        sh["r"] = sh["r"] * (sx + sy) / 2
                    if sh["type"] == "ellipse":
                        cx, cy, rx, ry = sh["at"]
                        sh["at"] = [tx(cx), ty(cy), rx * sx, ry * sy]
                    elif sh["type"] == "rect":
                        x0, y0, x1, y1 = sh["at"]
                        sh["at"] = [tx(x0), ty(y0), tx(x1), ty(y1)]
        if rule.get("touchups"):
            # 仕上げのドットは描き上がりの格子の座標（shift 込み）なので、形の座標に戻してから動かす
            hx, hy = spec.get("shift", (0, 0))
            for t in spec.get("touchups", []):
                t["at"] = [[int(tx(x + 0.5 - hx) + hx), int(ty(y + 0.5 - hy) + hy)] for x, y in t["at"]]
    return spec


def build(spec):
    spec = apply_transforms(spec)
    top, light, size = render_hi(spec)
    cells = downscale(spec, top, light, size)
    grid = quantize(spec, cells)
    colors, owner = outline(spec, grid)
    fill_pinholes(colors)
    protect = {tuple(p) for t in spec.get("touchups", []) for p in t["at"]}
    keep = spec.get("texture", {}).get("keep_orphans_within")
    clean_orphans(colors, protect, keep)
    apply_touchups(spec, colors)
    # 仕上げのドットを置くと、隣の地のドットが孤立することがある（眼鏡の横で起きた）。もう一度掃除する
    clean_orphans(colors, protect, keep)
    if spec.get("flatten_crown"):
        flatten_crown(colors)
    reduce_colors(colors, style_max_colors(spec), protect)
    return to_sprite(spec, colors, owner), (top, light, size)


def frame_spec(spec, frame):
    """動きの1コマ分の spec を作る。

    dy: 呼吸。部品ごとの breathe（0〜1）に掛けた量だけ下げる。頭と肩は 1、胴は 0.5、脚は 0
    override: {部品名: {変える項目}}。そのコマだけ部品を差し替える（構えの違い）
    mirror: 右向き。形だけを左右反転し、光は左上のまま描き直す。move の横の動きも逆にする
    （spec に mirror_frames: true があれば、左向きの全コマから right-<名前> のコマを作る）
    move: {部品名: {offset: [dx, dy], points: [[dx, dy], ...]}}。脚の前後のように、
          部品ごとに動かす。points は最初の形の点を1つずつずらす。無い部品は飛ばす
          （職業によって脚が法衣に隠れているため）
    body_dy: move に書いていない部品を丸ごと上下させる。歩きの上下動
    高い解像度で動かしてから縮小するので、0.5 ドットの動きも陰影の変化として出る。
    touchups（目や鼻）は頭と一緒に動く。動かさないものは touchup に breathe: 0 を書く。
    """
    out = copy.deepcopy(spec)
    for name, fields in frame.get("override", {}).items():
        # コマだけの構えの差し替え（歩くときは剣を立てて持つ、など）。左向きの座標で書く
        for part in out["parts"]:
            if part["name"] == name:
                part.update(copy.deepcopy(fields))
    mirror = frame.get("mirror")
    if mirror:
        _mirror(out)
    dy = frame.get("dy", 0)
    body = frame.get("body_dy", 0)
    move = frame.get("move", {})
    if mirror:
        # 左向きで書いた動きを右向きに使う。横の動きだけ向きを逆にする
        move = {n: {k: ([-v[0], v[1]] if k == "offset" else [[-x, y] for x, y in v]) for k, v in m.items()}
                for n, m in move.items()}
    for part in out["parts"]:
        ox, oy = part.get("offset", (0, 0))
        oy += part.get("breathe", 0) * dy
        m = move.get(part["name"])
        if m is None:
            oy += body
        else:
            mx, my = m.get("offset", (0, 0))
            ox, oy = ox + mx, oy + my
            if "points" in m:
                pts = part["shapes"][0]["points"]
                for i, (px, py) in enumerate(m["points"][:len(pts)]):
                    pts[i] = [pts[i][0] + px, pts[i][1] + py]
        part["offset"] = [ox, oy]
    for t in out.get("touchups", []):
        k = round(t.get("breathe", 1) * dy + body)
        t["at"] = [[x, y + k] for x, y in t["at"]]
    return out


def _mirror(spec):
    """形を左右反転する。光（左上）はそのまま。

    絵を反転すると光まで右上から当たることになり、同じ場面で向きによって陰影が逆になる。
    形だけを反転して描き直せば、どちら向きでも光は左上から当たる。
    """
    W = spec["canvas"][0]
    sx, sy = spec.get("shift", (0, 0))
    spec["shift"] = [-sx, sy]
    for part in spec["parts"]:
        for key in ("shapes", "cut"):
            for sh in part.get(key, []):
                if "points" in sh:
                    if sh["type"] == "pixline":
                        # ドット単位の線は、ドットの中心で折り返す
                        sh["points"] = [[W - 1 - x, y] for x, y in sh["points"]]
                    else:
                        sh["points"] = [[W - x, y] for x, y in sh["points"]]
                if sh["type"] == "ellipse":
                    cx, cy, rx, ry = sh["at"]
                    sh["at"] = [W - cx, cy, rx, ry]
                elif sh["type"] == "rect":
                    x0, y0, x1, y1 = sh["at"]
                    sh["at"] = [W - x1, y0, W - x0, y1]
        if "offset" in part:
            part["offset"] = [-part["offset"][0], part["offset"][1]]
        if "strands" in part:
            part["strands"] = dict(part["strands"], angle=180 - part["strands"].get("angle", 0))
    for t in spec.get("touchups", []):
        t["at"] = [[W - 1 - x, y] for x, y in t["at"]]
    for rule in spec.get("transforms", []):
        rule["origin"] = [W - rule["origin"][0], rule["origin"][1]]


def build_frames(spec):
    """基本のコマと、frames に書いたコマをすべて描く。{名前: sprite}。基本は名前 ''。"""
    frames = list(spec.get("frames", []))
    if spec.get("mirror_frames"):
        # 左向きの各コマから右向きのコマを作る（right-idle-2、right-walk-1 など）
        frames += [dict(f, name=f"right-{f['name']}", mirror=True) for f in frames if not f.get("mirror")]
    out = {"": build(spec)[0]}
    for frame in frames:
        out[frame["name"]] = build(frame_spec(spec, frame))[0]
    return out


def sprite_path(parts_path, name):
    """基本は sprite.json、ほかのコマは sprite.<名前>.json。check.py と render.py はどれも読める。"""
    parts_path = Path(parts_path)
    return parts_path.with_name(f"sprite.{name}.json" if name else "sprite.json")


def preview_hi(spec, top, light, size):
    """縮小前の高解像度の絵。光の当たり方を縮小の前に確かめるため。"""
    parts, mats = spec["parts"], spec["materials"]
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    px = img.load()
    w = size[0]
    for i, p in enumerate(top):
        if p < 0:
            continue
        ramp = [hex_to_rgb(c) for c in mats[parts[p]["material"]]["ramp"]]
        v = max(0.0, min(0.999, light[i])) * (len(ramp) - 1)
        a, t = int(v), v - int(v)
        c0, c1 = ramp[a], ramp[min(a + 1, len(ramp) - 1)]
        px[i % w, i // w] = tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3)) + (255,)
    return img


def load_spec(path):
    """parts.json を読む。base があれば、その上に差し替えを重ねる。

    職業ごとに頭や体格を一から書き直さずに済むようにするため。差し替えの書き方:
      base: 元にする parts.json（このファイルからの相対パス）
      remove: 取り除く部品の名前
      override: {名前: {変える項目}}  項目ごとに置き換える
      add: [部品]  部品に after か before（名前）があればその隣、無ければ一番手前
      materials: 素材ごとに置き換える
    それ以外の項目（name、canvas、touchups など）は丸ごと置き換える。
    """
    path = Path(path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    base = spec.pop("base", None)
    if not base:
        return spec
    return merge_spec(load_spec(path.parent / base), spec)


def merge_spec(base, child):
    out = copy.deepcopy(base)
    parts = out["parts"]
    names = lambda: [p["name"] for p in parts]  # noqa: E731
    for name in child.get("remove", []):
        if name not in names():
            raise ValueError(f"remove: 無い部品 {name}")
        parts.pop(names().index(name))
    for name, fields in child.get("override", {}).items():
        if name not in names():
            raise ValueError(f"override: 無い部品 {name}")
        parts[names().index(name)].update(copy.deepcopy(fields))
    for part in child.get("add", []):
        part = copy.deepcopy(part)
        after, before = part.pop("after", None), part.pop("before", None)
        if part["name"] in names():
            raise ValueError(f"add: 同じ名前の部品が既にある {part['name']}")
        if after:
            parts.insert(names().index(after) + 1, part)
        elif before:
            parts.insert(names().index(before), part)
        else:
            parts.append(part)
    out["materials"].update(copy.deepcopy(child.get("materials", {})))
    for k, v in child.items():
        if k not in ("remove", "override", "add", "materials"):
            out[k] = copy.deepcopy(v)
    return out


def restyle(spec, style_id):
    """箱庭ドット 用の spec を、別の作風（styles/<id>.json の render）で描く spec にする。

    同じ部品を作風ごとに描き分けるため。キャラクターの transforms の後に作風の transforms をかける。
    動きのコマは持ち越さない（作風ごとに動きの決まりが違うため、要るときに作風側で書く）。
    """
    style = json.loads((Path(__file__).resolve().parent.parent / "styles" / f"{style_id}.json").read_text(encoding="utf-8"))
    render = style["render"]
    out = copy.deepcopy(spec)
    out["style"] = style_id
    out["canvas"] = render["canvas"]
    ox, oy = spec.get("shift", (0, 0))
    out["shift"] = render["shift"]
    dx, dy = render["shift"][0] - ox, render["shift"][1] - oy
    for t in out.get("touchups", []):
        t["at"] = [[x + dx, y + dy] for x, y in t["at"]]
    out["transforms"] = spec.get("transforms", []) + copy.deepcopy(render["transforms"])
    out["frames"] = []
    out["mirror_frames"] = False
    # 面の質感（texture）は作風のもの。平らな塗りの作風に持ち越さない
    out.pop("texture", None)
    if "texture" in render:
        out["texture"] = copy.deepcopy(render["texture"])
    return out


def style_path(parts_path, style_id):
    return Path(parts_path).parent / style_id / "sprite.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts")
    ap.add_argument("--preview", help="高解像度の途中の絵を置くフォルダ")
    ap.add_argument("--style", help="別の作風で描く（styles/<id>.json の render）。書き出しは <キャラ>/<id>/sprite.json")
    args = ap.parse_args()
    src = Path(args.parts)
    spec = load_spec(src)
    if args.style:
        sprite = build(restyle(spec, args.style))[0]
        dst = style_path(src, args.style)
        dst.parent.mkdir(exist_ok=True)
        dst.write_text(json.dumps(sprite, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{dst}: {len(sprite['rows'][0])}x{len(sprite['rows'])}, {len(sprite['palette'])} 色")
        return
    _, (top, light, size) = build(spec)
    for name, sprite in build_frames(spec).items():
        dst = sprite_path(src, name)
        dst.write_text(json.dumps(sprite, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{dst}: {len(sprite['rows'][0])}x{len(sprite['rows'])}, {len(sprite['palette'])} 色")
    if args.preview:
        out = Path(args.preview)
        out.mkdir(parents=True, exist_ok=True)
        preview_hi(spec, top, light, size).save(out / f"{src.parent.name}_hi.png")


if __name__ == "__main__":
    sys.exit(main())
