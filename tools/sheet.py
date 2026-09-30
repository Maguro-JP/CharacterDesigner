"""設定資料の1枚目: 色指定と全コマの一覧。

左に拡大した立ち姿、右に素材ごとの色見本（最暗・輪郭から明るい段へ、16進の値つき）、
下に全コマ（待機、歩き、右向き）と作風ごとの描き分けを並べる。
別の人が同じキャラクターを描くとき、色と動きをこの1枚で拾えるようにするため。
文字は Pillow の既定フォントで書けるよう英数字だけ（素材名は parts.json のキー）。

使い方: python3 tools/sheet.py characters/<名前>/parts.json out.png
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import build  # noqa: E402
import sprite  # noqa: E402

BG = (150, 156, 166)
INK = (20, 20, 24)


def load_img(path):
    _, rows, width, palette = sprite.load(path)
    return sprite.to_image(rows, width, palette)


def used_colors(path):
    _, rows, _, palette = sprite.load(path)
    return {palette[c] for r in rows for c in r if c != "."}


def main():
    parts = Path(sys.argv[1])
    out = Path(sys.argv[2])
    spec = build.load_spec(parts)
    base = parts.with_name("sprite.json")
    # 左向きのコマ、右向きのコマの順に並べる
    rest = sorted(parts.parent.glob("sprite.*.json"), key=lambda p: (p.name.startswith("sprite.right"), p.name != "sprite.right.json", p.name))
    frames = [base] + rest
    styles = sorted(parts.parent.glob("*/sprite.json"))
    used = set().union(*(used_colors(p) for p in frames))

    main_img = load_img(base)
    k = 8
    big = main_img.resize((main_img.width * k, main_img.height * k), Image.NEAREST)

    # 素材ごとの色見本。実際にどれかのコマで使っている素材だけ
    mats = []
    for name in sorted({p["material"] for p in spec["parts"]}):
        m = spec["materials"][name]
        ramp = [m["outline"]] + list(m["ramp"])
        if any(build.hex_to_rgb(c) in used for c in ramp):
            mats.append((name, ramp))
    sw, row_h = 22, 28
    pal_w = 80 + (sw + 26) * 6 + 24
    small = 3
    strip_h = max(load_img(p).height for p in frames) * small + 24
    W = max(24 + big.width + 24 + pal_w, 24 + len(frames) * (main_img.width * small + 6))
    H = 24 + max(big.height, len(mats) * row_h * 2 + 20) + 24 + strip_h + (strip_h if styles else 0) + 24
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((24, 6), f"{parts.parent.name}  {main_img.width}x{main_img.height}  "
                     f"colors: {len(used)} in all frames (max per frame {build.style_max_colors(spec)})", fill=INK)
    img.paste(big, (24, 24), big)

    x0, y = 24 + big.width + 24, 24
    for name, ramp in mats:
        d.text((x0, y + 6), name, fill=INK)
        for i, c in enumerate(ramp):
            rgb = build.hex_to_rgb(c)
            bx = x0 + 80 + i * (sw + 26)
            d.rectangle([bx, y, bx + sw, y + sw], fill=rgb, outline=INK if rgb in used else BG)
            d.text((bx, y + sw + 2), c[1:], fill=INK if rgb in used else (90, 94, 102))
        y += row_h * 2

    y = 24 + max(big.height, len(mats) * row_h * 2 + 20) + 24
    d.text((24, y - 14), "frames: " + " ".join(p.name[len("sprite."):-len(".json")] or "base" for p in frames),
           fill=INK)
    x = 24
    for p in frames:
        f = load_img(p)
        img.paste(f.resize((f.width * small, f.height * small), Image.NEAREST), (x, y), f.resize(
            (f.width * small, f.height * small), Image.NEAREST))
        x += f.width * small + 6
    if styles:
        y += strip_h
        d.text((24, y - 14), "styles: diorama " + " ".join(p.parent.name for p in styles), fill=INK)
        x = 24
        for p in [base] + styles:
            f = load_img(p)
            s = small * 2 if f.height <= 24 else small
            img.paste(f.resize((f.width * s, f.height * s), Image.NEAREST), (x, y), f.resize(
                (f.width * s, f.height * s), Image.NEAREST))
            x += f.width * s + 12
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"{out}: {img.width}x{img.height}、素材 {len(mats)}、コマ {len(frames)}、作風 {len(styles) + 1}")


if __name__ == "__main__":
    main()
