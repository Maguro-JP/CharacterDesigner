"""設定資料の「詳細」の絵（目・髪・服の部位・持ち物の拡大）を、checker が通した全身の絵から作る。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/closeup.py <id> <出力フォルダ> [--src 全身の絵] [--only eyes,hair,outfit-upper,...]

全身の絵では目が 20〜40 画素、服の留め具や持ち物の金具は数画素しか無く、拡大しただけでは資料にならない。
部位の枠を切り出して 1024 画素に広げ、弱く描き直して細部を描かせる。言葉は設定資料集の言葉をそのまま使い、
色と形は元の絵に従わせる（強く描き直すと、拡大の絵が全身の絵と別の服・別の目になる）。
元の絵は既定で役割 view-front、無ければ color（どちらも checker が通して登録した絵）。

出力は detail-<部位>.png。checker に回し、通したものを bible.py add-image <id> detail-<部位> <絵> で登録する。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402

SIDE = 1024
# 部位ごとの描き足す言葉。部位分けの番号は edit.LABELS
PARTS = {
    "eyes": ("close-up of eyes, detailed iris, detailed eyelashes, eyebrows", None),
    "hair": ("close-up of hair, detailed hair strands, hair tie, hairstyle detail", None),
    "outfit-upper": ("close-up of clothing, upper body, collar, buttons, fabric folds, stitching", [4, 7, 17]),
    "outfit-lower": ("close-up of clothing, trousers, fabric folds, belt", [5, 6, 8]),
    "outfit-shoes": ("close-up of boots, shoes, leather texture, laces", [9, 10]),
}
NEGATIVE = "different outfit, different colors, extra buttons, text, watermark, blurry, lowres"


def _bbox(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    if len(xs) < 30:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def square(box, w: int, h: int, margin: float = 0.15, least: int = 96):
    """枠を正方形に広げ、絵の内側に収める（描き直しは正方形で行う。縦横比を変えると形が伸びる）"""
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0, least) * (1 + 2 * margin)
    side = int(min(side, w, h))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = int(min(max(cx - side / 2, 0), w - side))
    top = int(min(max(cy - side / 2, 0), h - side))
    return left, top, left + side, top + side


def boxes(seg, items: list[dict] | None = None) -> dict:
    """部位分け（edit.parts の番号の配列）から、拡大する枠を部位ごとに返す。読めない部位は入れない。
    目は顔の上半分の帯（顔の枠の 25〜60%）を使う。目の点の検出は横顔や伏せ目で外れるが、帯は顔さえ読めれば取れる"""
    import numpy as np
    h, w = seg.shape
    out = {}
    face = _bbox(seg == 11)
    if face:
        x0, y0, x1, y1 = face
        fh = y1 - y0
        out["eyes"] = square((x0, y0 + int(fh * 0.25), x1, y0 + int(fh * 0.6)), w, h, margin=0.1)
    hair = _bbox(np.isin(seg, [2]))
    if hair:
        out["hair"] = square(hair, w, h, margin=0.05)
    for name, (_, ids) in PARTS.items():
        if ids is None:
            continue
        b = _bbox(np.isin(seg, ids))
        if b:
            # 服は縦に長い。正方形にすると全身が入るので、上から縦横の短い方の 1.2 倍だけ取る
            x0, y0, x1, y1 = b
            span = int(min(x1 - x0, y1 - y0) * 1.2)
            out[name] = square((x0, y0, x1, min(y1, y0 + max(span, 1))), w, h, margin=0.05)
    for it in items or []:
        # 持ち物は部位分けに番号が無い。設定資料集の items[].box（元の絵の画素で x0,y0,x1,y1）があるときだけ切る
        if it.get("box"):
            out[f"item-{it['id']}"] = square(tuple(it["box"]), w, h)
    return out


def source(ident: str, src: str | None = None) -> Path:
    if src:
        return Path(src)
    p = bible.reference_path(ident, ("view-front", "color"))
    if p is None:
        raise SystemExit(f"{ident}: 元にする全身の絵（view-front か color）がまだ登録されていない")
    return p


def run(ident: str, outdir: str, src: str | None = None, only: list[str] | None = None,
        strength: float = 0.35, seed: int = 0) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    import demi
    import design
    import edit
    import free_text
    c = bible.load("characters", ident)
    path = source(ident, src)
    im = Image.open(path).convert("RGB")
    seg = np.asarray(edit.parts(str(path)))
    found = boxes(seg, c.get("items"))
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    pipe = demi.img2img()
    done = {}
    for name, box in found.items():
        if only and name not in only:
            continue
        if name.startswith("item-"):
            it = next(i for i in c["items"] if f"item-{i['id']}" == name)
            words = f"close-up of {it['tags']}, detailed texture"
        else:
            words = PARTS[name][0]
        base, neg = bible.prompt(ident, framing="")
        pos, neg = free_text.full_prompt(f"{words}, {base}", f"{neg}, {NEGATIVE}")
        pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
        crop = im.crop(box).resize((SIDE, SIDE), Image.LANCZOS)
        redone = pipe(image=crop, strength=strength, prompt_embeds=pe, negative_prompt_embeds=ne,
                      pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_, num_inference_steps=24,
                      guidance_scale=6.0, generator=torch.Generator().manual_seed(seed)).images[0]
        f = out / f"detail-{name}.png"
        redone.save(f)
        done[name] = {"file": str(f), "box": box, "crop_px": box[2] - box[0]}
    missing = [n for n in (only or ["eyes", "hair", "outfit-upper"]) if n not in found]
    rep = {"src": str(path), "done": done, "unreadable": missing}
    (out / "closeup.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id"); ap.add_argument("out")
    ap.add_argument("--src"); ap.add_argument("--only", help="部位をカンマ区切りで（eyes, hair, outfit-upper, outfit-lower, outfit-shoes, item-<id>）")
    ap.add_argument("--strength", type=float, default=0.35); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(run(a.id, a.out, a.src, a.only.split(",") if a.only else None, a.strength, a.seed),
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
