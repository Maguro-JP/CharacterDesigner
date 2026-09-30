"""手本の画像と自分のスプライトを、同じ倍率で横に並べる。

手本を見ずに自分の前の版とだけ比べると、手本から離れていっても気付かない。
描き直すたびに、手本の同じ部位（頭、手、足）を切り出して横に並べて見る。
手本の画像はリポジトリに置かない（著作物のため）。置き場所を毎回引数で渡す。

使い方:
  python3 tools/vsref.py out.png ref=<手本.png>@x0,y0,x1,y1 me=<sprite.json>@x0,y0,x1,y1 [...]
  文字で1ドットずつ読むとき: python3 tools/vsref.py --dump <手本.png>@x0,y0,x1,y1
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402

SCALE = 16


def load(kind, path, box):
    if kind == "ref":
        im = Image.open(path).convert("RGBA").crop(box)
    else:
        _, rows, width, palette = sprite.load(path)
        im = sprite.to_image(rows, width, palette).crop(box)
    bg = Image.new("RGBA", im.size, (170, 176, 186, 255))
    bg.alpha_composite(im)
    return bg


def parse(arg):
    kind, rest = arg.split("=", 1)
    path, box = rest.rsplit("@", 1)
    return kind, path, tuple(int(v) for v in box.split(","))


def dump(path, box):
    """色に番号を振って1ドットずつ文字で出す。目の組み方のような1ドットの置き方を読むため。"""
    im = Image.open(path).convert("RGBA").crop(box)
    px = im.load()
    pal = {}
    for y in range(im.height):
        line = ""
        for x in range(im.width):
            c = px[x, y]
            if c[3] < 128:
                line += " ."
                continue
            pal.setdefault(c[:3], len(pal))
            line += "%2d" % pal[c[:3]]
        print("%2d %s" % (y, line))
    for rgb, n in pal.items():
        luma = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
        print("%2d #%02x%02x%02x 明るさ %d" % (n, *rgb, luma))


def main():
    if sys.argv[1] == "--dump":
        path, box = sys.argv[2].rsplit("@", 1)
        dump(path, tuple(int(v) for v in box.split(",")))
        return
    out = Path(sys.argv[1])
    ims = [load(*parse(a)) for a in sys.argv[2:]]
    ims = [i.resize((i.width * SCALE, i.height * SCALE), Image.NEAREST) for i in ims]
    sheet = Image.new("RGB", (sum(i.width + 12 for i in ims), max(i.height for i in ims)), (50, 50, 50))
    x = 0
    for i in ims:
        sheet.paste(i, (x, 0))
        x += i.width + 12
    sheet.save(out)
    print(f"{out}: {len(ims)} 枚")


if __name__ == "__main__":
    main()
