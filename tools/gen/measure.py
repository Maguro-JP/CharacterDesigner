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
    # 部位分け（segformer）は、アニメの暗い大きな目を「サングラス」と読む。顔に入れないと目の大半が顔の外に落ち、
    # 前髪のかかる目は残りの塊が小さすぎて目が1つしか見つからなかった（目の寄りの顔、2026-10-17）
    m = (seg == labels["face"]) | (seg == labels.get("sunglasses", -1))
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
    if hint:
        # 前髪が目にかかると、部位分けは目の上半分を「髪」と読み、顔の範囲から目が抜ける（目の寄りの顔、2026-10-17）。
        # 骨格の点の目の周りは、部位の名前に関わらず目を探す範囲に入れる
        yy, xx = np.mgrid[:face.shape[0], :face.shape[1]]
        r = max(10.0, fw * 0.15)
        for hx, hy in hint:
            area |= (xx - hx) ** 2 + (yy - hy) ** 2 <= r * r
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


def bimodal(L, seg, labels, f=1.0):
    """肌の部位ごとに、明るさの分布が 2 つの山に分かれるか（セルの塗りの特徴）。山の間の谷の深さ（1 − 谷 ÷ 低い方の山）を、
    部位の画素数で重みづけして平均する。セルの塗りは明るい面と影の面の 2 つの山の間がほぼ空き 1 に近く、
    実写の陰はなだらかに続いて谷が浅い。境の急さ（段の割合）は実写の輪郭や服の縁でも高く出て、見分けられなかった"""
    from scipy import ndimage
    Lb = ndimage.gaussian_filter(L, 1 * f)
    tot, acc = 0, 0.0
    for name in ("face", "left_arm", "right_arm", "left_leg", "right_leg"):
        m = ndimage.binary_erosion(seg == labels[name], iterations=max(2, round(4 * f)))
        if m.sum() < 400:
            continue
        v = Lb[m]
        lo, hi = np.percentile(v, [1, 99])
        if hi - lo < 0.04:
            continue
        h, _ = np.histogram(v, 48, (lo, hi))
        h = ndimage.gaussian_filter1d(h.astype(float), 1.2)
        i = int(np.argmax(h))
        cand = [j for j in range(1, len(h) - 1) if abs(j - i) >= 6 and h[j] >= h[j - 1] and h[j] >= h[j + 1]]
        d = 0.0
        if cand:
            j = max(cand, key=lambda k: h[k])
            a, b = sorted((i, j))
            d = 1 - h[a:b + 1].min() / max(h[j], 1e-6)
        tot += m.sum()
        acc += d * m.sum()
    return round(float(acc / tot), 3) if tot else None


def shadow(rgb, seg, labels):
    """影の自然さを測る（写真級の描き直しの検品）。アニメの塗りを写真に描き直すと、セルの影の段差が残り、
    部位ごとに陰の側が食い違い、床に落ちる影が浮いた（足から離れた）。人はそれを一目で「不自然」と見る。
    - soft: 影の境の柔らかさ。大きな明るさの境（σ4 の傾きの上位 5%）で、σ4 と σ1 の傾きの比の中央値。
      段のような境は σ を大きくすると傾きが下がり（0.3 前後）、なだらかな陰はほとんど下がらない（1 に近い）
    - steps: 肌の明るさの山の数（ならした分布の、高さ 5% 以上の山）。セルの影は 2〜3 の段に分かれる
    - spread: 部位ごとの光の向き（measure.light）の最大のずれ。光が 1 つならそろう
    - ratio: 肌の陰と光の明るさの比（10 と 90 パーセンタイル）。1 に近いほど平らな光
    - cast: 足元の床の暗さ（足の下 4% の高さの帯の背景 ÷ 背景の中央値を 1 から引く）と、
      背景の暗い最大の塊が体から離れている距離（高さに対する割合）。浮いた影は離れて出る"""
    from scipy import ndimage
    f = rgb.shape[1] / 768
    L = rgb[..., :3].mean(-1)
    g1 = np.hypot(*np.gradient(ndimage.gaussian_filter(L, 1 * f)))
    g4 = np.hypot(*np.gradient(ndimage.gaussian_filter(L, 4 * f)))
    skin = np.isin(seg, [labels[k] for k in ("face", "left_arm", "right_arm", "left_leg", "right_leg")])
    body = seg > 0
    out = {}
    si = ndimage.binary_erosion(skin, iterations=max(2, round(6 * f)))   # 肌の輪郭と服との境を数えない
    if si.sum() > 500:
        sel = si & (g4 >= np.percentile(g4[si], 95))
        # 段の上では σ1 の傾きが段の線だけに立つので、近く（σ4 の幅）の σ1 の傾きの最大と比べる
        line = ndimage.binary_dilation(ndimage.grey_closing(L, size=max(3, round(5 * f))) - L > 0.06, iterations=max(2, round(3 * f)))
        g1m = ndimage.maximum_filter(np.where(line, 0, g1), size=max(3, round(8 * f)))   # 線（へそ、輪郭の描き線）は段に数えない
        sel &= ~line
        r = g4[sel] / np.maximum(g1m[sel], 1e-6)
        out["soft"] = round(float(np.median(r)), 3)
        out["step_frac"] = round(float((r < 0.45).mean()), 3)   # 段のような境の割合
    if si.sum() > 500:
        h, _ = np.histogram(L[si], 64, (0, 1))
        h = ndimage.gaussian_filter1d(h.astype(float), 1.5)
        pk = [i for i in range(1, 63) if h[i] >= h[i - 1] and h[i] > h[i + 1] and h[i] >= 0.05 * h.max()]
        out["steps"] = len(pk)
        out["bimodal"] = bimodal(L, seg, labels, f)
        lo, hi = np.percentile(L[si], [10, 90])
        out["ratio"] = round(float(lo / max(hi, 1e-6)), 3)
    regions = {"face": [labels["face"]], "arms": [labels["left_arm"], labels["right_arm"]],
               "legs": [labels["left_leg"], labels["right_leg"]],
               "clothes": [labels["upper"], labels["dress"], labels["skirt"], labels["pants"]]}
    out["spread"] = light(rgb, seg, labels, regions)["max_spread_deg"]
    bg = seg == 0
    ys, xs = np.nonzero(body)
    if bg.sum() > 1000 and len(ys):
        med = float(np.median(L[bg]))
        H = rgb.shape[0]
        foot = ys.max()
        band = np.zeros_like(bg)
        x0, x1 = np.percentile(xs[ys > foot - 0.08 * H], [0, 100]).astype(int) if (ys > foot - 0.08 * H).any() else (xs.min(), xs.max())
        pad = int(0.06 * H)
        band[max(foot - int(0.04 * H), 0):min(foot + int(0.04 * H), H), max(x0 - pad, 0):x1 + pad] = True
        band &= bg
        out["cast"] = round(1 - float(L[band].mean()) / max(med, 1e-6), 3) if band.any() else 0.0
        dark = ndimage.binary_opening(bg & (L < 0.85 * med), iterations=2)
        lab, n = ndimage.label(dark)
        if n:
            big = lab == 1 + int(np.argmax(ndimage.sum(dark, lab, range(1, n + 1))))
            if big.sum() > 0.002 * bg.size:
                dist = ndimage.distance_transform_edt(~body)
                out["cast_gap"] = round(float(dist[big].min()) / H, 3)
    return out


def lab(rgb):
    """sRGB（0〜1）を CIE Lab（D65）にする"""
    c = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]])
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def color_keep(ref, rgb, ref_seg, seg, labels):
    """描き直しで色が保てているか（基準の絵＝1 段目と比べる）。IC-Light の後に絵が灰色に抜け、黒髪が白くなった。
    sat_ratio: 人物の平均の彩度（Lab の a,b の長さ）の比。灰色に抜けると下がる
    color_dab: 肌・服の部位ごとの平均色の a,b の差の最大（明るさは光の付け直しで変わってよいので除く）
    hair_de: 髪の平均色の ΔE（明るさも含める。黒髪が白くなるのは明るさの変わり方）"""
    from scipy import ndimage
    from PIL import Image
    if ref.shape != rgb.shape:
        ref = np.asarray(Image.fromarray((ref * 255).astype(np.uint8)).resize(rgb.shape[1::-1], Image.LANCZOS)).astype(np.float32) / 255
        ref_seg = np.asarray(Image.fromarray(ref_seg).resize(rgb.shape[1::-1], Image.NEAREST))
    f = rgb.shape[1] / 768
    A = lab(ndimage.gaussian_filter(rgb, (2 * f, 2 * f, 0)))
    B = lab(ndimage.gaussian_filter(ref, (2 * f, 2 * f, 0)))
    out = {}
    body, rbody = seg > 0, ref_seg > 0
    if body.any() and rbody.any():
        out["sat_ratio"] = round(float(np.hypot(A[..., 1], A[..., 2])[body].mean() / max(np.hypot(B[..., 1], B[..., 2])[rbody].mean(), 1e-3)), 3)
    groups = {"skin": [labels[k] for k in ("face", "left_arm", "right_arm", "left_leg", "right_leg")],
              "clothes": [labels[k] for k in ("upper", "dress", "skirt", "pants")]}
    dab = []
    for ids in groups.values():
        m, r = np.isin(seg, ids), np.isin(ref_seg, ids)
        if m.sum() > 200 and r.sum() > 200:
            dab.append(float(np.hypot(*(A[m].mean(0)[1:] - B[r].mean(0)[1:]))))
    if dab:
        out["color_dab"] = round(max(dab), 2)
    m, r = seg == labels["hair"], ref_seg == labels["hair"]
    if m.sum() > 200 and r.sum() > 200:
        out["hair_de"] = round(float(np.linalg.norm(A[m].mean(0) - B[r].mean(0))), 2)
    return out


def floor_ref(L, bg):
    """背景（床と壁）の明るさの見込み。行ごとの背景の中央値（撮影の背景は上下にだけなだらかに変わる）。落ち影はこれより暗い所"""
    rows = np.array([np.median(L[y][bg[y]]) if bg[y].sum() > 20 else np.nan for y in range(L.shape[0])])
    idx = np.arange(len(rows))
    ok = ~np.isnan(rows)
    rows = np.interp(idx, idx[ok], rows[ok]) if ok.any() else np.full(len(rows), float(L.mean()))
    return rows[:, None] * np.ones((1, L.shape[1]))


def feet_line(body):
    """足の裏の行（人物の一番下）と、足の裏の画素（下から 1.5% の帯）"""
    ys, xs = np.nonzero(body)
    foot = int(ys.max())
    H = body.shape[0]
    sole = body & (np.arange(H)[:, None] >= foot - max(3, int(0.015 * H)))
    return foot, sole


def feet(seg, labels=None):
    """左右の足ごとの、足の裏の行（bottom）、足の裏の画素（sole）、足の列の範囲（x0, x1）。
    列ごとの人物の下端の山を足とし、離れた（幅の 3% 以上）2 つまでを取る。部位分けの脚の番号（12・13）は、
    片脚が両足の下まで覆うことがあり、足を分けるのに使えなかった"""
    from scipy import ndimage
    body = seg > 0
    H, W = body.shape
    ys, _ = np.nonzero(body)
    top, foot = ys.min(), ys.max()
    cols = body.any(0)
    b = np.where(cols, H - 1 - np.argmax(body[::-1], axis=0), -1).astype(np.float32)
    low = foot - 0.1 * (foot - top)
    b[b < low] = -1                                   # 下の 10% に届かない列（手など）は足でない
    bs = ndimage.maximum_filter1d(b, size=3)
    gap = max(3, int(0.03 * W))
    order = np.argsort(-bs)
    peaks = []
    for x in order:
        if bs[x] < 0 or len(peaks) == 2:
            break
        if all(abs(x - p) > gap * 2 for p in peaks) and bs[x] >= foot - 0.05 * H:
            peaks.append(int(x))
    out = []
    for p in sorted(peaks):
        x0 = p
        while x0 > 0 and b[x0 - 1] >= low and not any(q != p and abs(x0 - 1 - q) < abs(x0 - 1 - p) for q in peaks):
            x0 -= 1
        x1 = p
        while x1 < W - 1 and b[x1 + 1] >= low and not any(q != p and abs(x1 + 1 - q) < abs(x1 + 1 - p) for q in peaks):
            x1 += 1
        bottom = int(b[p])
        sole = np.zeros_like(body)
        sole[:, x0:x1 + 1] = body[:, x0:x1 + 1] & (np.arange(H)[:, None] >= bottom - max(3, int(0.03 * H)))
        out.append({"label": len(out) + 1, "bottom": bottom, "sole": sole, "x0": x0, "x1": x1, "cx": float(p)})
    return out


def project_shadow(body, light_deg, squash=0.45, lean=0.6, seg=None):
    """人物の切り抜きの全体（両脚と胴）を、光と逆の向きの床へ倒して写した形（真偽の配列）。高さ h の点を、
    横へ h×lean、奥へ h×squash だけ動かす（床は奥ほど上に写る）。脚の画素は、その脚の足の裏を支点にする（片足が上がって
    いても、その足から影が出る）。奥へ 0.22・横へ 0.9 で倒すと、脚 2 本と胴の幅が潰れて細い尾のような影になった"""
    from scipy import ndimage
    H, W = body.shape
    ys, xs = np.nonzero(body)
    foot, _ = feet_line(body)
    pivot = np.full(len(ys), float(foot))
    if seg is not None:   # 脚の下半分（足の列の範囲の画素）は、その足の裏を支点にする
        # 足首より下だけ、その足の裏を支点にする。膝から下まで分けると、胴の写しとの継ぎ目に影の抜けた横の筋が出た
        knee = foot - 0.06 * (foot - ys.min())
        for ft in feet(seg):
            sel = (xs >= ft["x0"]) & (xs <= ft["x1"]) & (ys >= knee)
            pivot[sel] = ft["bottom"]
    h = np.clip(pivot - ys, 0, None).astype(np.float32)
    dx = -np.cos(np.radians(light_deg))
    sx = np.round(xs + dx * h * lean).astype(int)
    sy = np.round(pivot - h * squash).astype(int)
    ok = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
    m = np.zeros((H, W), bool)
    m[sy[ok], sx[ok]] = True
    f = W / 768
    # 脚（足の裏が支点）と胴（下端が支点）の写し方の継ぎ目に、影の抜けた横の筋が出たので、穴を埋める
    m = ndimage.binary_closing(m, iterations=max(2, round(3 * f)))
    m = ndimage.binary_closing(m, structure=np.ones((max(3, round(9 * f)), 1), bool))
    return ndimage.binary_fill_holes(m)


def body_light_deg(rgb, seg, least=0.01):
    """体の陰から光の左右を読む。手足の、体の真ん中より右の画素と左の画素の明るさの平均を比べ、明るい側から光が来ているとする。
    返すのは光の向き（右上 45° か左上 135°）と、明るさの差（右が明るいと正）。差が least より小さければ None。
    手足の切り口ごとの左右で比べると、脚の内側の陰どうしが打ち消して、片脚がまるごと暗い（光が反対から来ている）のを読めなかった。
    光の向きを決め打ちにすると、体の陰と逆の向きに影を落とした"""
    L = rgb[..., :3].mean(-1)
    limb = np.isin(seg, (12, 13, 14, 15))
    body = seg > 0
    if limb.sum() < 200:
        return None, 0.0
    cx = float(np.nonzero(body)[1].mean())
    xx = np.arange(seg.shape[1])[None, :]
    r, l = limb & (xx > cx), limb & (xx < cx)
    if r.sum() < 100 or l.sum() < 100:
        return None, 0.0
    d = float(L[r].mean() - L[l].mean())
    if abs(d) < least:
        return None, round(d, 4)
    return (45.0 if d > 0 else 135.0), round(d, 4)


def leg_color(rgb, seg):
    """左右の脚の肌の平均の色の差（Lab の ΔE）。脚の部位（12・13）の、人物の下 45% の画素を、体の真ん中で左右に分けて比べる。
    部位の番号では左右の脚を分けられない（片脚の番号が両脚を覆った）。描き直しで片脚だけが赤く暗くなった"""
    body = seg > 0
    ys, xs = np.nonzero(body)
    if not len(ys):
        return None
    top, foot = ys.min(), ys.max()
    legs = np.isin(seg, (12, 13)) & (np.arange(seg.shape[0])[:, None] > foot - 0.45 * (foot - top))
    cx = float(xs.mean())
    xx = np.arange(seg.shape[1])[None, :]
    lm, rm = legs & (xx < cx), legs & (xx > cx)
    if lm.sum() < 200 or rm.sum() < 200:
        return None
    lab_ = lab(rgb[..., :3])
    return round(float(np.linalg.norm(lab_[lm].mean(0) - lab_[rm].mean(0))), 2)


def floor_step(rgb, seg, light_deg=None):
    """床の行ごとの明るさの段（0〜1）。人物の左と右の外側の背景で、行ごとの中央値を取り、12 行離れた行どうしの差から
    なだらかな傾き（σ40 行でならしたもの）の分を引いた値の、下 55% の行での最大。測るのは光の側（落ち影の無い側）。
    元の影を消して床を当てはめた範囲の上の端で、床の途中に横の段（12 行で 5 階調）が出たのを測る。
    隣の行どうしの差では 1 行 0.4 階調に薄まり、人物の左右をまとめると影の縁が混ざって測れなかった"""
    from scipy import ndimage
    L = rgb[..., :3].mean(-1)
    body = seg > 0
    H, W = L.shape
    xs = np.nonzero(body)[1]
    if not len(xs):
        return 0.0
    g = int(20 * W / 768)
    best = 0.0
    xx = np.arange(W)[None, :]
    if light_deg is None:
        light_deg = body_light_deg(rgb, seg)[0] or 135.0
    sides = [xx < xs.min() - g] if np.cos(np.radians(light_deg)) < 0 else [xx > xs.max() + g]   # 影の縁を段に数えない
    for side in sides:
        side = np.broadcast_to(side, L.shape)
        if side[0].sum() < 20:
            continue
        m = np.array([np.median(L[y][side[y]]) for y in range(H)])
        sm = ndimage.gaussian_filter1d(m, 2)
        tr = ndimage.gaussian_filter1d(m, 40)
        k = 6
        d = np.abs((sm[2 * k:] - sm[:-2 * k]) - (tr[2 * k:] - tr[:-2 * k]))
        best = max(best, float(d[int(0.45 * H):].max()))
    return round(best, 4)


def skin_vstep(rgb, seg):
    """体の縦の方向の肌の色の段（Lab の ΔE）。脚の肌の画素ごとに、3 画素上と 3 画素下の色の差を取り、行ごとの中央値の最大。
    行の全体に渡る横の帯（太腿の付け根の高さで上が白っぽく下が赤い。脚の色をそろえる処理の上の端で切っていた）は行の中央値に
    出るが、膝や陰の境は行の一部にしか無いので中央値には出にくい。行ごとの平均の色の段で測ると、膝の陰と見分けられなかった"""
    from scipy import ndimage
    legs = ndimage.binary_erosion(np.isin(seg, (12, 13)), iterations=4)
    H = seg.shape[0]
    lab_ = lab(ndimage.gaussian_filter(rgb[..., :3], (1.5, 3, 0)))   # 肌の粒（毛穴）を段に数えない
    k = 3
    both = legs[2 * k:] & legs[:-2 * k]
    d = np.linalg.norm(lab_[2 * k:] - lab_[:-2 * k], axis=-1)
    ys = np.nonzero(seg > 0)[0]
    lo, hi = ys.max() - 0.08 * (ys.max() - ys.min()), ys.min()     # 足（下から 8%）は指の間の色の差が大きいので除く
    best = 0.0
    for y in range(len(d)):
        if both[y].sum() > 40 and y + k < lo:
            best = max(best, float(np.median(d[y][both[y]])))
    return round(best, 2)


def contour_dev(src_seg, seg):
    """描いた後の体の輪郭が、元の絵の体の輪郭からどれだけ欠けたか（元の体の中で、描いた後に体でなくなった所の、
    描いた体からの距離の最大、画素）。左の肩の輪郭が欠けて膨らみと切れ込みになったのを測る"""
    from scipy import ndimage
    A, B = src_seg > 0, seg > 0
    miss = A & ~B
    if not miss.any():
        return 0.0
    return round(float(ndimage.distance_transform_edt(~B)[miss].max()), 1)


def leg_shade_width(rgb, seg):
    """脚の陰の境目の幅（画素、幅 768 にそろえて）。脚の中の明るさの大きな境（σ4 の傾きの上位 5%）で、明るさの差 ÷ 傾きの
    最大（境を横切るのにかかる幅）の中央値。セルの塗りの段が残る硬い境は 2〜3 画素、なだらかな陰は 10 画素以上になる。
    太腿の内側の陰の境目が線のように硬く見えた"""
    from scipy import ndimage
    f = rgb.shape[1] / 768
    L = rgb[..., :3].mean(-1)
    legs = ndimage.binary_erosion(np.isin(seg, (12, 13)), iterations=max(3, round(6 * f)))
    if legs.sum() < 500:
        return None
    g1 = np.hypot(*np.gradient(ndimage.gaussian_filter(L, 1 * f)))
    g4 = np.hypot(*np.gradient(ndimage.gaussian_filter(L, 4 * f)))
    sel = legs & (g4 >= np.percentile(g4[legs], 95))
    d = ndimage.gaussian_filter(L, 8 * f)
    span = ndimage.maximum_filter(d, size=max(5, round(16 * f))) - ndimage.minimum_filter(d, size=max(5, round(16 * f)))
    gmax = ndimage.maximum_filter(g1, size=max(3, round(6 * f)))
    w = span[sel] / np.maximum(gmax[sel], 1e-4) / f
    return round(float(np.median(w)), 2)


def skin_texture(rgb, seg, part="body"):
    """絵の肌の、周波数ごとの強さを、実写の手本の分布（styles/skin-texture.json）と比べる。絵を手本と同じ幅 768 に縮め、
    同じ測り方（48 画素の切り抜きの、3 画素のぼかしとの差のパワーを半径 16 段で平均）で測る。返すのは、高い方の 10 段
    （毛穴ときめの大きさ）での、絵のパワー ÷ 手本の中央値の比の中央値。1 で手本と同じ、小さいと平らな塗り、大きいと粒が多すぎる。
    肌の平らな面の割合は、粒を足すだけで下がり、多すぎる粒を落とせなかった"""
    import json
    from PIL import Image
    from scipy import ndimage
    tex = json.loads((ROOT / "styles" / "skin-texture.json").read_text(encoding="utf-8"))
    W = tex["ref_width"]
    H = round(rgb.shape[0] * W / rgb.shape[1])
    im = Image.fromarray((np.clip(rgb[..., :3], 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    sg = np.asarray(Image.fromarray(seg).resize((W, H), Image.NEAREST))
    labels = (11,) if part == "face" else (12, 13, 14, 15)
    L = np.asarray(im.convert("L")).astype(np.float32) / 255
    hp = L - ndimage.gaussian_filter(L, 3)
    skin = ndimage.binary_erosion(np.isin(sg, labels), iterations=3)
    if part == "face" and skin.any():
        a = np.asarray(im).astype(np.float32)
        red = a[..., 0] - a[..., 1]
        skin &= (a.mean(2) > np.median(a.mean(2)[skin]) * 0.8) & (red < np.median(red[skin]) + 15)
    P_, B = tex["patch"], tex["bins"]
    yy, xx = np.mgrid[:P_, :P_] - P_ // 2
    rad = np.hypot(yy, xx) / (P_ / 2)
    pows = []
    step = P_ // 2 if part == "face" else P_
    for y in range(0, H - P_, step):
        for x in range(0, W - P_, step):
            if skin[y:y + P_, x:x + P_].mean() > 0.95:
                q = hp[y:y + P_, x:x + P_]
                Pw = np.abs(np.fft.fftshift(np.fft.fft2(q - q.mean()))) ** 2
                pows.append([float(Pw[(rad >= i / B) & (rad < (i + 1) / B)].mean()) for i in range(B)])
    if not pows:
        return None
    mine = np.median(pows, 0)
    ref = np.array(tex[part]["power"])
    return round(float(np.median((mine / np.maximum(ref, 1e-9))[B - 10:])), 3)


def cast_check(rgb, seg, light_deg=None):
    """床の落ち影の検品。体の陰から読んだ光の向き（light_deg、0° が右、90° が上）で人物の形を床に写したものと比べる。
    6 周目の絵は、影が脚の形をしない左右の塊で、足の裏から離れ、体の陰と逆の向きに伸びていたのに、
    足元の暗さだけを見る検品（cast）が通した。
    cast_iou: 写した形（人物の外）と、実際の影（背景の見込みより 10% 以上暗い所）の重なり
    contact: 足の裏の真下 1% の帯のうち、写した形と重なる（IoU 0.5 以上の）影のひと続きの塊に入る割合（接地の影）
    cast_side: 実際の影のうち、足の裏から見て光と逆の側にある割合（体の陰の向きと影の向きの一致）
    cast_spill: 実際の影のうち、写した形（少し広げたもの）の外にはみ出た割合（脚の形をしない塊）
    halo: 人物の縁のすぐ外（1〜6 画素）が、少し外（10〜24 画素）の背景より明るい割合（白いにじみ）"""
    from scipy import ndimage
    H, W = seg.shape
    f = W / 768
    # 光の向きは渡された値ではなく、絵の体の陰から読む（描いた側が決めた光の向きで測ると、体の陰と逆の影を通した）
    seen, diff = body_light_deg(rgb, seg)
    light_deg = seen if seen is not None else (light_deg if light_deg is not None else 135.0)
    L = rgb[..., :3].mean(-1)
    body = seg > 0
    bg = ~ndimage.binary_dilation(body, iterations=max(2, round(3 * f)))
    ref = floor_ref(L, bg)
    foot, sole = feet_line(body)
    shade = bg & (L < 0.9 * ref) & (np.arange(H)[:, None] > foot - 0.35 * H)
    shade = ndimage.binary_opening(shade, iterations=2)
    # 足（下から 2%）は写さない（作る側と同じ。足の影は接地の影が受け持つ）
    exp = project_shadow(body & (np.arange(H)[:, None] < foot - 0.02 * H), light_deg, seg=seg) & ~body
    out = {"floor_step": floor_step(rgb, seg, light_deg),
           "cast_iou": round(float((shade & exp).sum() / max((shade | exp).sum(), 1)), 3),
           "light_deg": light_deg, "light_lr_diff": diff}
    # 接地: 左右の足ごとに、足の裏の真下 1% の帯が、写した形と重なる（IoU 0.5 以上の）影のひと続きの塊に入る割合。
    # 低い方を contact にする（8 周目の絵は片足にだけ影が付き、もう片足は浮いていた）
    sh2 = shade.copy()
    belows = []
    for ft in feet(seg):
        bl = np.zeros_like(body)
        fy, fx_ = np.nonzero(ft["sole"])
        cols = np.unique(fx_)
        for x in cols:
            yb = fy[fx_ == x].max()
            bl[yb + 1:min(yb + max(3, int(0.01 * H)), H), x] = True
        bl &= ~body
        belows.append((ft, bl))
        sh2 |= bl & (L < 0.85 * ref)
    lab, n = ndimage.label(ndimage.binary_dilation(sh2, iterations=max(4, round(6 * f)) + 2))
    good = np.zeros(n + 1, bool)
    for i in np.unique(lab[sh2]):
        if i:
            comp = (lab == i) & sh2          # つなぐために広げた分は重なりに数えない
            good[i] = (comp & exp).sum() / max((comp | exp).sum(), 1) >= 0.5
    per = {}
    for ft, bl in belows:
        per[ft["label"]] = round(float((sh2[bl] & good[lab[bl]]).mean()), 3) if bl.any() else 0.0
    out["contact_feet"] = per
    out["contact"] = min(per.values()) if per else 0.0
    sy, sx = np.nonzero(sole)
    # 影の太さ: 影の短い向きの幅（主成分の短い軸の ±2σ）÷ 人物の幅（腰から膝の行の幅の中央値）
    if shade.sum() > 50:
        py, px = np.nonzero(shade)
        cov = np.cov(np.stack([px, py]).astype(np.float64))
        minor = 4 * np.sqrt(max(np.linalg.eigvalsh(cov)[0], 0))
        rows = [r for r in range(int(0.45 * H), int(0.75 * H)) if body[r].any()]
        widths = [np.ptp(np.nonzero(body[r])[0]) + 1 for r in rows] or [1]
        out["cast_thick"] = round(float(minor / max(np.median(widths), 1)), 3)
    else:
        out["cast_thick"] = 0.0
    if shade.sum() > 50:
        fx = float(sx.mean()) if len(sx) else W / 2
        want = -np.sign(np.cos(np.radians(light_deg)))
        side = np.sign(np.nonzero(shade)[1] - fx)
        out["cast_side"] = round(float((side == want).mean()), 3) if want else 1.0   # 光と逆の側にある影の割合
        out["cast_spill"] = round(float((shade & ~ndimage.binary_dilation(exp, iterations=max(3, round(12 * f)))).sum() / shade.sum()), 3)
    else:
        out["cast_side"], out["cast_spill"] = 0.0, 1.0
    # 縁の内側も見る（部位分けは白いにじみを人物に含める）。にじみは白い（彩度が低い）
    mx, mn = rgb[..., :3].max(-1), rgb[..., :3].min(-1)
    white = (mx - mn) / np.maximum(mx, 1e-3) < 0.15
    near = ndimage.binary_dilation(body, iterations=max(2, round(6 * f))) & ~ndimage.binary_erosion(body, iterations=max(2, round(4 * f)))
    far = ndimage.binary_dilation(body, iterations=max(4, round(24 * f))) & ~ndimage.binary_dilation(body, iterations=max(3, round(10 * f)))
    if near.any() and far.any():
        sg = max(3, round(12 * f))
        Lf = ndimage.gaussian_filter(L * far, sg) / np.maximum(ndimage.gaussian_filter(far.astype(np.float32), sg), 1e-3)   # 少し外の背景の明るさを縁まで広げる
        hl = (L > Lf + 0.06) & white
        out["halo"] = round(float(hl[near].mean()), 3)
        # 足の周り（下から 8%）: 縁の内外 1〜3 画素の灰色の画素が、近くの床（外 4〜9 画素の暗い方）より 0.08 以上明るい割合。
        # 足の周りは床が接地の影で暗く、遠くの背景と比べる測り方では、影と肌の間の明るい灰色の縁を拾えなかった（9 周目 0.004）
        low = np.arange(H)[:, None] >= foot - 0.08 * H
        di, do = ndimage.distance_transform_edt(body), ndimage.distance_transform_edt(~body)
        fedge = (((di >= 1) & (di <= 3)) | ((do >= 1) & (do <= 3))) & low
        outr = (do >= 4) & (do <= 9)
        fref = ndimage.minimum_filter(np.where(outr, L, 1.0), size=max(3, round(9 * f)))
        gray = (mx - mn) / np.maximum(mx, 1e-3) < 0.15
        out["halo_feet"] = round(float((gray & (L > fref + 0.08))[fedge].mean()), 3) if fedge.any() else 0.0
    return out


PHOTO_NORMS = ROOT / "styles" / "photoreal-norms.json"


def judge_shadow(m: dict, norms: dict | None = None) -> list[dict]:
    """写真級の絵の影と肌・線の数字（shadow と photoreal.keep_metrics）を、styles/photoreal-norms.json の範囲で判定する。
    アニメの基準（anime-norms.json）には入れない。セルの影の段はアニメでは正しい"""
    norms = norms or json.loads(PHOTO_NORMS.read_text(encoding="utf-8"))
    out = []
    for c in norms["checks"]:
        v = m.get(c["path"])
        if v is None:
            continue
        if isinstance(v, bool):
            if v != c.get("equals", True):
                out.append({"path": c["path"], "value": v, "equals": c.get("equals", True), "means": c["means"]})
            continue
        lo, hi = c.get("min"), c.get("max")
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            out.append({"path": c["path"], "value": v, "min": lo, "max": hi, "means": c["means"]})
    return out


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


def limbs(rgb, seg, labels):
    """手足の影が体の形に沿っているかを測る。手足は円柱に近いので、光源が1つなら形の影の境は手足の長さに沿って走り、
    左右の脚は同じ光を受けて同じくらい暗くなる（docs/knowledge/anatomy.md の「体の影」）。
    across: 影の境のうち、手足の軸を 45° より大きく横切る割合（斜めの直線の境、まだらの影で増える）。
    leg_dark_gap: 左右の脚で、暗い所の割合の差（片脚だけ暗い絵で増える）。
    正しい手本がまだ無いので、境は判定しない値から始め、normlearn で学んで締める"""
    from scipy import ndimage
    lum = ndimage.gaussian_filter(rgb[..., :3].mean(-1), 2)
    out = {}
    for name in ("left_leg", "right_leg", "left_arm", "right_arm"):
        m = ndimage.binary_erosion(seg == labels[name], iterations=4)   # 縁の線を数えない
        if m.sum() < 2000:
            continue
        ys, xs = np.nonzero(m)
        _, vec = np.linalg.eigh(np.cov(np.vstack([xs, ys])))
        axis = vec[:, 1]
        # 明暗の境は、その手足の明るい所と暗い所の中ほどに置く（肌の色の違いで固定の値がずれないように）
        dark = (lum < (np.percentile(lum[m], 85) + np.percentile(lum[m], 15)) / 2) & m
        d = ndimage.gaussian_filter(dark.astype(float), 3)
        gy, gx = np.gradient(d)
        # 暗い所の切り抜きは手足の縁でも途切れるので、縁から離れた所の境だけを数える（縁の境は必ず軸に沿う）
        edge = ndimage.binary_erosion(m, iterations=8) & (np.hypot(gx, gy) > 0.02)
        across = 0.0
        if edge.sum() >= 50:
            cos = np.abs(-gy[edge] * axis[0] + gx[edge] * axis[1]) / np.hypot(gx[edge], gy[edge])
            across = float((cos < np.cos(np.radians(45))).mean())
        out[name] = {"dark_frac": round(float(dark.sum() / m.sum()), 3), "across": round(across, 3)}
    res = {"parts": out, "across_max": max((v["across"] for v in out.values()), default=None)}
    if "left_leg" in out and "right_leg" in out:
        res["leg_dark_gap"] = round(abs(out["left_leg"]["dark_frac"] - out["right_leg"]["dark_frac"]), 3)
    return res


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
            # 色の濃い指定（深紅など）に、色相だけ近い薄い色（光で桃色に染まった黒髪）を近いと数えていた。彩度が大きく足りない画素は外れ
            far_s = seen & (ss > 0.5) & (s < ss - 0.35)
            far &= far_v | far_h | far_h_dark | far_s
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


def skeleton(points, seen: float = 0.3) -> dict:
    """骨の長さの比。描いた体の骨格が人であり得るかを、関節の点（RTMPose）の間の長さで見る。
    肉と脂肪の付き方は絵によって変わるが、骨の長さの比は人ならほぼ決まっている（上腕骨に対する前腕、大腿骨に対する脛）。
    画面の上の長さなので、手足が奥へ向くと縮んで見える。そこで比の境は、縮みで説明できない値（前腕が上腕の 1.35 倍を超える、
    脛が太ももの 0.6 倍を下回る など）だけを外れにする。左右の差は、同じ骨の長さが左右で 1.5 倍を超えるときだけ見る。
    読めない点（seen 未満）がある骨は数えない"""
    if not points:
        return {}
    p = {q["name"]: q for q in points}

    def bone(a, b):
        if a not in p or b not in p or min(p[a]["score"], p[b]["score"]) < seen:
            return None
        return float(np.hypot(p[a]["x"] - p[b]["x"], p[a]["y"] - p[b]["y"]))

    out = {}
    for side in ("left", "right"):
        up, fore = bone(f"{side}_shoulder", f"{side}_elbow"), bone(f"{side}_elbow", f"{side}_wrist")
        thigh, shin = bone(f"{side}_hip", f"{side}_knee"), bone(f"{side}_knee", f"{side}_ankle")
        out[side] = {"upper_arm": up, "forearm": fore, "thigh": thigh, "shin": shin}
    ratios = {}
    for side in ("left", "right"):
        b = out[side]
        if b["upper_arm"] and b["forearm"] and b["upper_arm"] > 10:
            ratios[f"{side}_forearm_upper"] = round(b["forearm"] / b["upper_arm"], 2)
        if b["thigh"] and b["shin"] and b["thigh"] > 10:
            ratios[f"{side}_shin_thigh"] = round(b["shin"] / b["thigh"], 2)
    lr = []
    for k in ("upper_arm", "forearm", "thigh", "shin"):
        a, c = out["left"][k], out["right"][k]
        if a and c and min(a, c) > 10:
            lr.append(max(a, c) / min(a, c))
    fa = [v for k, v in ratios.items() if k.endswith("forearm_upper")]
    st = [v for k, v in ratios.items() if k.endswith("shin_thigh")]
    return {"ratios": ratios,
            "forearm_upper_max": max(fa, default=None), "forearm_upper_min": min(fa, default=None),
            "shin_thigh_max": max(st, default=None), "shin_thigh_min": min(st, default=None),
            "left_right_max": round(max(lr), 2) if lr else None}


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



def stray_color(rgb) -> float:
    """白い水着と灰の背景を頼んだ写実の絵の中で、鮮やかな色の画素が占める割合（%）。

    写実の段の模型は、頼んでいない光の漏れ・色のにじみ・小物を鮮やかな色で描いた。肌（彩度 0.36 前後）と
    灰の背景は彩度が低いので、彩度 0.5 を超える画素の多さで、頼んでいない色の物を数えられる。
    身体 回32〜42 の写実 11 枚では、崩れた 8 枚が 2.14% 以上、崩れの無い 3 枚が 1.72% 以下だった。
    """
    import numpy as np
    a = np.asarray(rgb, dtype=np.float32)
    if a.max() > 1.0:
        a = a / 255.0
    mx, mn = a.max(-1), a.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    return float(((sat > 0.5) & (mx > 0.25)).mean() * 100)


def stray_blob(rgb) -> float:
    """鮮やかな色の画素がつながった塊のうち、一番大きいものが絵に占める割合（%）。

    stray_color は鮮やかな画素の合計しか見ないので、小さくまとまった色の板（回73 の赤い長方形、0.93%）を
    合計 1.53% で見逃した。塊で見ると、身体 回40〜73 の写実 20 枚で、崩れの無い絵は 0.61% 以下、
    色の板や布が出た 3 枚は 0.73% 以上だった。
    """
    import numpy as np
    from scipy import ndimage
    a = np.asarray(rgb, dtype=np.float32)
    if a.max() > 1.0:
        a = a / 255.0
    mx, mn = a.max(-1), a.min(-1)
    m = ((mx - mn) / np.maximum(mx, 1e-6) > 0.5) & (mx > 0.25)
    lab, n = ndimage.label(m)
    if not n:
        return 0.0
    return float(np.bincount(lab.ravel())[1:].max() / m.size * 100)


def garment_saturation(rgb, parts) -> float:
    """部位分け（edit.LABELS）の服の画素の彩度の中央値。白い水着を頼んだ絵で、水着そのものの色違いを見る。

    水着が丸ごと桃色・水色になった絵は、色が面で広がるので stray_color と stray_blob が拾わない（身体 回69〜89）。
    写実 15 枚で、白か灰の水着は 0.133 以下、色の付いた水着は 0.182 以上だった。服の画素が無ければ 0。
    """
    import numpy as np
    a = np.asarray(rgb, dtype=np.float32)
    if a.max() > 1.0:
        a = a / 255.0
    m = np.isin(np.asarray(parts), [4, 5, 6, 7])
    if not m.any():
        return 0.0
    mx, mn = a[m].max(-1), a[m].min(-1)
    return float(np.median((mx - mn) / np.maximum(mx, 1e-6)))

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
            "temperature": temperature(rgb, seg, regions), "scene": scene_light(rgb, seg, L), "pairs": pairs(rgb, seg, L), "limbs": limbs(rgb, seg, L), "hair": hair(rgb, seg, L, hair_color),
            "background": background(rgb, prompt), "style": style(tags), "colors": colors(prompt, tags),
            "pose": hands_pose(points, prompt), "body": proportion(points, seg, prompt), "skeleton": skeleton(points), "hands": hands_seen(points, seg, prompt)}


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
