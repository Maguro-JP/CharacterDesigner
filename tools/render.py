"""スプライトを、検品用の拡大図と、HD-2D の見え方に近い舞台に置いた図に描き出す。

HD-2D の印象はスプライト単体ではなく、奥行きのぼかし・足元の影・ブルームと
組み合わさって決まる。単体だけで判定すると、画面に置いたときの見え方を外す。

使い方: python3 tools/render.py characters/<name>/sprite.json [out/]
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402

SCALE = 8


def enlarge(img, scale=SCALE):
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def grid_sheet(img, scale=SCALE):
    """ドットの境目に薄い格子を引いた拡大図。1ドットの過不足を見るため。"""
    big = enlarge(img, scale)
    bg = Image.new("RGBA", big.size, (58, 60, 70, 255))
    bg.alpha_composite(big)
    d = ImageDraw.Draw(bg)
    for x in range(0, big.width, scale):
        d.line([(x, 0), (x, big.height)], fill=(255, 255, 255, 18))
    for y in range(0, big.height, scale):
        d.line([(0, y), (big.width, y)], fill=(255, 255, 255, 18))
    return bg


def stage(img, scale=4):
    """HD-2D 風の舞台: 奥のぼけた背景、手前の地面、足元の影、周辺の減光、ブルーム。"""
    W, H = 96, 72
    base = Image.new("RGB", (W * scale, H * scale), (0, 0, 0))
    d = ImageDraw.Draw(base)
    # 空から地面へのグラデーション
    for y in range(H * scale):
        t = y / (H * scale)
        col = (int(40 + 60 * t), int(52 + 50 * t), int(78 + 20 * t))
        d.line([(0, y), (W * scale, y)], fill=col)
    # 奥の建物や木立を四角の塊で置き、ぼかして被写界深度に見せる
    far = Image.new("RGBA", base.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(far)
    blocks = [(4, 18, 22, 44, (70, 84, 96)), (26, 10, 40, 44, (58, 70, 86)),
              (58, 14, 80, 44, (66, 78, 92)), (82, 22, 96, 44, (74, 88, 100))]
    for x0, y0, x1, y1, c in blocks:
        fd.rectangle([x0 * scale, y0 * scale, x1 * scale, y1 * scale], fill=c + (255,))
    for i, (x, y) in enumerate([(30, 20), (66, 24), (12, 26), (48, 16)]):
        fd.ellipse([(x - 2) * scale, (y - 2) * scale, (x + 2) * scale, (y + 2) * scale],
                   fill=(255, 214, 140, 220))
    far = far.filter(ImageFilter.GaussianBlur(scale * 1.6))
    base.paste(far, (0, 0), far)
    # 地面
    d.rectangle([0, 44 * scale, W * scale, H * scale], fill=(92, 88, 70))
    for i in range(0, W, 6):
        d.rectangle([i * scale, 44 * scale, (i + 5) * scale, 45 * scale], fill=(104, 100, 80))
    # 足元の影
    sw = img.width
    cx, foot = W // 2, 58
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([(cx - sw // 2) * scale, (foot - 2) * scale,
                                (cx + sw // 2) * scale, (foot + 1) * scale], fill=(0, 0, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(scale))
    base.paste(sh, (0, 0), sh)
    # キャラクター
    spr = enlarge(img, scale)
    base.paste(spr, ((cx - img.width // 2) * scale, (foot - img.height) * scale), spr)
    # ブルーム: 明るい所だけをぼかして足す
    glow = base.point(lambda v: v if v > 190 else 0).filter(ImageFilter.GaussianBlur(scale * 2))
    base = ImageChops.screen(base, glow.point(lambda v: int(v * 0.35)))
    # 周辺の減光
    vig = Image.new("L", base.size, 0)
    ImageDraw.Draw(vig).ellipse([-W * scale * 0.2, -H * scale * 0.3, W * scale * 1.2, H * scale * 1.3], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(scale * 10))
    base = Image.composite(base, Image.new("RGB", base.size, (10, 10, 16)), vig)
    return base


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
    out.mkdir(parents=True, exist_ok=True)
    _, rows, width, palette = sprite.load(src)
    img = sprite.to_image(rows, width, palette)
    name = src.parent.name
    img.save(out / f"{name}.png")
    grid_sheet(img).save(out / f"{name}_x8.png")
    stage(img).save(out / f"{name}_stage.png")
    print(f"{name}: {img.width}x{img.height} → {out}/{name}.png, _x8.png, _stage.png")


if __name__ == "__main__":
    main()
