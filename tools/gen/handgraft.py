"""検品を通った絵の手を、別の絵の手へ移す（手首と指先の2点で位置・向き・大きさを合わせる）。

骨組みや手の点で縛っても、下ろした手の指が 2〜3 本に溶けた（羊娘のポーズ、6 回描いて 6 回とも）。
四面図の正面では下ろした手が描けているので、描かせずにその手を移す。
手の範囲は部位分け（edit.parts の腕）のうち手首より先だけを取り、ズボンや背景は持ってこない。
移す前に、先の絵の手首より先の腕の画素を白にして元の手を消す（新しい手が小さいと元の指がはみ出すため）。
境目は、このあと detail.py の範囲描き直し（強さ 0.3 前後）でなじませる。

  python3 tools/gen/handgraft.py SRC DST OUT --src-wrist x,y --src-tip x,y --dst-wrist x,y --dst-tip x,y
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))

ARMS = (14, 15)   # edit.LABELS の left_arm / right_arm
KEEP = (2, 4, 5, 6, 7, 8)   # 消さない部位: 髪、上着、スカート、ズボン、ワンピース、ベルト


def beyond(shape, wrist, tip, margin=0.0) -> np.ndarray:
    """手首を通り、手首→指先に直交する線より指先側の画素（手首より先）。margin は手の長さに対する割合で手首側へ広げる"""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    vx, vy = tip[0] - wrist[0], tip[1] - wrist[1]
    n = math.hypot(vx, vy) or 1.0
    t = ((xx - wrist[0]) * vx + (yy - wrist[1]) * vy) / n
    return t >= -margin * n


def near(shape, center, radius) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    return (xx - center[0]) ** 2 + (yy - center[1]) ** 2 <= radius ** 2


def hand_mask(seg: np.ndarray, wrist, tip) -> np.ndarray:
    """部位分けの腕のうち、手首より先で、手の長さの 1.6 倍の円の中（もう片方の手を拾わない）"""
    arm = np.isin(seg, ARMS)
    r = 1.6 * math.hypot(tip[0] - wrist[0], tip[1] - wrist[1])
    return arm & beyond(seg.shape, wrist, tip) & near(seg.shape, wrist, r)


def transform(src_wrist, src_tip, dst_wrist, dst_tip):
    """src の点を dst の点へ写す相似変換（回転・拡大・移動）の、PIL の affine に渡す逆写像の係数"""
    sv = complex(src_tip[0] - src_wrist[0], src_tip[1] - src_wrist[1])
    dv = complex(dst_tip[0] - dst_wrist[0], dst_tip[1] - dst_wrist[1])
    k = sv / dv           # dst → src の回転と拡大
    a, b = k.real, k.imag
    # src = k * (dst - dst_wrist) + src_wrist（複素数で）
    c = src_wrist[0] - (a * dst_wrist[0] - b * dst_wrist[1])
    f = src_wrist[1] - (b * dst_wrist[0] + a * dst_wrist[1])
    return (a, -b, c, b, a, f)


def graft(src_img: Image.Image, src_seg: np.ndarray, dst_img: Image.Image, dst_seg: np.ndarray,
          src_wrist, src_tip, dst_wrist, dst_tip, background=(255, 255, 255)) -> tuple[Image.Image, int]:
    """src の手を dst の手首と指先に合わせて貼る。返すのは (絵, 貼った画素の数)"""
    dst = np.asarray(dst_img.convert("RGB")).copy()
    # 元の手は輪郭の線が腕の部位に入らず残ったので、手首より先の円の中で、服・髪・背景以外を全部消す
    r = 1.3 * math.hypot(dst_tip[0] - dst_wrist[0], dst_tip[1] - dst_wrist[1])
    keep = np.isin(dst_seg, KEEP)
    old = beyond(dst_seg.shape, dst_wrist, dst_tip) & near(dst_seg.shape, dst_wrist, r) & ~keep
    dst[old] = background
    m = Image.fromarray((hand_mask(src_seg, src_wrist, src_tip) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    coef = transform(src_wrist, src_tip, dst_wrist, dst_tip)
    size = dst_img.size
    moved = src_img.convert("RGB").transform(size, Image.AFFINE, coef, resample=Image.BICUBIC)
    mm = m.transform(size, Image.AFFINE, coef, resample=Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.8))
    out = Image.fromarray(dst)
    out.paste(moved, (0, 0), mm)
    return out, int((np.asarray(mm) > 127).sum())


def point(s: str) -> tuple[float, float]:
    x, y = s.split(",")
    return float(x), float(y)


def main():
    import edit
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("out")
    for k in ("src-wrist", "src-tip", "dst-wrist", "dst-tip"):
        ap.add_argument("--" + k, type=point, required=True)
    a = ap.parse_args()
    seg_s, seg_d = np.asarray(edit.parts(a.src)), np.asarray(edit.parts(a.dst))
    out, n = graft(Image.open(a.src), seg_s, Image.open(a.dst), seg_d, a.src_wrist, a.src_tip, a.dst_wrist, a.dst_tip)
    out.save(a.out)
    print(f"{a.out}: 貼った画素 {n}")


if __name__ == "__main__":
    main()
