"""Blender で描いた部位の塗り分けと光の2枚を、今の描画器の後半（build.finish）でドット絵に落とす。

縮小・減色・輪郭・孤立ドットの掃除・色数の上限は、部品から描くときと同じ処理を通す。
作風の決まり（styles/*.json）と素材の色段も、既存の職業の parts.json から借りる。

使い方:
  python3 tools/engine/topixel.py <human.py の out> <出力 sprite.json> --canvas 26,35
      --materials characters/swordsman/parts.json --map skin=skin,hair=hair,male_casualsuit01=tunic,shoes01=leather
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402


def load_passes(base, canvas, regions):
    """2枚を読み、人物の範囲を切り出して画面（canvas×SS）の下中央に合わせる。

    人物の背の高さは画面の高さから上下1ドットずつ引いた分に合わせる。輪郭は外側に付くので、
    画面の端に触れると切れる（靴の底の輪郭が切れた件と同じ）。
    """
    ids = Image.open(base + ".id.png").convert("RGBA")
    light = Image.open(base + ".light.png").convert("RGBA")
    bb = ids.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()
    ids, light = ids.crop(bb), light.crop(bb)
    W, H = canvas[0] * build.SS, canvas[1] * build.SS
    target_h = (canvas[1] - 2) * build.SS
    scale = target_h / ids.height
    size = (max(1, round(ids.width * scale)), target_h)
    if size[0] > W - 2 * build.SS:
        scale = (W - 2 * build.SS) / ids.width
        size = (W - 2 * build.SS, max(1, round(ids.height * scale)))
    ids = ids.resize(size, Image.NEAREST)
    light = light.resize(size, Image.BILINEAR)
    ox, oy = (W - size[0]) // 2, H - build.SS - size[1]
    names = list(regions)
    keys = [tuple(regions[n]) for n in names]
    top = [-1] * (W * H)
    lum = [0.0] * (W * H)
    ip, lp = ids.load(), light.load()
    for y in range(size[1]):
        for x in range(size[0]):
            r, g, b, a = ip[x, y]
            if a < 128:
                continue
            # 縁のぼかしで混ざった色は、いちばん近い塗り分けの色の部位にする
            k = min(range(len(keys)), key=lambda i: sum((c - d) ** 2 for c, d in zip((r, g, b), keys[i])))
            i = (oy + y) * W + ox + x
            top[i] = k
            L = lp[x, y]
            lum[i] = (L[0] + L[1] + L[2]) / 3 / 255
    return names, top, match_levels(top, lum), (W, H)


# 部品から描くとき（build.render_hi）の明るさの分布（剣士で測った下位10%・中央・上位10%）
TARGET = (0.30, 0.65, 0.95)


def match_levels(top, lum):
    """Blender の光の絵の明るさを、部品から描くときの分布に合わせて並べ替える。

    素材の色段の境（steps）は部品から描く明るさに合わせて決めてある。Blender の光は中央が 0.83 と
    明るく、上が 1.0 に張り付いて、ほとんどが最も明るい段に入った。下位10%・中央・上位10% の3点を
    合わせる折れ線で写す。
    """
    v = sorted(l for t, l in zip(top, lum) if t >= 0)
    if not v:
        return lum
    src = (v[len(v) // 10], v[len(v) // 2], v[len(v) * 9 // 10])

    def f(x):
        if x <= src[1]:
            a, b, c, d = src[0], src[1], TARGET[0], TARGET[1]
        else:
            a, b, c, d = src[1], src[2], TARGET[1], TARGET[2]
        return c + (x - a) * (d - c) / ((b - a) or 1e-6)

    return [f(l) if t >= 0 else l for t, l in zip(top, lum)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("out")
    ap.add_argument("--canvas", default="26,35")
    ap.add_argument("--materials", default="characters/swordsman/parts.json")
    ap.add_argument("--map", default="skin=skin,hair=hair,male_casualsuit01=tunic,shoes01=leather")
    ap.add_argument("--name", default="engine-test")
    a = ap.parse_args()
    meta = json.loads(Path(a.base + ".json").read_text(encoding="utf-8"))
    src = build.load_spec(ROOT / a.materials)
    mapping = dict(kv.split("=") for kv in a.map.split(","))
    canvas = [int(v) for v in a.canvas.split(",")]
    names, top, lum, size = load_passes(a.base, canvas, meta["regions"])
    spec = {"name": a.name, "style": src["style"], "canvas": canvas, "materials": src["materials"],
            "texture": src.get("texture", {}),
            "parts": [{"name": n, "material": mapping.get(n, "skin"), "shapes": []} for n in names]}
    spec = build.apply_saturation(spec)
    out, _ = build.finish(spec, top, lum, size)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {len(out['palette'])} 色, 頭 {out['head_height']}px, 体 {out['body_box']}")


if __name__ == "__main__":
    main()
