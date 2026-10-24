"""出来た絵に掛ける後の加工（今ある絵を変える）。描く前に指示する画風とは別に持つ。ドット絵（縮める・色を減らす・輪郭を付ける）、線画。ちびキャラは AI の描き直しで行う（app.py）。

ドット絵は、絵の模型に直接ドット絵を描かせるより、出来た絵を縮めて色を減らす方が、元の絵の形と色を保てる。
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def paper_to_alpha(img: Image.Image, tolerance: int = 24) -> Image.Image:
    """四隅から続く紙の色（背景）を透明にする。人物の中の同じ色は、外とつながっていなければ残す"""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    key = (255, 0, 255, 0)
    flood = rgba.copy()
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flood.getpixel(corner)[3] != 0:
            ImageDraw.floodfill(flood, corner, key, thresh=tolerance)
    mask = Image.eval(ImageChops.difference(flood.convert("RGB"), Image.new("RGB", (w, h), key[:3])).convert("L"),
                      lambda v: 255 if v > 0 else 0)
    rgba.putalpha(ImageChops.multiply(rgba.getchannel("A"), mask))
    return rgba


def pixel_art(img: Image.Image, long: int = 128, colors: int = 24, outline: bool = True, transparent: bool = True) -> Image.Image:
    """img をドット絵にする。長い辺を long ドットに縮め、colors 色に減らし、透明な所との境に 1 ドットの輪郭を付ける"""
    src = paper_to_alpha(img) if transparent else img.convert("RGBA")
    k = long / max(src.size)
    small = src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)
    alpha = small.getchannel("A").point(lambda v: 255 if v >= 128 else 0)   # ドット絵に半透明は使わない
    rgb = Image.new("RGB", small.size, (255, 255, 255))
    rgb.paste(small.convert("RGB"), (0, 0), alpha)
    q = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    out = q.convert("RGBA")
    out.putalpha(alpha)
    if outline:
        ring = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(3)), alpha)   # 外側に 1 ドット
        dark = _darkest(q, alpha)
        out.paste(Image.new("RGBA", out.size, dark + (255,)), (0, 0), ring)
    return out


def _darkest(img: Image.Image, alpha: Image.Image) -> tuple:
    colors = img.getcolors(maxcolors=1 << 16) or []
    seen = [c for _n, c in colors]
    if not seen:
        return (20, 16, 24)
    d = min(seen, key=lambda c: sum(c))
    return tuple(max(0, v - 20) for v in d)


def lineart(img: Image.Image, strength: float = 1.0) -> Image.Image:
    """img から線だけを取り出し、白地に黒の線画にする。塗りの面と影は消え、線と色の境目だけが残る（AI は使わない）"""
    from PIL import ImageOps
    g = img.convert("L")
    # 少しぼかした絵より暗い所が線（明るい側の縁は拾わない）。面の濃さは引き算で消える
    darker = ImageChops.subtract(g.filter(ImageFilter.GaussianBlur(3)), g)
    lines = darker.point(lambda v: 0 if v < 6 else min(255, int((v - 6) * 10 * strength)))
    return ImageOps.invert(lines.filter(ImageFilter.MedianFilter(3))).convert("RGB")


def enlarge(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """ドットをにじませずに、キャンバスの大きさへ整数倍で広げ、真ん中に置く"""
    k = max(1, min(size[0] // img.width, size[1] // img.height))
    big = img.resize((img.width * k, img.height * k), Image.NEAREST)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(big, ((size[0] - big.width) // 2, (size[1] - big.height) // 2))
    return out


CHIBI_NOTE = "ちびキャラにする。頭を大きく、2 頭身のかわいいデフォルメ"
CHIBI_TAGS = "chibi, super deformed, 2 heads tall, big head, small body, cute"
