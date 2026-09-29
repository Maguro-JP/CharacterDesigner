"""動きのコマを並べて GIF と、コマを横に並べた静止画にする。

GIF は動きを見る人のため、静止画はコマの差を1ドット単位で見比べるため（GIF は差分が追いにくい）。

使い方: python3 tools/anim.py out.gif characters/a/sprite.json characters/b/sprite.json ...
  各 sprite.json の隣にある sprite.<コマ名>.json を、名前の順に続くコマとして読む
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402

SCALE = 6
GAP = 4
BG = (150, 156, 166, 255)


def frames_of(path):
    path = Path(path)
    paths = [path] + sorted(path.parent.glob("sprite.*.json"))
    out = []
    for p in paths:
        _, rows, width, palette = sprite.load(p)
        out.append(sprite.to_image(rows, width, palette))
    return out


def main():
    out = Path(sys.argv[1])
    chars = [frames_of(p) for p in sys.argv[2:]]
    n = max(len(c) for c in chars)
    W = sum(c[0].width for c in chars) + GAP * (len(chars) + 1)
    H = max(c[0].height for c in chars) + GAP * 2
    shots = []
    for k in range(n):
        im = Image.new("RGBA", (W, H), BG)
        x = GAP
        for c in chars:
            f = c[k % len(c)]
            im.alpha_composite(f, (x, H - GAP - f.height))
            x += c[0].width + GAP
        shots.append(im.resize((W * SCALE, H * SCALE), Image.NEAREST))
    out.parent.mkdir(parents=True, exist_ok=True)
    shots[0].convert("RGB").save(out, save_all=True, append_images=[s.convert("RGB") for s in shots[1:]],
                                 duration=500, loop=0)
    strip = Image.new("RGBA", (W * SCALE, H * SCALE * n), BG)
    for k, s in enumerate(shots):
        strip.alpha_composite(s, (0, k * H * SCALE))
    strip.save(out.with_suffix(".png"))
    print(f"{out}: {len(chars)} 人 × {n} コマ、{out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
