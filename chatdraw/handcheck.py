"""描いた絵の検品（手と指）。描き終わるたびに動かし、崩れを会話と記録に出す。

手の場所を手のひらを探す模型で見つけ、手の関節 21 点を読む模型（どちらも MediaPipe、Apache-2.0）で読み、
tools/gen/hands.py の measure で、指の長さの釣り合い・指の上の手の色・指の数（手の色の筋で数える）を測る。
測り方は tools/gen/hands.py の 1 か所だけに置き、ここはアプリと 2 段で描く流れから呼ぶ入口にする。
模型か部品（ai-edge-litert）が無いときは「読めない」を返し、絵は止めない（検品が無いことを隠さず出す）。
足の指は tools/gen/feet.py で数え、feet に足ごとの枠と数を入れる。手の模型は足の指を手の指と読むので、足は手とは別の道で数える。
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"


def _hands():
    """tools/gen/hands.py を読む。模型の置き場（CD_HOME）は、アプリのデータの置き場にする（Program Files は書けない）"""
    if "CD_HOME" not in os.environ:
        from chatdraw.paths import data_home
        os.environ["CD_HOME"] = str(data_home() / "cd")
    gen = ROOT / "tools" / "gen"
    if str(gen) not in sys.path:
        sys.path.insert(0, str(gen))
    import hands
    return hands


def ensure_models(fetch: bool = True) -> bool:
    """手の模型が置き場にあるか。無ければ取る（約 8MB）"""
    hands = _hands()
    d = hands.MODEL.parent
    if hands.MODEL.exists() and (d / "hand_detector.tflite").exists():
        return True
    if not fetch:
        return False
    import tempfile
    import urllib.request
    d.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        z = Path(t) / "h.task"
        urllib.request.urlretrieve(TASK, z)
        with zipfile.ZipFile(z) as f:
            for name in ("hand_landmarks_detector.tflite", "hand_detector.tflite"):
                (d / name).write_bytes(f.read(name))
    return True


LEAST = 0.3   # 手のひらの確からしさの下限。拾った手は measure の手らしさ（0.5 以上）で確かめる


def find_hands(hands, im) -> list[str]:
    """絵全体と、重ねて切った区画（一辺 = 短い辺の 6 割）の両方で手のひらを探す。
    手のひらを探す模型は絵を 192 画素に縮めて読むので、全身の絵では手が数画素になり、
    仕上げたビキニの絵では 2 つの手のうち 1 つも見つからなかった。区画で探すと手が大きく写る"""
    w, h = im.size
    found: list[tuple[float, float, str]] = []

    def add(b: str, ox: int = 0, oy: int = 0):
        box, ang = b.split(":")
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
        x0, y0, x1, y1 = x0 + ox, y0 + oy, x1 + ox, y1 + oy
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
        if any(abs(cx - fx) < r * 0.6 and abs(cy - fy) < r * 0.6 for fx, fy, _ in found):
            return   # 同じ手を 2 度数えない
        found.append((cx, cy, f"{x0},{y0},{x1},{y1}:{ang}"))
    for b in hands.detect_palms(im, LEAST):
        add(b)
    side = int(min(w, h) * 0.6)
    step = side // 2
    for y in range(0, max(1, h - side + step), step):
        for x in range(0, max(1, w - side + step), step):
            tile = im.crop((x, y, min(w, x + side), min(h, y + side)))
            for b in hands.detect_palms(tile, LEAST):
                add(b, x, y)
    return keep_hands(im, found)


_KP: dict = {}


def _keypoints(im) -> dict:
    """体の点を 1 枚につき 1 回だけ読む（手の振り分けと顔の検品で同じ点を使う。VitPose の読み込みは数秒かかる）"""
    key = (id(im), im.size)
    if key not in _KP:
        try:
            from chatdraw.twostage import keypoints
            _KP.clear()
            _KP[key] = keypoints(im)
        except Exception:
            return {}
    return _KP[key]


def _face(im, asked: str) -> dict:
    """顔の検品（tools/gen/facecheck.py）。部品が無ければ読めないことを返し、手の検品は止めない"""
    gen = ROOT / "tools" / "gen"
    if str(gen) not in sys.path:
        sys.path.insert(0, str(gen))
    try:
        import facecheck
        return facecheck.check_face(im, keypoints=_keypoints(im), asked=asked)
    except Exception as e:
        return {"box": None, "readable": False, "bad": [], "reason": f"顔の検品の部品がありません（{e}）"}


def keep_hands(im, found) -> list[str]:
    """見つけた手のひらから、足を外す。手のひらの模型は足の指を手の指と読み、手らしさ 0.9 以上で通した（ビキニの絵の両足）。
    体の点（VitPose）の手首が読めれば、手首の近く（肘から手首の長さの 1.2 倍以内）の物だけを手とする。
    読めなければ、足首の高さより下（読めなければ絵の下 15%）の物を外す"""
    w, h = im.size
    kp = _keypoints(im)
    wrists = [(kp[f"{s}_wrist"], kp.get(f"{s}_elbow")) for s in ("left", "right") if f"{s}_wrist" in kp]
    if wrists:
        out = []
        for cx, cy, b in found:
            for (wx, wy), el in wrists:
                reach = 1.2 * (((wx - el[0]) ** 2 + (wy - el[1]) ** 2) ** 0.5 if el else min(w, h) * 0.12)
                if ((cx - wx) ** 2 + (cy - wy) ** 2) ** 0.5 <= max(reach, min(w, h) * 0.08):
                    out.append(b)
                    break
        return out
    ankles = [kp[k][1] for k in ("left_ankle", "right_ankle") if k in kp]
    floor = min(ankles) - 0.03 * h if ankles else 0.85 * h
    return [b for cx, cy, b in found if cy < floor]


def ensure_feet_model(fetch: bool = True) -> bool:
    """足の点を読む模型（DWPose、約 134MB）が置き場にあるか。無ければ取る"""
    _hands()   # CD_HOME と tools/gen の道を整える
    import feet
    if feet.MODEL.exists():
        return True
    if not fetch:
        return False
    import urllib.request
    feet.MODEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = feet.MODEL.with_suffix(".part")
    urllib.request.urlretrieve(feet.URL, tmp)
    tmp.replace(feet.MODEL)
    return True


def check_feet(im, fetch: bool = True) -> tuple[list[dict], list[str], str]:
    """足の指を数える。返す: 足ごとの結果、bad に足す説明、読めなかった訳（読めたら空）"""
    try:
        ensure_feet_model(fetch)
        import feet
        found = feet.public(feet.count_toes(im))
    except Exception as e:   # 模型か部品が無い。手の検品は続ける
        return [], [], f"足の検品の部品がありません（{e}）"
    bad = []
    for i, f in enumerate(found, 1):
        n = f["count"]
        f["bad"] = []
        if n is not None and n != 5:
            f["bad"] = [f"指が{'多い' if n > 5 else '足りない'}（{n} 本。5 本のはず）"]   # 直す所の一覧（bad_regions）に入れる
            bad.append(f"足 {i}: " + f["bad"][0])
    return found, bad, ""


def check(image, fetch: bool = True, asked: str = "") -> dict:
    """絵（PIL か道）の手を全部測る。bad に崩れの説明を並べる。readable が False なら手を読めなかった。
    顔の検品も通し、顔の崩れは bad の後ろに足し、顔の枠を faces に返す（asked は頼んだタグ。閉じた目を頼んだかを見る）"""
    from PIL import Image
    if os.environ.get("CD_CHECK") == "off":   # 試験で、模型を取りに行かないようにする
        return {"readable": False, "bad": [], "hands": [], "feet": [], "reason": "検品を止めています（CD_CHECK=off）"}
    im = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    try:
        hands = _hands()
        hands._litert()   # 部品が無ければ、模型を取りに行く前に止める
        ensure_models(fetch)
        boxes = find_hands(hands, im)
    except Exception as e:   # 部品か模型が無い。描いた絵は止めず、検品が無いことを返す
        res = {"readable": False, "bad": [], "hands": [], "reason": f"検品の部品がありません（{e}）"}
        res["feet"], res["bad"], why = check_feet(im, fetch)
        if why:
            res["feet_reason"] = why
        return _add_face(res, im, asked)
    out = {"readable": False, "bad": [], "hands": []}
    for i, b in enumerate(boxes, 1):
        box, ang = b.split(":")
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
        # 枠の大きさと向きを少しずつ変え、手らしさの最も高い切り出しで測る（枠のままでは指先が切れ、指を数えられなかった）
        crop = hands.best_crop(im, (x0, y0, x1, y1), float(ang))
        m, bad, _ = hands.measure(crop)
        seen = not any(str(x).startswith("読めない") for x in bad)
        out["hands"].append({"box": [x0, y0, x1, y1], "angle": float(ang), "measure": m, "bad": bad, "seen": seen})
        out["readable"] = out["readable"] or seen
        if seen:
            out["bad"] += [f"手 {i}: {x}" for x in bad]
    _add_missed_hands(out, im)
    out["feet"], bad, why = check_feet(im, fetch)
    out["bad"] += bad
    if why:
        out["feet_reason"] = why
    return _add_face(out, im, asked)


def _add_missed_hands(out: dict, im) -> None:
    """体の点で手首と肘が見えているのに、手の模型が手を見つけなかった所を、崩れた手として足す。
    指がくっついた手、透けてぼやけた手は手の模型に見つからず、検品にも直しにも回らないまま通っていた（Windows の描画で 2 枚）"""
    kp = _keypoints(im)
    w, h = im.size
    for side in ("left", "right"):
        if f"{side}_wrist" not in kp or f"{side}_elbow" not in kp:
            continue
        (wx, wy), (ex, ey) = kp[f"{side}_wrist"], kp[f"{side}_elbow"]
        sh = [kp[k] for k in ("left_shoulder", "right_shoulder") if k in kp]
        hips = [kp[k][1] for k in ("left_hip", "right_hip") if k in kp]
        if len(sh) == 2 and hips and min(p[0] for p in sh) < wx < max(p[0] for p in sh) and min(p[1] for p in sh) < wy < max(hips):
            continue   # 手首が胴の前か後ろ。背中に回した腕の手は見えなくて当たり前なので、崩れにしない
        fore = max(((wx - ex) ** 2 + (wy - ey) ** 2) ** 0.5, min(w, h) * 0.04)
        # 手は手首から前腕の向きに、前腕の半分ほど先にある
        cx, cy = wx + (wx - ex) / fore * fore * 0.4, wy + (wy - ey) / fore * fore * 0.4
        if any(x0 - fore * 0.3 <= cx <= x1 + fore * 0.3 and y0 - fore * 0.3 <= cy <= y1 + fore * 0.3
               for x0, y0, x1, y1 in (hd["box"] for hd in out["hands"])):
            continue
        r = fore * 0.9   # 手首の点はずれやすい（1 枚で手の中心から 100 画素）ので、枠は広めに取る
        box = [int(max(0, cx - r)), int(max(0, cy - r)), int(min(w, cx + r)), int(min(h, cy + r))]
        why = "手の形が読めない（指がくっついたか、ぼやけている）"
        out["hands"].append({"box": box, "angle": 0.0, "measure": {}, "bad": [why], "seen": True, "missed": True})
        out["bad"].append(f"手 {len(out['hands'])}: {why}")


def _add_face(out: dict, im, asked: str) -> dict:
    f = _face(im, asked)
    # 直す所の一覧（bad_regions）が手や足と同じ形で読めるよう、枠と崩れを並べる
    out["faces"] = [{"box": f["box"], "bad": f.get("bad", []), "seen": bool(f.get("readable"))}] if f.get("box") else []
    out["face"] = f
    out["bad"] += f.get("bad", [])
    return out


def _feet_line(res: dict) -> str:
    """足の指の数の 1 句（数えた足が無ければ空）"""
    feet = res.get("feet") or []
    if not feet:
        return ""
    return "足の指 " + "・".join(f"{f['count']} 本" if f["count"] is not None else "読めない" for f in feet)


def summary(res: dict) -> str:
    """会話に出す 1 行"""
    face = [b for b in res.get("bad", []) if b.startswith("顔")]
    if face and (res.get("reason") or not res["readable"]):   # 手を読めなくても、顔の崩れは隠さない
        return "検品: 崩れ " + str(len(face)) + " 件。" + "、".join(face)
    foot = _feet_line(res)
    tail = f"。{foot}" if foot else ""
    feet_bad = [b for b in res["bad"] if b.startswith("足 ")]
    if res.get("reason"):
        return f"検品: {res['reason']}" + (("。崩れ " + "、".join(feet_bad)) if feet_bad else tail)
    if not res["readable"]:
        head = "検品: 手を読めませんでした（手が写っていないか、隠れています）。目で確かめてください"
        return head + (("。崩れ " + "、".join(feet_bad)) if feet_bad else tail)
    if res["bad"]:
        return "検品: 崩れ " + str(len(res["bad"])) + " 件。" + "、".join(res["bad"])
    return f"検品: 手 {sum(h['seen'] for h in res['hands'])} つで、指の数と形に崩れは見つかりませんでした" + tail


# 直す所の種類ごとに、描き直しの頼みに足す言葉
FIX_WORDS = {"hand": "detailed hand, five fingers, correct hand anatomy",
             "foot": "detailed feet, five toes, correct foot anatomy",
             "face": "detailed face, beautiful detailed eyes, clear eyes"}


def detail_regions(res: dict) -> list[tuple[list[int], str]]:
    """崩れの有無によらず、見つかった手・足・顔すべての枠と種類。検品が見逃す細部（くっついた指、薄く出た指、
    つぶれた足の指）があるので、検品を通った絵でも細部はもう一度描かせる"""
    out = []
    for key, kind in (("hands", "hand"), ("feet", "foot"), ("faces", "face")):
        for h in res.get(key, []):
            if h.get("seen", True) and h.get("box"):
                out.append((list(h["box"]), kind))
    return out


def bad_regions(res: dict) -> list[tuple[list[int], str]]:
    """検品で崩れの見つかった所の枠と種類（hand / foot / face）。AI が自分で直す所の一覧にする"""
    out = []
    for key, kind in (("hands", "hand"), ("feet", "foot"), ("faces", "face")):
        for h in res.get(key, []):
            if h.get("seen", True) and h.get("bad"):
                out.append((list(h["box"]), kind))
    return out
