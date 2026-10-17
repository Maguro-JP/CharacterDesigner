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
角度は、指先が上を向くまでに絵を回す角度（度。指先が下なら 180）。
--auto は肘と手首（tools/gen/joints.py）から枠と角度を出す。手は前腕の延長に付くので、手首から前腕の向きへ
前腕の 0.5 倍進んだ所を中心、前腕の 1.1 倍を一辺にする。握った手や手首を強く曲げた手では外れうるので、
外れた枠は .hand*.png の赤い線で見て、--hand で指定し直す。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".cache" / "gen" / "mediapipe" / "hand_landmarks_detector.tflite"
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


def _interp():
    global _IT
    if _IT is None:
        from ai_edge_litert.interpreter import Interpreter
        _IT = Interpreter(str(MODEL))
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
            if not lo <= v <= hi:
                bad.append(f"{name}{'の手の色' if k == 'cover' else ''} {v}（{lo}〜{hi}）")
    return m, bad, _overlay(sq, lm)


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
        a.hand += auto_boxes(a.src)
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
