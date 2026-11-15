"""自動選択の精度を測る。部位分け（facefeat.seg の SegFormer、.parts.png と同じ模型）を正解として、
髪・顔・服・手（腕）・背景の 5 つを、押して選んだときの重なり（IoU）で比べる。

押す所は正解の部位の中で、縁から一番遠い画素（人が押す所に近い）。四角で囲む形は正解の外の四角。
比べる設定: 押す 1 回で 3 つの候補から、模型の自信の高い物（iou）・一番大きい物（large）・一番小さい物（small）、
四角で囲む（box）、押した 1 回の答えの外の四角と押した所でもう一度聞く（refine）、部位分けそのもの（parts、正解と同じ模型なので上限の目安で、比べの外）。
python -m chatdraw.autoselbench 絵 … で流し、部位ごと・設定ごとの平均の IoU を出す。"""
from __future__ import annotations

import json
import sys
import time

PARTS = {"髪": [2], "顔": [11], "服": [4, 5, 6, 7], "手": [14, 15], "背景": [0]}


def _inner(m):
    from scipy import ndimage
    d = ndimage.distance_transform_edt(m)
    y, x = divmod(int(d.argmax()), m.shape[1])
    return x, y


def iou(a, b) -> float:
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def bench(paths, side: int = 768) -> dict:
    import numpy as np
    from PIL import Image
    from chatdraw import autosel, facefeat
    d, why = autosel.fetch()
    if not d:
        raise SystemExit(why)
    rows = []
    t0 = time.time()
    for p in paths:
        im = Image.open(p).convert("RGB")
        f = min(1.0, side / max(im.size))
        im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
        lab = facefeat.seg(im)
        if lab is None:
            raise SystemExit("部位分けの模型が無い")
        for name, vals in PARTS.items():
            truth = np.isin(lab, vals)
            if truth.sum() < 0.005 * truth.size:
                continue
            truth = facefeat._largest(truth) if name != "背景" else truth
            x, y = _inner(truth)
            masks, scores = autosel.sam_masks(im, point=(x, y), d=d, keep=True)
            ys, xs = np.nonzero(truth)
            bm, bs = autosel.sam_masks(im, box=(xs.min(), ys.min(), xs.max(), ys.max()), d=d, keep=True)
            row = {"image": str(p), "part": name}
            for c in ("iou", "large", "small"):
                row[c] = round(iou(autosel.pick_candidate(masks, scores, c), truth), 3)
            row["box"] = round(iou(autosel.pick_candidate(bm, bs, "iou"), truth), 3)
            row["refine"] = round(iou(autosel.refine(im, (x, y), masks, scores, d=d, keep=True), truth), 3)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    autosel._unload()
    keys = ("iou", "large", "small", "box", "refine")
    mean = {k: round(sum(r[k] for r in rows) / len(rows), 3) for k in keys} if rows else {}
    per = {n: {k: round(sum(r[k] for r in rows if r["part"] == n) / max(1, sum(r["part"] == n for r in rows)), 3) for k in keys}
           for n in PARTS}
    return {"mean": mean, "per_part": per, "count": len(rows), "sec": round(time.time() - t0, 1)}


if __name__ == "__main__":
    print(json.dumps(bench(sys.argv[1:]), ensure_ascii=False, indent=1))
