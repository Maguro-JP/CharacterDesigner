"""スプライトを作風の決まり（styles/*.json）と突き合わせて、数えられるものを数える。

目で見る検品の前に機械で落とす。色数・大きさ・純黒の輪郭・孤立ドットは、
見た目の印象で「たぶん大丈夫」と流しやすく、しかも数えれば確実に分かるから。

使い方: python3 tools/check.py characters/<name>/sprite.json styles/<style>.json
終了コード: 全部通れば 0、1つでも外れれば 1
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402


def luma(rgb):
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main():
    data, rows, width, palette = sprite.load(sys.argv[1])
    style = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    h = len(rows)
    grid = [row.ljust(width, ".") for row in rows]
    at = lambda x, y: grid[y][x] if 0 <= x < width and 0 <= y < h else "."  # noqa: E731

    results = []

    def judge(name, ok, detail):
        results.append((ok, name, detail))

    # 大きさ（体の芯）: 武器などのはみ出しは body_box で除けるようにする
    bx = data.get("body_box", [0, 0, width, h])
    bw, bh = bx[2] - bx[0], bx[3] - bx[1]
    wr, hr = style["canvas"]["width_range"], style["canvas"]["height_range"]
    # 体格の枠（子供など）は作風の決まりに別の範囲がある
    frame = style["canvas"].get("frames", {}).get(data.get("frame", ""))
    if frame:
        wr, hr = frame["width_range"], frame["height_range"]
    judge("体の大きさ" + (f"（{data['frame']}）" if frame else ""), wr[0] <= bw <= wr[1] and hr[0] <= bh <= hr[1],
          f"{bw}x{bh}（幅 {wr}、高さ {hr}）")

    # 頭身
    head = data.get("head_height")
    if head:
        heads = bh / head
        pr = style["proportion"]["heads_tall"]
        judge("頭身", pr[0] <= heads <= pr[1], f"{heads:.2f}（頭 {head}px、範囲 {pr}）")

    # 色数（実際に使っている色）
    used = {c for r in grid for c in r if c != "."}
    mc = style["palette"]["max_colors"]
    judge("色数", len(used) <= mc, f"{len(used)} 色（上限 {mc}）")
    unused = set(palette) - used
    if unused:
        judge("使っていない記号", False, f"{sorted(unused)}")

    # 輪郭: 透明に接する外周のドット
    edge = [(x, y) for y in range(h) for x in range(width) if at(x, y) != "."
            and any(at(x + dx, y + dy) == "." for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    black = [p for p in edge if palette[at(*p)] == (0, 0, 0)]
    if not style["outline"]["pure_black_allowed"]:
        judge("純黒の輪郭", not black, f"{len(black)} ドット")
    lim = style["outline"]["max_outline_luma"]
    bright = [p for p in edge if luma(palette[at(*p)]) > lim]
    ratio = len(bright) / max(1, len(edge))
    # 光の当たる縁は明るくてよい。ただし外周の3割を超えると輪郭が溶ける
    judge("輪郭の締まり", ratio <= 0.3, f"外周 {len(edge)} のうち明るい縁 {len(bright)}（{ratio:.0%}、上限 30%）")

    # 孤立ドット: 上下左右斜めに同じ色が無い
    orphans = []
    # 目や口のように意図して置いた1ドットは、ノイズではないので数えない（build.py が intended に書く）
    intended = {tuple(p) for p in data.get("intended", [])}
    for y in range(h):
        for x in range(width):
            c = at(x, y)
            if c == "." or (x, y) in intended:
                continue
            if not any(at(x + dx, y + dy) == c for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy):
                orphans.append((x, y))
    mo = style["cleanup"]["max_orphan_pixels"]
    judge("孤立ドット", len(orphans) <= mo, f"{len(orphans)}（上限 {mo}）{orphans[:8]}")

    for ok, name, detail in results:
        print(f"{'OK ' if ok else 'NG '} {name}: {detail}")
    bad = sum(1 for ok, *_ in results if not ok)
    print(f"-- {len(results) - bad}/{len(results)} 通過")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
