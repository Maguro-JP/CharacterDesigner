"""検品の合成の台。library/feedback に人の正解がほとんど無い種類（目のぼかし・虹色・白目・消えた目、鏡の映り込みの矛盾）を、
正しい絵に崩れを作って足し、検品（アプリと同じ facecheck.check_face と mirrorcheck.check）が見つけるかを測る。

    PYTHONPATH=.cache/simple/lib:.cache/gen/lib python3 tools/gen/qcsynth.py [--limit N] [--json 出力.json]

作った崩れは本物の模型の崩れと同じではない（画素で塗った物）。この台の数字は「その種類を測る仕組みが動くか」の下限で、
本物の絵での精度は tools/gen/qcbench.py の人の判定の台で見る。崩れを作る前の絵（そのままの絵）で崩れと言えば誤報として数える。
体の点（twostage.keypoints）は絵ごとに 1 回だけ読み、.cache/qcbench/synth/ に貯める。
崩れを作る場所は、顔の切り出しで読み直した目の点（facecheck.refine_points）にする。--raw は検品に絵全体の点を渡す（読み直す前の検品）。
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import qcbench  # noqa: E402

CACHE = qcbench.CACHE / "synth"
EYE_KINDS = ("blur", "rainbow", "white", "erase")
MIRROR_KINDS = ("mirror_ok", "mirror_color")


def sources(limit: int) -> list[Path]:
    """顔を読めた絵（qcbench の貯めた結果で face.readable）。人が目の崩れを書いた絵は除く"""
    out = []
    for r in qcbench.truth(with_cats=True):
        if {"eyes", "face", "mouth"} & set(r.get("cats", [])):
            continue
        key = qcbench.CACHE / (qcbench.re.sub(r"[^\w.-]", "_", r["path"]) + ".json")
        if not key.exists():
            continue
        res = json.loads(key.read_text(encoding="utf-8"))["res"]
        if (res.get("face") or {}).get("readable") and not (res.get("face") or {}).get("bad"):
            out.append(qcbench.ROOT / r["path"])
    return out[: limit or None]


def keypoints(im, path: Path, refined: bool = False) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (hashlib.sha1(path.read_bytes()).hexdigest() + (".kp2.json" if refined else ".kp.json"))
    if key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    if refined:
        import facecheck
        got = facecheck.refine_points(im, keypoints(im, path))
    else:
        from atelier.ai.two_stage import keypoints as kp
        got = kp(im)
    got = {k: [float(v) for v in xy] for k, xy in got.items() if k != "_refined"}
    key.write_text(json.dumps(got), encoding="utf-8")
    return got


def eye_boxes(kp: dict) -> list[tuple[int, int, int, int]]:
    a, b = kp["left_eye"], kp["right_eye"]
    dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    half = max(4, int(dist * 0.22))
    return [(int(x - half), int(y - half), int(x + half), int(y + half)) for x, y in (a, b)]


def make_eye(im, kp: dict, kind: str):
    """目の枠の中だけを崩す。blur: ぼかす、rainbow: 虹色の縞で塗る、white: 白目だけにする（瞳を消す）、erase: 肌の色で塗りつぶす"""
    from PIL import Image, ImageDraw, ImageFilter
    out = im.copy()
    for box in eye_boxes(kp):
        w, h = box[2] - box[0], box[3] - box[1]
        crop = out.crop(box)
        if kind == "blur":
            crop = crop.filter(ImageFilter.GaussianBlur(max(2, w / 5)))
        elif kind == "rainbow":
            crop = Image.new("RGB", (w, h))
            d = ImageDraw.Draw(crop)
            for i in range(w):
                r, g, b = colorsys.hsv_to_rgb(i / max(1, w), 0.9, 0.9)
                d.line([(i, 0), (i, h)], fill=(int(r * 255), int(g * 255), int(b * 255)))
        elif kind in ("white", "erase"):
            # 肌の色は目の枠の下（頬）から取る
            cheek = im.crop((box[0], box[3], box[2], box[3] + h // 2)).resize((1, 1), Image.BILINEAR).getpixel((0, 0))
            fill = (250, 250, 250) if kind == "white" else cheek
            d = ImageDraw.Draw(crop)
            d.ellipse([w * 0.1, h * 0.2, w * 0.9, h * 0.8], fill=fill, outline=(40, 30, 30) if kind == "white" else None,
                      width=max(1, w // 16))
        out.paste(crop, box[:2])
    return out


def make_mirror(im, kind: str):
    """絵の右に、左右を反転した写しを鏡の映りとして並べる。mirror_color は写しの色相を回す（鏡の中の服の色が違う）"""
    from PIL import Image, ImageOps
    w, h = im.size
    copy = ImageOps.mirror(im)
    if kind == "mirror_color":
        hsv = copy.convert("HSV")
        hch, s, v = hsv.split()
        hch = hch.point(lambda x: (x + 85) % 256)
        copy = Image.merge("HSV", (hch, s, v)).convert("RGB")
    gap = max(8, w // 12)
    out = Image.new("RGB", (w * 2 + gap, h), (235, 235, 235))
    out.paste(im, (0, 0))
    out.paste(copy, (w + gap, 0))
    return out


def run(limit: int, raw: bool = False) -> dict:
    from PIL import Image
    import facecheck
    from atelier.qc import mirror_check as mirrorcheck
    rows = []
    for p in sources(limit):
        im = Image.open(p).convert("RGB")
        where = keypoints(im, p, refined=True)
        kp = keypoints(im, p) if raw else where
        if "left_eye" not in where or "right_eye" not in where or "left_eye" not in kp or "right_eye" not in kp:
            continue
        row = {"path": str(p.relative_to(ROOT))}
        base = facecheck.check_face(im, keypoints=kp, precise=not raw)
        row["control"] = {"bad": base.get("bad", []), "readable": base.get("readable")}
        for kind in EYE_KINDS:
            r = facecheck.check_face(make_eye(im, where, kind), keypoints=kp, precise=not raw)
            row[kind] = {"bad": r.get("bad", []), "readable": r.get("readable"), "reason": r.get("reason")}
        small = im.copy()
        small.thumbnail((384, 384))
        for kind in MIRROR_KINDS:
            m = mirrorcheck.check(make_mirror(small, kind), {"mirror": 0.9})
            row[kind] = {"flaws": [f["bad"] for f in m.get("flaws", [])], "reason": m.get("reason")}
        rows.append(row)
        print(row["path"], {k: bool(v.get("bad") or v.get("flaws")) for k, v in row.items() if isinstance(v, dict)}, flush=True)
    return {"rows": rows, "score": score(rows)}


def _eye_flag(r: dict) -> bool:
    """目の種類に崩れか読めないを返したか（読めない目は崩れとして数える）"""
    return any("目" in str(b) for b in r.get("bad", [])) or r.get("readable") is False


def score(rows: list[dict]) -> dict:
    n = len(rows)
    pct = lambda a: round(100 * a / n, 1) if n else None   # noqa: E731
    out = {"images": n, "control_false": pct(sum(_eye_flag(r["control"]) for r in rows))}
    for k in EYE_KINDS:
        out[k] = pct(sum(_eye_flag(r[k]) for r in rows))
    out["mirror_false"] = pct(sum(bool(r["mirror_ok"]["flaws"]) for r in rows))
    out["mirror_unread"] = pct(sum(bool(r["mirror_ok"]["reason"]) for r in rows))
    out["mirror_color"] = pct(sum(bool(r["mirror_color"]["flaws"] or r["mirror_color"]["reason"]) for r in rows))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", default="")
    ap.add_argument("--raw", action="store_true", help="検品に絵全体で読んだ顔の点を渡す（読み直す前の検品）")
    a = ap.parse_args(argv)
    res = run(a.limit, a.raw)
    print(json.dumps(res["score"], ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
