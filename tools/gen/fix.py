"""描いた絵の崩れた所だけを描き直し、描き直した跡を必ず検品する。

下絵から毎回まっさらに描き直すと、良い所が出ても次の回で消えた（アラクネ 5 回。docs/knowledge/ai-drawing-notes.md）。
良い所のある 1 枚を土台にし、崩れた範囲だけを手元の絵の模型（animagine、people.MODEL）で描き直す。
描き直すと範囲の縁に背景の色の段とにじみが残り、描いた本人は見落とした。そこで描き直しのたびに
qc.background_seams と qc.repaint_scars を走らせ、結果を <出力>.qc.json に書く。数が 0 でなければ縁を直してから先へ進む。
この結果は跡の有無だけで、通す・戻すは検品担当（checker）が決める。

使い方:
  python3 tools/gen/fix.py 元.png 出力.png --box 0,640,832,1216 [--box ...] --prompt "..." [--negative "..."]
                           [--strength 0.75] [--seed 3]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
# design は模型の置き場所（HF_HOME）と、取りに行かない既定（HF_HUB_OFFLINE）を決める。diffusers より先に読まないと
# 決まる前に huggingface_hub が読まれ、置き場所を誤って手元の模型が見つからず、取りに行った（2026-10-14）
import design  # noqa: E402,F401


def box_mask(size: tuple[int, int], boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for b in boxes:
        d.rectangle(b, fill=255)
    return m


def parse_box(text: str) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (int(v) for v in text.split(","))
    if x1 <= x0 or y1 <= y0:
        raise argparse.ArgumentTypeError(f"範囲は 左,上,右,下 の順（右 > 左、下 > 上）: {text}")
    return x0, y0, x1, y1


def repaint(im: Image.Image, mask: Image.Image, prompt: str, negative: str, strength: float, seed: int,
            steps: int = 24) -> Image.Image:
    """手元の animagine で範囲だけを描き直す。描き直し専用の模型は手元に無く（約 5GB）、取りに行くとディスクを埋めた"""
    import torch
    from diffusers import StableDiffusionXLInpaintPipeline
    import people
    inp = StableDiffusionXLInpaintPipeline(**people.pipe().components)
    pe, ne, pp, np_ = design.encode_xl(inp, prompt, negative)
    g = inp(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
            image=im, mask_image=mask, strength=strength, num_inference_steps=steps, guidance_scale=6.0,
            width=im.width, height=im.height, generator=torch.Generator().manual_seed(seed)).images[0]
    # 範囲の外は元の画素のまま。縁は 8 画素ぼかしてなじませる
    return Image.composite(g, im, mask.filter(ImageFilter.GaussianBlur(8)))


def scars_report(before: Image.Image, after: Image.Image, mask: Image.Image) -> dict:
    import qc
    seams = qc.background_seams(np.asarray(after.convert("RGB")))
    scars = qc.repaint_scars(before, after, mask)
    holes = qc.repaint_holes(before, after, mask)
    return {"seams": seams, "scars": scars, "holes": holes, "clean": not seams and not scars and not holes}


FACE_POINTS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")


def face_box(points: list[dict], least: float = 0.3) -> tuple[int, int, int, int] | None:
    """骨格の点（顔の 5 点）から顔の枠。点の広がりの 1.5 倍（最小 40 画素）を足す。顔の点が読めなければ None"""
    p = [q for q in points if q["name"] in FACE_POINTS and q["score"] >= least]
    if len(p) < 2:
        return None
    xs, ys = [q["x"] for q in p], [q["y"] for q in p]
    pad = max(max(xs) - min(xs), max(ys) - min(ys), 40) * 1.5
    return int(min(xs) - pad), int(min(ys) - pad), int(max(xs) + pad), int(max(ys) + pad)


def carried_face(src: str, boxes, points: list[dict] | None = None) -> list[dict]:
    """描き直した範囲が顔に掛からないなら、元の絵で出ていた顔と目の外れ（face.*、eyes.*）を引き継ぐ。
    顔の測り方は絵全体の部位分けから顔を切り出すので、顔から離れた腹の前を描き直しただけで目として選ぶ塊が変わり、
    元の絵の瞳の色違い（0.155、基準 0.062）を描き直した絵では 0.059 と読んで通した（2026-10-15、検品担当が目で見つけた）。
    顔の枠が読めないときは、掛かるかを言えないので引き継ぐ"""
    q = Path(src + ".qc.json")
    if not q.exists():
        return []
    old = [pr for pr in json.loads(q.read_text()).get("problems", [])
           if "measure" in pr and pr["measure"]["path"].split(".")[0] in ("face", "eyes")]
    if not old:
        return []
    if points is None:
        import joints
        points = joints.find(src)
    fb = face_box(points)
    if fb is not None and any(b[0] < fb[2] and fb[0] < b[2] and b[1] < fb[3] and fb[1] < b[3] for b in boxes):
        return []
    return [{**pr, "carried": "元の絵の顔は描き直していない"} for pr in old]


def fix(src: str, out: str, boxes, prompt: str, negative: str = "", strength: float = 0.75, seed: int = 3,
        draw=repaint) -> dict:
    t = time.time()
    im = Image.open(src).convert("RGB")
    mask = box_mask(im.size, boxes)
    res = draw(im, mask, prompt, negative, strength, seed)
    res.save(out)
    mask.save(out + ".mask.png")
    rep = {"src": src, "out": out, "boxes": [list(b) for b in boxes], "prompt": prompt, "negative": negative,
           "strength": strength, "seed": seed, "seconds": round(time.time() - t)}
    rep.update(scars_report(im, res, mask))
    import qc
    auto = qc.auto_check(out, prompt)          # 描き直した絵全体も、描いた絵と同じ検品を必ず通す
    carried = carried_face(src, boxes)
    rep.update(problems=auto["problems"] + carried, unreadable=auto["unreadable"])
    rep["clean"] = rep["clean"] and auto["ok"] and not carried
    Path(out + ".qc.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--box", type=parse_box, action="append", required=True)
    ap.add_argument("--prompt", required=True); ap.add_argument("--negative", default="")
    ap.add_argument("--strength", type=float, default=0.75); ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    rep = fix(a.src, a.out, a.box, a.prompt, a.negative, a.strength, a.seed)
    print(json.dumps({k: rep[k] for k in ("out", "seconds", "seams", "scars", "clean")}, ensure_ascii=False))
    if not rep["clean"]:
        print("描き直しの跡が残っている。縁を直してから検品担当に回す", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
