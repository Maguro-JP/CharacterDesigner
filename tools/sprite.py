"""スプライトの読み込み。

キャラクターは JSON で持つ。palette は1文字の記号から色へ、rows はその記号の並び。
'.' は透明。絵をコードではなく文字の格子で持つのは、1ドット単位で読み書きでき、
差分がそのまま「どのドットを直したか」になるから。
"""
import json
from pathlib import Path

from PIL import Image


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data["rows"]
    width = max(len(r) for r in rows)
    palette = {k: hex_to_rgb(v) for k, v in data["palette"].items()}
    unknown = {c for r in rows for c in r if c != "." and c not in palette}
    if unknown:
        raise ValueError(f"palette に無い記号: {sorted(unknown)}")
    return data, rows, width, palette


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_image(rows, width, palette):
    img = Image.new("RGBA", (width, len(rows)), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c != ".":
                px[x, y] = palette[c] + (255,)
    return img
