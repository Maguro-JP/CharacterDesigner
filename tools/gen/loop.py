"""検品で崩れが見つかった絵を、落として終わらせず「直して検品し直す」を回す。

1 周: qc.auto_check と頼んだ言葉の欠け（タグで読めない言葉）を集める → 崩れごとに直す範囲（箱）と直す言葉を決める →
範囲だけを元の絵と同じ模型で描き直す → 検品し直す。崩れが 0 になるか回数の上限で止まり、崩れの一番少ない絵を best にする。
同じ崩れが 2 周続けて減らなければ「直せない」と記録して、それ以上は描き直さない（描き直しのたびに 1 分かかり、
直らない所に回すと他の崩れを直す時間がなくなるため）。範囲の外の画素は元のまま残す（fix.fix と同じ作り）。
通す・戻すは、この道具ではなく検品担当（checker）が目で見て決める。

使い方:
  python3 tools/gen/loop.py 絵.png 出力先/ [--prompt "..."] [--rounds 4]
  （--prompt を省くと、絵の隣の .png.json の prompt を読む）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401  模型の置き場所を diffusers より先に決める（fix.py と同じ理由）
import fix  # noqa: E402

TEXT_TAGS = ("watermark", "artist name", "signature", "text", "english text", "web address")
# 欠けた言葉から、直す部位を選ぶ。手の言葉を先に見る（shading eyes は目ではなく手の動作）
HAND_WORDS = ("hand", "holding", "shading", "waving", "wave", "arm", "glove", "finger", "pointing", "salute", "peace sign")
WEAR_WORDS = ("bikini", "trim", "shirt", "dress", "skirt", "jacket", "coat", "swimsuit", "top", "shorts", "pants",
              "uniform", "apron", "vest", "belt", "ribbon", "bow", "frills", "armor", "cape", "sash")
# タグの一覧にあっても、絵から読めないのが普通の言葉（構図、背景）。欠けに数えると直す所が無い
NOT_THINGS = ("full body", "upper body", "cowboy shot", "solo", "standing", "background", "looking at viewer", "outdoors",
              "day", "sky", "ocean", "beach")
LEAST = 0.35
STRENGTH = {"face": 0.5, "text": 0.8, "part": 0.7, "box": 0.75}


# ---- 崩れを集める ----

def missing_words(prompt: str, tags: dict, least: float = LEAST) -> list[str]:
    """頼んだ言葉のうちタグの一覧にあって、絵から least 未満でしか読めないもの。tagger.missing は shading を
    描き方の言葉として外す（shading eyes を数えない）ので、ここでは一覧にある言葉を直接比べる。
    一覧に無い言い方（black bikini with red trim）は qc.nouns_missing で最後の名詞を比べる"""
    import tagger
    import qc
    vocab = tagger.vocabulary()
    out = []
    for t in (x.strip().lower() for x in prompt.split(",")):
        if not t or any(w in t for w in NOT_THINGS):
            continue
        if t in vocab and tags.get(t, 0.0) < least:
            out.append(t)
        elif t not in vocab:
            # 言い方の中にある 2〜3 語のタグ（one hand shading eyes の shading eyes、... with red trim の red trim）を比べる
            ws = t.split()
            grams = {" ".join(ws[i:i + n]) for n in (3, 2) for i in range(len(ws) - n + 1)}
            out += sorted(g for g in grams if g in vocab and tags.get(g, 0.0) < least and not any(x in g for x in NOT_THINGS))
    out += [m for m in qc.nouns_missing(prompt, tags, vocab, least) if not any(m.startswith(o) for o in out)]
    return out


def check(src: str, prompt: str) -> dict:
    """崩れを 1 つずつ鍵（kind:中身）に直して並べる。鍵は周をまたいで同じ崩れを数えるのに使う"""
    import qc
    res = qc.auto_check(src, prompt)
    tags = res.get("tags", {})
    flaws = []
    for p in res["problems"]:
        kind = next(iter(p))
        key = f"measure:{p['measure']['path']}" if kind == "measure" else kind
        flaws.append({"key": key, "kind": kind, "detail": p})
    for t in TEXT_TAGS:
        if tags.get(t, 0.0) >= LEAST:
            flaws.append({"key": f"tag:{t}", "kind": "text", "detail": {t: tags[t]}})
    for w in missing_words(prompt, tags):
        flaws.append({"key": f"missing:{w}", "kind": "missing", "detail": w})
    return {"auto": res, "flaws": flaws, "count": len(flaws)}


# ---- 崩れから範囲と言葉へ ----

def _clip(b, size):
    x0, y0, x1, y1 = (int(v) for v in b)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, size[0]), min(y1, size[1])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _around(points, names, size, pad=0.35, least=0.3):
    p = [q for q in points if q["name"] in names and q["score"] >= least]
    if not p:
        return None
    xs, ys = [q["x"] for q in p], [q["y"] for q in p]
    s = max(max(xs) - min(xs), max(ys) - min(ys), 0.08 * size[1])
    return _clip((min(xs) - s * pad, min(ys) - s * pad, max(xs) + s * pad, max(ys) + s * pad), size)


def text_box(rgb: np.ndarray) -> tuple | None:
    """下端と上の隅にある文字の行。周りの色の中央値から大きく外れる画素を太らせてつなぎ、横長（幅が高さの 3 倍以上）で
    低い（高さが絵の 4% か 20 画素まで）塊のうち、絵の隅に一番近いものを囲む。
    下端の区域をまとめて囲むと、波の泡や足の輪郭の小さな塊まで入り、箱が絵の全面になった（512x768 で 0,0,512,768）"""
    from scipy import ndimage
    g = rgb.astype(float).mean(-1)
    dev = np.abs(g - ndimage.median_filter(g, size=15)) > 40
    h, w = g.shape
    zone = np.zeros_like(dev)
    zone[int(h * 0.88):] = True
    zone[:h // 5, :w // 4] = True
    zone[:h // 5, w * 3 // 4:] = True
    lab, _ = ndimage.label(ndimage.binary_dilation(dev & zone, iterations=3))
    rows = []
    for s in ndimage.find_objects(lab):
        if s is None:
            continue
        bh, bw = s[0].stop - s[0].start, s[1].stop - s[1].start
        if bw >= 3 * bh and bh <= max(0.04 * h, 20) and bw < 0.6 * w:
            cx, cy = (s[1].start + s[1].stop) / 2, (s[0].start + s[0].stop) / 2
            rows.append((min(np.hypot(cx - x, cy - y) for x in (0, w) for y in (0, h)), s))
    if not rows:
        return None
    s = min(rows, key=lambda r: r[0])[1]
    return _clip((s[1].start - 6, s[0].start - 6, s[1].stop + 6, s[0].stop + 6), (w, h))


def background_words(prompt: str) -> str:
    bg = [t.strip() for t in prompt.split(",") if any(w in t for w in ("background", "sky", "ocean", "beach", "room", "street"))]
    return ", ".join(bg or ["plain background"]) + ", no text"


def plan(flaw: dict, src: str, prompt: str, points: list[dict], size) -> dict | None:
    """崩れ 1 つを、直す範囲と言葉にする。対応の分からない崩れは None（記録して飛ばす）"""
    import qc
    kind, key = flaw["kind"], flaw["key"]
    if kind in ("eyes", "extra_eyes") or key.startswith(("measure:eyes.", "measure:face.")):
        box = qc._face_from_joints(src, size) or fix.face_box(points)
        if box is None:
            return None
        return {"region": "face", "boxes": [_clip(box, size)],
                "prompt": "matching eyes, symmetrical eyes, same eye color, detailed face, " + prompt,
                "negative": "extra eyes, heterochromia, mismatched eyes, bad face"}
    if kind == "text":
        box = text_box(np.asarray(Image.open(src).convert("RGB")))
        if box is None:
            return None
        return {"region": "text", "boxes": [box], "prompt": background_words(prompt),
                "negative": "text, watermark, signature, artist name, letters, 1girl, person"}
    if kind == "missing":
        w = flaw["detail"].split("（")[0]
        if any(h in w for h in HAND_WORDS):
            names = ("left_wrist", "right_wrist", "left_elbow", "right_elbow")
            # 片手の動作は、顔に近い方（上がっている方）の腕を描き直す
            arms = [_around(points, (f"{s}_wrist", f"{s}_elbow"), size) for s in ("left", "right")]
            arms = [a for a in arms if a]
            one = arms and ("one hand" in w or "shading" in w)
            box = min(arms, key=lambda b: b[1]) if one else _around(points, names, size)
            if one and any(x in w for x in ("eyes", "face", "head", "forehead")):
                # 手を顔へ上げる動作は、下がった腕の範囲だけでは手を描く場所が無い。その側の肩から顔までを含める
                side = min(("left", "right"), key=lambda sd: next((q["y"] for q in points if q["name"] == f"{sd}_wrist"), 1e9))
                box = _around(points, (f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist", "nose", f"{side}_eye"), size, pad=0.2)
        elif any(c in w for c in WEAR_WORDS):
            box = _around(points, ("left_shoulder", "right_shoulder", "left_hip", "right_hip"), size, pad=0.25)
        else:
            return None
        if box is None:
            return None
        return {"region": "part", "boxes": [box], "prompt": f"{w}, {w}, " + prompt, "negative": design.NEGATIVE}
    if kind == "floating":
        return {"region": "box", "boxes": [_clip(b["box"], size) for b in flaw["detail"]["floating"]],
                "prompt": background_words(prompt), "negative": "floating object, debris"}
    if kind == "seams":
        boxes = []
        for s in flaw["detail"]["seams"]:
            a, b = s["pos"] - 24, s["pos"] + 24
            boxes.append(_clip((0, a, size[0], b) if s["at"] == "row" else (a, 0, b, size[1]), size))
        return {"region": "box", "boxes": [b for b in boxes if b], "prompt": background_words(prompt), "negative": ""}
    return None


# ---- 描き直し ----

def make_draw(style: str):
    """元の絵と同じ模型で範囲だけを描き直す関数。模型は最初の 1 回だけ読み、以後は使い回す"""
    if style in design.XL:
        return fix.repaint
    held = {}

    def draw(im, mask, prompt, negative, strength, seed):
        import torch
        from diffusers import StableDiffusionInpaintPipeline
        if "p" not in held:
            held["p"] = StableDiffusionInpaintPipeline(**design._pipe(style).components)
        p = held["p"]
        pe, ne = design.encode(p, prompt, negative)
        g = p(prompt_embeds=pe, negative_prompt_embeds=ne, image=im, mask_image=mask, strength=strength,
              num_inference_steps=max(6, int(round(6 / strength))), guidance_scale=1.5, width=im.width, height=im.height,
              generator=torch.Generator().manual_seed(seed)).images[0]
        return Image.composite(g, im, mask.filter(ImageFilter.GaussianBlur(8)))
    return draw


# ---- 回す ----

def run(src: str, outdir: str, prompt: str | None = None, rounds: int = 4, draw=None, seed: int | None = None,
        checker=check, points_of=None) -> dict:
    t0 = time.time()
    meta_p = Path(src + ".json")
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    prompt = prompt or meta.get("prompt", "")
    seed = meta.get("seed", 3) if seed is None else seed
    if draw is None:
        draw = make_draw(meta.get("style", "anime"))
    if points_of is None:
        import joints
        points_of = joints.find
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    cur = str(out / "round-0.png")
    Image.open(src).convert("RGB").save(cur)
    res = checker(cur, prompt)
    history = [{"round": 0, "image": cur, "count": res["count"], "flaws": [f["key"] for f in res["flaws"]],
                "seconds": round(time.time() - t0, 1)}]
    unfixable: dict[str, str] = {}
    skipped: list[str] = []
    for r in range(1, rounds + 1):
        if res["count"] == 0:
            break
        t = time.time()
        im = Image.open(cur).convert("RGB")
        points = points_of(cur)
        done, repaints = set(), []
        for f in res["flaws"]:
            if f["key"] in unfixable:
                continue
            pl = plan(f, cur, prompt, points, im.size)
            if pl is None or not pl["boxes"]:
                skipped.append(f["key"])
                continue
            # 同じ範囲（顔の外れが 3 つ出ても顔は 1 回）を 1 周に 2 度描き直さない
            sig = (pl["region"], tuple(pl["boxes"]))
            if sig in done:
                continue
            done.add(sig)
            mask = fix.box_mask(im.size, pl["boxes"])
            im = draw(im, mask, pl["prompt"], pl["negative"], STRENGTH[pl["region"]], seed + r)
            repaints.append({"for": f["key"], "region": pl["region"], "boxes": [list(b) for b in pl["boxes"]],
                             "prompt": pl["prompt"]})
        if not repaints:
            break  # 直せる崩れが残っていない
        cur = str(out / f"round-{r}.png")
        im.save(cur)
        res = checker(cur, prompt)
        keys = [f["key"] for f in res["flaws"]]
        history.append({"round": r, "image": cur, "count": res["count"], "flaws": keys, "repaints": repaints,
                        "seconds": round(time.time() - t, 1)})
        # 同じ崩れが 2 周続けて減らない（数が前の周以上）なら直せないと記録し、以後は描き直さない
        for k in set(keys) & {x["for"] for h in history[1:] for x in h["repaints"]}:  # 描き直しを試した崩れだけ
            c = [h["flaws"].count(k) for h in history]
            if len(c) >= 3 and c[-1] >= c[-2] >= c[-3]:
                unfixable.setdefault(k, f"{len(c) - 1} 周描き直して減らなかった")
    best = min(history, key=lambda h: (h["count"], h["round"]))
    rep = {"src": src, "prompt": prompt, "rounds": history, "best": best["image"], "best_count": best["count"],
           "unfixable": unfixable, "skipped": sorted(set(skipped)), "seconds": round(time.time() - t0, 1)}
    (out / "loop.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("outdir")
    ap.add_argument("--prompt"); ap.add_argument("--rounds", type=int, default=4); ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    rep = run(a.src, a.outdir, a.prompt, a.rounds, seed=a.seed)
    print(json.dumps({k: rep[k] for k in ("best", "best_count", "unfixable", "skipped", "seconds")}, ensure_ascii=False))
    for h in rep["rounds"]:
        print(h["round"], h["count"], h["seconds"], h["flaws"])


if __name__ == "__main__":
    main()
