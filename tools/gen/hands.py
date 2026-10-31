"""絵の中の手を測る。指が何本あるか、どこから生えているか、長さの釣り合いを数字で出す。

目で見る検品（checker）は、指の溶けや付け根のずれを見落とし、崩れた手を「5本」と数えて通した
（2026-10-15 の鬼娘。親指が手首から生え、指の付け根がばらばらだった）。そこで、手の関節 21 点を読む模型
（MediaPipe の手の模型、Apache-2.0。.cache/gen/mediapipe に置く）で関節の位置を読み、
  - 模型が読んだ指の線の上に、本当に手の色があるか（無ければ、その指は描かれていない・ずれている）
  - 指どうしの長さの比、手のひらと中指の比、親指の長さ
を測って、決まりの範囲（下の NORMS）と比べる。模型は「手らしい形」に寄せて点を置くので、
点の比だけでは崩れが隠れる。絵の色と突き合わせる所が肝心。

手を指先が上になる向きに回してから読ませる（下向きのまま読ませると、点が手の外に散った）。

  python3 tools/gen/hands.py <絵> --hand x0,y0,x1,y1:角度 [--hand ...]
  python3 tools/gen/hands.py <絵> --auto
--auto は手のひらを探す模型（hand_detector.tflite）で枠と角度を出し、見つからなければ肘と手首から見当する。
角度は、指先が上を向くまでに絵を回す角度（度。指先が下なら 180）。
--auto は肘と手首（tools/gen/joints.py）から枠と角度を出す。手は前腕の延長に付くので、手首から前腕の向きへ
前腕の 0.5 倍進んだ所を中心、前腕の 1.1 倍を一辺にする。握った手や手首を強く曲げた手では外れうるので、
外れた枠は .hand*.png の赤い線で見て、--hand で指定し直す。
"""
from __future__ import annotations

import cdhome
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MODEL = cdhome.HOME / "gen" / "mediapipe" / "hand_landmarks_detector.tflite"
FINGERS = {"thumb": [1, 2, 3, 4], "index": [5, 6, 7, 8], "middle": [9, 10, 11, 12], "ring": [13, 14, 15, 16],
           "pinky": [17, 18, 19, 20]}
EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (0, 9), (9, 10), (10, 11), (11, 12),
         (0, 13), (13, 14), (14, 15), (15, 16), (0, 17), (17, 18), (18, 19), (19, 20), (5, 9), (9, 13), (13, 17)]
# 中指の長さ（付け根から先まで）を 1 とした比。3D の素体の手（tools/engine/pose_stand.py --hand L --twist 60、
# 手の甲を正面に向けた立ち姿）で測った値 palm 1.30・thumb 0.98・index 0.86・ring 0.88・pinky 0.72・手の色 5 本とも 1.0、
# 手らしさ 0.82 を中心に幅を持たせた。親指は付け根の関節（手首の近く）から数えるので、中指とほぼ同じ長さになる。
# cover は指の線の上で手の色だった割合。崩れた鬼娘の手は人差し指 0.42・薬指 0.67 で、ここで外れた
NORMS = {"presence": (0.8, 1.01), "thumb": (0.8, 1.12), "index": (0.80, 1.0), "ring": (0.85, 1.02),
         "pinky": (0.55, 0.85), "palm": (0.85, 1.35), "cover": (0.85, 1.01)}

# これより低い手らしさは「読めない」として、崩れとは別に返す。try の絵で、袖に隠れた手・布だけの枠は 0.0〜0.15、
# 写っている手は 0.74〜0.96 だった
READABLE = 0.5
_IT = None


class Unavailable(RuntimeError):
    """手の模型か、それを読む部品（ai-edge-litert）が無い。崩れではなく「読めない」として扱う"""


def _litert():
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError as e:
        raise Unavailable("手の模型を読む部品 ai-edge-litert が無い（sh tools/gen/setup.sh で入る）") from e
    return Interpreter


def _model(path):
    if not path.exists():
        raise Unavailable(f"手の模型 {path.name} が無い（sh tools/gen/setup.sh で入る）")
    return str(path)


def _interp():
    global _IT
    if _IT is None:
        _IT = _litert()(_model(MODEL))
        _IT.allocate_tensors()
    return _IT


def landmarks(img):
    """正方形に余白を足して 224 に縮め、関節 21 点（448 画素の座標）と、手らしさ（0〜1）を返す"""
    it = _interp()
    w, h = img.size
    s = max(w, h)
    sq = Image.new("RGB", (s, s), img.getpixel((0, 0)))
    sq.paste(img, ((s - w) // 2, (s - h) // 2))
    x = np.asarray(sq.resize((224, 224), Image.LANCZOS), np.float32)[None] / 255.0
    it.set_tensor(it.get_input_details()[0]["index"], x)
    it.invoke()
    out = {d["name"]: it.get_tensor(d["index"]) for d in it.get_output_details()}
    return sq.resize((448, 448), Image.LANCZOS), out["Identity"].reshape(21, 3)[:, :2] * 2, float(out["Identity_1"].ravel()[0])


def length(lm, ids):
    return float(sum(np.linalg.norm(lm[ids[i + 1]] - lm[ids[i]]) for i in range(len(ids) - 1)))


def measure(img):
    sq, lm, presence = landmarks(img)
    a = np.asarray(sq).astype(float)
    # 手のひらの色は指の付け根の 4 点で取る。手首の点は袖口に乗りやすく、手首との中点では袖の色を手の色と取り違えた
    palm_pts = [lm[k] for k in (5, 9, 13, 17)]
    palm_col = np.median([a[int(p[1]), int(p[0])] for p in palm_pts], axis=0)

    def on_hand(p):
        x, y = int(np.clip(p[0], 0, 447)), int(np.clip(p[1], 0, 447))
        return np.abs(a[y, x] - palm_col).sum() < 90

    lens = {k: length(lm, v) for k, v in FINGERS.items()}
    mid = lens["middle"] or 1.0
    m = {"presence": round(presence, 2), "palm": round(float(np.linalg.norm(lm[9] - lm[0])) / mid, 2)}
    for k in ("thumb", "index", "ring", "pinky"):
        m[k] = round(lens[k] / mid, 2)
    # 指の線（付け根から先の手前 1 割まで）の上で手の色だった割合。先端は輪郭の線に乗るので外す
    m["cover"] = {k: round(float(np.mean([on_hand(p) for p in np.linspace(lm[v[0]], lm[v[0]] + (lm[v[-1]] - lm[v[0]]) * 0.9, 24)])), 2)
                  for k, v in FINGERS.items()}
    m["fingers"] = count_fingers(a, lm, palm_col)
    bad = []
    # 手らしさが低いときは、枠に手が写っていない（袖や布に隠れた、枠が外れた）。点はでたらめなので比を崩れとして数えない
    if presence < READABLE:
        return m, ["読めない: 手らしさ " + str(m["presence"])], _overlay(sq, lm)
    # 手のひらが中指の半分より短いのは、点が指の上につぶれた読み（カップを包んで重なった両手で 0.23、0.46）
    if m["palm"] < 0.5:
        return m, ["読めない: 点がつぶれた（手のひら " + str(m["palm"]) + "）"], _overlay(sq, lm)
    # 長さの比は伸びた指でしか測れない。折った指は絵の上で短く見え、ピースの薬指（0.56）を短すぎると数えた。
    # 付け根から先までの直線が、関節をたどった長さの 9 割に満たない指は折れているとして比べない
    bent = {k for k, v in FINGERS.items() if np.linalg.norm(lm[v[-1]] - lm[v[0]]) < 0.9 * (length(lm, v) or 1.0)}
    for k, (lo, hi) in NORMS.items():
        vals = m[k].items() if isinstance(m[k], dict) else [(k, m[k])]
        if k in bent:
            continue
        for name, v in vals:
            # 折った指は指の線が握った物や手のひらの上を通るので、指の色も比べない（剣の柄を握った手の 5 本が 0.0〜0.29 だった）
            if k == "cover" and name in bent:
                continue
            if not lo <= v <= hi:
                bad.append(f"{name}{'の手の色' if k == 'cover' else ''} {v}（{lo}〜{hi}）")
    # 指の数。模型の点はいつも 5 本に置くので、点の数では数えられない（6 本指の絵でも 5 本と読む）。
    # 指の付け根から先を横に切り、付け根から先まで続く手の色の筋を数える（count_fingers）。数えられなければ何も言わない
    n = m["fingers"]
    if n["count"] is not None and n["count"] > 4:
        bad.append(f"指が多い（親指の外に {n['count']} 本。4 本のはず）")
    # 足りないと言うのは、指どうしが指 1 本の幅より離れていて、重なって隠れた指が無いと言えるときだけ。
    # 横から見た手や重ねた手は指が隠れるので、3 本に見えても崩れとは限らない（腰に当てた手、重ねた両手）
    elif n["count"] is not None and n["count"] < 4 and not bent and n.get("apart", 0) >= 1.0:
        bad.append(f"指が足りない（親指の外に {n['count']} 本。4 本のはず）")
    if n.get("fused") and not bent:
        bad.append("指がくっついている（指 2 本分の幅の塊）")
    if n.get("ghost"):
        bad.append(f"指の間に薄い指がある（{n['ghost']} 本。余分な指が透けて描かれている）")
    return m, bad, _overlay(sq, lm)


FAN = (5, 9, 13, 17)        # 人差し指〜小指の付け根
CUTS = (0.3, 0.4, 0.5, 0.6, 0.7)   # 付け根から指先までのどこで切るか（割合）


def _sample(a, xy):
    """xy（x, y の並び）の上の色を、隣の 4 画素から重みを付けて取る"""
    h, w = a.shape[:2]
    x = np.clip(xy[:, 0], 0, w - 1.001)
    y = np.clip(xy[:, 1], 0, h - 1.001)
    x0, y0 = x.astype(int), y.astype(int)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    return (a[y0, x0] * (1 - fx) * (1 - fy) + a[y0, x0 + 1] * fx * (1 - fy)
            + a[y0 + 1, x0] * (1 - fx) * fy + a[y0 + 1, x0 + 1] * fx * fy)


def _strips(a, lm, t, palm_col, tol, ext=1.0, depth=0.07):
    """指の扇を横に切る 1 本の線の上で、両側を区切られた手の色の筋（中心と幅）を返す。
    線は 4 本の指の点（付け根から指先へ t の所）を結び、両端の指から指 1 本分だけ外へ延ばす。
    筋を区切るのは、手の色でない所と、両側より暗い谷（アニメの絵の指の間の線）。
    線の端に触れた筋は数えない。指の外に重なった体の肌や同じ色の髪は、輪郭の線の外で端まで続くので、
    ここで落ちる（前の数え方は、手の色の続く所を全部数え、4 本指の手を 5〜6 本と数えた）"""
    pts = np.array([lm[k] + (lm[k + 3] - lm[k]) * t for k in FAN])
    s = float(np.median(np.linalg.norm(np.diff(pts, axis=0), axis=1))) or 1.0
    u0 = (pts[0] - pts[1]) / (np.linalg.norm(pts[0] - pts[1]) or 1.0)
    u1 = (pts[3] - pts[2]) / (np.linalg.norm(pts[3] - pts[2]) or 1.0)
    poly = np.vstack([pts[0] + u0 * s * ext, pts, pts[3] + u1 * s * ext])
    L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))])
    q = np.arange(0.0, L[-1], 1.0)
    xy = np.stack([np.interp(q, L, poly[:, 0]), np.interp(q, L, poly[:, 1])], 1)
    col = _sample(a, xy)
    lp = float(np.mean(palm_col)) or 1.0
    lum = np.convolve(np.pad(col.mean(1), 2, mode="edge"), [0.06, 0.24, 0.4, 0.24, 0.06], "valid")
    n = len(lum)
    cut = np.abs(col - palm_col).sum(1) >= tol
    w = max(3, int(s * 0.3))
    for i in range(1, n - 1):
        if lum[i] <= lum[i - 1] and lum[i] <= lum[i + 1]:
            if min(lum[max(0, i - w):i].max(), lum[i + 1:i + 1 + w].max()) - lum[i] > depth * lp:
                cut[i] = True
    out, i = [], 0
    while i < n:
        if cut[i]:
            i += 1
            continue
        j = i
        while j < n and not cut[j]:
            j += 1
        if i > 0 and j < n and j - i >= 0.2 * s:
            out.append((xy[(i + j) // 2], float(j - i)))
        i = j
    return out


def straightness(lm) -> list[float]:
    """人差し指〜小指の、付け根から指先までの直線と関節をたどった長さの比（1 が伸びた指）"""
    return [float(np.linalg.norm(lm[k + 3] - lm[k]) / (length(lm, [k, k + 1, k + 2, k + 3]) or 1.0)) for k in FAN]


def count_fingers(a, lm, palm_col, tol: float = 120.0) -> dict:
    """親指の外の指の本数を数える。数えられないときは count を None にする（自信の無い数で手を落とさない）。

    指の付け根から指先までを 5 か所で横に切り、切った線ごとに、手の色の筋を取る（_strips）。
    筋を切った線から切った線へ、横の位置が筋の幅の半分より動かないものをつなぎ、3 本以上の線に続いた物を 1 本の指とする。
    指は付け根から先まで続くが、指の間の隙間や影の切れ端は 1〜2 本の線にしか出ない。
    次のときは数えない。
      - 指が 1 本でも曲がっている（握った手。曲げた指は横に切っても筋にならず、握り拳を 3 本と数えた）
      - 指が 2 本以下に見える（横から見た手や閉じた指。重なって隠れた指は数えられない）
      - 指として数えた本数と同じ数の筋が出た線が 4 本に満たない（線ごとに数が揺れる）
      - 指の幅の 2 倍より広い筋がある（体の肌や閉じた指の塊が指の扇の中に入っている）"""
    a = np.asarray(a, float)
    palm_col = np.asarray(palm_col, float)
    out = {"count": None, "rows": [], "reason": ""}
    tip_y = float(np.mean([lm[k + 3][1] for k in FAN]))
    base_y = float(np.mean([lm[k][1] for k in FAN]))
    if tip_y >= base_y - 8:
        out["reason"] = "指先が付け根より上に無い"
        return out
    if min(straightness(lm)) < 0.8:
        out["reason"] = "曲げた指がある"
        return out
    axis = np.mean([lm[k + 3] - lm[k] for k in FAN], axis=0)
    axis = axis / (np.linalg.norm(axis) or 1.0)
    perp = np.array([-axis[1], axis[0]])
    rows = [[(float(c @ perp), w) for c, w in _strips(a, lm, t, palm_col, tol)] for t in CUTS]
    out["rows"] = [len(r) for r in rows]
    chains: list[dict] = []
    for r, strips in enumerate(rows):
        for c, w in strips:
            near = [ch for ch in chains if ch["last"] == r - 1 and abs(ch["c"] - c) < 0.5 * max(w, ch["w"][-1])]
            if near:
                ch = min(near, key=lambda ch: abs(ch["c"] - c))
                ch.update(c=c, last=r)
                ch["w"].append(w)
            else:
                chains.append({"c": c, "w": [w], "last": r})
    fingers = [ch for ch in chains if len(ch["w"]) >= 3]
    n = len(fingers)
    if n <= 2:
        out["reason"] = f"指が {n} 本にしか見えない（重なって隠れている）"
        return out
    width = float(np.median([np.mean(ch["w"]) for ch in fingers]))
    agree = sum(len(r) == n for r in rows)
    # くっついた指: 3 本に見え、そのうち 1 本だけが残りの指の 1.6〜3 倍の幅（指 2 本と間の隙間）で、付け根から先まで続く。
    # 指 2 本が 1 本の塊になった形で、これまでは「広い手の色がある」として数えずに通していた
    ws = sorted(float(np.mean(ch["w"])) for ch in fingers)
    if n == 3 and agree >= 4 and 1.6 * ws[1] <= ws[2] <= 3.0 * ws[1] and len(fingers[int(np.argmax([np.mean(ch["w"]) for ch in fingers]))]["w"]) >= 4:
        out.update(reason="指がくっついている（指 2 本分の幅の塊）", fused=True, width=round(ws[1], 1))
        return out
    # 5 本の線のうち 4 本で同じ数が出たときだけ数える。3 本で通すと、崩れて読めない手（腕が絡んだ絵）を 3 本、5 本と言い切った
    if agree < 4:
        out["reason"] = f"切った線ごとに数が揺れる（{n} 本と同じ線が {agree} 本）"
        return out
    if any(w > 2.0 * width for r in rows for _, w in r):
        out["reason"] = "指の扇に、指の 2 倍より広い手の色がある"
        return out
    out["count"] = n
    out["width"] = round(width, 1)
    # 指の点どうしの一番狭い間（真ん中で切った所）。指 1 本の幅より広く離れていれば、指どうしは重なっていない
    mid = np.array([lm[k] + (lm[k + 3] - lm[k]) * 0.5 for k in FAN])
    out["apart"] = round(float(np.linalg.norm(np.diff(mid, axis=0), axis=1).min()) / (width or 1.0), 2)
    out["ghost"] = ghost_fingers(a, lm, palm_col, fingers, perp, width)
    return out


def ghost_fingers(a, lm, palm_col, fingers, perp, width) -> int:
    """数えた指の間に、薄く出た余分な指（下の色が透けた指）がいくつあるか。
    指の間の隙間のうち、指 1 本の幅の 0.6 倍より広い所の真ん中の色を、切った線ごとに見る。
    隙間の色が、手の色と扇の外（背景）の色の間（手の色への近さが背景の 3〜8 割）にある線が 3 本以上なら、薄い指とする。
    5 本と数えた手の指の間に、6 本目が薄く描かれた絵は、指の数でも形でも検品を逃れていた"""
    cs = sorted(ch["c"] for ch in fingers)
    if len(cs) < 2:
        return 0
    pts0 = np.array([lm[k] + (lm[k + 3] - lm[k]) * 0.5 for k in FAN])
    out_pts = np.array([pts0[0] + (pts0[0] - pts0[1]) * 1.2, pts0[3] + (pts0[3] - pts0[2]) * 1.2])
    bg = _sample(a, out_pts).mean(0)
    d_bg = float(np.abs(bg - palm_col).sum())
    if d_bg < 60:   # 扇の外も手の色に近い（体の肌の前の手）。薄い指と見分けられない
        return 0
    n = 0
    for c0, c1 in zip(cs, cs[1:]):
        if c1 - c0 < 1.6 * width:   # 隙間が指 0.6 本分に満たない
            continue
        hits = 0
        for t in CUTS:
            pts = np.array([lm[k] + (lm[k + 3] - lm[k]) * t for k in FAN])
            proj = pts @ perp
            # 切った線の上で、隙間の真ん中（c0 と c1 の中点）に当たる位置を、指の点の並びから補う
            order = np.argsort(proj)
            mid = (c0 + c1) / 2
            xy = np.array([np.interp(mid, proj[order], pts[order, 0]), np.interp(mid, proj[order], pts[order, 1])])
            col = _sample(a, xy[None])[0]
            r = float(np.abs(col - palm_col).sum()) / d_bg
            hits += 0.3 <= r <= 0.8
        n += hits >= 3
    return n


def _overlay(sq, lm):
    d = ImageDraw.Draw(sq)
    for i, j in EDGES:
        d.line([tuple(lm[i]), tuple(lm[j])], fill=(255, 0, 0), width=2)
    return sq


def auto_boxes(src, least=0.3):
    """肘と手首から、手の枠と、指先を上に向ける回転の角度を出す（--hand と同じ書式の文字列）"""
    sys.path.insert(0, str(Path(__file__).parent))
    import joints
    pts = {p["name"]: p for p in joints.find(src)}
    # 前腕が手前へ縮んで見えると、前腕の長さだけでは枠が手より小さくなる。鼻から足首までの高さの 4.5% を下限にする
    ankles = [pts[k]["y"] for k in ("left_ankle", "right_ankle") if pts[k]["score"] >= least]
    if ankles:
        tall = max(ankles) - pts["nose"]["y"]
    else:
        # 上半身の絵には足首が無い。でたらめな足首で枠が顔まで広がったので、肩幅（全身の高さのおよそ 1/4）から見当する
        tall = abs(pts["left_shoulder"]["x"] - pts["right_shoulder"]["x"]) * 4
    out = []
    for side in ("left", "right"):
        e, w = pts[f"{side}_elbow"], pts[f"{side}_wrist"]
        if min(e["score"], w["score"]) < least:
            continue
        dx, dy = w["x"] - e["x"], w["y"] - e["y"]
        fore = float(np.hypot(dx, dy)) or 1.0
        cx, cy = w["x"] + dx * 0.5, w["y"] + dy * 0.5
        r = max(fore * 0.55, tall * 0.045)
        # 前腕の向きを上（-y）に回す角度。PIL の rotate は反時計回りが正
        ang = float(np.degrees(np.arctan2(dx, -dy)))
        out.append(f"{int(cx - r)},{int(cy - r)},{int(cx + r)},{int(cy + r)}:{ang:.0f}")
    return out


def _anchors():
    """手のひらを探す模型の下敷きの点（192 画素、刻み 8 で 2 つずつ、刻み 16 で 6 つずつ。計 2016）"""
    out = []
    for stride, per in ((8, 2), (16, 6)):
        n = 192 // stride
        for y in range(n):
            for x in range(n):
                out += [((x + 0.5) / n, (y + 0.5) / n)] * per
    return np.array(out, np.float32)


_PD = None


def detect_palms(im, least=0.5):
    """手のひらを探す模型（MediaPipe）で手の場所を探し、--hand と同じ書式の枠を返す。
    肘が枠の外にある上半身の絵では、肘と手首から見当できなかった（2026-10-17、関節の確からしさ 0.12〜0.25）"""
    global _PD
    if _PD is None:
        _PD = _litert()(_model(MODEL.parent / "hand_detector.tflite"))
        _PD.allocate_tensors()
    w, h = im.size
    s = max(w, h)
    sq = Image.new("RGB", (s, s), (0, 0, 0))
    sq.paste(im, ((s - w) // 2, (s - h) // 2))
    x = np.asarray(sq.resize((192, 192), Image.BILINEAR), np.float32)[None] / 255.0
    _PD.set_tensor(_PD.get_input_details()[0]["index"], x)
    _PD.invoke()
    out = {d["name"]: _PD.get_tensor(d["index"]) for d in _PD.get_output_details()}
    raw, score = out["Identity"][0], 1 / (1 + np.exp(-np.clip(out["Identity_1"][0, :, 0], -50, 50)))
    anc = _anchors()
    found = []
    for i in np.argsort(-score):
        if score[i] < least:
            break
        cx, cy = raw[i, 0] / 192 + anc[i, 0], raw[i, 1] / 192 + anc[i, 1]
        if any(abs(cx - fx) < 0.05 and abs(cy - fy) < 0.05 for fx, fy, *_ in found):
            continue  # 同じ手を 2 度数えない
        side = max(raw[i, 2], raw[i, 3]) / 192
        wx, wy = raw[i, 4] / 192 + anc[i, 0], raw[i, 5] / 192 + anc[i, 1]      # 手首
        mx, my = raw[i, 8] / 192 + anc[i, 0], raw[i, 9] / 192 + anc[i, 1]      # 中指の付け根
        found.append((cx, cy, side, mx - wx, my - wy))
    boxes = []
    for cx, cy, side, dx, dy in found:
        # 手のひらの枠を指の向きへ半分ずらし、2.6 倍に広げると指先まで入る（MediaPipe の手の追跡と同じ）
        n = float(np.hypot(dx, dy)) or 1.0
        cx, cy = cx + dx / n * side * 0.5, cy + dy / n * side * 0.5
        r = side * 1.3 * s
        px, py = cx * s - (s - w) / 2, cy * s - (s - h) / 2
        ang = float(np.degrees(np.arctan2(dx, -dy)))
        boxes.append(f"{int(px - r)},{int(py - r)},{int(px + r)},{int(py + r)}:{ang:.0f}")
    return boxes


def best_crop(im, box, rot):
    """--auto の枠は肘と手首からの見当なので、大きさと角度を少しずつ変えて、手らしさが最も高い切り出しを選ぶ。
    模型は手が枠いっぱいで指先が上のときにしか読めず、見当のままでは写っている手の 4 つに 3 つを読めなかった"""
    x0, y0, x1, y1 = box
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
    best = None
    # 一辺 64 画素より小さく切ると、指だけの拡大を手と読んだ（手らしさ 0.97 で、点は指の上にでたらめに乗った）
    # 中心も前腕の向きに沿って手首側へずらす。手が前腕に比べて小さい絵（上半身で手を上げた絵）では、見当の中心が顔まで行き過ぎた
    ux, uy = np.sin(np.radians(rot)), -np.cos(np.radians(rot))
    cands = [(cx - ux * r * t, cy - uy * r * t, k) for t in (0, 0.5, 0.9) for k in (0.4, 0.6, 0.8, 1.0) if r * k * 2 >= 64]
    for x, y, k in cands or [(cx, cy, 1.0)]:
        for d in (-35, 0, 35):
            c = im.crop((int(x - r * k), int(y - r * k), int(x + r * k), int(y + r * k)))
            c = c.rotate(rot + d, expand=True, fillcolor=im.getpixel((0, 0)))
            p = landmarks(c)[2]
            if best is None or p > best[0]:
                best = (p, c)
    return best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--hand", action="append", default=[], metavar="x0,y0,x1,y1:角度")
    ap.add_argument("--auto", action="store_true", help="肘と手首から枠を出す")
    a = ap.parse_args()
    if a.auto:
        # 手のひらの模型を先に使う。肘と手首からの見当は、肘が枠の外にあると出ず、手の大きさも外しやすい
        a.hand += detect_palms(Image.open(a.src).convert("RGB")) or auto_boxes(a.src)
    if not a.hand:
        ap.error("手の枠が無い（--hand を付けるか、--auto で肘と手首が読める絵にする）")
    im = Image.open(a.src).convert("RGB")
    ok = True
    for i, h in enumerate(a.hand):
        box, _, rot = h.partition(":")
        crop = best_crop(im, tuple(int(v) for v in box.split(",")), float(rot or 0)) if a.auto else \
            im.crop(tuple(int(v) for v in box.split(","))).rotate(float(rot or 0), expand=True, fillcolor=im.getpixel((0, 0)))
        m, bad, view = measure(crop)
        view.save(f"{a.src}.hand{i}.png")
        print(json.dumps({"hand": h, "measure": m, "outside": bad}, ensure_ascii=False))
        ok = ok and not bad
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
