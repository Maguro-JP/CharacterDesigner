"""仕上がった絵の清書: 線と色をきれいにする（4096 画素の仕上げの後に掛ける）。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/cleanup.py in.png out.png [--line 1] [--color 0.6]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/cleanup.py measure in.png      # 線と色の数字だけを出す

画像生成の模型で描いた絵は、主線のまわりに細かい黒い粒（ごみ）、主線の小さな途切れ、塗りの面のまだら・濁りが残る。
描き直す模型を使うと新しい崩れが出るので、ここでは模型で描かず、絵そのものを整える。
  線: 主線（まわりより暗く細い所）を取り出し、小さな粒を消して周りの塗りで埋め、細い途切れをつなぎ、縁をなめらかにして重ね直す
  色: 部位分け（edit.parts）の部位ごとに、明るさで 2〜3 段（影・地・光）に分け、段ごとの色に寄せる。段の境がはっきりし、まだらが減る
顔（目・口の細い線と瞳の色）は崩しやすいので触らない。

数字（measure）:
  specks: 主線から離れた小さな暗い粒の数（少ないほど線がきれい）
  ends:   主線の芯の端の数（少ないほど線がつながっている）
  mottle: 部位ごと・段ごとの明るさのばらつきの平均（少ないほど塗りが平ら）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))

FACE = 11
SPECK = 60          # これより小さい暗い粒はごみ（4096 画素の絵で、主線の一筆は数千画素ある）
DARK = 0.42         # 主線とみなす暗さ（明るさ 0〜1）
CONTRAST = 0.10     # まわりよりこれだけ暗いと線


def _lum(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114) / 255.0


def line_mask(rgb: np.ndarray, radius: int = 6) -> np.ndarray:
    """主線: まわり（radius の範囲の明るい方）より CONTRAST 以上暗く、DARK より暗い画素"""
    from scipy.ndimage import grey_closing
    L = _lum(rgb)
    closed = grey_closing(L, size=(2 * radius + 1, 2 * radius + 1))
    return ((closed - L) > CONTRAST) & (L < DARK)


def _parts(src: str, size) -> np.ndarray:
    import edit
    return np.asarray(edit.parts(src).resize(size, Image.NEAREST))


def measure(src: str, rgb: np.ndarray | None = None, seg: np.ndarray | None = None) -> dict:
    from scipy.ndimage import label
    from skimage.morphology import skeletonize
    if rgb is None:
        rgb = np.asarray(Image.open(src).convert("RGB")).astype(float)
    if seg is None:
        seg = _parts(src, (rgb.shape[1], rgb.shape[0]))
    m = line_mask(rgb)
    lab, n = label(m, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())[1:]
    specks = int((sizes < SPECK).sum())
    big = np.isin(lab, np.nonzero(sizes >= SPECK)[0] + 1)
    sk = skeletonize(big)
    from scipy.ndimage import convolve
    nb = convolve(sk.astype(int), np.ones((3, 3), int), mode="constant") - sk
    ends = int((sk & (nb == 1)).sum())
    L = _lum(rgb)
    devs = []
    for p in np.unique(seg):
        if p in (0, FACE):
            continue
        sel = (seg == p) & ~m
        if sel.sum() < 2000:
            continue
        for band in _bands(L[sel]):
            if band.size > 500:
                devs.append(float(band.std()))
    return {"specks": specks, "ends": ends, "mottle": round(float(np.mean(devs)) * 1000, 1) if devs else None}


def _split(values: np.ndarray, k: int = 3, rounds: int = 12) -> np.ndarray:
    """1 次元の k 個の塊に分けた中心（明るさの段）。少ない値は分けない"""
    c = np.quantile(values, np.linspace(0.15, 0.85, k))
    for _ in range(rounds):
        idx = np.abs(values[:, None] - c[None]).argmin(1)
        c = np.array([values[idx == i].mean() if (idx == i).any() else c[i] for i in range(k)])
    return c


def _bands(values: np.ndarray, k: int = 3) -> list[np.ndarray]:
    c = _split(values, k)
    idx = np.abs(values[:, None] - c[None]).argmin(1)
    return [values[idx == i] for i in range(k)]


def clean_lines(rgb: np.ndarray, seg: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """粒を消して塗りで埋め、細い途切れをつなぎ、縁をなめらかにした主線を重ね直す。顔は触らない"""
    from scipy.ndimage import binary_closing, grey_erosion, label, median_filter
    m = line_mask(rgb)
    lab, _ = label(m, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep = sizes[lab] >= SPECK
    face = seg == FACE
    # 消す粒の所は、まわりの塗りの中央値で埋める
    fill = np.stack([median_filter(rgb[..., c], size=9) for c in range(3)], -1)
    dirt = m & ~keep & ~face
    base = rgb.copy()
    base[dirt] = fill[dirt]
    # 細い途切れ（2〜3 画素）をつなぐ。つないだ所は近くの線の色で塗る
    joined = binary_closing(keep, structure=np.ones((5, 5))) & ~face
    ink = np.stack([grey_erosion(rgb[..., c], size=(7, 7)) for c in range(3)], -1)
    # 縁をなめらかにする: 線の形をぼかして濃さにし、線の色を重ねる
    alpha = np.asarray(Image.fromarray((joined * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1.2))).astype(float) / 255.0
    alpha = (np.clip((alpha - 0.2) / 0.6, 0, 1) * strength)[..., None]
    out = base * (1 - alpha) + np.minimum(ink, base) * alpha
    out[face] = rgb[face]
    return out


def clean_colors(rgb: np.ndarray, seg: np.ndarray, strength: float = 0.6, k: int = 3) -> np.ndarray:
    """部位ごとに明るさで k 段に分け、段ごとの中央の色へ strength だけ寄せる。主線と顔は触らない"""
    from scipy.ndimage import uniform_filter
    m = line_mask(rgb)
    L = _lum(rgb)
    # 段の分け方は少しならした明るさで決める（1 画素ずつの粒で段が細かく割れないように）
    Ls = uniform_filter(L, 5)
    out = rgb.copy()
    for p in np.unique(seg):
        if p in (0, FACE):
            continue
        sel = (seg == p) & ~m
        if sel.sum() < 2000:
            continue
        c = _split(Ls[sel], k)
        idx = np.abs(Ls[sel][:, None] - c[None]).argmin(1)
        px = rgb[sel]
        target = np.zeros_like(px)
        for i in range(k):
            if (idx == i).any():
                target[idx == i] = np.median(px[idx == i], axis=0)
        out[sel] = px * (1 - strength) + target * strength
    return out


def cleanup(src: str, out: str, line: float = 1.0, color: float = 0.6) -> dict:
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(float)
    seg = _parts(src, (rgb.shape[1], rgb.shape[0]))
    before = measure(src, rgb, seg)
    res = rgb
    if color:
        res = clean_colors(res, seg, color)
    if line:
        res = clean_lines(res, seg, line)
    res = np.clip(res, 0, 255).astype("uint8")
    Image.fromarray(res).save(out)
    after = measure(out, res.astype(float), seg)
    return {"before": before, "after": after}


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "measure":
        print(json.dumps(measure(sys.argv[2]), ensure_ascii=False))
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--line", type=float, default=1.0, help="線の清書の強さ（0 で掛けない）")
    ap.add_argument("--color", type=float, default=0.6, help="色を段の色へ寄せる割合（0 で掛けない）")
    a = ap.parse_args()
    print(json.dumps(cleanup(a.src, a.out, a.line, a.color), ensure_ascii=False))


if __name__ == "__main__":
    main()
