"""工程に分けて描く（chatdraw/phases.py）の、模型を使わない測り方と処理。

人が描くときに工程の合間で見ている物（重心、等身、左右の目、画面の重さ、光源と影の向き、目の光、縮めて見る・反転して見る）を数字にし、
模型で描かなくてもできる事（線の強弱、影の 2 段目）は、ここで絵に掛ける。どれも numpy と Pillow だけで、1 回 1 秒に届かない軽さにする
（工程を重くすると進まず、まとめるとメモリが溢れて落ちたので）。

しきい値はどれも私の推測の値で、Actions の phase-bench の絵で見直す。
"""
from __future__ import annotations

BG_DIFF = 30          # 四隅の色からこれだけ離れた画素を人物（紙でない所）とする（0〜255 の RGB の距離）
BALANCE_MOST = 0.6    # 重心が足の幅の中心から、足の幅のこの割合より外れたら「立てない」とする
HEADS = (2.0, 9.5)    # 等身の範囲。外れたら体の比が崩れている
EYE_TILT = 0.25       # 左右の目の高さの差が、目の間の幅のこの割合を超えたら崩れ
WEIGHT_MOST = 0.35    # サムネイルの画面の重さ（暗い塊）の重心が、真ん中から幅のこの割合より外れたら釣り合いが悪い
LINE_GAP_MOST = 0.75  # 人物の外の輪郭のうち、線の無い所の割合がこれを超えたら輪郭が途切れている
OUTER_DARK = 0.65     # 線の強弱: 外の輪郭の線をこの倍率まで暗くする（手前・外側を太く濃く）
SHADE2 = 0.82         # 影の 2 段目: 影の中の一番暗い所をこの倍率で暗くする
SHADE2_PART = 0.12    # 影の 2 段目にする割合（人物の画素のうち暗い方から）
CATCHLIGHT = 200      # 目の中にこれより明るい画素が無ければ、目の光が無い
SHRINK = 8            # 縮めて見る倍率
SHRINK_CONTRAST = 12  # 縮めた絵で人物と紙の明るさの差がこれより小さければ、主役が目立たない
FLIP_MOST = 0.32      # 顔を左右に反転して重ねた差（0〜1）がこれを超えたら、顔が片側に歪んでいる

SKIN = {11, 12, 13, 14, 15}            # 部位分け（facefeat.seg）の顔・脚・腕
HAIR = {2}
WEAR = {1, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17}   # 帽子・眼鏡・服・靴・鞄・マフラー


def _np(image):
    import numpy as np
    return np.asarray(image.convert("RGB"), dtype=np.int16)


def luminance(image):
    import numpy as np
    a = _np(image).astype(np.float32)
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def silhouette(image):
    """人物（紙でない所）の真偽の配列。四隅の色の中央を紙の色とする。部位分けがあればそれを使う"""
    import numpy as np
    a = _np(image)
    h, w = a.shape[:2]
    k = max(2, min(w, h) // 20)
    corners = np.concatenate([a[:k, :k].reshape(-1, 3), a[:k, -k:].reshape(-1, 3), a[-k:, :k].reshape(-1, 3), a[-k:, -k:].reshape(-1, 3)])
    paper = np.median(corners, axis=0)
    return np.sqrt(((a - paper) ** 2).sum(axis=2)) > BG_DIFF


def parts(image):
    """部位分けの番号の配列。部位分けの模型が無いときは None（測れなかったことを測れたことにしない）"""
    try:
        from chatdraw import facefeat
        return facefeat.seg(image)
    except Exception:   # noqa: BLE001
        return None


def thumb_weight(image) -> dict:
    """サムネイルの画面の重さ: 64 画素に縮め、暗い塊の重心が真ん中からどれだけ外れているか（幅・高さの割合）"""
    import numpy as np
    from PIL import Image
    small = image.convert("L").resize((64, max(8, int(64 * image.height / image.width))), Image.BOX)
    a = 255.0 - np.asarray(small, dtype=np.float32)
    total = float(a.sum()) or 1.0
    ys, xs = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    cx, cy = float((a * xs).sum() / total) / a.shape[1], float((a * ys).sum() / total) / a.shape[0]
    return {"weight_x": round(abs(cx - 0.5), 3), "weight_y": round(cy, 3), "ink": round(total / a.size / 255, 3)}


def balance(image, mask=None) -> dict:
    """重心: 人物の画素の重心の横の位置が、下の 8% の行（足）の幅の中心からどれだけ外れているか（足の幅の割合）"""
    import numpy as np
    m = silhouette(image) if mask is None else mask
    ys, xs = np.nonzero(m)
    if len(xs) < 50:
        return {"readable": False}
    y1 = ys.max()
    y0 = y1 - max(2, int((y1 - ys.min()) * 0.08))
    feet = xs[ys >= y0]
    mid, width = (feet.min() + feet.max()) / 2, max(feet.max() - feet.min(), m.shape[1] * 0.1)
    off = abs(float(xs.mean()) - mid) / width
    return {"readable": True, "balance": round(off, 3), "height": int(y1 - ys.min())}


def heads(points: dict, height: int) -> float | None:
    """等身: 人物の高さ ÷ 頭の高さ。頭の高さは、目から肩の中ほどまでの 1.3 倍とみる（私の推測の比）"""
    need = ("left_eye", "right_eye", "left_shoulder", "right_shoulder")
    if not height or not all(k in points for k in need):
        return None
    eye = (points["left_eye"][1] + points["right_eye"][1]) / 2
    sh = (points["left_shoulder"][1] + points["right_shoulder"][1]) / 2
    head = abs(sh - eye) * 1.3
    return round(height / head, 2) if head > 1 else None


def eye_tilt(points: dict) -> float | None:
    """左右の目の高さの差 ÷ 目の間の幅"""
    if "left_eye" not in points or "right_eye" not in points:
        return None
    (lx, ly), (rx, ry) = points["left_eye"][:2], points["right_eye"][:2]
    return round(abs(ly - ry) / max(abs(lx - rx), 1.0), 3)


def _erode(m, r):
    from PIL import Image, ImageFilter
    import numpy as np
    img = Image.fromarray((m * 255).astype("uint8"))
    return np.asarray(img.filter(ImageFilter.MinFilter(2 * r + 1))) > 127


def _dilate(m, r):
    from PIL import Image, ImageFilter
    import numpy as np
    img = Image.fromarray((m * 255).astype("uint8"))
    return np.asarray(img.filter(ImageFilter.MaxFilter(2 * r + 1))) > 127


def lines(image) -> dict:
    """線画を見る: 外の輪郭のうち線（暗い画素）の無い所の割合と、線と周りの明るさの差"""
    import numpy as np
    lum = luminance(image)
    m = silhouette(image)
    if m.sum() < 50:
        return {"readable": False}
    edge = m & ~_erode(m, 1)
    dark = lum < np.percentile(lum[m], 20)
    near = _dilate(dark, 2)
    gap = 1.0 - float((edge & near).sum()) / max(int(edge.sum()), 1)
    contrast = float(lum[m & ~dark].mean() - lum[dark & m].mean()) if (dark & m).any() else 0.0
    return {"readable": True, "gap": round(gap, 3), "contrast": round(contrast, 1)}


def weight_lines(image):
    """線の強弱: 外の輪郭に掛かっている線だけを暗くする（手前・外側を太く濃く、内側の細い線はそのまま）。人物の外は 1 画素も変えない"""
    import numpy as np
    from PIL import Image
    a = _np(image).astype(np.float32)
    lum = luminance(image)
    m = silhouette(image)
    if m.sum() < 50:
        return image, 0
    outer = _dilate(m, 1) & ~_erode(m, 2)
    dark = lum < np.percentile(lum[m], 30)
    hit = outer & dark & m
    a[hit] *= OUTER_DARK
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8")), int(hit.sum())


def light(image) -> dict:
    """光源: 人物の左右・上下の明るさの差から、光の来る向きを決める。dx が正なら右から、dy が負なら上から"""
    import numpy as np
    lum = luminance(image)
    m = silhouette(image)
    ys, xs = np.nonzero(m)
    if len(xs) < 50:
        return {"readable": False}
    cx, cy = xs.mean(), ys.mean()
    v = lum[ys, xs]
    dx = float(v[xs > cx].mean() - v[xs <= cx].mean()) if (xs > cx).any() and (xs <= cx).any() else 0.0
    dy = float(v[ys > cy].mean() - v[ys <= cy].mean()) if (ys > cy).any() and (ys <= cy).any() else 0.0
    return {"readable": True, "dx": round(dx, 1), "dy": round(dy, 1), "side": "右" if dx > 0 else "左"}


def shadows(image, lit: dict) -> dict:
    """影の向き: 光源と反対の側の明るさが光の側より暗いか（影が光より明るくなっていないか）、暗い画素の何割が影の側にあるか"""
    import numpy as np
    lum = luminance(image)
    m = silhouette(image)
    ys, xs = np.nonzero(m)
    if len(xs) < 50 or not lit.get("readable"):
        return {"readable": False}
    cx = xs.mean()
    v = lum[ys, xs]
    shade_side = (xs <= cx) if lit["dx"] > 0 else (xs > cx)
    dark = v < np.percentile(v, 30)
    share = float((dark & shade_side).sum()) / max(int(dark.sum()), 1)
    brighter = float(v[shade_side].mean() - v[~shade_side].mean()) if shade_side.any() and (~shade_side).any() else 0.0
    return {"readable": True, "shade_share": round(share, 3), "shade_minus_lit": round(brighter, 1)}


def shade_second(image, lit: dict, keep=None):
    """影の 2 段目: 光源と反対の側の、人物の中で一番暗い所だけを一段暗くする。keep（守る所、真の所）は変えない"""
    import numpy as np
    from PIL import Image
    a = _np(image).astype(np.float32)
    lum = luminance(image)
    m = silhouette(image)
    ys, xs = np.nonzero(m)
    if len(xs) < 50 or not lit.get("readable"):
        return image, 0
    cx = xs.mean()
    cols = np.arange(m.shape[1])[None, :]
    side = (cols <= cx) if lit["dx"] > 0 else (cols > cx)
    hit = m & side & (lum <= np.percentile(lum[m], SHADE2_PART * 100))
    if keep is not None:
        hit &= ~keep
    a[hit] *= SHADE2
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8")), int(hit.sum())


def eye_boxes(points: dict) -> list[tuple[int, int, int, int]]:
    if "left_eye" not in points or "right_eye" not in points:
        return []
    (lx, ly), (rx, ry) = points["left_eye"][:2], points["right_eye"][:2]
    r = max(3, int(abs(lx - rx) * 0.3))
    return [(int(x - r), int(y - r), int(x + r), int(y + r)) for x, y in ((lx, ly), (rx, ry))]


def catchlights(image, points: dict) -> dict:
    """目の光: 両目の囲みの中の一番明るい画素"""
    import numpy as np
    lum = luminance(image)
    boxes = eye_boxes(points)
    if not boxes:
        return {"readable": False}
    h, w = lum.shape
    best = []
    for x0, y0, x1, y1 in boxes:
        part = lum[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
        best.append(int(part.max()) if part.size else 0)
    return {"readable": True, "eye_max": best, "boxes": boxes}


def shrink_view(image) -> dict:
    """縮めて見る: 1/8 に縮め、人物と紙の明るさの差（主役が目立つか）"""
    import numpy as np
    from PIL import Image
    small = image.resize((max(8, image.width // SHRINK), max(8, image.height // SHRINK)), Image.BOX)
    m = silhouette(small)
    lum = luminance(small)
    if m.sum() < 4 or (~m).sum() < 4:
        return {"readable": False}
    return {"readable": True, "contrast": round(abs(float(lum[m].mean() - lum[~m].mean())), 1)}


def flip_view(image, box) -> dict:
    """反転して見る: 顔の囲みを左右に反転して重ね、差の平均（0〜1）。人は反転すると片側に寄った歪みに気づく"""
    import numpy as np
    from PIL import ImageOps
    if not box:
        return {"readable": False}
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return {"readable": False}
    face = image.convert("L").crop((x0, y0, x1, y1))
    a = np.asarray(face, dtype=np.float32)
    b = np.asarray(ImageOps.mirror(face), dtype=np.float32)
    return {"readable": True, "asym": round(float(np.abs(a - b).mean()) / 255, 3)}


def face_box(points: dict):
    """体の点から顔の囲み（目・耳・鼻）"""
    keys = [k for k in ("nose", "left_eye", "right_eye", "left_ear", "right_ear") if k in points]
    if len(keys) < 3:
        return None
    xs = [points[k][0] for k in keys]
    ys = [points[k][1] for k in keys]
    r = max(max(xs) - min(xs), 8) * 0.8
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return (cx - r, cy - r * 1.1, cx + r, cy + r * 1.2)


def wear_mask(image, protect_boxes=()):
    """服・髪・持ち物の工程で描いてよい所（L の絵）。部位分けがあれば髪・服・持ち物、無ければ人物の全体。顔・手の囲みは除く"""
    import numpy as np
    from PIL import Image, ImageDraw
    p = parts(image)
    if p is not None:
        m = np.isin(p, list(HAIR | WEAR))
    else:
        m = silhouette(image)
    m = _dilate(m, 3)
    mask = Image.fromarray((m * 255).astype("uint8"))
    d = ImageDraw.Draw(mask)
    for b in protect_boxes:
        d.rectangle([int(v) for v in b], fill=0)
    return mask, p is not None
