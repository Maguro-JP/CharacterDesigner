"""体の釣り合いの検品。利用者の基準の体（chatdraw/body.py）から大きく外れた体（大きすぎる胸、張りすぎた腰、細すぎる腰）を数字で見つける。

体の点（DWPose の体の 17 点、tools/gen/feet.py と同じ模型）で肩・腰の高さを取り、その高さの行ごとに人の輪郭の幅を測る。
輪郭は、行の両端の色（背景）から離れた色の続きのうち、体の中心を含むものとする。
輪郭の幅は、垂らした腕や背景の物を胴と一緒に拾い、8 枚の絵で胸 / くびれが 2.0〜9.6 とばらついた
（タグで胸が普通と読めた絵も外れた）。それで輪郭の比は記録だけにし、崩れを決めるのはタグの確からしさ（from_tags）にする。
"""
from __future__ import annotations

import numpy as np

# 基準の体（chatdraw/body.py の NEGATIVE）で描かない体のタグと、崩れとする確からしさ。
# 9 枚の絵で、目で見て胸と脚が大きすぎた絵は huge breasts 0.42〜0.68、thick thighs 0.54。普通の絵は 0.15 以下と 0.33 以下だった
EXAGGERATED = {"huge breasts": 0.4, "gigantic breasts": 0.3, "thick thighs": 0.45, "plump": 0.4, "fat": 0.4, "muscular": 0.5, "abs": 0.5}
WORDS = {"huge breasts": "胸が大きすぎる", "gigantic breasts": "胸が大きすぎる", "thick thighs": "太ももが太すぎる",
         "plump": "体が太すぎる", "fat": "体が太すぎる", "muscular": "筋肉が付きすぎ", "abs": "腹筋が割れている"}


def from_tags(got: dict, prompt: str) -> list[str]:
    """読んだタグのうち、基準の体から外れた体のタグ（頼みに同じ語があれば数えない）"""
    low = prompt.lower()
    return [f"体: {WORDS[t]}（{t} {got[t]}）" for t, least in EXAGGERATED.items() if got.get(t, 0.0) >= least and t not in low]
COCO = ("nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
        "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")


def body_points(im) -> dict:
    """DWPose の体の 17 点（確からしさ 0.3 以上）。模型が無ければ例外"""
    import feet
    w, h = im.size
    k = feet._pose(im, (0, 0, w, h))
    return {n: (float(k[i, 0]), float(k[i, 1])) for i, n in enumerate(COCO) if k[i, 2] >= feet.LEAST}


def _row_width(a, y, cx, tol=45.0) -> float | None:
    """行 y の、背景（行の両端 3% の色）から離れた色の続きのうち cx を含むものの幅。両端の色が揺れれば None"""
    row = a[int(y)]
    n = len(row)
    e = max(3, n // 33)
    ends = np.concatenate([row[:e], row[-e:]])
    if ends.std(0).sum() > 60:   # 背景が一様でない
        return None
    bg = np.median(ends, 0)
    fg = np.abs(row - bg).sum(1) > tol
    # 線画の 1〜2 画素の隙間で輪郭が切れないよう、5 画素までの隙間は埋める
    idx = np.flatnonzero(fg)
    if idx.size == 0:
        return None
    c = int(np.clip(cx, 0, n - 1))
    gaps = np.flatnonzero(np.diff(idx) > 5)
    starts = np.concatenate([[idx[0]], idx[gaps + 1]])
    ends_ = np.concatenate([idx[gaps], [idx[-1]]])
    for s, t in zip(starts, ends_):
        if s <= c <= t:
            return float(t - s + 1)
    return None


def measure(im, kp: dict) -> dict:
    """肩と腰の点から、胸・くびれ・腰の行の幅と比を返す。測れなければ reason を入れる"""
    need = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    if not all(n in kp for n in need):
        return {"reason": "肩と腰の点が読めない"}
    a = np.asarray(im.convert("RGB"), np.float32)
    ls, rs, lh, rh = (np.array(kp[n]) for n in need)
    sy, hy = (ls[1] + rs[1]) / 2, (lh[1] + rh[1]) / 2
    torso = hy - sy
    if torso < 20:
        return {"reason": "胴が短すぎる（横か後ろ向き）"}
    shoulder = float(np.linalg.norm(ls - rs))
    cx = lambda t: float((ls[0] + rs[0]) / 2 * (1 - t) + (lh[0] + rh[0]) / 2 * t)

    def band(t0, t1, pick):
        ws = [w for t in np.linspace(t0, t1, 7) if (w := _row_width(a, sy + torso * t, cx(min(t, 1.0)))) is not None]
        return pick(ws) if len(ws) >= 4 else None
    chest = band(0.2, 0.45, max)      # 胸の行のうち一番広い所
    waist = band(0.55, 0.85, min)     # くびれ（一番狭い所）
    hip = band(0.95, 1.25, max)       # 腰（一番広い所）
    if None in (chest, waist, hip) or waist < 5:
        return {"reason": "輪郭が取れない（背景が一様でないか、腕が胴に重なっている）"}
    m = {"chest": chest, "waist": waist, "hip": hip, "shoulder": round(shoulder, 1),
         "chest_waist": round(chest / waist, 2), "hip_waist": round(hip / waist, 2),
         "chest_shoulder": round(chest / max(shoulder, 1.0), 2)}
    return m


def check(im, kp: dict | None = None) -> dict:
    """輪郭の幅の比（記録だけ。崩れは from_tags で決める）。模型か点が無ければ readable を False にする"""
    try:
        if kp is None or not all(n in kp for n in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")):
            kp = body_points(im)
    except Exception as e:
        return {"readable": False, "reason": f"体の点の模型がありません（{e}）"}
    m = measure(im, kp)
    if "reason" in m:
        return {"readable": False, "reason": m["reason"]}
    return {"readable": True, "measure": m}
