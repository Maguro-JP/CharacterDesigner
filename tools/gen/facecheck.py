"""顔の検品。描いた絵の顔を切り出し、目が描かれているかを測る。

手の影や強い光で目が消え、顔の無い人に見える絵が出た（全身の絵で、顔の幅が 120 画素ほどのとき）。
絵全体をタグで読むと、顔が小さいので目の有無が埋もれる。そこで VitPose の鼻・目・耳の点から顔を切り出し、
切り出しだけをタグの模型（wd-vit-tagger-v3）で読む。目の色のタグ（brown eyes など）は目が見えている印、
closed eyes・faceless・no eyes は目が無い印として使う。

- 閉じた目を頼んだ絵（closed eyes、sleeping、wink など）では、閉じた目を崩れにしない
- 顔が写っていない・小さすぎる・人でないと読めたときは「読めない」を返す。読めない絵を崩れにしない（誤りの警告で描き直しが止まらなくなる）
- 目の帯の暗い画素の割合（eye_dark）も控える。今は判定に使わず、数字を貯めて閾値を決めるために残す
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACE_POINTS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")
# 目が閉じている・無いと読むタグ。頼んだ言葉にこれらがあれば、閉じた目は崩れではない
CLOSED_ASKED = ("closed eyes", "sleeping", "wink", "one eye closed", "eyes closed", "^^^", "half-closed eyes", "faceless",
                "covering eyes", "blindfold", "eyepatch", "eye mask", "hair over eyes")
NO_EYES = ("faceless", "no eyes", "blank eyes")
MIN_FACE = 64         # 顔の切り出しがこれより小さい（画素）と、目を読み分けられない（52 画素の顔ではタグが何も出なかった）
CLOSED_AT = 0.6       # 試した絵で、目の消えた絵は 0.95、普通の顔の最大は 0.41 だった
OPEN_BELOW = 0.3      # 目の色のタグの最大がこれ未満のときだけ「目が無い」とする
NO_EYES_AT = 0.4


def face_box(keypoints: dict, size: tuple[int, int]):
    """顔の点から、髪の生え際から顎までが入る正方形の枠。点が 2 つ未満か小さすぎれば None"""
    pts = [keypoints[k] for k in FACE_POINTS if k in keypoints]
    if len(pts) < 2 or "nose" not in keypoints or not ("left_eye" in keypoints or "right_eye" in keypoints):
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    sh = [keypoints[k] for k in ("left_shoulder", "right_shoulder") if k in keypoints]
    span = max(max(xs) - min(xs), abs(sh[0][0] - sh[1][0]) * 0.6 if len(sh) == 2 else 0)
    half = 1.3 * span
    w, h = size
    box = [max(0, int(cx - half)), max(0, int(cy - half * 1.1)), min(w, int(cx + half)), min(h, int(cy + half * 0.9))]
    if box[2] - box[0] < MIN_FACE or box[3] - box[1] < MIN_FACE:
        return None
    return box


def eye_dark(image, keypoints: dict) -> float | None:
    """目の点の間の帯で、顔の肌の中央値より 60 以上暗い画素の割合。目が描かれていれば瞳とまつ毛で暗い画素が出る"""
    import numpy as np
    eyes = [keypoints[k] for k in ("left_eye", "right_eye") if k in keypoints]
    if len(eyes) < 2:
        return None
    d = max(abs(eyes[0][0] - eyes[1][0]), 8)
    x0, x1 = int(min(e[0] for e in eyes) - 0.4 * d), int(max(e[0] for e in eyes) + 0.4 * d)
    y = sum(e[1] for e in eyes) / 2
    band = np.asarray(image.convert("L").crop((x0, int(y - 0.3 * d), x1, int(y + 0.3 * d))), dtype=np.float32)
    if band.size == 0:
        return None
    return round(float((band < np.median(band) - 60).mean()), 4)


def _read_tags(crop) -> dict:
    sys.path.insert(0, str(ROOT))
    from chatdraw import requestcheck
    tg = requestcheck._tagger(False)
    tmp = Path(tempfile.mkdtemp()) / "face.png"
    crop.save(tmp)
    return tg.read(str(tmp), threshold=0.05)


def judge(tags: dict, asked: str = "") -> list[str]:
    """顔の切り出しのタグから崩れを返す（模型を使わないので試験で直に確かめられる）"""
    low = asked.lower()
    if any(a in low for a in CLOSED_ASKED):
        return []
    open_ = max([p for t, p in tags.items() if t.endswith(" eyes") and t.split(" ")[0] in COLORS] or [0.0])
    if max(tags.get(t, 0.0) for t in NO_EYES) >= NO_EYES_AT:
        return ["顔: 目が描かれていない（顔の無い人に読める）"]
    if tags.get("closed eyes", 0.0) >= CLOSED_AT and open_ < OPEN_BELOW:
        return ["顔: 目が描かれていない（目が消えて閉じた目に読める。頼んでいない）"]
    return []


COLORS = ("brown", "black", "blue", "red", "green", "grey", "purple", "pink", "yellow", "orange", "aqua", "white",
          "silver", "gold", "amber", "golden", "multicolored", "heterochromia")


def check_face(image, keypoints: dict | None = None, asked: str = "") -> dict:
    """絵（PIL か道）の顔を測る。box は顔の枠、readable が False なら顔を読めなかった（崩れとは言わない）"""
    from PIL import Image
    im = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    out = {"box": None, "readable": False, "bad": [], "tags": {}, "eye_dark": None}
    try:
        if keypoints is None:
            sys.path.insert(0, str(ROOT))
            from chatdraw import twostage
            keypoints = twostage.keypoints(im)
        box = face_box(keypoints, im.size)
        if box is None:
            out["reason"] = "顔が写っていないか、小さすぎます"
            return out
        out["box"] = box
        tags = _read_tags(im.crop(box))
    except Exception as e:   # 部品か模型が無い。描いた絵は止めず、検品が無いことを返す
        out["reason"] = f"顔の検品の部品がありません（{e}）"
        return out
    out["tags"] = {t: p for t, p in tags.items() if "eye" in t or "face" in t or t == "no humans"}
    if tags.get("no humans", 0.0) >= 0.5:
        out["reason"] = "顔の枠に人が読めません"
        return out
    out["readable"] = True
    out["eye_dark"] = eye_dark(im, keypoints)
    out["bad"] = judge(tags, asked)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="絵の顔に目が描かれているかを測る")
    ap.add_argument("image", nargs="+")
    ap.add_argument("--asked", default="", help="頼んだタグ（closed eyes を頼んだ絵は閉じた目を崩れにしない）")
    a = ap.parse_args(argv)
    for p in a.image:
        print(p, json.dumps(check_face(p, asked=a.asked), ensure_ascii=False))


if __name__ == "__main__":
    main()
