"""人体の比率から、服を着せる前の人間本体（土台）の parts.json を書き出す。

職業ごとに鎧や服の形から描くと、中の人間の骨格が無く、顔が長い・髪が頭より大きいといった
人間に見えない形になった。まず骨格の目印（docs/knowledge/anatomy.md）から本体を組み、
その上に服を着せる。

数字はすべて頭の高さ H を単位にする。左向きの 3/4（手前が画面の左）。
使い方: python3 tools/body.py            # 全部の体型を characters/body-<体型>/parts.json に書く
       python3 tools/body.py male       # 1つだけ
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 体型。heads: 頭身、torso: 顎から股、sw: 肩幅、waist: くびれの幅、hw: 腰幅（いずれも H 単位、正面の幅）
# arm / leg: 上腕と太腿の太さ（半径、H 単位）。chest: 胸の厚み（女性の胸、H 単位）
# H: 描くときの頭の高さ（ドット）。箱庭ドットの手本は頭 11〜12 ドット
TYPES = {
    "male": {"note": "標準の男性（箱庭ドットの大人 2.9 頭身）", "H": 11.5, "heads": 2.9, "torso": 1.3,
             "sw": 1.2, "waist": 0.8, "hw": 0.85, "arm": 0.13, "leg": 0.17, "neck": 0.2},
    "large": {"note": "大柄の男性（肩と胸が厚い）", "H": 11.5, "heads": 3.0, "torso": 1.35,
              "sw": 1.5, "waist": 1.05, "hw": 1.0, "arm": 0.18, "leg": 0.21, "neck": 0.26},
    "female": {"note": "標準の女性（肩が狭く腰が広い、くびれ）", "H": 11, "heads": 2.9, "torso": 1.25,
               "sw": 0.95, "waist": 0.6, "hw": 0.95, "arm": 0.1, "leg": 0.15, "neck": 0.16, "chest": 0.12},
    "child": {"note": "子供（頭が大きく脚が短い）", "H": 11, "heads": 2.4, "torso": 0.95,
              "sw": 0.85, "waist": 0.7, "hw": 0.72, "arm": 0.1, "leg": 0.13, "neck": 0.16},
    "canon": {"note": "写実の男性 7.5 頭身。骨格の比率を確かめるための基準", "H": 11, "heads": 7.5, "torso": 3.0,
              "sw": 2.0, "waist": 1.3, "hw": 1.45, "arm": 0.2, "leg": 0.28, "neck": 0.3},
}

# 3/4 の向きで、正面の幅が見える割合。体の奥行きの分だけ細く見える
TURN = 0.85


def limb(joints):
    """関節の並び [(x, y, 太さの半径), ...] から、太さが変わる手足の輪郭（poly）を作る。

    筒（capsule）では太腿も足首も同じ太さになり、手足が棒に見えた。
    関節ごとに半径を変え、太腿から足首へ、上腕から手首へ細くする。
    """
    import math
    left, right = [], []
    for i, (x, y, r) in enumerate(joints):
        a = joints[max(0, i - 1)]
        b = joints[min(len(joints) - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n
        left.append([x + nx * r, y + ny * r])
        right.append([x - nx * r, y - ny * r])
    # 両端は半円で閉じる
    def cap(x, y, r, a0):
        return [[x + r * math.cos(a0 + k * math.pi / 4), y + r * math.sin(a0 + k * math.pi / 4)] for k in range(1, 4)]
    (x0, y0, r0), (x1, y1, _) = joints[0], joints[1]
    (xe, ye, re), (xp, yp, _) = joints[-1], joints[-2]
    a_start = math.atan2(y1 - y0, x1 - x0) + math.pi / 2
    a_end = math.atan2(ye - yp, xe - xp) - math.pi / 2
    return left + cap(xe, ye, re, a_end) + right[::-1] + cap(x0, y0, r0, a_start)


def head_parts(cx, top, H, names=None, bangs=False):
    """頭の部品（頭蓋骨・顔・耳・髪）と目の仕上げのドットを返す。座標は形の座標（shift を含まない）。

    頭は頭蓋骨の楕円と、その前下に付く顔（顎）で組む。髪は頭蓋骨に沿う厚み 0.05 H の帽子で、
    顔より大きな塊にしない。職業のキャラクターも同じ頭を使えるように、部品名は names で付け替える。
    目: 奥の目は顔の前の縁の最初の列、黒目はその3列後ろ（輪郭・奥の目・肌・肌・黒目）。
    """
    import math
    n = {"skull": "skull", "face": "face", "ear": "ear", "hair": "hair", "bangs": "bangs"}
    n.update(names or {})
    chin = top + H
    out = []
    skull_c = (cx + 0.06 * H, top + 0.43 * H)
    skull_r = (0.4 * H, 0.43 * H)
    out.append({"name": n["skull"], "material": "skin", "head": True, "breathe": 1,
                "shapes": [{"type": "ellipse", "at": [skull_c[0], skull_c[1], skull_r[0], skull_r[1]]}]})
    front = cx - 0.37 * H
    out.append({"name": n["face"], "material": "skin", "head": True, "breathe": 1, "relief": 1.0, "bias": 0.1,
                "shapes": [{"type": "poly", "points": [
                    [cx - 0.34 * H, top + 0.35 * H], [front, top + 0.6 * H], [cx - 0.33 * H, top + 0.78 * H],
                    [cx - 0.22 * H, top + 0.95 * H], [cx - 0.05 * H, chin], [cx + 0.18 * H, top + 0.86 * H],
                    [cx + 0.22 * H, top + 0.55 * H], [cx, top + 0.3 * H]]}]})
    out.append({"name": n["ear"], "material": "skin", "head": True, "breathe": 1, "bias": -0.2,
                "shapes": [{"type": "ellipse", "at": [cx + 0.2 * H, top + 0.6 * H, 0.07 * H, 0.12 * H]}]})
    # 髪: 生え際は額の上（頭の高さの 0.3）、後ろは耳の下まで
    rx, ry = skull_r[0] + 0.05 * H, skull_r[1] + 0.05 * H
    hair = [[skull_c[0] + rx * math.cos(math.radians(d)), skull_c[1] + ry * math.sin(math.radians(d))]
            for d in range(200, 381, 12)]
    # 後ろの下端は耳の上の高さまで。下げると後頭部が暗い塊になり、髪が顔より大きく見える
    hair += [[skull_c[0] + rx * 0.9, top + 0.66 * H], [cx + 0.24 * H, top + 0.6 * H],
             [cx + 0.14 * H, top + 0.42 * H], [cx - 0.1 * H, top + 0.3 * H], [cx - 0.36 * H, top + 0.34 * H]]
    out.append({"name": n["hair"], "material": "hair", "head": True, "breathe": 1,
                "strands": {"angle": 15, "period": 2.0, "amp": 0.2}, "shapes": [{"type": "poly", "points": hair}]})
    if bangs:
        # 前髪: 額に少しだけ下ろす房。目にはかけない
        out.append({"name": n["bangs"], "material": "hair", "group": n["hair"], "head": True, "breathe": 1,
                    "no_line_behind": True, "strands": {"angle": -20, "period": 2.0, "amp": 0.2},
                    "shapes": [{"type": "poly", "points": [
                        [cx - 0.39 * H, top + 0.30 * H], [cx - 0.1 * H, top + 0.16 * H], [cx + 0.14 * H, top + 0.24 * H],
                        [cx + 0.06 * H, top + 0.4 * H], [cx - 0.06 * H, top + 0.32 * H], [cx - 0.18 * H, top + 0.42 * H],
                        [cx - 0.3 * H, top + 0.35 * H], [cx - 0.37 * H, top + 0.44 * H]]}]})
    far = int(front + 0.5)
    eye = round(top + 0.58 * H)
    touchups = [
        {"note": "眉: 手前の黒目と白目の真上に2ドット", "at": [[far + 3, eye - 1], [far + 4, eye - 1]], "c": "#181818"},
        {"note": "手前の黒目", "at": [[far + 3, eye]], "c": "#3a2a48"},
        {"note": "白目: 黒目の後ろ側", "at": [[far + 4, eye]], "c": "#e0d8b8"},
        {"note": "奥の目: 1段上、瞳の色だけ。顔の前の縁の最初の列", "at": [[far, eye - 1]], "c": "#3a2a48"},
    ]
    return out, touchups


def build_parts(t):
    H = t["H"]
    heads, torso = t["heads"], t["torso"]
    legs = heads - 1 - torso
    top = 1.0
    chin = top + H
    crotch = chin + torso * H
    sole = crotch + legs * H
    # 胴の目印は、顎から股までを写実の比率（顎1・脇2・臍3・股4）で割る
    shoulder = chin + torso * H * (0.33 / 3)
    armpit = chin + torso * H * (1 / 3)
    navel = chin + torso * H * (2 / 3)
    knee = crotch + legs * H * (1.6 / 3.5)
    ankle = sole - 0.12 * H

    W = round(max(t["sw"], t["hw"]) * H * TURN + 8 * 2 + H * 0.4) + 2
    cx = W / 2
    sw, hw, wa = t["sw"] * H * TURN / 2, t["hw"] * H * TURN / 2, t["waist"] * H * TURN / 2
    ra, rl = t["arm"] * H, t["leg"] * H

    p = []

    def part(name, material, shapes, **kw):
        p.append(dict({"name": name, "material": material, "shapes": shapes}, **kw))

    # 奥（右）の腕と脚
    far_sh = (cx + sw * 0.9, shoulder + 0.15 * H)
    fe = (far_sh[0] + 0.12 * H, navel)
    fw = (far_sh[0] + 0.08 * H, crotch - 0.05 * H)
    part("far_arm", "skin", [{"type": "poly", "points": limb([
        (far_sh[0], far_sh[1], ra * 1.05), (fe[0], fe[1], ra * 0.75), (fe[0] - 0.01 * H, fe[1] + 0.25 * H * t["torso"] / 3, ra * 0.8),
        (fw[0], fw[1], ra * 0.5)])}], breathe=0.5, bias=-0.15, line_same=True)
    part("far_hand", "skin", [{"type": "ellipse", "at": [fw[0], crotch + 0.08 * H, ra * 0.7, ra * 1.25]}],
         bias=-0.15, line_same=True)
    far_hip = (cx + hw * 0.5, crotch - 0.15 * H)
    calf = knee + (ankle - knee) * 0.3
    part("far_leg", "skin", [{"type": "poly", "points": limb([
        (far_hip[0], far_hip[1], rl), (far_hip[0] + 0.05 * H, knee, rl * 0.62), (far_hip[0] + 0.08 * H, calf, rl * 0.72),
        (far_hip[0] + 0.1 * H, ankle, rl * 0.38)])}], bias=-0.12)
    fa = far_hip[0] + 0.1 * H
    part("far_foot", "skin", [{"type": "poly", "points": [
        [fa - 0.12 * H, ankle - 0.05 * H], [fa + 0.12 * H, ankle - 0.05 * H],
        [fa + 0.1 * H, sole], [fa - 0.32 * H, sole], [fa - 0.3 * H, sole - 0.08 * H]]}], bias=-0.12, line_same=True)

    # 胴: 肩 → 脇 → くびれ → 腰 → 股
    chest = t.get("chest", 0)
    nk = t["neck"] * H
    torso_pts = [
        [cx - nk * 0.7, shoulder - 0.12 * H], [cx - sw * 0.75, shoulder + 0.02 * H], [cx - sw, shoulder + 0.18 * H],
        [cx - sw, armpit - 0.1 * H], [cx - sw * 0.85 - chest * H, armpit + 0.05 * H],
        [cx - wa, navel], [cx - hw, crotch - 0.25 * H], [cx - hw * 0.8, crotch], [cx + hw * 0.8, crotch],
        [cx + hw, crotch - 0.25 * H], [cx + wa, navel], [cx + sw * 0.9, armpit], [cx + sw * 0.92, shoulder + 0.18 * H],
        [cx + sw * 0.7, shoulder + 0.02 * H], [cx + nk * 1.1, shoulder - 0.12 * H]]
    # 同じ肌どうしでも、手前の部品には境の線を引く（line_same）。引かないと腕も脚も胴に溶けて1つの塊になる
    part("torso", "skin", [{"type": "poly", "points": torso_pts}], breathe=0.5, relief=1.2, line_same=True)
    # 筋肉の起伏: 同じ肌の部品を境の線なしで重ね、部品ごとの膨らみの陰影で形を浮かせる
    m = t.get("muscle", 1.0)
    part("chest", "skin", [{"type": "ellipse", "at": [cx - sw * 0.3, armpit - 0.12 * H, sw * 0.55, 0.28 * H * m]}],
         breathe=0.5, relief=1.6 * m)
    part("abdomen", "skin", [{"type": "ellipse", "at": [cx - wa * 0.15, (armpit + navel) / 2 + 0.2 * H, wa * 0.6, (navel - armpit) * 0.55]}],
         breathe=0.5, relief=1.2 * m)
    # 下着: 腰から股まで。服を着せる前の目印として、股の高さを見せる
    part("briefs", "cloth", [{"type": "poly", "points": [
        [cx - hw * 1.02, crotch - 0.3 * H], [cx + hw * 1.02, crotch - 0.3 * H], [cx + hw * 0.85, crotch + 0.05 * H],
        [cx + 0.1 * H, crotch + 0.12 * H], [cx - hw * 0.85, crotch + 0.05 * H]]}])
    near_hip = (cx - hw * 0.5, crotch - 0.15 * H)
    part("near_leg", "skin", [{"type": "poly", "points": limb([
        (near_hip[0], near_hip[1], rl * 1.05), (near_hip[0] - 0.07 * H, knee, rl * 0.65), (near_hip[0] - 0.1 * H, calf, rl * 0.75),
        (near_hip[0] - 0.12 * H, ankle, rl * 0.4)])}], line_same=True)
    part("near_knee", "skin", [{"type": "ellipse", "at": [near_hip[0] - 0.07 * H, knee, rl * 0.6, rl * 0.7]}], relief=1.4)
    part("near_calf", "skin", [{"type": "ellipse", "at": [near_hip[0] - 0.08 * H, calf + (ankle - calf) * 0.1, rl * 0.72, (ankle - knee) * 0.3]}],
         relief=1.2)
    na = near_hip[0] - 0.12 * H
    part("near_foot", "skin", [{"type": "poly", "points": [
        [na - 0.12 * H, ankle - 0.05 * H], [na + 0.12 * H, ankle - 0.05 * H],
        [na + 0.1 * H, sole], [na - 0.34 * H, sole], [na - 0.32 * H, sole - 0.08 * H]]}], line_same=True)

    # 首と頭。頭は頭蓋骨の楕円と、その前下に付く顔（顎）で組む
    part("neck", "skin", [{"type": "rect", "at": [cx - nk * 0.6, chin - 0.2 * H, cx + nk * 1.2, shoulder + 0.1 * H]}],
         breathe=1, bias=-0.2)
    for q in head_parts(cx, top, H)[0]:
        p.append(q)

    # 手前（左）の腕: 肩 → 肘（臍）→ 手首（股）
    near_sh = (cx - sw * 0.95, shoulder + 0.15 * H)
    ne = (near_sh[0] - 0.14 * H, navel)
    nw = (near_sh[0] - 0.1 * H, crotch - 0.05 * H)
    part("near_arm", "skin", [{"type": "poly", "points": limb([
        (near_sh[0], near_sh[1], ra * 1.15), (ne[0], ne[1], ra * 0.8), (ne[0] + 0.01 * H, ne[1] + 0.25 * H * t["torso"] / 3, ra * 0.85),
        (nw[0], nw[1], ra * 0.55)])}], breathe=0.5, line_same=True)
    part("near_deltoid", "skin", [{"type": "ellipse", "at": [near_sh[0] + 0.02 * H, near_sh[1] + 0.05 * H, ra * 1.25, ra * 1.5]}],
         breathe=0.5, relief=1.5 * m, line_same=True)
    part("near_hand", "skin", [{"type": "ellipse", "at": [nw[0], crotch + 0.08 * H, ra * 0.75, ra * 1.3]}],
         line_same=True)

    touchups = head_parts(cx, top, H)[1]
    return p, [W, round(sole) + 2], touchups


def spec_for(kind):
    t = TYPES[kind]
    parts, canvas, touchups = build_parts(t)
    warrior = json.loads((ROOT / "characters" / "warrior" / "parts.json").read_text(encoding="utf-8"))
    return {
        "name": f"人間本体（{t['note']}）",
        "style": "diorama",
        "brief": f"服を着せる前の人間本体。tools/body.py が {kind} の比率から書き出す。手で直さず TYPES を直す",
        "canvas": canvas,
        "shift": [0, 0],
        "materials": {
            "skin": warrior["materials"]["skin"],
            "hair": warrior["materials"]["hair"],
            "cloth": {"outline": "#1a1a22", "line": "#1a1a22", "ramp": ["#3a3a48", "#5a5a6e", "#80809a"], "steps": [0.42, 0.72]},
        },
        "texture": warrior.get("texture", {}),
        "flatten_crown": True,
        "parts": parts,
        "touchups": touchups,
    }


def main():
    kinds = sys.argv[1:] or list(TYPES)
    for k in kinds:
        out = ROOT / "characters" / f"body-{k}" / "parts.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(spec_for(k), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
