"""部品で組んだキャラクター（parts.json）を、光を当てて高い解像度で描き、ドット絵に落とす。

1ドットずつ文字で打つ描き方は、陰影の密度で頭打ちになる。そこで形は部品（楕円、多角形、
太さのある線）で組み、光で陰影を付けてから、縮小・減色・輪郭付け・孤立ドットの掃除で
ドットにする。最後だけ touchups で1ドット単位に直す。オクトパストラベラーが 3D の
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

# 光は左上・手前から。styles/hd2d.json の light.direction に合わせている
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
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if mdata[i] < 128:
                continue
            hx = (height[i + 1] if x + 1 < w else 0) - (height[i - 1] if x > 0 else 0)
            hy = (height[i + w] if y + 1 < h else 0) - (height[i - w] if y > 0 else 0)
            n = _norm((-hx * relief, -hy * relief, 1.0))
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
        mask = part_mask(part, size, spec.get("shift", (0, 0)))
        sh = shade_part(part, mask, mats[part["material"]])
        md = _data(mask)
        for i, m in enumerate(md):
            if m >= 128:
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


def quantize(spec, cells):
    """明るさを素材の色段に落とす。段の境は素材の steps（無ければ等分）。"""
    mats = spec["materials"]
    parts = spec["parts"]
    out = [[None] * len(cells[0]) for _ in cells]
    for y, row in enumerate(cells):
        for x, c in enumerate(row):
            if c is None:
                continue
            p, v = c
            m = mats[parts[p]["material"]]
            ramp = m["ramp"]
            steps = m.get("steps") or [(i + 1) / len(ramp) for i in range(len(ramp) - 1)]
            k = sum(1 for t in steps if v >= t)
            out[y][x] = (p, k)
    return out


def outline(spec, grid):
    """輪郭は形の外側に1ドット足す。部品の境目は奥の部品側に線を引く。

    純黒の一律の線ではなく素材ごとの最暗色で縁取る（FF6 系の決まり、styles/hd2d.json）。
    外周のドットを塗り替えるのではなく外に足すのは、剣のような2ドット幅の部品が
    輪郭だけになって中身が消えるのを防ぐため。
    境目の線は、手前の部品を浮かせるために奥の部品にだけ引く。
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
            color = m["ramp"][k]
            if parts[p].get("inner_line", True):
                for n in (at(x + dx, y + dy) for dx, dy in four):
                    if n is None:
                        continue
                    q = n[0]
                    if q > p and groups[q] != groups[p] and parts[q]["material"] != parts[p]["material"] \
                            and not parts[q].get("no_line_behind"):
                        color = m.get("line", m["outline"])
                        break
            colors[y][x] = color
            owner[y][x] = p
    return colors, owner


def clean_orphans(colors, protect=()):
    """周り8方向に同じ色が無いドットを、周りで最も多い色に替える。ノイズに見えるため。"""
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
                # 周りの色のうち、明るさが最も近いものを選ぶ。形の明暗を崩さないため
                best = min(set(opaque), key=lambda n: (_luma_dist(n, c), -opaque.count(n)))
                colors[y][x] = best
                n_changed += 1
        changed += n_changed
        if not n_changed:
            break
    return changed


def _luma_dist(a, b):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return abs((0.2126 * ra[0] + 0.7152 * ra[1] + 0.0722 * ra[2])
               - (0.2126 * rb[0] + 0.7152 * rb[1] + 0.0722 * rb[2]))


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
        "head_height": head,
        "body_box": box,
        "palette": {sym[c]: c for c in used},
        "rows": rows,
    }


def build(spec):
    top, light, size = render_hi(spec)
    cells = downscale(spec, top, light, size)
    grid = quantize(spec, cells)
    colors, owner = outline(spec, grid)
    protect = {tuple(p) for t in spec.get("touchups", []) for p in t["at"]}
    clean_orphans(colors, protect)
    apply_touchups(spec, colors)
    return to_sprite(spec, colors, owner), (top, light, size)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts")
    ap.add_argument("--preview", help="高解像度の途中の絵を置くフォルダ")
    args = ap.parse_args()
    src = Path(args.parts)
    spec = load_spec(src)
    sprite, (top, light, size) = build(spec)
    dst = src.with_name("sprite.json")
    dst.write_text(json.dumps(sprite, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{dst}: {len(sprite['rows'][0])}x{len(sprite['rows'])}, {len(sprite['palette'])} 色")
    if args.preview:
        out = Path(args.preview)
        out.mkdir(parents=True, exist_ok=True)
        preview_hi(spec, top, light, size).save(out / f"{src.parent.name}_hi.png")


if __name__ == "__main__":
    sys.exit(main())
