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
角度は、指先が上を向くまでに絵を回す角度（度。指先が下なら 180）。
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
    palm_pts = [lm[0] * 0.5 + lm[k] * 0.5 for k in (5, 9, 13, 17)]
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
    for k, (lo, hi) in NORMS.items():
        vals = m[k].items() if isinstance(m[k], dict) else [(k, m[k])]
        for name, v in vals:
            if not lo <= v <= hi:
                bad.append(f"{name}{'の手の色' if k == 'cover' else ''} {v}（{lo}〜{hi}）")
    d = ImageDraw.Draw(sq)
    for i, j in EDGES:
        d.line([tuple(lm[i]), tuple(lm[j])], fill=(255, 0, 0), width=2)
    return m, bad, sq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--hand", action="append", required=True, metavar="x0,y0,x1,y1:角度")
    a = ap.parse_args()
    im = Image.open(a.src).convert("RGB")
    ok = True
    for i, h in enumerate(a.hand):
        box, _, rot = h.partition(":")
        crop = im.crop(tuple(int(v) for v in box.split(","))).rotate(float(rot or 0), expand=True, fillcolor=im.getpixel((0, 0)))
        m, bad, view = measure(crop)
        view.save(f"{a.src}.hand{i}.png")
        print(json.dumps({"hand": h, "measure": m, "outside": bad}, ensure_ascii=False))
        ok = ok and not bad
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
