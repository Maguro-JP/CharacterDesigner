"""複数の版のスプライトを1枚に並べる。良くなったかを目で判定するための図。

上の段は拡大（明るい地で輪郭が見えるように）、下の段は HD-2D 風の舞台に置いた図。
単体で良く見えても舞台で沈むことがあるので、両方を同じ1枚で見る。
文字は Pillow の既定フォントで書けるように英数字だけにする。

使い方: python3 tools/compare.py out.png v3=characters/a/sprite.json v4=characters/b/sprite.json
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402
import sprite  # noqa: E402

SCALE = 8
GAP = 24
LABEL_H = 20


def load_image(path):
    _, rows, width, palette = sprite.load(path)
    return sprite.to_image(rows, width, palette)


def sheet(entries):
    imgs = [(label, load_image(p)) for label, p in entries]
    cell_w = max(i.width for _, i in imgs) * SCALE
    cell_h = max(i.height for _, i in imgs) * SCALE
    stages = [render.stage(i) for _, i in imgs]
    st_w = max(s.width for s in stages)
    st_h = max(s.height for s in stages)
    col_w = max(cell_w, st_w)
    W = GAP + len(imgs) * (col_w + GAP)
    H = LABEL_H + cell_h + GAP + st_h + GAP
    out = Image.new("RGB", (W, H), (150, 156, 166))
    d = ImageDraw.Draw(out)
    for n, ((label, img), st) in enumerate(zip(imgs, stages)):
        x = GAP + n * (col_w + GAP)
        d.text((x, 4), f"{label}  {img.width}x{img.height}", fill=(20, 20, 24))
        big = img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)
        # 足元をそろえて置く。大きさの違いがそのまま見えるように
        out.paste(big, (x + (col_w - big.width) // 2, LABEL_H + cell_h - big.height), big)
        out.paste(st, (x + (col_w - st.width) // 2, LABEL_H + cell_h + GAP))
    return out


def main():
    out = Path(sys.argv[1])
    entries = [a.split("=", 1) for a in sys.argv[2:]]
    if not entries or any(len(e) != 2 for e in entries):
        sys.exit("使い方: compare.py out.png label=sprite.json [label=sprite.json ...]")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet(entries).save(out)
    print(f"{out}: {len(entries)} 版")


if __name__ == "__main__":
    main()
