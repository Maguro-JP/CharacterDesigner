"""CharacterDesigner 独自の作画監督（数字の検品）と学習を、アプリのおまかせから呼ぶ入口。

測り方と基準は tools/gen の 1 か所だけに置き（measure.py、faceform.py、normlearn.py、styles/anime-norms.json）、
ここは呼ぶだけにする。アプリの中に写しを作ると、片方だけ直って基準が食い違うため。

- check: 絵を measure.py で測り、基準（共通の基準に利用者の判定から学んだ基準を重ねたもの）から外れた数字を崩れとして返す。
  外れは全部「直す所」として囲みを付けて返す。顔の形と目は顔の囲み、髪は髪の囲み、光・影・左右の対・手足・頭身は
  人物の囲み。おまかせがその囲みの中だけを直し、直したあとで検品し直す（見つけた崩れを、描き直しに逃がさない）。
  「指示との違い」（基準の kind が request）は崩れに数えない。頼みとの違いは requestcheck が見る。
- verdict: 利用者が絵に付けた判定（★ は通す、戻すは戻す）を normlearn.py に記録し、基準を学び直す。
  学んだ基準は利用者のデータの置き場に書き、次のおまかせの check から効く。

重い部品は、アプリが「絵を描く部品」として入れる物（torch、transformers、scipy）だけを使う。
部品が無いときは測らず、測っていないことを notes に書いて返す（測っていないのに「崩れなし」とは言わない）。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "gen"
NEEDS = ("numpy", "scipy", "torch", "transformers")
MIN_SIDE = 128                    # これより小さい絵は顔も目も測れないので、判定を学ばない
# tools/gen/edit.py の LABELS の番号。外れの数字の頭（path の最初）から、直す囲みの部位を決める
FACE_LABEL, HAIR_LABEL = 11, 2
KIND_OF = {"face": "face", "eyes": "face", "hair": "hair"}   # ほかは人物の囲み（body）
FIX_WORDS = {"hair": "detailed hair, natural hair color, consistent hair strands",
             "body": "consistent lighting, correct shading, correct anatomy, matching pair"}


def _setup():
    """tools/gen を読めるようにし、利用者のデータ（判定の記録と学んだ基準）の置き場をアプリのデータの置き場にそろえる"""
    from chatdraw.paths import data_home
    # 部位分けの模型（tools/gen/edit.py、約 190MB）は初めの 1 回だけ取る。取らない設定のままだと、測れずに全部の絵を落とした
    import os
    os.environ.setdefault("CD_FETCH", "1")
    if str(GEN) not in sys.path:
        sys.path.insert(0, str(GEN))
    import measure
    import normlearn
    # 入れた場所（Program Files）は書けないので、記録と学んだ基準はアプリのデータの置き場に置く。
    # measure と normlearn の両方を同じ場所に向ける（環境変数は変えない。ほかの部品の模型の置き場まで動くため）
    store = data_home() / "learn"
    normlearn.STORE, normlearn.RECORDS = store, store / "records.jsonl"
    measure.USER_NORMS = normlearn.USER_NORMS = store / "norms.user.json"
    return measure, normlearn


def missing() -> list[str]:
    """数字の検品に要る部品のうち、入っていない物"""
    return [m for m in NEEDS if importlib.util.find_spec(m) is None]


def _short(means: str) -> str:
    for cut in ("（", "。"):
        means = means.split(cut, 1)[0]
    return means


def boxes_from_parts(parts, size, grow: float = 0.15) -> dict:
    """部位分けから、顔・髪・人物（背景でない所）の囲み。無い部位は入れない"""
    import numpy as np
    a = np.asarray(parts)
    w, h = size
    out = {}
    for kind, m in (("face", a == FACE_LABEL), ("hair", a == HAIR_LABEL), ("body", a != 0)):
        ys, xs = np.nonzero(m)
        if not len(xs):
            continue
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        gx, gy = int((x1 - x0) * grow) + 4, int((y1 - y0) * grow) + 4
        out[kind] = (max(0, x0 - gx), max(0, y0 - gy), min(w, x1 + gx), min(h, y1 + gy))
    return out


def from_outliers(outliers: list[dict], boxes: dict, size) -> dict:
    """measure.judge の外れを、おまかせの検品の形（bad と regions）に直す。指示との違いは崩れに数えない。
    崩れには必ず直す囲みを付ける。部位が読めなければ人物の囲み、それも無ければ絵全体"""
    bad, regions = [], []
    whole = (0, 0, size[0], size[1])
    for o in outliers:
        if o.get("kind") == "request":
            continue
        v = o["value"]
        v = round(v, 3) if isinstance(v, float) else v
        bad.append(f"数字の検品: {_short(o['means'])}（{o['path']} = {v}）")
        kind = KIND_OF.get(o["path"].split(".", 1)[0], "body")
        box = boxes.get(kind) or boxes.get("body") or whole
        if (box, kind) not in regions:
            regions.append((box, kind))
    return {"bad": bad, "regions": regions}


def check(image, prompt: str = "", hair: str = "") -> dict:
    """返すのは {readable, bad, regions, notes, measured}。部品が無ければ measured=False で、notes に理由を書く"""
    lack = missing()
    if lack:
        return {"readable": True, "bad": [], "regions": [], "measured": False,
                "notes": [f"数字の検品をしていません（部品が無い: {', '.join(lack)}）"]}
    measure, _nl = _setup()
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "image.png"
        image.convert("RGB").save(src)
        try:
            m = measure.measure(src, hair, prompt=prompt)
            outliers = measure.judge(m)
            from PIL import Image
            boxes = boxes_from_parts(Image.open(str(src) + ".parts.png"), image.size)
        except Exception as e:   # 測れなかった絵は崩れとして扱う（読めない物は崩れ）
            return {"readable": False, "bad": [f"数字の検品で測れませんでした（{type(e).__name__}: {e}）"],
                    "regions": [((0, 0, image.size[0], image.size[1]), "body")],
                    "measured": False, "notes": []}
    out = from_outliers(outliers, boxes, image.size)
    return {"readable": True, **out, "measured": True, "notes": []}


def verdict(path, value: str, reason: str = "", learn: bool = True) -> dict:
    """利用者の判定を記録して学び直す。value は "pass"（★）か "reject"（戻す）"""
    lack = missing()
    if lack:
        return {"recorded": False, "why": f"部品が無い: {', '.join(lack)}"}
    from PIL import Image
    try:
        with Image.open(path) as im:
            if min(im.size) < MIN_SIDE:
                return {"recorded": False, "why": f"小さすぎて測れない（{im.size[0]}×{im.size[1]}）"}
    except OSError as e:
        return {"recorded": False, "why": f"絵を開けない（{e}）"}
    _m, normlearn = _setup()
    rec = normlearn.record(Path(path), value, by="user", reason=reason)
    out = {"recorded": True, **rec}
    if learn:
        got = normlearn.learn()
        out["learned"] = {"changed": got["changed"], "records": got["records"]}
    return out
