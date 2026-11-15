"""模型を使わない編集の道具（整える・揃える・消す）。

AI の絵の小さな崩れは、模型で描き直すより、画素を直接いじる方が元の絵を崩さない。どの道具も
- 囲み（mask の白）があれば、その中だけを変える。囲みの外は 1 画素も変えない
- 入力の絵は書き換えず、新しい絵を返す（アプリは変わった画素だけのレイヤーにして置き、元に戻すで戻せる）
- numpy と Pillow だけで動く（scipy があれば塊の数え上げに使い、無ければ自前で数える）
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter


def _inside(original, result, mask):
    """囲みの中だけ result、外は original。囲みが無ければ result"""
    if mask is None:
        return result
    m = mask.convert("L").resize(original.size).point(lambda v: 255 if v > 127 else 0)
    return Image.composite(result, original, m)


def _labels(hit):
    """真偽の 2 次元の並びの、つながった塊に番号を振る（8 近傍）。(番号の並び, 数)"""
    import numpy as np
    try:
        from scipy import ndimage
        return ndimage.label(hit, structure=np.ones((3, 3), int))
    except ImportError:
        pass
    lab = np.zeros(hit.shape, np.int32)
    n = 0
    h, w = hit.shape
    for y, x in zip(*np.nonzero(hit)):
        if lab[y, x]:
            continue
        n += 1
        stack = [(y, x)]
        lab[y, x] = n
        while stack:
            cy, cx = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and hit[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = n
                        stack.append((ny, nx))
    return lab, n


def erase(image, mask, rounds: int = 60):
    """囲んだ所の物を、周りの色で埋めて消す（余計な物・文字・ゴミ）。囲みが無ければ何もしない"""
    if mask is None:
        return image.convert("RGB").copy()
    from chatdraw.engine import erase as _erase
    img = image.convert("RGB")
    return _erase(img, mask.convert("L").resize(img.size), rounds)


def despeckle(image, mask=None, max_area: int = 12, contrast: int = 60):
    """ゴミの点（周りの色から浮いた、max_area 画素以下の小さな塊）を、周りの色で消す。
    線の一部は塊が大きいので残る。消した点の数は last_count に入れる"""
    import numpy as np
    img = image.convert("RGB")
    # 9 画素の窓の真ん中の値を地の色とする。細い線は線ごと 1 つの大きな塊になり、点だけが小さな塊で残る
    # （5 画素の窓では線の端だけが地と違って小さな塊になり、線の端まで消していた）
    med = img.filter(ImageFilter.MedianFilter(9))
    a = np.asarray(img).astype(np.int16)
    b = np.asarray(med).astype(np.int16)
    hit = np.abs(a - b).sum(axis=2) > contrast
    if mask is not None:
        hit &= np.asarray(mask.convert("L").resize(img.size)) > 127
    lab, n = _labels(hit)
    out = a.copy()
    count = 0
    if n:
        sizes = np.bincount(lab.ravel())
        small = np.zeros(n + 1, bool)
        small[1:] = sizes[1:] <= max_area
        sel = small[lab]
        out[sel] = b[sel]
        count = int(small.sum())
    despeckle.last_count = count
    return _inside(img, Image.fromarray(out.astype(np.uint8), "RGB"), mask)


despeckle.last_count = 0


def smooth_lines(image, mask=None, strength: int = 2, dark: int = 110):
    """線の揺れを滑らかにする。暗い線の形をぼかして閾値で取り直し（輪郭のがたつきが均される）、
    はみ出した所は線の色で足し、削れた所は周りの色で埋める。線の太さはおよそ保つ"""
    import numpy as np
    img = image.convert("RGB")
    gray = np.asarray(img.convert("L"))
    line = gray < dark
    if mask is not None:
        line_m = np.asarray(mask.convert("L").resize(img.size)) > 127
    else:
        line_m = np.ones_like(line)
    lm = Image.fromarray((line * 255).astype(np.uint8), "L")
    soft = np.asarray(lm.filter(ImageFilter.GaussianBlur(strength))) > 127
    add = soft & ~line & line_m
    rem = line & ~soft & line_m
    a = np.asarray(img).copy()
    if line.any():
        ink = np.median(a[line], axis=0).astype(np.uint8)
        a[add] = ink
    out = Image.fromarray(a, "RGB")
    if rem.any():
        out = erase(out, Image.fromarray((rem * 255).astype(np.uint8), "L"), rounds=20)
    smooth_lines.last_count = int(add.sum() + rem.sum())
    return _inside(img, out, mask)


smooth_lines.last_count = 0


def _box(mask):
    return mask.convert("L").point(lambda v: 255 if v > 127 else 0).getbbox()


def align(image, masks, size: bool = True, height: bool = True):
    """囲んだ物を、1 つ目の囲みの物に揃える（大きさと高さ）。2 つ目からの囲みの中身を切り取り、
    元の所は周りの色で消し、1 つ目の大きさに伸び縮みさせて、横の中心はそのまま、縦の中心を 1 つ目に合わせて置く。
    左右の目・耳・手など、左右の物の大きさ・高さの食い違いを直す"""
    img = image.convert("RGB")
    masks = [m.convert("L").resize(img.size) for m in masks if m is not None and _box(m.convert("L").resize(img.size))]
    if len(masks) < 2:
        raise ValueError("揃えるには、基準の物と揃える物を 2 つ以上囲んでください（1 つ目が基準）")
    ref = _box(masks[0])
    rw, rh = ref[2] - ref[0], ref[3] - ref[1]
    rcy = (ref[1] + ref[3]) / 2
    out = img
    for m in masks[1:]:
        box = _box(m)
        w, h = box[2] - box[0], box[3] - box[1]
        piece = img.crop(box)
        alpha = m.crop(box)
        nw, nh = (rw, rh) if size else (w, h)
        piece = piece.resize((max(1, nw), max(1, nh)), Image.LANCZOS)
        alpha = alpha.resize((max(1, nw), max(1, nh)), Image.LANCZOS)
        cx = (box[0] + box[2]) / 2
        cy = rcy if height else (box[1] + box[3]) / 2
        at = (int(round(cx - nw / 2)), int(round(cy - nh / 2)))
        out = erase(out, m, rounds=40)
        out.paste(piece, at, alpha)
    return out


def changed_pixels(a, b) -> int:
    """2 枚の絵で変わった画素の数（報告と試験に使う）"""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").point(lambda v: 255 if v else 0)
    return sum(diff.histogram()[255:])
