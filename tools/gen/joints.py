"""絵の人物の関節の位置を取る（肩・肘・手首・腰・膝・足首・目・耳・鼻）。

しわ・線の強弱・目の向きを、乱数でなく理由から決めるための手がかり（docs/knowledge/folds-and-lines.md）。
布が引っかかる支点（肩・腰）、曲がった関節（肘・膝）、顔の向き（両目と耳）が要る。部位分けだけでは分からない。

模型は RTMPose-m（body7、Apache-2.0、OpenMMLab）の ONNX。人物の枠は背景抜きの範囲から取るので、人物検出の模型は使わない。
前処理と後処理（枠を 1.25 倍に広げて 192x256 に切る、SimCC の最大値の位置を 2 で割る）は模型の pipeline.json のとおり。

  sh tools/gen/setup.sh で取ったあと  python3 tools/gen/joints.py IMAGE [OUT.png]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".cache" / "gen" / "pose" / "rtmpose-m-body7.onnx"
URL = ("https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
       "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip")
# COCO の 17 点の並び
NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
         "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]
BONES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
         (0, 1), (0, 2), (1, 3), (2, 4)]
W, H = 192, 256
MEAN = np.array([123.675, 116.28, 103.53])
STD = np.array([58.395, 57.12, 57.375])


def crop_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """人物の枠を 1.25 倍に広げ、縦横比 192:256 に合わせた切り出し枠（左, 上, 右, 下）"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = (x1 - x0) * 1.25, (y1 - y0) * 1.25
    if w / h > W / H:
        h = w * H / W
    else:
        w = h * W / H
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def decode(simcc_x: np.ndarray, simcc_y: np.ndarray, box) -> list[dict]:
    """SimCC の出力（点ごとの x・y の分布、2 倍の細かさ）から、元の絵の座標と確からしさを取る"""
    x0, y0, x1, y1 = box
    out = []
    for i, name in enumerate(NAMES):
        px, py = simcc_x[i].argmax() / 2, simcc_y[i].argmax() / 2
        score = float(min(simcc_x[i].max(), simcc_y[i].max()))
        out.append({"name": name, "x": float(x0 + px / W * (x1 - x0)), "y": float(y0 + py / H * (y1 - y0)), "score": score})
    return out


def find(src: str) -> list[dict]:
    import onnxruntime as ort
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    im = Image.open(src).convert("RGB")
    alpha = np.asarray(design.cut_background(im).getchannel("A")) > 0
    ys, xs = np.nonzero(alpha)
    box = crop_box((xs.min(), ys.min(), xs.max(), ys.max()))
    # 枠が絵の外へ出る所は、学習時の平均の色で埋める（PIL の crop は外を黒で埋め、黒い塊を体と取り違えうる）
    bx = tuple(int(round(v)) for v in box)
    canvas = Image.new("RGB", (bx[2] - bx[0], bx[3] - bx[1]), tuple(int(v) for v in MEAN))
    canvas.paste(im, (-bx[0], -bx[1]))
    patch = canvas.resize((W, H), Image.BILINEAR)
    x = ((np.asarray(patch).astype(np.float32) - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    sx, sy = sess.run(None, {sess.get_inputs()[0].name: x})
    return decode(sx[0], sy[0], box)


def draw(src: str, points: list[dict], out: str, least: float = 0.3):
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    for a, b in BONES:
        if points[a]["score"] >= least and points[b]["score"] >= least:
            d.line([(points[a]["x"], points[a]["y"]), (points[b]["x"], points[b]["y"])], fill=(0, 200, 255), width=3)
    for p in points:
        r = 5
        c = (255, 40, 40) if p["score"] >= least else (120, 120, 120)
        d.ellipse([p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r], fill=c)
    im.save(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    pts = find(sys.argv[1])
    if len(sys.argv) > 2:
        draw(sys.argv[1], pts, sys.argv[2])
    print(json.dumps([{**p, "x": round(p["x"]), "y": round(p["y"]), "score": round(p["score"], 2)} for p in pts], ensure_ascii=False))
