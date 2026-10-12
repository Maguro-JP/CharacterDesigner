"""顔の形の検品: 描かれた顔が「1つの頭を、ある向きから見た形」として成り立つかを測る。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/faceform.py 絵.png [--debug 図.png]

人は斜めの顔を見ても、頭の中で正面に回して「目の高さがずれている」「片目だけ大きい」と気づく。
ここでは同じことを計算で行う。顔から目頭・目尻・目の中心・目の上端と下端・口の 11 点を取り、
3D の頭の型（styles/face-template.json。3D の素体を回して撮った絵から学んだ点の立体の位置）を
回転・拡大・平行移動で当てはめる。当てはまった向き（左右・上下・傾き）が「この顔はどこを向いているか」、
当てはめても残るずれ（両目の間隔で割った値）が「正面に戻すと歪む量」。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "styles" / "face-template.json"
NAMES = ["eyeL_out", "eyeL_c", "eyeL_in", "eyeL_top", "eyeL_bot", "eyeR_in", "eyeR_c", "eyeR_out", "eyeR_top", "eyeR_bot", "mouth"]


def landmarks(rgb, seg, labels) -> dict:
    """顔から点を取る。画面の左の目を L とする。取れなかった点は入れない"""
    from scipy import ndimage
    import measure
    face = measure.face_mask(seg, labels)
    e = measure.eyes(rgb, seg, labels)
    if e.get("found") != 2:
        return {"reason": e.get("reason", "両目が読めない")}
    lum = rgb[..., :3].mean(-1)
    pts = {}
    for side, key in (("L", "left"), ("R", "right")):
        b = e[key]
        pts[f"eye{side}_c"] = (b["cx"], b["cy"])
        # 目の縦の長さは顔を左右に回しても縮まない。左右の目の大きさの食い違いがここのずれに出る
        pts[f"eye{side}_top"], pts[f"eye{side}_bot"] = (b["cx"], b["cy"] - b["h"] / 2), (b["cx"], b["cy"] + b["h"] / 2)
        # 目の塊の左右の端を目頭・目尻にする（画面の左の目は、左端が目尻、右端が目頭）
        x_lo, x_hi = b["cx"] - b["w"] / 2, b["cx"] + b["w"] / 2
        if side == "L":
            pts["eyeL_out"], pts["eyeL_in"] = (x_lo, b["cy"]), (x_hi, b["cy"])
        else:
            pts["eyeR_in"], pts["eyeR_out"] = (x_lo, b["cy"]), (x_hi, b["cy"])
    # 口: 両目の間隔を物差しにして、目の線から間隔の 0.5〜1.4 倍下の帯で、肌より暗いか赤い小さな塊のうち、
    # 両目の中点の真下に近いもの。顔の部位は首まで含むことがあるので、顔の下端は使わない（斜めの顔で首の影を口と取った）
    mid_x = (e["left"]["cx"] + e["right"]["cx"]) / 2
    eye_y = (e["left"]["cy"] + e["right"]["cy"]) / 2
    gap = e["right"]["cx"] - e["left"]["cx"]
    band = np.zeros_like(face)
    band[int(eye_y + gap * 0.5):int(eye_y + gap * 1.4)] = True
    area = ndimage.binary_erosion(face, iterations=2) & band
    if area.sum() > 30:
        r, g, bch = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        skin = float(np.median(lum[area]))
        redness = r - (g + bch) / 2
        # 口は肌と明るさが違う横長の線（逆光では肌より明るく見えた）。暗い・明るい・赤いのどれかで肌から外れた所を候補にし、
        # 両目の間隔から決まる口のあるべき位置（目の線から間隔の約 0.7 倍下、中点の真下）に近いものを選ぶ。
        # 近さで選ばないと、あごの下の影の線を口と取った
        cand = area & ((lum < skin * 0.82) | (lum > skin * 1.12) | (redness > float(np.median(redness[area])) + 0.12))
        lab, n = ndimage.label(cand)
        best = None
        for i in range(1, n + 1):
            yy, xx = np.nonzero(lab == i)
            if len(xx) < 4 or (xx.max() - xx.min() + 1) < (yy.max() - yy.min() + 1):
                continue
            d = abs(xx.mean() - mid_x) / gap + abs(yy.mean() - (eye_y + gap * 0.7)) / gap
            if best is None or d < best[0]:
                best = (d, xx.mean(), yy.mean())
        if best:
            pts["mouth"] = (best[1], best[2])
    return {"points": {k: (round(float(x), 1), round(float(y), 1)) for k, (x, y) in pts.items()},
            "eye_gap": float(e["right"]["cx"] - e["left"]["cx"])}


def _rot(yaw, pitch, roll):
    cy, sy, cp, sp, cr, sr = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch), np.cos(roll), np.sin(roll)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return Rz @ Rx @ Ry


def fit(points: dict, template: dict) -> dict:
    """頭の型を、回転（左右・上下・傾き）と拡大と平行移動で点に当てはめる（正射影）。残ったずれを返す"""
    from scipy.optimize import least_squares
    names = [n for n in NAMES if n in points and n in template]
    if len(names) < 8:
        return {"reason": f"点が足りない（{len(names)} 点）"}
    P = np.array([template[n] for n in names], dtype=float)          # 型の点（x 右、y 下、z 見る人の側が正）
    Q = np.array([points[n] for n in names], dtype=float)
    gap = np.linalg.norm(Q[names.index("eyeR_c")] - Q[names.index("eyeL_c")]) if "eyeL_c" in names and "eyeR_c" in names else 1.0
    tg = np.linalg.norm(np.array(template["eyeR_c"]) - np.array(template["eyeL_c"]))

    def resid(v):
        yaw, pitch, roll, s, tx, ty = v
        X = (P @ _rot(yaw, pitch, roll).T)[:, :2] * s + [tx, ty]
        return (X - Q).ravel() / gap

    best = None
    for y0 in (-0.6, -0.3, 0, 0.3, 0.6):
        r = least_squares(resid, [y0, 0, 0, gap / tg, *Q.mean(0)],
                          bounds=([-1.4, -0.8, -1.0, 0, -np.inf, -np.inf], [1.4, 0.8, 1.0, np.inf, np.inf, np.inf]))
        if best is None or r.cost < best.cost:
            best = r
    res = resid(best.x).reshape(-1, 2)
    per = {n: round(float(np.hypot(*res[i])), 3) for i, n in enumerate(names)}
    worst = max(per, key=per.get)
    return {"yaw_deg": round(float(np.degrees(best.x[0])), 1), "pitch_deg": round(float(np.degrees(best.x[1])), 1),
            "roll_deg": round(float(np.degrees(best.x[2])), 1),
            "rms": round(float(np.sqrt((res ** 2).sum(1).mean())), 3), "worst": worst, "per_point": per, "used": names}


def measure_face(src) -> dict:
    from PIL import Image
    import edit
    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0
    seg = np.asarray(edit.parts(src))
    lm = landmarks(rgb, seg, edit.LABELS)
    if "points" not in lm:
        return lm
    out = {"points": lm["points"]}
    if TEMPLATE.exists():
        out.update(fit(lm["points"], json.loads(TEMPLATE.read_text())["points"]))
    return out


def learn(srcs, yaws, out=TEMPLATE) -> dict:
    """顔の向きの分かっている絵（3D の素体を回して撮ったもの）から、点の立体の位置を学ぶ。
    正射影で x = X cos t - Z sin t + tx_t、y = Y + ty_t とおき、最小二乗で X・Z を解く（X と Z の平均は 0）。
    点の取り方（landmarks）を変えたら、必ず学び直す（取り方と型の定義が食い違うと、正しい顔まで外れになった）"""
    got = [(measure_face(s), y) for s, y in zip(srcs, yaws)]
    skipped = [y for m, y in got if "points" not in m]
    data = [m["points"] for m, y in got if "points" in m]
    yaws = [y for m, y in got if "points" in m]
    names = [n for n in NAMES if all(n in d for d in data)]
    N, F = len(names), len(yaws)
    A, b = [], []
    for f, t in enumerate(np.radians(yaws)):
        for i, n in enumerate(names):
            row = np.zeros(2 * N + F)
            row[i], row[N + i], row[2 * N + f] = np.cos(t), -np.sin(t), 1
            A.append(row)
            b.append(data[f][n][0])
    A += [np.r_[np.ones(N), np.zeros(N + F)], np.r_[np.zeros(N), np.ones(N), np.zeros(F)]]
    b += [0, 0]
    sol, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    X, Z = sol[:N], sol[N:2 * N]
    Y = np.array([np.mean([d[n][1] for d in data]) for n in names])
    Y -= Y.mean()
    gap = X[names.index("eyeR_c")] - X[names.index("eyeL_c")]
    # 顔は左右対称なので、左右の組の点（eyeL_* と eyeR_*）を鏡に写して平均する。片側の向きだけから学ぶと、
    # 撮影の癖（左右の目の高さの差）まで型に入り、逆向きの正しい顔を外れにした
    idx = {n: i for i, n in enumerate(names)}
    for n in names:
        if n.startswith("eyeL_") and n.replace("eyeL_", "eyeR_") in idx:
            i, j = idx[n], idx[n.replace("eyeL_", "eyeR_")]
            x = (X[j] - X[i]) / 2
            y, z = (Y[i] + Y[j]) / 2, (Z[i] + Z[j]) / 2
            X[i], X[j], Y[i], Y[j], Z[i], Z[j] = -x, x, y, y, z, z
        elif not n.startswith("eyeR_"):
            X[idx[n]] = 0.0
    tpl = {n: [round(float(X[i] / gap), 4), round(float(Y[i] / gap), 4), round(float(Z[i] / gap), 4)] for i, n in enumerate(names)}
    resid = float(np.abs(np.array(A) @ sol - np.array(b))[:-2].max())
    Path(out).write_text(json.dumps({
        "about": "顔の点の立体の位置（両目の中心の間隔を 1 とする。x 右、y 下、z 見る人の側）。tools/gen/faceform.py が当てはめに使う",
        "learned_from": f"顔の向き {yaws}° の絵 {len(srcs)} 枚から faceform.py learn で解いた。x の当てはめの残りは最大 {resid:.1f} 画素",
        "points": tpl}, ensure_ascii=False, indent=1))
    return {"points": names, "max_resid_px": round(resid, 2), "used_yaws": yaws, "skipped_yaws": skipped}


def debug(src, m, out):
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGB")
    pts = m.get("points", {})
    if not pts:
        return
    xs, ys = [p[0] for p in pts.values()], [p[1] for p in pts.values()]
    pad = (max(xs) - min(xs)) * 0.6 + 10
    box = (int(min(xs) - pad), int(min(ys) - pad), int(max(xs) + pad), int(max(ys) + pad))
    crop = im.crop(box)
    k = 600 / crop.width
    crop = crop.resize((600, int(crop.height * k)))
    d = ImageDraw.Draw(crop)
    for n, (x, y) in pts.items():
        X, Y = (x - box[0]) * k, (y - box[1]) * k
        d.ellipse((X - 4, Y - 4, X + 4, Y + 4), outline="#00ff00", width=2)
        d.text((X + 5, Y - 12), n, fill="#00ff00")
    crop.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+")
    ap.add_argument("--learn", default="", help="顔の向き（度）をカンマ区切りで渡すと、src から型を学び直す")
    ap.add_argument("--debug", default="")
    a = ap.parse_args()
    if a.learn:
        print(learn(a.src, [float(x) for x in a.learn.split(",")]))
        return
    for src in a.src:
        m = measure_face(src)
        print(json.dumps({"src": src, **m}, ensure_ascii=False))
        if a.debug:
            debug(src, m, a.debug if len(a.src) == 1 else f"{a.debug}-{Path(src).stem}.png")


if __name__ == "__main__":
    main()
