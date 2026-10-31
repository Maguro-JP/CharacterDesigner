"""背景のパース（遠近）を測る。直線を拾い、消失点に集まっているか・縦の線が立っているかを数字にする。

背景を描かせると、建物の線がばらばらの点へ向かう（消失点が 1 つにまとまらない）、柱が傾く、
2 点透視の 2 つの消失点が別の高さにある（地平線が 2 本ある）、という崩れが出る。
人は「なんとなく歪んでいる」と感じるだけだが、直線の向きを集めれば数字で見つけられる。

測るもの:
- vertical_tilt: 縦の線の傾きの中央値（度）。目の高さのカメラでは 0 に近いはず
- vp: 消失点（画面に対する割合。画面の外もあり得る）と、そこへ集まる線の数
- converge: 奥へ向かう線（長さの和）のうち、どれかの消失点に集まる割合。低いとパースが崩れている
- horizon_gap: 消失点が 2 つあるとき、その高さの差（画面の高さに対する割合）。大きいと地平線が 2 本
- horizon: 消失点の高さから出した地平線（画面の上から割合）

  PYTHONPATH=.cache/gen/lib python3 tools/gen/perspective.py 背景.png [重ねた図.png]   数字を出し、図を渡すと消失点への線を重ねて書く
"""
from __future__ import annotations

import json
import sys

import numpy as np
from PIL import Image, ImageDraw

SIDE = 512          # 測る大きさ。直線の向きは縮めても変わらず、Hough の票の計算が速くなる


def _segments(im: Image.Image):
    """線分を拾う（Canny の輪郭に確率的 Hough）。戻り値は [(x0, y0, x1, y1, 長さ)]。
    無限に伸びる直線の Hough では、雪や石の模様の票が建物の線より強くなり、消失点がでたらめな所に出た。
    長さのある線分を拾い、長さで重みを付ける"""
    from skimage.feature import canny
    from skimage.transform import probabilistic_hough_line
    g = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    e = canny(g, sigma=2.0)
    h, w = g.shape
    segs = probabilistic_hough_line(e, threshold=10, line_length=max(h, w) // 12, line_gap=3, rng=0)
    return [(x0, y0, x1, y1, float(np.hypot(x1 - x0, y1 - y0))) for (x0, y0), (x1, y1) in segs], (h, w)


def _intersect(a, b):
    """2 本の線分を伸ばした直線の交点"""
    p = np.cross([a[0], a[1], 1.0], [a[2], a[3], 1.0])
    q = np.cross([b[0], b[1], 1.0], [b[2], b[3], 1.0])
    x = np.cross(p, q)
    if abs(x[2]) < 1e-9:
        return None
    return x[:2] / x[2]


def _through(sg, p, tol_deg=2.0):
    """線分が点 p へ向かっているか。線分の向きと、線分の中点から p への向きの差で見る"""
    d = np.array([sg[2] - sg[0], sg[3] - sg[1]]) / max(sg[4], 1e-6)
    v = p - np.array([(sg[0] + sg[2]) / 2, (sg[1] + sg[3]) / 2])
    n = np.linalg.norm(v)
    if n < 1:
        return True
    return np.degrees(np.arcsin(min(1.0, abs(d[0] * v[1] - d[1] * v[0]) / n))) < tol_deg


def measure(im: Image.Image) -> dict:
    s = SIDE / max(im.size)
    small = im.convert("RGB").resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BILINEAR)
    lines, (h, w) = _segments(small)
    vert, recede = [], []
    for sg in lines:
        ang = np.degrees(np.arctan2(sg[3] - sg[1], sg[2] - sg[0])) % 180   # 0 = 横、90 = 縦
        if abs(ang - 90) < 10:
            vert.append(ang - 90)
        elif 8 < ang < 172 and abs(ang - 90) > 10 and min(ang, 180 - ang) > 8:
            recede.append(sg)
    rng = np.random.default_rng(0)
    vps, left = [], list(recede)
    for _ in range(2):
        best, best_in = None, []
        for _ in range(300):
            if len(left) < 2:
                break
            i, j = rng.choice(len(left), 2, replace=False)
            p = _intersect(left[i], left[j])
            if p is None:
                continue
            inl = [ln for ln in left if _through(ln, p)]
            # 線の数でなく長さの和で選ぶ。数で選ぶと、短い模様の線が偶然集まる点を消失点にした
            if sum(ln[4] for ln in inl) > sum(ln[4] for ln in best_in):
                best, best_in = p, inl
        if best is None or len(best_in) < 3:
            break
        vps.append({"x": round(float(best[0] / w), 3), "y": round(float(best[1] / h), 3), "lines": len(best_in),
                    "length": round(sum(ln[4] for ln in best_in), 1)})
        left = [ln for ln in left if not any(ln is b for b in best_in)]
    used = sum(v["length"] for v in vps)
    total = sum(sg[4] for sg in recede)
    out = {
        "lines": len(lines), "vertical": len(vert), "receding": len(recede),
        "vertical_tilt": round(float(np.median(np.abs(vert))), 2) if vert else None,
        "vp": vps,
        "converge": round(used / total, 3) if recede else None,
        "horizon": round(float(np.mean([v["y"] for v in vps])), 3) if vps else None,
        "horizon_gap": round(abs(vps[0]["y"] - vps[1]["y"]), 3) if len(vps) == 2 else None,
    }
    return out


def overlay(im: Image.Image, m: dict, out: str):
    """消失点から放射状の線と地平線を重ねた図。数字を目で確かめるため"""
    im = im.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    W, H = im.size
    for v, col in zip(m["vp"], ((255, 40, 40), (40, 120, 255))):
        p = (v["x"] * W, v["y"] * H)
        for k in range(24):
            a = k * np.pi / 12
            d.line([p, (p[0] + np.cos(a) * 3 * W, p[1] + np.sin(a) * 3 * W)], fill=col, width=1)
    if m["horizon"] is not None:
        y = m["horizon"] * H
        d.line([(0, y), (W, y)], fill=(255, 200, 0), width=3)
    im.save(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    im = Image.open(sys.argv[1])
    m = measure(im)
    print(json.dumps(m, ensure_ascii=False))
    if len(sys.argv) > 2:
        overlay(im, m, sys.argv[2])
