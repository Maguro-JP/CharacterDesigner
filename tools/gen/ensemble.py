"""複数の人物を1つの背景に置く（Ensemble）。切り抜き・接地の影・色寄せ・縁の光は layers.py の関数をそのまま使う。

  - 重なりの順番: 足元が画面の下にある人ほど手前。手前の人を後から重ねる
  - 大きさ: 背景の地平線と足元の高さから遠近で決め（layers.perspective_height）、人物ごとの身長の比を掛ける
  - 重なりの警告: 奥の人が手前の人に大きく隠れる（全体の 35% 以上、または顔の帯の 30% 以上）配置を ensemble.json に書く。
    並べ方の失敗は絵を見る前に数字で分かるので、描き直し（--blend）の前に止められるようにする

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/ensemble.py <出力フォルダ> --bg <背景の絵> \
      --person <絵>:<x>:<身長の比>[:<足元の高さ>] --person ... [--light front|left|right|back] [--horizon 0.45] \
      [--blend 0.3 --prompt "<言葉>"]

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


def main():
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
