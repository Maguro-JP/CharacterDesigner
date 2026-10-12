"""線の清書: 手で描いたラフ線（同じ所に何本も重ねた線、途切れた線）を、1本のきれいな線にまとめる。

  python3 tools/gen/inking.py <ラフ.png> <出力.png> [--width 3] [--merge 3]

描く板（app/web の「描く」）のレイヤーをそのまま渡す前提で、透明な地に描いた線も、白い地の線も読む。
模型を使わないので数秒で済む。
1. 重なった線をまとめる: 線をぼかして（merge）、近くの何本もの線を1つの太い帯にする
2. 芯を取る: 帯を細くして1画素の芯線にする（skeletonize）。ここで二重線・ガタつきが1本になる
3. 短いひげを落とす: 芯線から出る短い枝（ラフのはみ出し）を消す
4. 太さをそろえる: 芯線を width の太さに太らせ、縁をなめらかにする
返すのは透明な地に黒い線の PNG（描く板の新しいレイヤーにそのまま重ねられるように）。
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageFilter


def _ink_mask(im: Image.Image) -> np.ndarray:
    """描いた線のある所。透明な地なら不透明度で、白い地なら暗さで見る"""
    rgba = np.asarray(im.convert("RGBA")).astype(float)
    a = rgba[..., 3] / 255.0
    if a.min() < 0.99:
        return a > 0.15
    g = rgba[..., :3].mean(axis=2) / 255.0
    return g < 0.6


def _prune(skel: np.ndarray, length: int) -> np.ndarray:
    """芯線の端から length 画素以内の短い枝を消す（端点を繰り返し削る）。長い線の端も同じだけ縮むので、最後に伸ばし直す"""
    from scipy.ndimage import convolve
    k = np.ones((3, 3), int)
    k[1, 1] = 0
    s = skel.copy()
    removed = np.zeros_like(s)
    for _ in range(length):
        n = convolve(s.astype(int), k, mode="constant")
        tips = s & (n == 1)
        if not tips.any():
            break
        removed |= tips
        s &= ~tips
    # 長い線の削れた端を戻す: 残った芯に触れている削った画素を、削った回数だけ足し戻す
    for _ in range(length):
        grow = convolve(s.astype(int), np.ones((3, 3), int), mode="constant") > 0
        back = removed & grow & ~s
        if not back.any():
            break
        s |= back
        removed &= ~back
    return s


def ink(src: str, out: str, width: float = 3.0, merge: float = 3.0, spur: int = 6) -> dict:
    from skimage.morphology import skeletonize
    im = Image.open(src)
    mask = _ink_mask(im)
    before = int(mask.sum())
    if before == 0:
        Image.new("RGBA", im.size, (0, 0, 0, 0)).save(out)
        return {"ink_before": 0, "ink_after": 0, "strokes": 0}
    # 1. 近くの線をまとめる。ぼかして薄く残る所まで帯にする（60 で切ると、重ねた線が離れて1本ずつになる所で帯が割れた）
    band = np.asarray(Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(merge))) > 25
    # 2. 芯を取る
    skel = skeletonize(band)
    # 3. 短いひげを落とす
    skel = _prune(skel, spur)
    # 4. 太さをそろえ、縁をなめらかにする（芯線をぼかして、太さに合う濃さで切る）
    soft = np.asarray(Image.fromarray((skel * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(width / 2))).astype(float) / 255.0
    peak = max(float(soft[skel].mean()) if skel.any() else 1.0, 1e-6)
    alpha = np.clip(soft / peak * 1.6, 0, 1)
    res = np.zeros((*alpha.shape, 4), np.uint8)
    res[..., 3] = (alpha * 255).astype(np.uint8)
    Image.fromarray(res, "RGBA").save(out)
    from scipy.ndimage import label
    _, strokes = label(skel, structure=np.ones((3, 3)))
    return {"ink_before": before, "ink_after": int((alpha > 0.5).sum()), "strokes": int(strokes)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--width", type=float, default=3.0)
    ap.add_argument("--merge", type=float, default=3.0)
    a = ap.parse_args()
    print(json.dumps(ink(a.src, a.out, a.width, a.merge), ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
