"""ドット絵の明暗の塊を数え、小さな破片を周りの塊の明るさにそろえる。

箱庭ドットの決まり（styles/diorama.json）は、実機に合わせて孤立ドットを約2割、隣と色が変わる割合を高く求める。
点を散らしてそれを満たすと、明暗の塊が割れて、顔・剣・盾・脚が読めなくなった（docs/knowledge/learning/hd2d-warrior.md）。
質感の点は「明るさは周りと同じで、色みだけ違う点」にすれば、ざらつきを残したまま明暗の塊を保てる、という見立てで作った。

  python3 tools/value_mass.py measure SPRITE.json [...]     明・中・暗の3段での塊の数と、3ドット以下の破片の割合
  python3 tools/value_mass.py fix SPRITE.json OUT.json      破片の色を、周りの段の色のうち元の色みに一番近い色へ置き換える
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


if __name__ == "__main__":
    main()
