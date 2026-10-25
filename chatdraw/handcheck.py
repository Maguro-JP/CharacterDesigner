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
        boxes = hands.detect_palms(im, 0.5)
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
