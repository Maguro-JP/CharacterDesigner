"""描いた絵の「当たり前」を数字で測り、基準から外れた所を挙げる。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/measure.py 絵.png [--json]

人は、目の左右がそろっている・光が一方から来る・影は光と逆の色温度になる・髪は塊で流れる、を見ただけで分かる。
ここではそれを数字にする。基準の数字は styles/anime-norms.json（出典と学び方はそちらに書く）。
目で見て気づく前に、数字の外れで見つけるための道具。数字が通っても絵として良いとは限らないので、検品の代わりにはしない。

測るもの:
- 目: 左右の面積の比、高さの差（顔の高さに対する割合）、目の線の傾き、目の間隔（顔の幅に対する割合）
- 光: 顔・髪・服それぞれの明るさの傾きから、光の来る向き（画面の上で何度か）。部位ごとの向きのずれ
- 影の色温度: 部位ごとに明るい所と暗い所の色相の差（暗い所が青寄りなら負）
- 髪: 白く飛んだ画素の割合、髪の主な色から色相が外れた画素の割合、毛の流れのそろい方（構造テンソルのコヒーレンス）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[2]
NORMS = ROOT / "styles" / "anime-norms.json"


def _hsv(rgb: np.ndarray):
    import colorsys
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, (g - b) / d % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    del colorsys
    return h % 360, s, v


def _hue_mean(h, w):
    a = np.deg2rad(h)
    return float(np.rad2deg(np.arctan2((np.sin(a) * w).sum(), (np.cos(a) * w).sum())) % 360)


def _hue_diff(a, b):
    return float((a - b + 180) % 360 - 180)


def face_mask(seg, labels):
    """顔の部位から顔だけを取る。部位分けの「顔」は首や出ている胴の肌まで含むことがある（水着の素体で頭から腰まで続いた）。
    一番上の塊を取り、上から見て幅が最も細くなる行（首のくびれ）より下を切る"""
    from scipy import ndimage
    m = ndimage.binary_fill_holes(seg == labels["face"])
    lab, n = ndimage.label(m)
    if n == 0:
        return m
    tops = [np.nonzero(lab == i)[0].min() for i in range(1, n + 1)]
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    cand = [i for i in range(n) if sizes[i] >= sizes.max() * 0.1]
    k = min(cand, key=lambda i: tops[i]) + 1
    m = lab == k
    rows = np.nonzero(m.any(1))[0]
    y0, y1 = rows.min(), rows.max()
    widths = m.sum(1)
    # 顔の幅が出そろう所（上から 30%）より下で、幅が最大の 60% を切った最初の細い所を首とみなす
    wmax = widths[y0:y0 + max(1, int((y1 - y0) * 0.5))].max()
    for y in range(y0 + int((y1 - y0) * 0.3), y1):
        if widths[y] < wmax * 0.6:
            m[y:] = False
            break
    return m


def eyes(rgb, seg, labels):
    """顔の中の暗い塊のうち大きい2つを目とみなして測る"""
    from scipy import ndimage
    face = face_mask(seg, labels)
    ys, xs = np.nonzero(face)
    if len(xs) < 200:
        return {"found": 0, "reason": "顔が小さいか読めない"}
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    fh, fw = y1 - y0 + 1, x1 - x0 + 1
    lum = rgb[..., :3].mean(-1)
    band = np.zeros_like(face)
    band[y0 + int(fh * 0.2):y0 + int(fh * 0.75), x0:x1 + 1] = True
    # 前髪は顔の部位に入らないので、目の上を髪が横切っても暗い所は肌の内側だけを見る
    area = face & band
    if area.sum() < 100:
        return {"found": 0, "reason": "目の帯が読めない"}
    thr = min(0.42, float(np.percentile(lum[area], 12)))
    dark = ndimage.binary_opening(area & (lum < thr), iterations=1)
    lab, n = ndimage.label(dark)
    if n == 0:
        return {"found": 0, "reason": "暗い塊が無い"}
    sizes = ndimage.sum(dark, lab, range(1, n + 1))
    order = np.argsort(sizes)[::-1]
    blobs = []
    for i in order[:6]:
        if sizes[i] < max(12, fh * fw * 0.002):
            break
        yy, xx = np.nonzero(lab == i + 1)
        blobs.append({"cx": float(xx.mean()), "cy": float(yy.mean()), "area": float(sizes[i]),
                      "w": float(xx.max() - xx.min() + 1), "h": float(yy.max() - yy.min() + 1)})
    # 目は横に並ぶ2つ。縦に重なるもの（眉と目、目と口）を避け、横の間隔が顔の幅の 15% 以上ある組を選ぶ
    best = None
    for i in range(len(blobs)):
        for j in range(i + 1, len(blobs)):
            a, b = blobs[i], blobs[j]
            dx, dy = abs(a["cx"] - b["cx"]), abs(a["cy"] - b["cy"])
            if dx < fw * 0.15 or dy > fh * 0.25:
                continue
            score = a["area"] + b["area"]
            if best is None or score > best[0]:
                best = (score, a, b)
    if best is None:
        return {"found": 1 if blobs else 0, "reason": "横に並ぶ2つの目が読めない"}
    _, a, b = best
    left, right = (a, b) if a["cx"] < b["cx"] else (b, a)
    # 顔の向き（ヨー）の目安: 両目の中点が顔の幅の中心からどれだけ横にずれたか（-0.5〜0.5）
    # （3D の素体を回して測ると、0° で 0.02、20° で 0.06、40° で 0.15 だった）。斜めの顔ほど遠い目は小さく、前髪に隠れる
    yaw = ((left["cx"] + right["cx"]) / 2 - xs.mean()) / fw
    return {
        "yaw_offset": round(float(yaw), 3),
        "found": 2,
        "area_ratio": round(max(left["area"], right["area"]) / max(1.0, min(left["area"], right["area"])), 2),
        "height_ratio": round(max(left["h"], right["h"]) / max(1.0, min(left["h"], right["h"])), 2),
        "dy_face": round((right["cy"] - left["cy"]) / fh, 3),
        "tilt_deg": round(float(np.degrees(np.arctan2(right["cy"] - left["cy"], right["cx"] - left["cx"]))), 1),
        "gap_face": round((right["cx"] - left["cx"]) / fw, 3),
        "eye_line": round(((left["cy"] + right["cy"]) / 2 - y0) / fh, 3),
        "left": {k: round(v, 1) for k, v in left.items()}, "right": {k: round(v, 1) for k, v in right.items()},
    }


def light(rgb, seg, labels, regions):
    """部位ごとに、明るさの傾き（明るい方へ向かう向き）を平均して光の向きを出す。0° が右、90° が上"""
    from scipy import ndimage
    lum = ndimage.gaussian_filter(rgb[..., :3].mean(-1), 3)
    gy, gx = np.gradient(lum)
    out = {}
    for name, ids in regions.items():
        m = np.isin(seg, ids)
        m = ndimage.binary_erosion(m, iterations=3)   # 縁の線（輪郭）の強い傾きを数えない
        if m.sum() < 300:
            continue
        vx, vy = float(gx[m].sum()), float(-gy[m].sum())
        mag = float(np.hypot(gx[m], gy[m]).sum())
        out[name] = {"deg": round(float(np.degrees(np.arctan2(vy, vx))) % 360, 1),
                     "strength": round(float(np.hypot(vx, vy) / max(mag, 1e-6)), 3)}
    degs = [(k, v["deg"], v["strength"]) for k, v in out.items() if v["strength"] >= 0.05]
    spread = 0.0
    for i in range(len(degs)):
        for j in range(i + 1, len(degs)):
            spread = max(spread, abs(_hue_diff(degs[i][1], degs[j][1])))
    return {"regions": out, "max_spread_deg": round(spread, 1)}


def light3d(src, rgb, seg, regions):
    """奥行きの推定から面の向き（法線）を出し、部位ごとに 明るさ = 回り込み + 法線・光 を最小二乗で当てはめて光の向きを出す。
    向きは画面の上の角度（0° が右、90° が上）と、手前への傾き（0° が画面に平行、90° が見る人の側から）。
    明るさの傾きだけで出すと前髪の落ち影などを光と取り違え、部位ごとに 160° ずれた（光ではなく影の形を拾う）"""
    import imgproc
    alpha = (seg != 0).astype(float)
    h = imgproc.height_field(str(src), alpha)
    gy, gx = np.gradient(h)
    n = np.dstack([-gx, gy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    lum = rgb[..., :3].mean(-1)
    out = {}
    from scipy import ndimage
    for name, ids in regions.items():
        m = ndimage.binary_erosion(np.isin(seg, ids), iterations=3)
        if m.sum() < 300:
            continue
        A = np.column_stack([np.ones(m.sum()), n[m]])
        coef, *_ = np.linalg.lstsq(A, lum[m], rcond=None)
        lv = coef[1:]
        fit = A @ coef
        r2 = 1 - float(((lum[m] - fit) ** 2).sum() / max(((lum[m] - lum[m].mean()) ** 2).sum(), 1e-9))
        out[name] = {"deg": round(float(np.degrees(np.arctan2(lv[1], lv[0]))) % 360, 1),
                     "toward_viewer_deg": round(float(np.degrees(np.arctan2(lv[2], np.hypot(lv[0], lv[1])))), 1),
                     "r2": round(r2, 3)}
    # 較正（3D の素体で光を 6 通り）で、左右の向きは当たるが上下は外れた。判定には左右だけを使う。
    # 当てはまりの良い部位（r2 >= 0.2）で、光がはっきり横から来る（|cos| >= 0.5）ものの右・左を数え、少ない方の数を食い違いとする
    sides = [1 if np.cos(np.radians(v["deg"])) > 0 else -1 for v in out.values()
             if v["r2"] >= 0.2 and abs(np.cos(np.radians(v["deg"]))) >= 0.5]
    conflict = min(sides.count(1), sides.count(-1))
    return {"regions": out, "side_conflict": conflict, "sided_regions": len(sides)}


def temperature(rgb, seg, regions):
    """部位ごとに、明るい半分と暗い半分の色相と彩度の差。暖かい光なら暗い所は青寄り（負）になるのが自然"""
    h, s, v = _hsv(rgb[..., :3])
    out = {}
    for name, ids in regions.items():
        m = np.isin(seg, ids) & (s > 0.08)
        if m.sum() < 300:
            continue
        med = np.median(v[m])
        lit, dark = m & (v >= med), m & (v < med)
        hl, hd = _hue_mean(h[lit], s[lit]), _hue_mean(h[dark], s[dark])
        out[name] = {"lit_hue": round(hl, 1), "shadow_hue": round(hd, 1), "shift": round(_hue_diff(hd, hl), 1),
                     "contrast": round(float(np.median(v[lit]) - np.median(v[dark])), 3)}
    return out


def hair(rgb, seg, labels):
    from scipy import ndimage
    m = seg == labels["hair"]
    if m.sum() < 300:
        return {"found": False}
    h, s, v = _hsv(rgb[..., :3])
    blown = float(((v > 0.94) & (s < 0.12) & m).sum() / m.sum())
    main = _hue_mean(h[m], s[m] * v[m])
    colored = m & (s > 0.22) & (v > 0.25)
    off = float((colored & (np.abs((h - main + 180) % 360 - 180) > 45)).sum() / m.sum())
    # 白く飛んではいないが、髪の地の色より明るく色のついた所（暖色の光で桃色に染まるなど）。
    # 髪の暗い半分の明るさの中央値を地の明るさとし、その 2 倍を超えて彩度のある画素を数える
    base_v = float(np.median(v[m][v[m] <= np.median(v[m])]))
    glow = float((m & (v > min(0.95, base_v * 2 + 0.15)) & (s > 0.15)).sum() / m.sum())
    lum = rgb[..., :3].mean(-1)
    gy, gx = np.gradient(ndimage.gaussian_filter(lum, 1.0))
    jxx, jyy, jxy = (ndimage.gaussian_filter(a, 4) for a in (gx * gx, gy * gy, gx * gy))
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / np.maximum(jxx + jyy, 1e-6)
    inner = ndimage.binary_erosion(m, iterations=4)
    return {"found": True, "blown": round(blown, 4), "main_hue": round(main, 1), "off_hue": round(off, 4), "glow": round(glow, 4), "base_v": round(base_v, 3),
            "coherence": round(float(np.median(coh[inner])) if inner.any() else 0.0, 3)}


def measure(src) -> dict:
    from PIL import Image
    import edit
    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0
    seg = np.asarray(edit.parts(src))
    L = edit.LABELS
    regions = {"face": [L["face"]], "hair": [L["hair"]], "clothes": [L["upper"], L["dress"], L["skirt"], L["pants"]],
               "arms": [L["left_arm"], L["right_arm"]], "legs": [L["left_leg"], L["right_leg"]]}
    return {"size": list(rgb.shape[1::-1]), "eyes": eyes(rgb, seg, L), "light": light3d(src, rgb, seg, regions),
            "temperature": temperature(rgb, seg, regions), "hair": hair(rgb, seg, L)}


def _get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def judge(m: dict, norms: dict | None = None) -> list[dict]:
    """基準（norms の checks）から外れた数字を挙げる。各行は 何を・値・基準・意味"""
    norms = norms or json.loads(NORMS.read_text(encoding="utf-8"))
    out = []
    for c in norms["checks"]:
        w = c.get("when")
        if w:
            wv = _get(m, w["path"])
            if wv is None or not (w.get("min", -1e9) <= abs(wv) < w.get("max", 1e9)):
                continue
        v = _get(m, c["path"])
        if v is None:
            continue
        x = abs(v) if c.get("abs") else v
        lo, hi = c.get("min"), c.get("max")
        if (lo is not None and x < lo) or (hi is not None and x > hi):
            out.append({"path": c["path"], "value": v, "min": lo, "max": hi, "means": c["means"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    for src in a.src:
        m = measure(src)
        bad = judge(m) if NORMS.exists() else []
        if a.json:
            print(json.dumps({"src": src, "measure": m, "outliers": bad}, ensure_ascii=False))
            continue
        print(f"== {src}")
        print(json.dumps(m, ensure_ascii=False, indent=1))
        for b in bad:
            print(f"外れ: {b['path']} = {b['value']}（基準 {b['min']}〜{b['max']}）{b['means']}")
        if not bad:
            print("外れ: なし")


if __name__ == "__main__":
    main()
