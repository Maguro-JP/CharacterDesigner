"""複数の人物を1つの背景に置く（Ensemble）。切り抜き・接地の影・色寄せ・縁の光は layers.py の関数をそのまま使う。

  - 重なりの順番: 足元が画面の下にある人ほど手前。手前の人を後から重ねる
  - 大きさ: 背景の地平線と足元の高さから遠近で決め（layers.perspective_height）、人物ごとの身長の比を掛ける
  - 重なりの警告: 奥の人が手前の人に大きく隠れる（全体の 35% 以上、または顔の帯の 30% 以上）配置を ensemble.json に書く。
    並べ方の失敗は絵を見る前に数字で分かるので、描き直し（--blend）の前に止められるようにする

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/ensemble.py <出力フォルダ> --bg <背景の絵> \
      --person <絵>:<x>:<身長の比>[:<足元の高さ>] --person ... [--light front|left|right|back] [--horizon 0.45] \
      [--blend 0.3 --prompt "<言葉>"]

  描き入れ（完成）: 貼った絵は位置と大きさを決める下書き。下書きを土台に、人物ごとの設定資料（言葉と手本の絵）で
  場面の光・向き・ポーズに合わせて模型に描き直させる。
  PYTHONPATH=.cache/gen/lib python3 tools/gen/ensemble.py drawin <下書き composite.png> <出力.png> \
      --character <id>@<x0,y0,x1,y1> --character ... --scene "<場面の言葉>" [--strength 0.55 --seed N] [--reference 参考資料]

  x は中心の横位置（画面の割合）、足元の高さは画面の上からの割合（既定 0.93、大きいほど手前）。
  --horizon を省くと背景の奥行きから地平線を求める（layers.horizon）。空が見えない背景では --base-height を使う。
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import layers as L   # noqa: E402

COVER_WARN = 0.35   # 奥の人の見えている所のうち、手前の人に隠れる割合
FACE_WARN = 0.30    # 奥の人の顔の帯（上から 18%）のうち、隠れる割合
FACE_BAND = 0.18


def parse_person(spec):
    """<絵>:<x>:<身長の比>[:<足元>]。絵の名前に : が入っても読めるよう、右から数字を取る。"""
    parts = spec.split(":")
    nums = []
    while len(parts) > 1 and len(nums) < 3:
        try:
            nums.insert(0, float(parts[-1]))
        except ValueError:
            break
        parts.pop()
    if len(nums) < 2:
        raise ValueError(f"--person は <絵>:<x>:<身長の比>[:<足元>]: {spec}")
    x, ratio, foot = nums[0], nums[1], (nums[2] if len(nums) > 2 else 0.93)
    return {"src": ":".join(parts), "x": x, "ratio": ratio, "foot": foot}


def screen_height(foot, ratio, hz, base=0.8):
    """画面に対する人物の高さ。地平線があれば遠近で、無ければ base に比を掛ける。足元より上にはみ出さない。"""
    h = L.perspective_height(hz, foot) if hz is not None else base
    return float(min(h * ratio, foot, 0.95))


def order(people):
    """奥から手前の順（足元が小さい＝上にあるほど奥）。同じ高さなら渡した順。"""
    return sorted(range(len(people)), key=lambda i: (people[i]["foot"], i))


def overlaps(names, alphas):
    """奥の人が、それより手前の人たち全員にどれだけ隠れるか。alphas は奥から手前の順。"""
    warns, stats = [], []
    masks = [np.asarray(a) > 128 for a in alphas]
    for i, m in enumerate(masks):
        if not m.any():
            continue
        front = np.zeros_like(m)
        for f in masks[i + 1:]:
            front |= f
        ys = np.nonzero(m.any(axis=1))[0]
        top, h = ys.min(), ys.max() - ys.min() + 1
        face = m.copy()
        face[top + int(h * FACE_BAND):] = False
        cover = float((m & front).sum() / m.sum())
        fcover = float((face & front).sum() / max(face.sum(), 1))
        stats.append({"name": names[i], "covered": round(cover, 3), "face_covered": round(fcover, 3)})
        if cover >= COVER_WARN or fcover >= FACE_WARN:
            warns.append(f"{names[i]} が手前の人物に隠れている（全体 {cover:.0%}、顔の帯 {fcover:.0%}）")
    return warns, stats


def compose(bg, cuts, people, light_side="front", hz=None, base_height=0.8):
    """背景と切り抜いた人物から、レイヤーの並び（奥から手前）と人物ごとの情報を作る。模型は使わない。"""
    light, ambient = L.light_of(bg)
    layers = [("背景", bg.convert("RGBA"), "normal", 1.0)]
    info, names, alphas = [], [], []
    for i in order(people):
        p = people[i]
        name = f"人物{i + 1}: {Path(p['src']).stem}"
        h = screen_height(p["foot"], p["ratio"], hz, base_height)
        char = L.place(cuts[i], h, p["x"], p["foot"])
        char = L.match_colors(char, bg, light)
        layers += [(f"{name} 接地の影", L.contact_shadow(char, ambient), "multiply", 1.0),
                   (name, char, "normal", 1.0),
                   (f"{name} 色寄せ", L.color_grade(char, ambient), "multiply", 1.0),
                   (f"{name} 縁の光", L.rim_light(char, light, light_side, bg=bg), "screen", 0.6)]
        names.append(name)
        alphas.append(char.getchannel("A"))
        bbox = char.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
        info.append({"name": name, "src": p["src"], "x": p["x"], "foot": p["foot"], "ratio": p["ratio"],
                     "height": round(h, 3), "bbox": list(bbox) if bbox else None})
    warns, stats = overlaps(names, alphas)
    return layers, {"light": light, "ambient": ambient, "horizon": hz, "people": info, "overlap": stats, "warnings": warns}


def build(outdir, bg_path, people, light_side="front", horizon=None, base_height=0.8, blend=0.0, prompt="", seed=7):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bg = Image.open(bg_path).convert("RGB").resize(L.SIZE)
    hz = horizon if horizon is not None else L.horizon(bg)
    cuts = [L.cut_character(p["src"]) for p in people]
    layers, info = compose(bg, cuts, people, light_side, hz, base_height)
    flat = L.flatten(layers)
    flat.save(outdir / "composite.png")
    L.save_psd(layers, outdir / "ensemble.psd")
    info["layers"] = [n for n, *_ in layers]
    if blend > 0:
        L.blend(flat, prompt, blend, seed).save(outdir / "final.png")
        info["blend"] = blend
    (outdir / "ensemble.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    return info


# ---- 描き入れ ----
# 手本の絵の渡し方: 人物ごとの範囲を順に描き直す。IP-Adapter は 1 回の描画で複数の手本を受けても、
# 埋め込みを混ぜて絵全体に効かせるだけで、どの手本をどの人物に効かせるかを分けられない（色と顔が混ざる）。
# そこで 1 回目に絵全体を言葉だけで描き直して光と向きをそろえ、2 回目から人物の範囲だけを、その人の手本を読ませて描き直す
REF_ROLES = ("color", "turnaround")
COUNT_TAGS = ("1girl", "1boy", "solo")


def parse_character(spec):
    """<id>@<x0,y0,x1,y1>。範囲は下書きの画素"""
    ident, sep, box = spec.rpartition("@")
    if not sep or not ident:
        raise ValueError(f"--character は <id>@<x0,y0,x1,y1>: {spec}")
    try:
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
    except ValueError:
        raise ValueError(f"範囲は整数 4 つ: {spec}") from None
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"範囲は 左,上,右,下 の順（右 > 左、下 > 上）: {spec}")
    return {"id": ident, "box": (x0, y0, x1, y1)}


def _strip_count(text):
    return ", ".join(t.strip() for t in text.split(",") if t.strip() and t.strip() not in COUNT_TAGS)


def headcount(looks):
    """bible の見た目の言葉（1girl / 1boy）から人数の言葉。性別の書かれていない人は数えない"""
    g = sum("1girl" in l for l in looks)
    b = sum("1boy" in l for l in looks)
    words = [f"{g}girl" + ("s" if g > 1 else "") if g else "", f"{b}boy" + ("s" if b > 1 else "") if b else ""]
    return ", ".join(w for w in words if w) or f"{len(looks)}people"


def drawin_prompts(chars, scene, prompt_of=None):
    """全体の言葉と、人物ごとの言葉。人物の言葉は bible.prompt を使い回し、人数の言葉だけ取り除く（全体で 2girls などに置き換える）"""
    import bible
    prompt_of = prompt_of or (lambda i: bible.prompt(i, framing="", background=False))
    each = [prompt_of(c["id"]) for c in chars]
    count = headcount([p for p, _ in each])
    people_words = [f"({_strip_count(p)})" for p, _ in each]
    whole = ", ".join(x for x in [count, *people_words, scene] if x)
    negs = []
    for _, n in each:
        negs += [t.strip() for t in n.split(",") if t.strip() and t.strip() not in negs]
    neg = ", ".join(negs + ["solo"])
    parts = [", ".join(x for x in [_strip_count(p), scene] if x) for p, _ in each]
    return whole, neg, parts


class GateClosed(RuntimeError):
    pass


def gate(ids, reference=None):
    import modes
    st = modes.check("Ensemble", ids, reference)
    if not st["ok"]:
        raise GateClosed("描き入れを始められない: " + " / ".join(st["missing"]))
    return st


def _whole(im, prompt, negative, strength, seed):
    """絵全体を言葉だけで描き直す（光と向きをそろえる）"""
    import torch
    import design
    import demi
    import people
    i2i = demi.img2img()
    pe, ne, pp, np_ = design.encode_xl(people.pipe(), prompt, negative)
    return i2i(image=im, prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp,
               negative_pooled_prompt_embeds=np_, strength=strength, num_inference_steps=24, guidance_scale=6.0,
               generator=torch.Generator().manual_seed(seed)).images[0]


def _region(im, mask, prompt, negative, strength, seed, ref=None, ref_scale=0.6):
    """範囲の描き直し。fix.repaint と同じ作り（同じ模型の部品で描き直し、縁を 8 画素ぼかす）に、手本の絵を足したもの"""
    import torch
    from diffusers import StableDiffusionXLInpaintPipeline
    from PIL import ImageFilter
    import design
    import people
    args = {}
    if ref is not None:
        people.use_reference()
    inp = StableDiffusionXLInpaintPipeline(**people.pipe().components)
    if ref is not None:
        inp.set_ip_adapter_scale(ref_scale)
        args["ip_adapter_image"] = ref
    pe, ne, pp, np_ = design.encode_xl(inp, prompt, negative)
    g = inp(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
            image=im, mask_image=mask, strength=strength, num_inference_steps=24, guidance_scale=6.0,
            width=im.width, height=im.height, generator=torch.Generator().manual_seed(seed), **args).images[0]
    return Image.composite(g, im, mask.filter(ImageFilter.GaussianBlur(8)))


def drawin(draft, out, chars, scene, strength=0.55, seed=7, reference=None, ref_scale=0.6,
           whole=_whole, region=_region, prompt_of=None, ref_of=None, check=None):
    """下書きを土台に描き入れる。門（modes.check）を通らなければ模型を読まずに止める"""
    import time
    import fix
    gate([c["id"] for c in chars], reference)
    t = time.time()
    im = Image.open(draft).convert("RGB")
    for c in chars:
        x0, y0, x1, y1 = c["box"]
        if x0 < 0 or y0 < 0 or x1 > im.width or y1 > im.height:
            raise ValueError(f"{c['id']} の範囲が下書き（{im.width}x{im.height}）からはみ出している: {c['box']}")
    pos, neg, parts = drawin_prompts(chars, scene, prompt_of)
    if ref_of is None:
        import bible
        ref_of = lambda i: bible.reference_image(i, REF_ROLES)  # noqa: E731
    res = whole(im, pos, neg, strength, seed)
    refs = []
    for k, c in enumerate(chars):
        ref = ref_of(c["id"])
        refs.append(ref is not None)
        res = region(res, fix.box_mask(res.size, [c["box"]]), parts[k], neg, strength, seed + 1 + k, ref, ref_scale)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    res.save(out)
    if check is None:
        import qc
        check = qc.auto_check
    auto = check(str(out), pos)
    rep = {"draft": str(draft), "out": str(out), "prompt": pos, "negative": neg, "parts": parts,
           "characters": [{"id": c["id"], "box": list(c["box"]), "reference": r} for c, r in zip(chars, refs)],
           "strength": strength, "seed": seed, "seconds": round(time.time() - t),
           "problems": auto["problems"], "unreadable": auto["unreadable"], "ok": auto["ok"]}
    Path(str(out) + ".qc.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


def main_drawin(argv):
    ap = argparse.ArgumentParser(prog="ensemble.py drawin")
    ap.add_argument("draft"); ap.add_argument("out")
    ap.add_argument("--character", action="append", required=True, help="<id>@<x0,y0,x1,y1>")
    ap.add_argument("--scene", required=True)
    ap.add_argument("--strength", type=float, default=0.55)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ref-scale", type=float, default=0.6)
    ap.add_argument("--reference", default=None, help="人の参考資料（あれば設計がそろっていなくても描ける）")
    a = ap.parse_args(argv)
    try:
        chars = [parse_character(s) for s in a.character]
    except ValueError as e:
        ap.error(str(e))
    try:
        rep = drawin(a.draft, a.out, chars, a.scene, a.strength, a.seed, a.reference, a.ref_scale)
    except GateClosed as e:
        raise SystemExit(str(e))
    print(json.dumps({k: rep[k] for k in ("out", "seconds", "ok")}, ensure_ascii=False))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "drawin":
        return main_drawin(sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--bg", required=True)
    ap.add_argument("--person", action="append", required=True, help="<絵>:<x>:<身長の比>[:<足元の高さ>]")
    ap.add_argument("--light", default="front", choices=["front", "left", "right", "back"])
    ap.add_argument("--horizon", type=float, default=None, help="地平線の高さ（画面の割合）。省くと背景の奥行きから求める")
    ap.add_argument("--base-height", type=float, default=0.8, help="地平線が無いときの、身長の比 1.0 の高さ")
    ap.add_argument("--blend", type=float, default=0.0)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    people = [parse_person(s) for s in a.person]
    if len(people) < 2:
        ap.error("--person は 2 人以上")
    info = build(a.outdir, a.bg, people, a.light, a.horizon, a.base_height, a.blend, a.prompt, a.seed)
    for w in info["warnings"]:
        print("警告:", w)
    print(json.dumps({p["name"]: p["height"] for p in info["people"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
