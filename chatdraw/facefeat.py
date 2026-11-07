"""加工の前と後で、その人物らしさ（目の色、目の位置、髪の色）が変わっていないかを測り、変わった所を元の絵に戻す。

加工は絵を整える物で、人物を描き替える物ではない。前は「顔を整える」が顔を描き直し、どの絵も同じ顔・同じ目の色になった。
目の色・目の位置・髪の色は、利用者がその人物を見分ける所なので、加工がそこを変えたら加工のほうを捨てる。
部位分け（tools/gen/edit.py の SegFormer）で顔（11）と髪（2）を取る。部位分けは 1 枚で数秒かかるので、同じ絵では測り直さない。
部位分けの模型が無いときは測れないので、測っていないと返す（測れなかったことを「変わっていない」と扱わない）。
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

FACE, HAIR = 11, 2
SIDE = 768             # 部位分けに渡す大きさ（模型は 512 で見るので、大きな絵を渡しても細かくならない）
EYE_BAND = (0.2, 0.65)  # 顔の囲みの高さのうち、目と眉のある帯
EYE_FROM_SKIN = 50.0   # 肌の色からこれだけ離れた画素を、目・眉の画素とする（0〜255 の RGB の距離）
EYE_COLOR = 8.0        # 目の色の平均がこれより変わったら、顔を戻す
EYE_MOVE = 0.03        # 目の位置が顔の高さのこの割合より動いたら、顔を戻す
HAIR_COLOR = 8.0       # 髪の色の平均がこれより変わったら、髪を戻す
GROW = 0.06            # 戻すときに顔の大きさのこの割合だけ広げる（眉と顎の線を含める）

_SEG: dict = {}


def _key(image) -> str:
    from PIL import Image
    return hashlib.md5(image.convert("RGB").resize((64, 64), Image.BOX).point(lambda v: v // 16).tobytes()).hexdigest()


def ready() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
        from chatdraw.finishers import _gen
        return isinstance(try_to_load_from_cache(_gen("edit").SEG_MODEL, "config.json"), str)
    except Exception:
        return False


def seg(image):
    """部位の番号の配列（image と同じ大きさ、uint8）。部位分けが使えないときは None。同じ絵は測り直さない"""
    import numpy as np
    from PIL import Image
    s = seg_small(image)
    if s is None:
        return None
    if s.size != image.size:
        s = s.resize(image.size, Image.NEAREST)
    return np.asarray(s)


def seg_small(image):
    """部位分けの番号の絵（L、長い辺 SIDE まで縮めた大きさ）。広げる・ぼかすはこの大きさで済ませる（大きな絵では重いので）"""
    from PIL import Image
    k = _key(image)
    if k in _SEG:
        s = _SEG[k]
    else:
        s = None
        if ready():
            try:
                from chatdraw.finishers import _gen
                src = image.convert("RGB")
                f = min(1.0, SIDE / max(src.size))
                small = src.resize((max(1, round(src.width * f)), max(1, round(src.height * f))), Image.LANCZOS) if f < 1 else src
                with tempfile.TemporaryDirectory() as d:
                    p = Path(d) / "s.png"
                    small.save(p, compress_level=1)
                    s = _gen("edit").parts(str(p)).copy()
            except Exception:
                s = None
        if len(_SEG) > 16:
            _SEG.clear()
        _SEG[k] = s
    return s


def _largest(m):
    import numpy as np
    from scipy import ndimage
    lab, n = ndimage.label(m)
    if n == 0:
        return m
    return lab == (int(np.bincount(lab.ravel())[1:].argmax()) + 1)


def features(image, labels=None) -> dict:
    """目の色の平均（RGB）、左右の目の位置（顔の囲みに対する割合）、髪の色の平均。測れない物は入れない"""
    import numpy as np
    labels = seg(image) if labels is None else labels
    if labels is None:
        return dict(measured=False)
    a = np.asarray(image.convert("RGB"), np.float32)
    out = dict(measured=True)
    hair = labels == HAIR
    if hair.sum() >= 50:
        out["hair"] = a[hair].mean(0)
    face = _largest(labels == FACE)
    if face.sum() < 30:
        return out
    ys, xs = np.nonzero(face)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    h, w = y1 - y0, x1 - x0
    out["face_box"] = (int(x0), int(y0), int(x1), int(y1))
    skin = np.median(a[face], 0)
    band = np.zeros_like(face)
    band[y0 + int(h * EYE_BAND[0]):y0 + int(h * EYE_BAND[1]), x0:x1] = True
    # 目は部位分けで顔に入ることも入らないこともあるので、顔の囲みの帯の中の髪でない画素を見る
    cand = band & ~hair & (np.linalg.norm(a - skin, axis=2) > EYE_FROM_SKIN)
    if cand.sum() < 10:
        return out
    out["eye"] = a[cand].mean(0)
    cx = (x0 + x1) / 2
    pos = []
    for side in (np.arange(a.shape[1]) < cx, np.arange(a.shape[1]) >= cx):
        m = cand & side[None, :]
        if m.sum() >= 5:
            yy, xx = np.nonzero(m)
            pos.append(((xx.mean() - x0) / max(1, w), (yy.mean() - y0) / max(1, h)))
    out["eyes"] = pos
    return out


def compare(f0: dict, f1: dict) -> dict:
    """前と後の差。eye（目の色の距離）、move（目の位置の動き、顔の高さに対する割合）、hair（髪の色の距離）"""
    import numpy as np
    d = {}
    if "eye" in f0 and "eye" in f1:
        d["eye"] = round(float(np.linalg.norm(f0["eye"] - f1["eye"])), 2)
    if f0.get("eyes") and f1.get("eyes") and len(f0["eyes"]) == len(f1["eyes"]):
        d["move"] = round(float(max(np.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(f0["eyes"], f1["eyes"]))), 4)
    elif f0.get("eyes") or f1.get("eyes"):
        d["move"] = 1.0   # 片方で目が見つからないのは、目が消えた・増えた崩れ
    if "hair" in f0 and "hair" in f1:
        d["hair"] = round(float(np.linalg.norm(f0["hair"] - f1["hair"])), 2)
    return d


def keep(src, out, mask=None) -> tuple:
    """out の目・髪が src から変わっていたら、その所を src の画素に戻す。返りは (絵, 報告)。
    報告: measured、before（差）、back（戻した所の名前の並び）、after（戻したあとの差）"""
    import numpy as np
    from PIL import Image, ImageFilter
    from scipy import ndimage
    s, o = src.convert("RGB"), out.convert("RGB")
    if o.size != s.size:
        return out, dict(measured=False)
    labels = seg(s)
    if labels is None:
        return out, dict(measured=False)
    f0, f1 = features(s, labels), features(o, labels)   # 後の絵も元の絵の部位で測る（加工で部位が動いたかを見るので）
    diff = compare(f0, f1)
    back = []
    small = np.asarray(seg_small(s))
    region = np.zeros(small.shape, bool)
    if diff.get("eye", 0) > EYE_COLOR or diff.get("move", 0) > EYE_MOVE:
        face = _largest(small == FACE)
        ys, xs = np.nonzero(face)
        r = max(2, int(max(np.ptp(ys), np.ptp(xs)) * GROW))
        region |= ndimage.binary_dilation(face, iterations=r)
        back.append("顔（目の色と形）")
    if diff.get("hair", 0) > HAIR_COLOR:
        region |= ndimage.binary_dilation(small == HAIR, iterations=2)
        back.append("髪の色")
    rep = dict(measured=True, before=diff, back=back)
    if not back:
        rep["after"] = diff
        return o, rep
    m = Image.fromarray((region * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2)).resize(s.size, Image.BILINEAR)
    if mask is not None:   # 囲みの外はもともと変えていないので、戻すのも囲みの中だけ
        from chatdraw.finishers import binary
        m = Image.composite(m, Image.new("L", s.size, 0), binary(mask, s.size))
    o = Image.composite(s, o, m)
    rep["after"] = compare(f0, features(o, labels))
    return o, rep


def note(rep: dict, label: str) -> str:
    """戻した所を利用者に知らせる 1 文。戻していなければ空"""
    if not rep or not rep.get("back"):
        return ""
    return f"{label}で" + "・".join(rep["back"]) + "が元の絵から変わったので、その所は元の絵に戻しました。"
