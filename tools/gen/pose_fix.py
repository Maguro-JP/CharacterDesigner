"""骨組みで描いたポーズの絵を、手本（四面図の正面）にそろえるひと続きの手順。羊娘の手を振るポーズで検品を通った順に並べる。

  1. redraw : 全体を手本で描き直す（強さ 0.55、openpose 0.8、IP-Adapter 0.8）。部位ごとの描き直しを重ねると、
              部位ごとに作風と色がずれた
  2. hands  : 手を 1 つずつ、人形の手の輪郭（線の型、control_mode=3）で強さ 0.9 → 0.3 で描き直す。
              奥行きの型や、検品を通った手の移植では、指が分かれなかった
  3. bell   : 角を色で取り、内側の縁の 14 画素内側に鈴とリボンを PIL で描き、外周だけを強さ 0.2 で混ぜる。
              枠全体をなじませると、角の巻きの線が消えた
  4. color  : 髪・瞳・ズボン・ベルトを、手本の同じ部位の色の中央値へ寄せる（recolor.py --match）

各段の出力が既にあれば飛ばす（コンテナの再起動で止まっても、続きから入れる）。
手首と指先の位置は redraw の絵を見て決めるので、設定に hands が無ければ redraw のあとで止まる。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/pose_fix.py CONFIG.json

設定の例（座標は 832x1216 の絵の画素）:
  {"src": "...png", "pose": "wave", "ref": "...sheep-girl-7.png", "words": "...words-v5.txt", "out": "outdir",
   "negative": "...", "seed": 21,
   "hands": [{"name": "L", "depth": "...L90.png", "src_wrist": [180, 115], "src_tip": [320, 395],
              "wrist": [527, 555], "tip": [532, 650], "box": [450, 515, 610, 675], "scale": 0.8, "seed": 9}],
   "bell": {"side": "image-left"}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _done(p: Path) -> bool:
    if p.exists():
        print(f"飛ばす（あり）: {p}", flush=True)
        return True
    return False


def step_redraw(c, out: Path) -> Path:
    import openpose_draw
    dst = out / "1-redraw.png"
    if not _done(dst):
        openpose_draw.redraw(c["src"], c["pose"], str(dst), c["ref"], Path(c["words"]).read_text().strip(),
                             c.get("negative", ""), c.get("strength", 0.55), 0.8, 0.8, seed=c.get("seed", 0))
    return dst


def step_hand(c, h, src: Path, out: Path) -> Path:
    import detail
    import handgraft
    from PIL import Image
    words = Path(c["words"]).read_text().strip()
    line = out / f"hand-{h['name']}-line.png"
    if not line.exists():
        handgraft.place_depth(handgraft.outline(Image.open(h["depth"]), 5), tuple(h["src_wrist"]), tuple(h["src_tip"]),
                              Image.open(src).size, tuple(h["wrist"]), tuple(h["tip"])).save(line)
    first, dst = out / f"2-hand-{h['name']}.png", out / f"2-hand-{h['name']}-blend.png"
    box = tuple(h["box"])
    if not _done(first):
        tmp = str(first) + ".tmp.png"
        detail.detail(str(src), tmp, words, "", h.get("strength", 0.9), seed=h.get("seed", 9), box=box,
                      words=detail.HAND_WORDS + ", back of hand, five separated fingers",
                      extra_negative=detail.HAND_NEGATIVE + ", fused fingers, fist",
                      control=str(line), control_scale=h.get("scale", 0.8), control_mode=3)
        Path(tmp).rename(first)
    if not _done(dst):
        tmp = str(dst) + ".tmp.png"
        detail.detail(str(first), tmp, words, "", 0.3, seed=h.get("seed", 9) + 1, box=box,
                      words=detail.HAND_WORDS, extra_negative=detail.HAND_NEGATIVE)
        Path(tmp).rename(dst)
    return dst


def horn_box(src: str, side: str = "image-left"):
    """角の範囲（色相 25〜60 度・彩度 70 以上・明るさ 90〜215 で、髪か帽子の部位）の最大の塊を、頭の片側で取る"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    import edit
    a = np.asarray(Image.open(src).convert("RGB"))
    seg = np.asarray(edit.parts(src))
    hsv = np.asarray(Image.fromarray(a).convert("HSV")).astype(int)
    h = hsv[..., 0] * 360 / 255
    m = (h > 25) & (h < 60) & (hsv[..., 1] > 70) & (hsv[..., 2] > 90) & (hsv[..., 2] < 215) & np.isin(seg, (1, 2))
    face = np.nonzero(seg == 11)
    cx = int(face[1].mean()) if len(face[1]) else a.shape[1] // 2
    top = int(face[0].min()) if len(face[0]) else 200
    m[top + 80:] = False
    if side == "image-left":
        m[:, cx:] = False
    else:
        m[:, :cx] = False
    lab, n = ndimage.label(m)
    if not n:
        return None
    k = int(np.argmax(ndimage.sum(m, lab, range(1, n + 1)))) + 1
    return ndimage.binary_fill_holes(lab == k)


def step_bell(c, src: Path, out: Path) -> Path:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    import detail
    dst = out / "3-bell.png"
    if _done(dst):
        return dst
    side = c.get("bell", {}).get("side", "image-left")
    horn = horn_box(str(src), side)
    if horn is None:
        raise RuntimeError("角が取れなかった")
    ys, xs = np.nonzero(horn)
    y0 = int(ys.min() + 0.62 * (ys.max() - ys.min()))
    row = xs[ys == y0]
    x0 = int(row.max()) - 14 if side == "image-left" else int(row.min()) + 14
    print(f"角 {xs.min()}-{xs.max()} x {ys.min()}-{ys.max()}、鈴の位置 ({x0}, {y0})", flush=True)
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    d.line([(x0 - 7, y0 - 2), (x0 + 5, y0 + 2)], fill=(60, 125, 70), width=3)
    d.polygon([(x0 - 8, y0 - 6), (x0, y0), (x0 - 8, y0 + 4)], fill=(70, 140, 80), outline=(40, 90, 50))
    d.polygon([(x0 + 8, y0 - 4), (x0, y0), (x0 + 8, y0 + 6)], fill=(70, 140, 80), outline=(40, 90, 50))
    d.line([(x0, y0 + 2), (x0, y0 + 6)], fill=(50, 110, 60), width=2)
    d.ellipse([x0 - 4, y0 + 6, x0 + 4, y0 + 14], fill=(200, 160, 60), outline=(120, 85, 30))
    paint = out / "3-bell-paint.png"
    im.save(paint)
    tmp = str(out / "3-bell-blend.tmp.png")
    detail.detail(str(paint), tmp, Path(c["words"]).read_text().strip(), "", 0.2, seed=24, box=(x0 - 32, y0 - 32, x0 + 32, y0 + 32),
                  words="small brass bell with green ribbon on ram horn, clean lineart", extra_negative="blurry")
    inner = Image.new("L", im.size, 0)
    di = ImageDraw.Draw(inner)
    di.polygon([(x0 - 9, y0 - 7), (x0 + 9, y0 - 5), (x0 + 9, y0 + 7), (x0 - 9, y0 + 5)], fill=255)
    di.ellipse([x0 - 5, y0 + 5, x0 + 5, y0 + 15], fill=255)
    ring = np.clip(np.asarray(inner.filter(ImageFilter.MaxFilter(9))).astype(int) - np.asarray(inner), 0, 255)
    ring = Image.fromarray(ring.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1))
    im.paste(Image.open(tmp).convert("RGB"), (0, 0), ring)
    Path(tmp).unlink()
    im.save(dst)
    return dst


def step_color(c, src: Path, out: Path) -> Path:
    import numpy as np
    from PIL import Image
    import recolor
    dst = out / "4-color.png"
    if _done(dst):
        return dst
    res = np.asarray(Image.open(src).convert("RGB"))
    for part in ("hair", "eyes", "pants", "belt"):
        target = recolor.mean_color(c["ref"], part)
        before = recolor.mean_color(str(src), part)
        res = recolor.recolor(res, recolor.part_mask(str(src), part), target)
        print(f"{part}: 手本 {target} 元 {before} ΔE {recolor.delta_e(before, target):.1f}", flush=True)
    Image.fromarray(res).save(dst)
    return dst


def run(cfg: str) -> Path:
    c = json.loads(Path(cfg).read_text(encoding="utf-8"))
    out = Path(c["out"])
    out.mkdir(parents=True, exist_ok=True)
    cur = step_redraw(c, out)
    if not c.get("hands"):
        print("hands が無いので redraw のあとで止める。絵を見て手首と指先の位置を設定に書く", flush=True)
        return cur
    for h in c["hands"]:
        cur = step_hand(c, h, cur, out)
    if c.get("bell"):
        cur = step_bell(c, cur, out)
    cur = step_color(c, cur, out)
    print("できた:", cur, flush=True)
    return cur


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run(sys.argv[1])
