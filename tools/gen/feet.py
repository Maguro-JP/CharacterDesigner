"""絵の中の足の指を数える。描き終わるたびの検品（chatdraw/handcheck.py）から呼ぶ。

足の輪郭の下端の山（指先の膨らみ）を数える方法、行ごとの暗い線を数える方法、服の部位分けの脚の形で数える方法は、
どれも全身の絵で大きく数え違えた（左右の足を 1 つと数える、爪や影の線を指の境と数える）。そこで次の順にする。

1. 足の場所と向き: 全身の 133 点を読む模型（DWPose、COCO-WholeBody。Apache-2.0）で、足首・親指の先・小指の先・かかとを読む。
   左右の足は模型が別々に読むので、2 つの足を 1 つと数えない。
2. 足を、指先が下を向き、親指の先から小指の先が横に並ぶ向きに切り出して伸ばす（帯）。
3. 帯の中で 2 つの手がかりを別々に数える。
   - 境の線: 指と指の間の暗い線（線画の線、塗りの影の筋）。横の二階微分で縦の暗い筋を拾い、指先の線より少し奥
     （指の長さの中ほど）を指先の線に沿ってなぞり、筋の数を数える。外側の 2 本（足の輪郭）を除いた本数 + 1 が指の数。
   - 指先の山: 指先の線（明るい肌から前の暗い所・線へ変わる所）の、前へ出た山の数。
4. 2 つが合えばその数を返す。合わなければ数を返さず「読めない」とし、手がかりの数を両方添える。
   自信の無い数を出すと、通すべき絵を落とすか、落とすべき絵を通す。読めないことは隠さず出す。

横向きの足（親指の先と小指の先が重なる）では、指が奥行きの方向に並ぶので数えない（読めない）。

  python3 tools/gen/feet.py <絵>            JSON を出し、<絵>.feet.png に重ね描きを置く
"""
from __future__ import annotations

import cdhome
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MODEL = cdhome.HOME / "gen" / "pose" / "dw-ll_ucoco_384.onnx"
URL = "https://huggingface.co/yzd-v/DWPose/resolve/main/dw-ll_ucoco_384.onnx"
SIZE = (288, 384)   # 模型の入力（幅, 高さ）
# COCO-WholeBody の番号。模型の left/right は人物から見た左右（絵では逆の側に来る）
POINTS = {"left_ankle": 15, "right_ankle": 16, "left_big_toe": 17, "left_small_toe": 18, "left_heel": 19,
          "right_big_toe": 20, "right_small_toe": 21, "right_heel": 22}
LEAST = 0.3    # これより低い確からしさの点は使わない
Z = 4          # 帯の標本の細かさ（原画 1 画素 = Z 標本）。境の線は 1〜2 画素幅なので、細かく取らないと隣の線と溶ける
_SESS = None


class Unavailable(RuntimeError):
    """模型か onnxruntime が無い。崩れではなく「読めない」として扱う"""


def _session():
    global _SESS
    if _SESS is None:
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise Unavailable("onnxruntime が無い（sh tools/gen/setup.sh で入る）") from e
        if not MODEL.exists():
            raise Unavailable(f"全身の点の模型が無い（{MODEL}。sh tools/gen/setup.sh で取る）")
        _SESS = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    return _SESS


def _pose(im, box):
    """枠の中を模型に読ませ、133 点の (x, y, 確からしさ) を返す"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = (x1 - x0) * 1.25, (y1 - y0) * 1.25
    if w / h > SIZE[0] / SIZE[1]:
        h = w * SIZE[1] / SIZE[0]
    else:
        w = h * SIZE[0] / SIZE[1]
    b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    crop = im.crop(tuple(int(round(v)) for v in b)).resize(SIZE, Image.BILINEAR)
    a = (np.asarray(crop, np.float32) - [123.675, 116.28, 103.53]) / [58.395, 57.12, 57.375]
    s = _session()
    sx, sy = s.run(None, {s.get_inputs()[0].name: a.transpose(2, 0, 1)[None].astype(np.float32)})
    px, py = sx[0].argmax(1) / 2, sy[0].argmax(1) / 2   # SimCC は 1 画素を 2 つに割って読む
    sc = np.minimum(sx[0].max(1), sy[0].max(1))
    return np.stack([b[0] + px * (b[2] - b[0]) / SIZE[0], b[1] + py * (b[3] - b[1]) / SIZE[1], sc], 1)


def keypoints(im) -> dict:
    """足に要る点を読む。絵全体で 1 度読み、体の点の外枠で読み直す（小さく写った人でも足が大きく写る）"""
    w, h = im.size
    k = _pose(im, (0, 0, w, h))
    good = k[:23][k[:23, 2] >= LEAST]
    if len(good) >= 6:
        x0, y0 = good[:, :2].min(0)
        x1, y1 = good[:, :2].max(0)
        m = 0.08 * max(x1 - x0, y1 - y0)
        k = _pose(im, (max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m)))
    return {n: (float(k[i, 0]), float(k[i, 1])) for n, i in POINTS.items() if k[i, 2] >= LEAST}


def _strip(a, big, small, ank):
    """足を、指先が下・親指が左になる帯に伸ばす。返す: 帯の画素、帯の座標から原画の座標へ戻す関数、足の長さ F"""
    from scipy.ndimage import map_coordinates
    big, small, ank = (np.asarray(p, float) for p in (big, small, ank))
    L = float(np.linalg.norm(small - big))
    u = (small - big) / L
    mid = (big + small) / 2
    F = float(np.linalg.norm(mid - ank))
    f = mid - ank
    f = f - np.dot(f, u) * u
    f /= np.linalg.norm(f)
    us = np.arange(L / 2 - 0.7 * F, L / 2 + 0.7 * F, 1 / Z)
    vs = np.arange(-0.6 * F, 0.4 * F, 1 / Z)
    UU, VV = np.meshgrid(us, vs)
    X = big[0] + UU * u[0] + VV * f[0]
    Y = big[1] + UU * u[1] + VV * f[1]
    st = np.stack([map_coordinates(a[..., c], [Y, X], order=1, mode="nearest") for c in range(3)], -1)

    def back(col, row):
        uu, vv = us[0] + col / Z, vs[0] + row / Z
        return (float(big[0] + uu * u[0] + vv * f[0]), float(big[1] + uu * u[1] + vv * f[1]))
    cols = ((0 - us[0]) * Z, (L - us[0]) * Z)
    return st, back, F, int(round(-vs[0] * Z)), cols


def _tips(Y, F, row0):
    """指先の線を、列ごとに 1 点ずつ選ぶ。明るい肌から前（下）の暗い所へ変わる強さの和が最大になる、なめらかな線
    （1 列ごとに 2 標本までしか上下しない）。列ごとに最も強い所を選ぶと、爪の線や影の縁に飛んだ"""
    from scipy.ndimage import gaussian_filter
    g = gaussian_filter(Y, (1.0 * Z, 1.5 * Z))
    gv = -np.gradient(g, axis=0)
    gv = np.clip(gv, 0, None)
    lo, hi = max(0, row0 - int(0.3 * F * Z)), min(Y.shape[0] - 1, row0 + int(0.35 * F * Z))
    E = gv[lo:hi]
    n, m = E.shape
    cost = E[:, 0].copy()
    prev = np.zeros((n, m), int)
    for j in range(1, m):
        best = np.full(n, -1e9)
        arg = np.zeros(n, int)
        for d in (-2, -1, 0, 1, 2):
            sh = np.full(n, -1e9)
            if d >= 0:
                sh[d:] = cost[:n - d] if d else cost
            else:
                sh[:d] = cost[-d:]
            better = sh > best
            best[better] = sh[better]
            arg[better] = (np.arange(n) - d)[better]
        cost = best + E[:, j]
        prev[:, j] = arg
    path = np.zeros(m, int)
    path[-1] = int(cost.argmax())
    for j in range(m - 1, 0, -1):
        path[j - 1] = prev[path[j], j]
    rows = path + lo
    strength = E[path, np.arange(m)]
    return rows, strength


def _runs(mask):
    """True の続く区間 (始め, 終わり) の一覧"""
    out, s = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            out.append((s, i))
            s = None
    return out


def count_one(st, F, row0, mids) -> dict:
    """1 つの足の帯で指を数える。mids は親指の先と小指の先の列"""
    from scipy.ndimage import gaussian_filter, gaussian_filter1d
    from scipy.signal import find_peaks
    Y = st[..., 1] * 0.6 + st[..., 2] * 0.4   # 肌は赤が飽和するので、緑と青で明るさを見る
    rows, strength = _tips(Y, F, row0)
    rows = np.round(gaussian_filter1d(rows.astype(float), 0.6 * Z)).astype(int)
    # 足の幅: 指先の線が、最も前に出た所（親指か人差し指の先）から 0.2F 以内にある列の、親指と小指の間を含む続き。
    # 足の外では線が足の横の輪郭を上へ登るので、深さで切ると足の横の輪郭の所で止まる。
    # 線の強さで切ると、明るい肌と明るい床の境（線画の無い所）で途切れ、足の半分しか取れなかった
    s = gaussian_filter1d(strength, 1.0 * Z)
    mid_c0, mid_c1 = (int(c) for c in mids)
    deep = rows[mid_c0:mid_c1 + 1].max()
    from scipy.ndimage import binary_closing
    strong = binary_closing(s > 0.15 * np.percentile(s, 95), np.ones(int(0.1 * F * Z) | 1))
    on = (rows >= deep - 0.2 * F * Z) & strong
    runs = [r for r in _runs(on) if r[0] <= (mid_c0 + mid_c1) // 2 < r[1]]
    if not runs:
        return {"count": None, "why": "指先の線が見つからない"}
    c0, c1 = runs[0]
    width = (c1 - c0) / Z
    # 境の線: 縦に伸びる暗い筋（横の二階微分が正）
    sm = gaussian_filter(Y, (2.5 * Z, 0.7 * Z))
    R = np.clip(np.gradient(np.gradient(sm, axis=1), axis=1), 0, None)
    # 指先の線から奥へ 0.05F〜0.16F の所を、指先の線に沿ってなぞる
    ds = np.arange(int(0.05 * F * Z), int(0.16 * F * Z) + 1, Z)
    cols = np.arange(R.shape[1])
    P = np.mean([R[np.clip(rows - d, 0, R.shape[0] - 1), cols] for d in ds], 0)
    P = gaussian_filter1d(P, 0.4 * Z)
    seg = P[c0:c1]
    if seg.size < 4 * Z:
        return {"count": None, "why": "足の幅が狭すぎる"}
    peaks, _ = find_peaks(seg, height=0.3 * np.percentile(seg, 98), distance=max(2, int(0.045 * F * Z)),
                          prominence=0.12 * seg.max())
    edge = int(0.035 * F * Z)   # 足の外側の輪郭。帯の端の近くの筋は境ではない
    inner = [int(p) for p in peaks if edge <= p < seg.size - edge]
    by_lines = len(inner) + 1
    power = [round(float(seg[p] / max(seg[inner].max(), 1e-6)), 2) for p in inner] if inner else []
    # 指先の山: 指先の線を、ぼかしの少ない明るさの変わり目で列ごとに細かく置き直し、前に出た所（rows が大きい所）を数える。
    # 線を選ぶときのぼかしのままでは、小さい指の間のくぼみ（1〜2 画素）が埋まって山が 1〜2 つになった
    g2 = gaussian_filter(Y, (0.6 * Z, 0.5 * Z))
    gv2 = np.clip(-np.gradient(g2, axis=0), 0, None)
    w2 = int(1.5 * Z)
    fine = np.empty(c1 - c0)
    for j, c in enumerate(range(c0, c1)):
        r0 = max(0, rows[c] - w2)
        col = gv2[r0:rows[c] + w2 + 1, c]
        k = int(col.argmax())
        if 0 < k < len(col) - 1:   # 放物線で 1 標本より細かく
            den = col[k - 1] - 2 * col[k] + col[k + 1]
            k = k + (0.5 * (col[k - 1] - col[k + 1]) / den if den else 0)
        fine[j] = r0 + k
    tip = gaussian_filter1d(fine, 0.35 * Z)
    bumps, _ = find_peaks(tip, prominence=0.4 * Z, distance=max(2, int(0.045 * F * Z)))
    bumps = [int(b) for b in bumps]
    by_tips = len(bumps)
    ev = {"lines": by_lines, "tips": by_tips, "width": round(width, 1), "F": round(F, 1),
          "line_at": [int(p + c0) for p in inner], "line_power": power, "tip_at": [int(b + c0) for b in bumps],
          "span": [int(c0), int(c1)], "rows": rows, "tipline": tip}
    if by_lines == by_tips:
        return {"count": by_lines, "by": "境の線と指先の山が合う", **ev}
    # 指先の山は、先が横一列にそろった指どうし・重なって描いた小さい指を 1 つの山と読む（数え足りない側へしか外れない）。
    # 境の線がどれも強く（最も強い線の 4 割以上）、山との差が 2 本以内なら、境の線の数を取る。
    # 線画の FLUX の絵（6 本指）では、重なった小指の先が山 4 つにしか見えず、境の線は 5 本とも見えていた
    if by_tips < by_lines <= by_tips + 2 and power and min(power) >= 0.4:
        return {"count": by_lines, "by": "境の線（指先の山は先がそろって少なく見える）", **ev}
    return {"count": None, "why": f"境の線では {by_lines} 本、指先の山では {by_tips} 本で、合わない", **ev}


def count_toes(image, keypoints=None) -> list[dict]:
    """絵の足ごとに {side, box, count（読めなければ None）, evidence} を返す。
    keypoints は keypoints() と同じ形の辞書（与えれば模型を読まない）"""
    im = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    kp = keypoints if keypoints is not None else globals()["keypoints"](im)
    a = np.asarray(im, np.float32)
    feet = []
    for side in ("left", "right"):
        need = [f"{side}_big_toe", f"{side}_small_toe", f"{side}_ankle"]
        if not all(n in kp for n in need):
            continue
        big, small, ank = (np.asarray(kp[n]) for n in need)
        F = float(np.linalg.norm((big + small) / 2 - ank))
        L = float(np.linalg.norm(small - big))
        pts = np.array([big, small, ank] + ([kp[f"{side}_heel"]] if f"{side}_heel" in kp else []))
        m = 0.35 * F
        box = [int(pts[:, 0].min() - m), int(pts[:, 1].min() - m), int(pts[:, 0].max() + m), int(pts[:, 1].max() + m)]
        foot = {"side": side, "box": box, "count": None, "evidence": {"F": round(F, 1), "toe_line": round(L, 1)}}
        feet.append(foot)
        if F < 12:
            foot["evidence"]["why"] = "足が小さすぎる"
            continue
        if L < 0.22 * F:
            foot["evidence"]["why"] = "横向きの足で、指が奥行きの方向に並んでいる"
            continue
        st, back, F2, row0, mids = _strip(a, big, small, ank)
        r = count_one(st, F2, row0, mids)
        rows = r.pop("rows", None)
        tl = r.pop("tipline", None)
        if rows is not None:
            c0, c1 = r["span"]
            foot["_tipline"] = [back(c, tl[c - c0]) for c in range(c0, c1, Z)]
            foot["_lines"] = [back(c, rows[c] - int(0.1 * F2 * Z)) for c in r["line_at"]]
            foot["_tips"] = [back(c, tl[c - c0]) for c in r["tip_at"]]
        foot["count"] = r.pop("count")
        foot["evidence"].update(r)
    # 2 つの足が重なっている（片足の上に片足が乗る、模型が同じ足を 2 度読んだ）ときは、どちらも数えない
    if len(feet) == 2:
        a0, a1 = feet
        c = [np.array([(f["box"][0] + f["box"][2]) / 2, (f["box"][1] + f["box"][3]) / 2]) for f in feet]
        if np.linalg.norm(c[0] - c[1]) < 0.3 * min(f["evidence"]["F"] for f in feet):
            for f in feet:
                f["count"] = None
                f["evidence"]["why"] = "2 つの足が重なっていて、分けられない"
    feet.sort(key=lambda f: f["box"][0])   # 絵の左から順に並べる
    return feet


def overlay(image, feet, out):
    """足の枠、指先の線、拾った境の線と指先の山を描いた絵を置く"""
    im = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    d = ImageDraw.Draw(im)
    for f in feet:
        x0, y0, x1, y1 = f["box"]
        col = (0, 200, 0) if f["count"] == 5 else (230, 0, 0) if f["count"] else (230, 160, 0)
        d.rectangle(f["box"], outline=col, width=2)
        d.text((x0 + 2, y0 + 2), f"{f['count'] if f['count'] is not None else '?'}", fill=col)
        if f.get("_tipline"):
            d.line(f["_tipline"], fill=(0, 120, 255), width=1)
        for x, y in f.get("_lines", []):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), outline=(255, 0, 255))
        for x, y in f.get("_tips", []):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(0, 200, 255))
    im.save(out)


def public(feet) -> list[dict]:
    """重ね描き用の内部の値（_ で始まる）を外した結果"""
    return [{k: v for k, v in f.items() if not k.startswith("_")} for f in feet]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    t = time.time()
    feet = count_toes(src)
    out = src.with_name(src.name + ".feet.png")
    overlay(src, feet, out)
    print(json.dumps({"feet": public(feet), "seconds": round(time.time() - t, 2), "overlay": str(out)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
