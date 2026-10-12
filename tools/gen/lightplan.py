"""光の設計と、それを当てた 3D の下絵。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/lightplan.py <空気感> out.png [--hair "#2a2230"] [--inner "#c23a5a"] [--pose stand]

言葉だけで描くと、光の向き・影の色・縁の光が顔と髪と服でばらばらになる（模型は立体を知らずに明暗を置く）。
そこで描く前に光を決め、3D の素体（tools/engine/viewer/vrm-base.html）にその光を当てて撮り、下絵にして描く。
立体の向きに沿った影と、主光の反対側の縁の光が下絵から来るので、絵の中の光がそろう。

光の決め方（docs/knowledge/atmosphere.md、painting-workflow.md）:
- 主の光（key）: 向き az（0 が顔の正面、正は画面の右から）、高さ el、強さ、色。暖かい主光なら影は冷たく
- 回り込み（amb）: 影の側の明るさと色。空や照り返しの色で、主光の補色に寄せる
- 縁の光（rim）: 主光の反対の後ろから。逆光の絵で輪郭を立てる
- 背景（bg）: 下絵の背景の色。暗い場所ほど暗く
陰の段の暗い側は 0 にし、影の明るさは回り込みだけで決める（暗い側に主光が一定の割合で入ると、逆光でも正面が明るくなった）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PLANS = {
    "day": {"az": 35, "el": 40, "key": 110, "color": "#fff1dc", "amb": 55, "ambColor": "#a9b4cf", "rim": 0, "bg": "#cfd6df"},
    "holy": {"az": 160, "el": 50, "key": 120, "color": "#ffe6b0", "amb": 55, "ambColor": "#9aa6c8", "rim": 150, "rimColor": "#fff0c8", "bg": "#8a7a68"},
    "dust": {"az": 120, "el": 35, "key": 110, "color": "#ffd9a0", "amb": 45, "ambColor": "#8f8070", "rim": 90, "rimColor": "#ffe0a8", "bg": "#7a6a55"},
    "komorebi": {"az": 50, "el": 60, "key": 105, "color": "#fff0c0", "amb": 55, "ambColor": "#88a890", "rim": 60, "rimColor": "#f0ffd0", "bg": "#5d7552"},
    "underground": {"az": -70, "el": 5, "key": 120, "color": "#ff9c50", "amb": 25, "ambColor": "#3c4660", "rim": 0, "bg": "#1c1a20"},
    "space": {"az": 60, "el": 20, "key": 110, "color": "#fff0dc", "amb": 25, "ambColor": "#5a4a90", "rim": 130, "rimColor": "#9ab8ff", "bg": "#0c0c1c"},
    "haze": {"az": 30, "el": 45, "key": 80, "color": "#f4f0ea", "amb": 70, "ambColor": "#b8c0cc", "rim": 0, "bg": "#c8ccd2"},
}


def plan_of(mood: str) -> dict:
    p = dict(PLANS.get(mood or "day", PLANS["day"]))
    p["shadow"] = 0.0
    return p


def underlay(mood: str, out, hair: str = "", inner: str = "", pose: str = "stand", size=(832, 1216), view: int = 15) -> dict:
    """光を当てた 3D の素体を撮り、背景の色に載せて下絵にする。返すのは使った光"""
    from PIL import Image
    import demi
    plan = plan_of(mood)
    demi.write_page()
    out = Path(out)
    url, stop = demi.serve()
    try:
        arg = {"url": url, "out": str(out.with_suffix("")) + "-shot", "kind": "none", "hair": "keep", "body": "ideal",
               "pose": pose, "views": [view], "light": {k: v for k, v in plan.items() if k != "bg"}}
        if hair:
            arg.update(hairColor=hair, hairInner=inner or None)
        subprocess.run(["node", str(demi.SHOOT), json.dumps(arg)], check=True, env=demi.node_env(), timeout=900,
                       capture_output=True)
    finally:
        stop()
    shot = Path(arg["out"] + "-color-0.png")
    fig = Image.open(shot).convert("RGBA")
    fig = fig.crop(fig.getbbox())
    # 全身が縦の 88% に収まる大きさで、下寄せ（足元に少し余白）に置く
    s = size[1] * 0.88 / fig.height
    fig = fig.resize((round(fig.width * s), round(fig.height * s)), Image.LANCZOS)
    bg = Image.new("RGBA", size, plan["bg"])
    bg.alpha_composite(fig, ((size[0] - fig.width) // 2, size[1] - fig.height - round(size[1] * 0.04)))
    bg.convert("RGB").save(out)
    for p in shot.parent.glob(shot.name.replace("-color-0.png", "-*.png")):
        p.unlink()
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mood", choices=sorted(PLANS))
    ap.add_argument("out")
    ap.add_argument("--hair", default="")
    ap.add_argument("--inner", default="")
    ap.add_argument("--pose", default="stand")
    a = ap.parse_args()
    print(underlay(a.mood, a.out, a.hair, a.inner, a.pose))


if __name__ == "__main__":
    main()
