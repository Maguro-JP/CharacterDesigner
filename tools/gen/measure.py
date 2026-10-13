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
    # 首は顔の幅が出そろった行より下にある。前髪が額を覆うと上の方の幅が細く、30% の行から探すと額を首と取って
    # 顔の上の端だけが残った（顔の高さ 87 行が 26 行になり、目が見つからなかった）
    full = next(y for y in range(y0, y1 + 1) if widths[y] >= wmax * 0.9)
    for y in range(max(y0 + int((y1 - y0) * 0.3), full), y1):
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
    # まつ毛と瞳は肌の影より暗い。割合（下から 12%）だけで決めると、横からの光で影の側の肌まで目に入った。
    # 明るさの絶対値で切ると、逆光で顔全体が暗いときに影の肌まで入る。顔の明るさの中央値に対する割合で切る
    thr = min(float(np.percentile(lum[area], 8)), 0.45 * float(np.median(lum[area])))
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
    # 影の向きの順序: 絵全体の主な光の左右（当てはまりの良さで重みづけした多数決）を決め、部位ごとに、同じ色の素材の中で
    # 光に向いた面（法線の横の成分が光の側に 0.25 以上）と背を向けた面（反対側に 0.25 以上）の明るさの中央値を比べる。
    # 背を向けた面が明るいのは、照り返しなどの別の条件が無い限り自然ではあり得ない（逆の値が order に出る）
    wsum = sum(np.sign(np.cos(np.radians(v["deg"]))) * max(v["r2"], 0) for v in out.values())
    order = {}
    if abs(wsum) >= 0.2:
        side = 1.0 if wsum > 0 else -1.0
        h_, s_, v_ = _hsv(rgb[..., :3])
        for name, ids in regions.items():
            m = ndimage.binary_erosion(np.isin(seg, ids), iterations=3)
            if m.sum() < 300:
                continue
            nx = n[..., 0] * side
            # 素材を色相でまとめる（彩度の低い所は 1 つの組）。組ごとに明暗を比べ、画素の多い組の結果を採る
            hue_bin = np.where(s_ > 0.15, (h_ // 45).astype(int), -1)
            best = None
            for hb in np.unique(hue_bin[m]):
                mm = m & (hue_bin == hb)
                lit, away = mm & (nx > 0.25), mm & (nx < -0.25)
                if lit.sum() < 80 or away.sum() < 80:
                    continue
                d = float(np.median(lum[lit]) - np.median(lum[away]))
                if best is None or mm.sum() > best[1]:
                    best = (d, int(mm.sum()))
            if best:
                order[name] = round(best[0], 3)
    inverted = [k for k, d in order.items() if d < -0.03]
    return {"regions": out, "side_conflict": conflict, "sided_regions": len(sides),
            "key_side": None if abs(wsum) < 0.2 else ("right" if wsum > 0 else "left"), "order": order, "inverted": len(inverted),
            "inverted_regions": inverted}


def face_spots(lum, fm):
    """顔の中の、肌に囲まれた白い点を探す。返すのは（最大の点の面積 ÷ 顔の面積、点の全部の範囲）。
    目のハイライトは暗い瞳に囲まれるので数えない（点の周り 3 画素の暗い側が、顔の明るさの中央値の 0.85 倍未満なら目とみなす。
    目のハイライトは 0.39〜0.75、鼻筋の点は 0.9〜1.11）"""
    from scipy import ndimage
    f = ndimage.binary_erosion(fm, iterations=2)
    spots = np.zeros_like(fm, dtype=bool)
    if f.sum() < 100:
        return 0.0, spots
    med = float(np.median(lum[f]))
    b = f & (lum > min(0.97, med * 1.5))
    lab, n = ndimage.label(b)
    best = 0
    for i in range(1, n + 1):
        bl = lab == i
        ring = ndimage.binary_dilation(bl, iterations=3) & ~bl
        if np.percentile(lum[ring], 10) >= med * 0.85:
            best = max(best, int(bl.sum()))
            spots |= bl
    return round(best / float(f.sum()), 4), spots


def scene_light(rgb, seg, labels=None):
    """背景の光と人物の照らされ方を比べる数字。
    bg_dx: 背景の最も明るい 3% の重心が、人物の中心から横にどれだけずれているか（人物の幅で割る。0 付近なら真後ろ）
    interior: 人物の内側の明るさの中央値 ÷ 背景の明るい所（97 パーセンタイル）
    rim: 人物の輪郭の内側の細い帯の明るい側 ÷ 内側の明るさ。逆光なら縁が明るく 1 を大きく超える"""
    from scipy import ndimage
    lum = rgb[..., :3].mean(-1)
    fig = seg != 0
    if fig.sum() < 1000 or (~fig).sum() < 1000:
        return {"found": False}
    ys, xs = np.nonzero(fig)
    fx0, fx1 = xs.min(), xs.max()
    fw = fx1 - fx0 + 1
    bg = ~ndimage.binary_dilation(fig, iterations=6)
    # 光源（窓・光の筋）は人物の後ろに隠れて見えている所が小さいことがある。上位 3% では窓を取り逃したので、
    # 位置は上位 3% の重心、明るさは上位 0.5% で取る
    top = bg & (lum >= float(np.percentile(lum[bg], 97)))
    hi = float(np.percentile(lum[bg], 99.5))
    by, bx = np.nonzero(top)
    # 縁の光は細い。帯を太く取ると中央値に埋もれたので、幅の 1.5% の帯の明るい側（90 パーセンタイル）で測る
    band = max(2, int(fw * 0.015))
    inner = ndimage.binary_erosion(fig, iterations=band)
    edge = fig & ~inner
    inside = float(np.median(lum[inner])) if inner.any() else float(np.median(lum[fig]))
    # 顔の明るさ ÷ 人物の明るい所（95 パーセンタイル）。逆光なら顔は影に入り低くなる。人物の内側の平均だけでは、
    # 金属の鎧の照り返しや真っ白な窓に紛れて、正面から照らされた顔を見逃した
    face_lit = None
    face_spot = 0.0
    if labels is not None:
        fm = face_mask(seg, labels)
        if fm.sum() > 100:
            face_lit = round(float(np.median(lum[fm])) / max(float(np.percentile(lum[fig], 95)), 1e-6), 3)
            face_spot = face_spots(lum, fm)[0]
    # 逆光の場面なのに顔が正面から照らされている: 背景にはっきりした光源があり（明るい所が背景の中央値の 1.5 倍超）、
    # それが人物の後ろ（横のずれが人物の幅の半分以内）にあり、顔が人物の明るい所の 0.88 倍を超えて明るい。
    # 較正: 正面から照らした素体 0.97〜0.98、逆光の素体 0.52〜0.61、検品で戻した外部の生成と手元の騎士 0.967・0.979
    contrast = hi / max(float(np.median(lum[bg])), 1e-6)
    dx = float((bx.mean() - (fx0 + fx1) / 2) / fw)
    backlit = contrast > 1.5 and abs(dx) <= 0.5
    backlit_front = int(face_lit is not None and backlit and face_lit > 0.88)
    # 逆光なのに顔の真ん中（鼻筋など）に白い光の点がある。顔の 0.2% 以上の点を数える。
    # 較正: 下絵ありの逆光の騎士 3 枚 0.0069・0.0042・0.003（鼻筋の点）、点の無い逆光の騎士 0、外部の生成の騎士 0.0006
    backlit_spot = int(backlit and face_spot >= 0.002)
    return {"found": True, "face_lit": face_lit, "face_spot": face_spot, "backlit_spot": backlit_spot, "bg_contrast": round(contrast, 2), "backlit_front": backlit_front, "bg_dx": round(float((bx.mean() - (fx0 + fx1) / 2) / fw), 3),
            "bg_dy": round(float((by.mean() - ys.min()) / (ys.max() - ys.min() + 1)), 3),
            "bg_bright": round(hi, 3), "interior": round(inside / max(hi, 1e-6), 3),
            "rim": round(float(np.percentile(lum[edge], 90)) / max(inside, 1e-6), 3)}


def pairs(rgb, seg, labels):
    """左右の対（靴、腕）を比べる。片手だけ籠手、左右で形の違う靴などの食い違いを見つけるため。
    色: 平均の色の差（0〜1 の RGB の距離）。面積: 大きい方 ÷ 小さい方。形: 縦横の比の比。
    部位分けは左右を取り違えたり一部を落としたりする（左右のそろった素体でも腕の面積の比が 3.8 になった）ので、
    面積と形は判定に使わない。色の差は、そろった絵で 0.03〜0.06、左右で違う靴の外部の生成で 0.116。
    手本が 1 枚しか無いので、境は最初は判定しない値に置き、判定と指摘（normlearn）が溜まったら学んで締める"""
    out = {}
    for name, (a, b) in {"shoes": ("left_shoe", "right_shoe"), "arms": ("left_arm", "right_arm")}.items():
        ma, mb = seg == labels[a], seg == labels[b]
        if ma.sum() < 150 or mb.sum() < 150:
            continue
        def shape(m):
            ys, xs = np.nonzero(m)
            return (ys.max() - ys.min() + 1) / (xs.max() - xs.min() + 1)
        ca, cb = rgb[ma][:, :3].mean(0), rgb[mb][:, :3].mean(0)
        sa, sb = shape(ma), shape(mb)
        out[name] = {"color": round(float(np.linalg.norm(ca - cb)), 3),
                     "area": round(float(max(ma.sum(), mb.sum()) / min(ma.sum(), mb.sum())), 2),
                     "shape": round(float(max(sa, sb) / min(sa, sb)), 2)}
    return out


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


def hair(rgb, seg, labels, spec: str = ""):
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
    spec_off = None
    if spec:
        # 指定の髪の色（例 #1e1a24）と比べる。光が当たれば明るくなるのは当然なので、明るさは 0.45 まで、
        # 色相は 40° までのずれを許し、それを超えて色のある画素（黒髪が桃色や白に染まるなど）を数える。
        # 色はカンマで複数渡せる（地の色とインナーカラーなど）。どれか1色に近ければ外れにしない
        # （1色だけで比べると、頼んだとおりのインナーカラーまで外れに数えた）
        far = np.ones_like(m)
        for one in [c.strip() for c in spec.split(",") if c.strip()]:
            sr, sg, sb = (int(one[i:i + 2], 16) / 255 for i in (1, 3, 5))
            hs, ss, vs = (x.item() for x in _hsv(np.array([[sr, sg, sb]], dtype=np.float32)))
            far_v = v > vs + 0.45
            far_h = (s > 0.25) & (ss > 0.15) & (np.abs((h - hs + 180) % 360 - 180) > 40)
            far_h_dark = (s > 0.25) & (ss <= 0.15)   # 色の無い髪（黒・白・灰）に色がついた
            far &= far_v | far_h | far_h_dark
        spec_off = float((m & far).sum() / m.sum())
    return {"found": True, "blown": round(blown, 4), "main_hue": round(main, 1), "off_hue": round(off, 4), "glow": round(glow, 4), "base_v": round(base_v, 3),
            "spec_off": None if spec_off is None else round(spec_off, 4),
            "coherence": round(float(np.median(coh[inner])) if inner.any() else 0.0, 3)}


def measure(src, hair_color: str = "") -> dict:
    from PIL import Image
    import edit
    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0
    seg = np.asarray(edit.parts(src))
    L = edit.LABELS
    regions = {"face": [L["face"]], "hair": [L["hair"]], "clothes": [L["upper"], L["dress"], L["skirt"], L["pants"]],
               "arms": [L["left_arm"], L["right_arm"]], "legs": [L["left_leg"], L["right_leg"]]}
    import faceform
    lm = faceform.landmarks(rgb, seg, L)
    face = faceform.fit(lm["points"], json.loads(faceform.TEMPLATE.read_text())["points"]) if "points" in lm and faceform.TEMPLATE.exists() else lm
    return {"size": list(rgb.shape[1::-1]), "eyes": eyes(rgb, seg, L), "face": face, "light": light3d(src, rgb, seg, regions),
            "temperature": temperature(rgb, seg, regions), "scene": scene_light(rgb, seg, L), "pairs": pairs(rgb, seg, L), "hair": hair(rgb, seg, L, hair_color)}


def _get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


USER_NORMS = ROOT / "config" / "norms.user.json"


def load_norms() -> dict:
    """共通の基準に、利用者の判定から学んだ基準（config/norms.user.json、normlearn.py learn が書く）を重ねる。
    同じ path（と when）の基準は利用者の方を使う。壊れていれば共通の基準だけで判定する"""
    base = json.loads(NORMS.read_text(encoding="utf-8"))
    try:
        user = json.loads(USER_NORMS.read_text(encoding="utf-8")) if USER_NORMS.exists() else {"checks": []}
    except ValueError:
        return base
    key = lambda c: (c["path"], json.dumps(c.get("when"), sort_keys=True))
    over = {key(c): c for c in user.get("checks", [])}
    base["checks"] = [over.get(key(c), c) for c in base["checks"]]
    return base


def judge(m: dict, norms: dict | None = None) -> list[dict]:
    """基準（norms の checks）から外れた数字を挙げる。各行は 何を・値・基準・意味"""
    norms = norms or load_norms()
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
    ap.add_argument("--hair", default="", help="指定の髪の色（#rrggbb。インナーカラーなどはカンマで並べる）。渡すと、髪がその色から外れた割合を判定する")
    a = ap.parse_args()
    for src in a.src:
        m = measure(src, a.hair)
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
