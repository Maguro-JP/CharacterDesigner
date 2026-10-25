"""描いた絵の検品（手と指）。描き終わるたびに動かし、崩れを会話と記録に出す。

手の場所を手のひらを探す模型で見つけ、手の関節 21 点を読む模型（どちらも MediaPipe、Apache-2.0）で読み、
tools/gen/hands.py の measure で、指の長さの釣り合い・指の上の手の色・指の数（手の色の筋で数える）を測る。
測り方は tools/gen/hands.py の 1 か所だけに置き、ここはアプリと 2 段で描く流れから呼ぶ入口にする。
模型か部品（ai-edge-litert）が無いときは「読めない」を返し、絵は止めない（検品が無いことを隠さず出す）。
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


def keep_hands(im, found) -> list[str]:
    """見つけた手のひらから、足を外す。手のひらの模型は足の指を手の指と読み、手らしさ 0.9 以上で通した（ビキニの絵の両足）。
    体の点（VitPose）の手首が読めれば、手首の近く（肘から手首の長さの 1.2 倍以内）の物だけを手とする。
    読めなければ、足首の高さより下（読めなければ絵の下 15%）の物を外す"""
    w, h = im.size
    try:
        from chatdraw.twostage import keypoints
        kp = keypoints(im)
    except Exception:
        kp = {}
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


def check(image, fetch: bool = True) -> dict:
    """絵（PIL か道）の手を全部測る。bad に崩れの説明を並べる。readable が False なら手を読めなかった"""
    from PIL import Image
    if os.environ.get("CD_CHECK") == "off":   # 試験で、模型を取りに行かないようにする
        return {"readable": False, "bad": [], "hands": [], "reason": "検品を止めています（CD_CHECK=off）"}
    im = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    try:
        hands = _hands()
        hands._litert()   # 部品が無ければ、模型を取りに行く前に止める
        ensure_models(fetch)
        boxes = find_hands(hands, im)
    except Exception as e:   # 部品か模型が無い。描いた絵は止めず、検品が無いことを返す
        return {"readable": False, "bad": [], "hands": [], "reason": f"検品の部品がありません（{e}）"}
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
    return out


def summary(res: dict) -> str:
    """会話に出す 1 行"""
    if res.get("reason"):
        return f"検品: {res['reason']}"
    if not res["readable"]:
        return "検品: 手を読めませんでした（手が写っていないか、隠れています）。目で確かめてください"
    if res["bad"]:
        return "検品: 崩れ " + str(len(res["bad"])) + " 件。" + "、".join(res["bad"])
    return f"検品: 手 {sum(h['seen'] for h in res['hands'])} つで、指の数と形に崩れは見つかりませんでした"


# 直す所の種類ごとに、描き直しの頼みに足す言葉
FIX_WORDS = {"hand": "detailed hand, five fingers, correct hand anatomy",
             "foot": "detailed feet, five toes, correct foot anatomy",
             "face": "detailed face, beautiful detailed eyes, clear eyes"}


def bad_regions(res: dict) -> list[tuple[list[int], str]]:
    """検品で崩れの見つかった所の枠と種類（hand / foot / face）。AI が自分で直す所の一覧にする"""
    out = []
    for key, kind in (("hands", "hand"), ("feet", "foot"), ("faces", "face")):
        for h in res.get(key, []):
            if h.get("seen", True) and h.get("bad"):
                out.append((list(h["box"]), kind))
    return out
