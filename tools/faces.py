"""全キャラクターの全コマの頭を1枚に並べる。顔の直しを全コマで確かめるための図。

最初の1コマだけを見て良しとすると、呼吸・歩き・右向きのコマで目や髪が崩れていても気付かない。
行がキャラクター、列がコマ。頭の範囲（上から HEAD_ROWS 行）だけを拡大する。

使い方: python3 tools/faces.py out.png [キャラクター名 ...]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HEAD_ROWS = 16
SCALE = 8
GAP = 6
LABEL_W = 90


def frames(char):
    d = ROOT / "characters" / char
    first = [d / "sprite.json"]
    rest = sorted(p for p in d.glob("sprite.*.json"))
    return [p for p in first + rest if p.exists()]


def head(path):
    _, rows, width, palette = sprite.load(path)
    im = sprite.to_image(rows, width, palette).crop((0, 0, width, HEAD_ROWS))
    bg = Image.new("RGBA", im.size, (170, 176, 186, 255))
    bg.alpha_composite(im)
    return bg.resize((im.width * SCALE, im.height * SCALE), Image.NEAREST), path.stem.replace("sprite", "") or "."


def main():
    out = Path(sys.argv[1])
    chars = sys.argv[2:] or sorted(p.parent.name for p in (ROOT / "characters").glob("*/parts.json"))
    rows = [(c, [head(p) for p in frames(c)]) for c in chars]
    cw = max(im.width for _, hs in rows for im, _ in hs)
    ch = HEAD_ROWS * SCALE
    ncol = max(len(hs) for _, hs in rows)
    sheet = Image.new("RGB", (LABEL_W + ncol * (cw + GAP), len(rows) * (ch + GAP + 12)), (60, 60, 60))
    d = ImageDraw.Draw(sheet)
    for r, (c, hs) in enumerate(rows):
        y = r * (ch + GAP + 12)
        d.text((4, y + ch // 2), c, fill=(230, 230, 230))
        for i, (im, name) in enumerate(hs):
            x = LABEL_W + i * (cw + GAP)
            sheet.paste(im, (x, y + 12))
            d.text((x, y), name.strip(".") or "idle-1", fill=(200, 200, 200))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"{out}: {len(rows)} 人、最大 {ncol} コマ")


if __name__ == "__main__":
    main()
