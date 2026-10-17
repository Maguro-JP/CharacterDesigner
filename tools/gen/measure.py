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
- 背景: 四隅の明るさと彩度（white background を頼んだ絵だけ判定する）
- 作風: タグを読む模型の realistic / photorealistic の確からしさ（写実に寄りすぎた絵を外れにする）
"""
from __future__ import annotations

import argparse
import json
import re
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
    m = seg == labels["face"]
    # 顔を横切る前髪の細い束で、顔が2つの塊に割れる（頭を拡大して部位分けすると束まで分かれて出た）。束の太さ程度を閉じてつなぐ
    k = max(1, int(np.sqrt(m.sum()) * 0.04))
    m = ndimage.binary_fill_holes(ndimage.binary_closing(np.pad(m, k), iterations=k)[k:-k, k:-k])
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


def iris_color(rgb, blob):
    """目の塊のまわりで、枠の中央値より暗い画素（瞳とまつ毛）の色を (彩度, R/平均, G/平均, B/平均) で返す。
    彩度の高い画素だけを見ると灰色の瞳が抜け、茶と灰の左右違いを見逃した。明るさで割って、光の当たり方の差は消す"""
    x0, x1 = int(blob["cx"] - blob["w"] * 0.6), int(blob["cx"] + blob["w"] * 0.6)
    # 細いまつ毛の塊（高さ 9、幅 12〜36）では、高さだけで枠を決めるとまつ毛しか入らず、すぐ下の瞳を測らなかった。
    # 下へは目の幅の 6 割まで広げる（丸い目では高さの 8 割と同じくらい）
    y0, y1 = int(blob["cy"] - blob["h"] * 0.8), int(blob["cy"] + max(blob["h"] * 0.8, blob["w"] * 0.6))
    p = rgb[max(0, y0):max(0, y1), max(0, x0):max(0, x1), :3].reshape(-1, 3)
    if len(p) < 5:
        return None
    _, _, v = _hsv(p)
    q = p[(v > 0.12) & (v < np.median(v))]
    if len(q) < 5:
        return None
    _, s, _ = _hsv(q)
    mean = q.mean(0)
    return np.array([s.mean(), *(mean / max(float(mean.mean()), 1e-3))])


def iris_delta(rgb, left, right):
    """左右の瞳の色の差（iris_color の各成分の差の最大）。読めなければ None"""
    a, b = iris_color(rgb, left), iris_color(rgb, right)
    return None if a is None or b is None else round(float(np.abs(a - b).max()), 3)


def eyes(rgb, seg, labels, hint=None):
    """顔の中の暗い塊のうち大きい2つを目とみなして測る。hint（骨格の点の両目の位置、この絵の座標）があれば、
    それぞれに一番近い塊を目とする。斜めの顔では遠い目が小さく、顔の縁の髪の筋（幅 12、高さ 37）を左目として拾い、
    髪の色と瞳の色を比べて、そろった紫の目を「瞳の色が違う」と 28 通り落とした（2026-10-16）。骨格の点の目は、
    検品担当が見た目の位置と 3 枚とも 10 画素以内で合った"""
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
    for i in order[:12 if hint else 6]:
        if sizes[i] < max(12, fh * fw * 0.002):
            break
        yy, xx = np.nonzero(lab == i + 1)
        blobs.append({"cx": float(xx.mean()), "cy": float(yy.mean()), "area": float(sizes[i]),
                      "w": float(xx.max() - xx.min() + 1), "h": float(yy.max() - yy.min() + 1)})
    best = None
    if hint:
        near = max(10.0, fw * 0.15)
        picked = []
        for hx, hy in hint:
            c = min(blobs, key=lambda b: (b["cx"] - hx) ** 2 + (b["cy"] - hy) ** 2, default=None)
            if c is None or ((c["cx"] - hx) ** 2 + (c["cy"] - hy) ** 2) ** 0.5 > near or c in picked:
                return {"found": len(picked), "reason": "骨格の点の目の近くに目の塊が無い"}
            picked.append(c)
        best = (0, picked[0], picked[1])
    # 目は横に並ぶ2つ。縦に重なるもの（眉と目、目と口）を避け、横の間隔が顔の幅の 15% 以上ある組を選ぶ
    for i in range(len(blobs) if best is None else 0):
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
        "iris_delta": iris_delta(rgb, left, right),
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
    # 主な光の左右も、食い違いと同じ部位（r2 >= 0.2 で光が横から来る）だけで決める。どの部位も当てはまらない柔らかい光の絵
    # （3101、r2 0.06〜0.2、ほぼ真下を向いた腕）で左右を決め、服の左右の明るさの差 0.033 を影の逆転と取り違えた
    wsum = sum(np.sign(np.cos(np.radians(v["deg"]))) * v["r2"] for v in out.values()
               if v["r2"] >= 0.2 and abs(np.cos(np.radians(v["deg"]))) >= 0.5)
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
    dy = float((by.mean() - ys.min()) / (ys.max() - ys.min() + 1))
    # contrast は背景の中央値で割るので、暗い背景・むらのある灰色の背景では、足元の床の照り返しや光の輪でも 1.5 を超えた
    # （正面から照らした 2 枚で、明るい所の重心が人物の高さの 0.63・0.99）。人物の後ろの光源は人物の上半分（bg_dy 0.5 以下）にあるものだけにする。
    # 光源の明るさ ÷ 顔の明るさでは分けない: 窓が人物に隠れて見える所が小さいと、窓の方が顔より暗く測れる
    source = dy <= 0.5
    backlit = contrast > 1.5 and abs(dx) <= 0.5 and source
    backlit_front = int(face_lit is not None and backlit and face_lit > 0.88)
    # 逆光なのに顔の真ん中（鼻筋など）に白い光の点がある。顔の 0.2% 以上の点を数える。
    # 較正: 下絵ありの逆光の騎士 3 枚 0.0069・0.0042・0.003（鼻筋の点）、点の無い逆光の騎士 0、外部の生成の騎士 0.0006
    backlit_spot = int(backlit and face_spot >= 0.002)
    return {"found": True, "face_lit": face_lit, "face_spot": face_spot, "backlit_spot": backlit_spot, "bg_contrast": round(contrast, 2), "backlit_front": backlit_front, "bg_dx": round(float((bx.mean() - (fx0 + fx1) / 2) / fw), 3),
            "bg_dy": round(dy, 3),
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


# 髪の色の照合で、色相と彩度を読む明るさの下限。これより暗い画素は色が見えないので、明るさのずれだけで見る
SPEC_SEEN_V = 0.3


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
            # 色相と彩度は、明るさが SEEN_V 以上の画素でだけ読む。ほぼ黒の画素は (max-min)/max の彩度が
            # 少しの揺れで跳ね、色相も定まらない。光の帯を入れずに塗りつぶした黒髪は、髪の 5〜8 割がこの
            # ほぼ黒の画素になり、指定どおりの黒髪を 0.62〜0.84 の外れと読んでいた
            seen = v > SPEC_SEEN_V
            far_h = seen & (s > 0.25) & (ss > 0.15) & (np.abs((h - hs + 180) % 360 - 180) > 40)
            far_h_dark = seen & (s > 0.25) & (ss <= 0.15)   # 色の無い髪（黒・白・灰）に色がついた
            far &= far_v | far_h | far_h_dark
        spec_off = float((m & far).sum() / m.sum())
    return {"found": True, "blown": round(blown, 4), "main_hue": round(main, 1), "off_hue": round(off, 4), "glow": round(glow, 4), "base_v": round(base_v, 3),
            "spec_off": None if spec_off is None else round(spec_off, 4),
            "coherence": round(float(np.median(coh[inner])) if inner.any() else 0.0, 3)}


def _eye_hint(points, view, least: float = 0.5):
    """骨格の点の両目を、測る絵（切り出していれば切り出しの座標）に直す。確からしさが least 未満なら None"""
    if not points:
        return None
    p = {q["name"]: q for q in points}
    if any(p.get(n, {}).get("score", 0) < least for n in ("left_eye", "right_eye")):
        return None
    box, k = view.get("box"), view.get("k", 1.0)
    ox, oy = (box[0], box[1]) if box else (0, 0)
    return [((p[n]["x"] - ox) * k, (p[n]["y"] - oy) * k) for n in ("left_eye", "right_eye")]


def background(rgb, prompt: str = ""):
    """四隅（短い辺の 5% の正方形）の明るさと彩度。corner_lum は4隅の中央値の最も暗いもの、corner_sat は最も色づいたもの。
    人物が隅にかかる絵もあるので、平均ではなく中央値で取る。asked_white は頼んだ言葉に white background があるか"""
    h, w = rgb.shape[:2]
    s = max(8, int(min(h, w) * 0.05))
    cs = [rgb[:s, :s], rgb[:s, -s:], rgb[-s:, :s], rgb[-s:, -s:]]
    lum = min(float(np.median(c[..., :3].mean(-1))) for c in cs)
    sat = max(float(np.median(c[..., :3].max(-1) - c[..., :3].min(-1))) for c in cs)
    return {"asked_white": int("white background" in prompt.lower()), "corner_lum": round(lum, 3), "corner_sat": round(sat, 3)}


def style(tags: dict | None):
    """写実への寄り: タグを読む模型の realistic と photorealistic の大きい方。タグが読めなければ found False"""
    if tags is None:
        return {"found": False}
    return {"found": True, "realism": round(max(float(tags.get("realistic", 0)), float(tags.get("photorealistic", 0))), 3)}


# 頼んだ言葉の「色 + 物」と、タグの模型が読んだ「色 + 物」を照合する表。物は小さく始め、タグの名前（靴は footwear）に合わせる
COLOR_ITEMS = {"skirt": "skirt", "sweater": "sweater", "boots": "footwear", "eyes": "eyes", "hair": "hair"}
COLORS = ("black", "white", "grey", "brown", "red", "orange", "yellow", "green", "blue", "aqua", "purple", "pink", "blonde", "silver")
# タグに無い色の名前を、タグの色に寄せる（navy は blue skirt として読まれる）
COLOR_ALIAS = {"navy": "blue", "gray": "grey", "cyan": "aqua", "violet": "purple", "beige": "brown", "golden": "blonde", "blond": "blonde"}
# 頼んだ色のタグがこれ未満で、別の色のタグがこれ以上なら食い違い。白いスカートは 0.18 でしか読まれなかったので低めに置く。
# 頼んだ色も 0.1 以上で読まれていれば、濃い茶と黒のような近い色の揺れとみなして数えない
COLOR_ASKED_MIN = 0.1
COLOR_OTHER_MIN = 0.15


def asked_colors(prompt: str) -> list[tuple[str, str]]:
    """頼んだ言葉から（色, 物）を拾う。dark / light などの前置きは外し、最後の色の語を取る"""
    out = []
    for part in prompt.lower().split(","):
        words = part.replace("-", " ").split()
        for i, w in enumerate(words):
            if w in COLOR_ITEMS and i > 0:
                c = COLOR_ALIAS.get(words[i - 1], words[i - 1])
                if c in COLORS:
                    out.append((c, w))
    return out


def colors(prompt: str, tags: dict | None):
    """頼んだ色・髪の長さと髪型と、描かれたものの食い違い。mismatch は食い違った物の数、items はその中身（頼んだ色・読めた色・確からしさ）。
    タグが読めなければ found False。tags は閾値で絞る前のもの（0.35 で絞ると白いスカート 0.18 を落とした）"""
    if tags is None:
        return {"found": False}
    items = []
    asked = asked_colors(prompt)
    for c, it in asked:
        name = COLOR_ITEMS[it]
        got = float(tags.get(f"{c} {name}", 0))
        other = max(((float(tags.get(f"{o} {name}", 0)), o) for o in COLORS if o != c), default=(0.0, ""))
        if got < COLOR_ASKED_MIN and other[0] >= COLOR_OTHER_MIN:
            items.append({"item": it, "asked": c, "seen": other[1], "score": round(other[0], 3)})
    styles = asked_hair_styles(prompt)
    items += hair_style_items(prompt, tags)
    return {"found": True, "asked": len(asked) + len(styles), "mismatch": len(items), "items": items}


# 頼んだ髪の長さ・髪型と、タグの模型が読んだ髪型の照合。頼んだ言葉 → それと両立しないタグ。
# 長い下ろし髪とまとめ髪・短い髪は両立しない。逆向き（短い髪・まとめ髪を頼んで長い下ろし髪）も同じ形で持つ
_LONG = ("long hair", "very long hair", "absurdly long hair", "hair down")
_SHORT = ("short hair", "very short hair", "bob cut")
_UP = ("hair bun", "single hair bun", "double bun", "ponytail", "updo", "twintails")
HAIR_STYLE_CONFLICT = {**{a: _SHORT + _UP for a in _LONG}, **{a: ("long hair", "very long hair", "hair down") for a in _SHORT},
                       **{a: ("hair down",) for a in _UP}}
# 両立しないタグがこれ以上なら食い違い（506 のまとめ髪 hair bun 0.385、508 のボブ short hair 0.601）
HAIR_STYLE_STRONG = 0.3
# 頼んだタグ自体が弱い（これ未満）ときは、両立しないタグが HAIR_STYLE_WEAK 以上でも食い違いとする
# （505 のまとめ髪は long hair 0.323 に short hair 0.131 と ponytail 0.105 で、強く出たタグが無かった）
HAIR_STYLE_ASKED_MIN = 0.5
HAIR_STYLE_WEAK = 0.1


def asked_hair_styles(prompt: str) -> list[str]:
    """頼んだ言葉から髪の長さ・髪型の語を拾う。long black hair のように色が挟まっても long hair として拾う"""
    out = []
    for part in prompt.lower().split(","):
        words = [w for w in part.replace("-", " ").split() if w not in COLORS and w not in COLOR_ALIAS and w not in ("dark", "light", "straight", "wavy", "silky")]
        text = " ".join(words)
        for a in sorted(HAIR_STYLE_CONFLICT, key=len, reverse=True):
            if re.search(r"\b" + a + r"\b", text):
                if a not in out:
                    out.append(a)
                break
    return out


def hair_style_items(prompt: str, tags: dict) -> list[dict]:
    items = []
    for a in asked_hair_styles(prompt):
        got = float(tags.get(a, 0))
        if a in ("hair down", "very long hair", "absurdly long hair"):
            got = max(got, float(tags.get("long hair", 0)))
        score, seen = max(((float(tags.get(c, 0)), c) for c in HAIR_STYLE_CONFLICT[a]), default=(0.0, ""))
        if score >= HAIR_STYLE_STRONG or (got < HAIR_STYLE_ASKED_MIN and score >= HAIR_STYLE_WEAK):
            items.append({"item": "hairstyle", "asked": a, "seen": seen, "score": round(score, 3)})
    return items


def hands_pose(points, prompt: str, seen: float = 0.5) -> dict:
    """頼んだ手の姿勢（hands behind back）が描けているか。骨格の点（tools/gen/joints.py）の手首と肩・腰から測る。
    手を後ろに回すと、手首は胴に隠れて確からしさが下がるか、腰の幅の内側に来る。見えている手首（seen 以上）が
    腰の幅からどれだけ外へ出ているかを、肩の幅で割った値の大きい方を behind_out にする（0 なら両手とも胴の内側か隠れている）。
    頼んでいない絵、骨格が読めない絵では None（判定しない）"""
    low = (prompt or "").lower()
    if "hands behind back" not in low and "arms behind back" not in low:
        return {"asked": None, "behind_out": None}
    if not points:
        return {"asked": "hands behind back", "behind_out": None}
    p = {q["name"]: q for q in points}
    sw = abs(p["left_shoulder"]["x"] - p["right_shoulder"]["x"])
    if sw <= 0 or min(p[k]["score"] for k in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")) < seen:
        return {"asked": "hands behind back", "behind_out": None}
    lo, hi = sorted((p["left_hip"]["x"], p["right_hip"]["x"]))
    outs = []
    for s in ("left", "right"):
        w = p[s + "_wrist"]
        outs.append(0.0 if w["score"] < seen else max(0.0, lo - w["x"], w["x"] - hi) / sw)
    return {"asked": "hands behind back", "behind_out": round(float(max(outs)), 3), "wrists": [round(v, 3) for v in outs]}


ADULT_WORDS = ("adult", "woman", "women", "mature", "man ", "lady")


def proportion(points, seg, prompt: str, seen: float = 0.3) -> dict:
    """頭身。人物の上端（部位分けの背景でない所）から目の高さまでを頭の半分とみなし、人物の上端から下端までをその2倍で割る。
    頭の大きさを顔の部位の幅で取ると横向きで狭くなり、目の間で取ると横向きで縮むので、縦の長さだけで測る。
    帽子が高いと小さく出るが、外れる向き（大人を子どもと見る）は検品で戻す側なので許す。
    目・足首の点が読めない絵（seen 未満）では None。adult は頼んだ言葉に大人の語があるか"""
    low = " " + (prompt or "").lower() + " "
    adult = any(w in low for w in ADULT_WORDS)
    if not points or seg is None:
        return {"adult": adult, "heads": None}
    p = {q["name"]: q for q in points}
    if min(p[k]["score"] for k in ("left_eye", "right_eye", "left_ankle", "right_ankle")) < seen:
        return {"adult": adult, "heads": None}
    ys = np.nonzero((np.asarray(seg) != 0).any(axis=1))[0]
    if not len(ys):
        return {"adult": adult, "heads": None}
    top, bot = float(ys.min()), float(ys.max())
    eye = (p["left_eye"]["y"] + p["right_eye"]["y"]) / 2
    if eye <= top:
        return {"adult": adult, "heads": None}
    return {"adult": adult, "heads": round((bot - top) / (2 * (eye - top)), 2)}


def hands_seen(points, seg, prompt: str) -> dict:
    """手が見えているか。手首の点の確からしさは袖に隠れた手でも 0.5〜0.68 が出て、見えている手と分けられなかった。
    手首の点の周り（目の間の 0.6 倍 + 20 画素の四方）の腕の肌の画素を、顔の面積で割った値の大きい方を shown にする。
    hands behind back を頼んだ絵、骨格か部位分けが無い絵では None"""
    low = (prompt or "").lower()
    if "behind back" in low or not points or seg is None:
        return {"shown": None}
    seg = np.asarray(seg)
    face = float((seg == 11).sum())
    if face <= 0:
        return {"shown": None}
    p = {q["name"]: q for q in points}
    r = int(0.6 * abs(p["left_eye"]["x"] - p["right_eye"]["x"]) + 20)
    out = []
    for s in ("left", "right"):
        x, y = int(p[s + "_wrist"]["x"]), int(p[s + "_wrist"]["y"])
        win = seg[max(0, y - r):y + r, max(0, x - r):x + r]
        out.append(round(float(np.isin(win, [14, 15]).sum()) / face, 4))
    return {"shown": max(out), "wrists": out}


def _prompt_of(src) -> str:
    """描いた道具が隣に置く 絵.png.json の prompt。部分を描き直した絵（-face、.ff など）は元の絵の控えを見る
    （.ff を見ないと、顔を直した絵だけ頼んだ言葉が空になり、色と髪型の照合が素通りしていた）"""
    p = Path(src)
    for j in (p.with_name(p.name + ".json"), p.with_name(p.stem.rsplit("-", 1)[0] + p.suffix + ".json"),
              p.with_name(p.stem.split(".", 1)[0] + p.suffix + ".json")):
        try:
            return json.loads(j.read_text(encoding="utf-8")).get("prompt", "")
        except (OSError, ValueError):
            continue
    return ""


def measure(src, hair_color: str = "", points=None, prompt: str | None = None, tags: dict | None = None) -> dict:
    """prompt と tags は、呼ぶ側（qc.auto_check）が持っていれば渡す。タグの模型を2度走らせないため"""
    from PIL import Image
    import edit
    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0
    seg = np.asarray(edit.parts(src))
    L = edit.LABELS
    regions = {"face": [L["face"]], "hair": [L["hair"]], "clothes": [L["upper"], L["dress"], L["skirt"], L["pants"]],
               "arms": [L["left_arm"], L["right_arm"]], "legs": [L["left_leg"], L["right_leg"]]}
    import faceform
    view = {}
    hrgb, hseg = faceform.head_view(src, rgb, seg, view)
    lm = faceform.landmarks(hrgb, hseg, L)
    face = faceform.fit(lm["points"], json.loads(faceform.TEMPLATE.read_text())["points"]) if "points" in lm and faceform.TEMPLATE.exists() else lm
    if prompt is None:
        prompt = _prompt_of(src)
    if tags is None:
        try:
            import tagger
            tags = tagger.read(src, 0.0)
        except Exception:   # タグの模型が無い環境（sh tools/gen/setup.sh 前）でも、ほかの数字は出す
            tags = None
    return {"size": list(rgb.shape[1::-1]), "eyes": eyes(hrgb, hseg, L, _eye_hint(points, view)), "face": face, "light": light3d(src, rgb, seg, regions),
            "temperature": temperature(rgb, seg, regions), "scene": scene_light(rgb, seg, L), "pairs": pairs(rgb, seg, L), "hair": hair(rgb, seg, L, hair_color),
            "background": background(rgb, prompt), "style": style(tags), "colors": colors(prompt, tags),
            "pose": hands_pose(points, prompt), "body": proportion(points, seg, prompt), "hands": hands_seen(points, seg, prompt)}


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
    # 区分（kind）は共通の基準の方を残す。学んだ基準で「指示との違い」が「崩れ」に戻り、絵を落とす判定に入らないように
    base["checks"] = [{**over[key(c)], **({"kind": c["kind"]} if "kind" in c else {})} if key(c) in over else c
                      for c in base["checks"]]
    return base


def judge(m: dict, norms: dict | None = None) -> list[dict]:
    """基準（norms の checks）から外れた数字を挙げる。各行は 何を・値・基準・意味。
    指示との違い（kind が request）の行には kind を付ける。崩れとは分けて扱う（qc.auto_check の differences）"""
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
            out.append({"path": c["path"], "value": v, "min": lo, "max": hi, "means": c["means"],
                        **({"kind": c["kind"]} if "kind" in c else {})})
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
