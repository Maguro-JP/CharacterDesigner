"""検品を通った動物の絵を、画風ごとの図鑑（一覧図）にまとめる。

使い方:
  python3 tools/gen/zukan.py <animal_cycle の出力フォルダ> [docs/zukan]

<出力>/<日付>/<動物>/<番号-画風>-<種>.png のうち、隣に .pass がある絵だけを使う。
画風ごとに1枚の一覧図（docs/zukan/<番号-画風>.jpg）と、目次（docs/zukan/README.md）を書く。
縮小した JPEG だけを残すのは、リポジトリを重くしないため（元の絵は手元に残る）。
"""
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

THUMB = (288, 192)
COLS = 4


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/zukan")
    out.mkdir(parents=True, exist_ok=True)
    book = defaultdict(list)
    for p in sorted(src.glob("[0-9]*/*/*.png")):
        if p.with_name(p.name + ".pass").exists():
            # 名前は <番号-画風>-<種>.png。種を外した部分を画風とする
            book[p.stem.rsplit("-", 1)[0]].append((p.parent.name, p))
    lines = ["# 動物図鑑", "", "検品を通った絵だけを、画風ごとにまとめた一覧。番号は簡単な画風から本格的な画風への順。", ""]
    for style in sorted(book):
        items = book[style]
        rows = (len(items) + COLS - 1) // COLS
        sheet = Image.new("RGB", (THUMB[0] * COLS, (THUMB[1] + 20) * rows), "white")
        d = ImageDraw.Draw(sheet)
        for i, (name, p) in enumerate(items):
            im = Image.open(p).convert("RGB")
            im.thumbnail(THUMB)
            x, y = (i % COLS) * THUMB[0], (i // COLS) * (THUMB[1] + 20)
            sheet.paste(im, (x, y))
            d.text((x + 4, y + THUMB[1] + 4), name, fill="black")
        sheet.save(out / f"{style}.jpg", quality=85)
        lines += [f"## {style}（{len(items)} 種）", "", f"![{style} の動物の一覧]({style}.jpg)", "",
                  ", ".join(n for n, _ in items), ""]
    (out / "README.md").write_text("\n".join(lines))
    print({k: len(v) for k, v in sorted(book.items())})


if __name__ == "__main__":
    main()
