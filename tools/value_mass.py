"""ドット絵の明暗の塊を数え、小さな破片を周りの塊の明るさにそろえる。

箱庭ドットの決まり（styles/diorama.json）は、実機に合わせて孤立ドットを約2割、隣と色が変わる割合を高く求める。
点を散らしてそれを満たすと、明暗の塊が割れて、顔・剣・盾・脚が読めなくなった（docs/knowledge/learning/hd2d-warrior.md）。
質感の点は「明るさは周りと同じで、色みだけ違う点」にすれば、ざらつきを残したまま明暗の塊を保てる、という見立てで作った。

  python3 tools/value_mass.py measure SPRITE.json [...]     明・中・暗の3段での塊の数と、3ドット以下の破片の割合
  python3 tools/value_mass.py fix SPRITE.json OUT.json      破片の色を、周りの段の色のうち元の色みに一番近い色へ置き換える
  python3 tools/value_mass.py texture SPRITE.json OUT.json [--rate 0.3]   塊の内側に、明るさが同じで色みだけ違う点を散らす
"""
from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402

SMALL = 3   # この画素数以下の塊を破片とみなす


def _luma(rgb):
    r, g, b = (v / 255 for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def levels(grid, palette):
    """人物の画素を明るさで3等分した段（0 暗・1 中・2 明）。透明は -1"""
    lum = {c: _luma(rgb) for c, rgb in palette.items()}
    vals = sorted(lum[c] for row in grid for c in row if c != ".")
    if not vals:
        return [], (0, 0), lum
    t = (vals[len(vals) // 3], vals[2 * len(vals) // 3])
    lv = [[-1 if c == "." else (0 if lum[c] < t[0] else 1 if lum[c] < t[1] else 2) for c in row] for row in grid]
    return lv, t, lum


def components(lv):
    h, w = len(lv), len(lv[0]) if lv else 0
    seen, comps = set(), []
    for y in range(h):
        for x in range(w):
            if lv[y][x] < 0 or (x, y) in seen:
                continue
            st, cells = [(x, y)], []
            seen.add((x, y))
            while st:
                cx, cy = st.pop()
                cells.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and lv[ny][nx] == lv[cy][cx]:
                        seen.add((nx, ny))
                        st.append((nx, ny))
            comps.append(cells)
    return comps


def measure_grid(grid, palette) -> dict:
    lv, _, _ = levels(grid, palette)
    comps = components(lv)
    total = sum(len(c) for c in comps) or 1
    small = sum(len(c) for c in comps if len(c) <= SMALL)
    return {"masses": len(comps), "fragment_ratio": round(small / total, 3), "pixels": total}


def fix_grid(grid, palette, intended=()) -> tuple[list[str], int]:
    """破片の画素を、隣で一番多い段の色のうち、元の色の色相に一番近い色へ置き換える。
    意図して置いた1ドット（目や口、build.py の intended）は触らない"""
    lv, _, lum = levels(grid, palette)
    keep = {tuple(p) for p in intended}
    t = levels(grid, palette)[1]
    band = {c: (0 if lum[c] < t[0] else 1 if lum[c] < t[1] else 2) for c in palette}
    hue = {c: colorsys.rgb_to_hsv(*(v / 255 for v in rgb)) for c, rgb in palette.items()}
    out = [list(r) for r in grid]
    h, w = len(grid), len(grid[0])
    changed = 0
    for cells in components(lv):
        if len(cells) > SMALL:
            continue
        for x, y in cells:
            if (x, y) in keep:
                continue
            around = [lv[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      if (dx or dy) and 0 <= y + dy < h and 0 <= x + dx < w and lv[y + dy][x + dx] >= 0]
            if not around:
                continue
            target = max(set(around), key=around.count)
            if target == lv[y][x]:
                continue
            c = grid[y][x]
            cands = [k for k in palette if band[k] == target]
            if not cands:
                continue
            hh, ss, _ = hue[c]
            best = min(cands, key=lambda k: min(abs(hue[k][0] - hh), 1 - abs(hue[k][0] - hh)) + abs(hue[k][1] - ss) * 0.5)
            out[y][x] = best
            changed += 1
    return ["".join(r) for r in out], changed


def _same_luma_variant(rgb, shift, boost=True):
    """色相を shift（0〜1）だけ回し、明るさ（luma）を元にそろえた色。boost で彩度を少し足す（灰色を温・寒に振るため）"""
    h, sat, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    target = _luma(rgb)
    sat2 = min(1.0, sat * 1.15 + 0.04) if boost else sat
    best = None
    for k in range(101):          # 明るさがそろう v を探す
        v2 = k / 100
        r, g, b = colorsys.hsv_to_rgb((h + shift) % 1, sat2, v2)
        d = abs(_luma((r * 255, g * 255, b * 255)) - target)
        if best is None or d < best[0]:
            best = (d, (round(r * 255), round(g * 255), round(b * 255)))
    return best[1]


def texture_grid(grid, palette, rate=0.3, intended=()) -> tuple[list[str], dict]:
    """塊の内側（上下左右が同じ色の画素）に、明るさが同じで色みだけ違う点を、決まった並びで散らす。
    塊の縁には置かないので形の輪郭は崩れない。明暗の塊も変わらない（同じ明るさの色に替えるため）。
    灰色（彩度が低い色）は色相を回しても変わらないので、彩度を少し足して温かみと冷たさで振る"""
    keep = {tuple(p) for p in intended}
    lv, _, _ = levels(grid, palette)
    free = [ch for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&*+=?@" if ch not in palette and ch != "."]
    pal = dict(palette)
    variant = {}
    h, w = len(grid), len(grid[0])
    out = [list(r) for r in grid]
    for y in range(h):
        for x in range(w):
            c = grid[y][x]
            if c == "." or (x, y) in keep:
                continue
            # 彩度の高い色（赤い布など）には置かない。色みをずらした点が質感でなく汚れに見えた（周2）
            # 彩度の高い色（赤い布 0.62〜0.68）は、色みのずれを半分にする。0.03 ずらすと汚れに見え（周2）、
            # 置かないと盾を広げたとき点が足りず検査が落ちた（周5）
            vivid = colorsys.rgb_to_hsv(*(v / 255 for v in palette[c]))[1] > 0.6
            # 塊の内側: 人物の輪郭ではなく、上下左右が同じ明るさの段。同じ色に限ると、平らな面の少ない手打ちの絵では置き場が足りなかった
            if not all(0 <= y + dy < h and 0 <= x + dx < w and lv[y + dy][x + dx] == lv[y][x] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                continue
            # 選ぶ画素は (x + 2y) を 4 で割った余りが 0 の所。上下左右にも斜めにも隣り合わないので、置いた点は孤立する
            # （ハッシュで選ぶと斜めに並び、孤立ドットの数が増えなかった。5 で割る並びは、赤い布を外すと点が足りなかった）。
            # rate は 0.25 を上限に、間引いて下げる
            if (x + 2 * y) % 4 or ((x * 7 + y * 13) % 100) >= rate * 400:
                continue
            warm = ((x // 5) + y) % 2 == 0          # 暖かい側と冷たい側を交互に置く（1色につき2つの色）
            key = (c, warm)
            if key not in variant:
                if not free:
                    continue
                k = free.pop(0)
                variant[key] = k
                step = 0.015 if vivid else 0.03
                pal[k] = _same_luma_variant(palette[c], step if warm else -step, boost=not vivid)
            out[y][x] = variant[key]
    return ["".join(r) for r in out], pal


def main():
    cmd = sys.argv[1]
    if cmd == "measure":
        for p in sys.argv[2:]:
            data, rows, width, palette = sprite.load(p)
            grid = [r.ljust(width, ".") for r in rows]
            print(p, json.dumps(measure_grid(grid, palette), ensure_ascii=False))
    elif cmd == "fix":
        src, out = sys.argv[2], sys.argv[3]
        data, rows, width, palette = sprite.load(src)
        grid = [r.ljust(width, ".") for r in rows]
        before = measure_grid(grid, palette)
        new, changed = fix_grid(grid, palette, data.get("intended", []))
        raw = json.loads(Path(src).read_text(encoding="utf-8"))
        raw["rows"] = new
        # 置き換えで使われなくなった色はパレットから外す（残すと検査の「使っていない記号」で落ちる）
        used = {c for r in new for c in r}
        raw["palette"] = {k: v for k, v in raw["palette"].items() if k in used}
        Path(out).write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"changed": changed, "before": before, "after": measure_grid(new, palette)}, ensure_ascii=False))
    elif cmd == "texture":
        src, out = sys.argv[2], sys.argv[3]
        rate = float(sys.argv[sys.argv.index("--rate") + 1]) if "--rate" in sys.argv else 0.3
        data, rows, width, palette = sprite.load(src)
        grid = [r.ljust(width, ".") for r in rows]
        new, pal = texture_grid(grid, palette, rate, data.get("intended", []))
        raw = json.loads(Path(src).read_text(encoding="utf-8"))
        raw["rows"] = new
        raw["palette"] = {k: "#%02x%02x%02x" % tuple(v) for k, v in pal.items() if any(k in r for r in new)}
        Path(out).write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"before": measure_grid(grid, palette), "after": measure_grid(new, pal),
                          "colors": len(raw["palette"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
