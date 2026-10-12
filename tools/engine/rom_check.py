"""人形のポーズで、関節が可動域（casts/rom.json）を超えていないかを数える。

人形に姿勢を付けると、IK（手先の位置から肘と肩の曲げを逆算する仕組み）や手の回転の指定しだいで、
肘が逆に曲がる、首が真後ろを向く、のような人にできない姿勢になる。下絵にした姿勢は絵にそのまま残るので、
描く前に関節の角度を数えて止める。

角度は、親の骨から見た子の骨の向きで測る。
- 蝶番の関節（肘・膝・手首・足首）: 子の骨の向きが、親の骨の X 軸まわりに何度回ったか。正が自然な曲げ
  （人形で確かめた: 肘を +X に 60 度回すと前腕が前へ、膝を +X に 60 度回すとすねが後ろへ動く）。負は逆曲がり
- 球の関節（首・胴・肩・股）: 骨の向きが休みの姿勢から何度振れたか（swing）と、骨の向きを軸に何度ねじれたか（twist）

  PYTHONPATH=.cache/engine/bpy python3 tools/engine/rom_check.py --self-test     自然な姿勢と、わざと壊した姿勢で確かめる
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROM = json.loads((ROOT / "casts" / "rom.json").read_text(encoding="utf-8"))["joints"]


# ---- 角度の計算（Blender を使わない。試験はここを見る） ----

def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _t(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def relative(parent_rest, child_rest, parent_pose, child_pose):
    """休みの姿勢からの、親から見た子の回転（3x3）。各引数は骨の向きの 3x3 行列（列が骨の X・Y・Z 軸）"""
    rest = _mul(_t(parent_rest), child_rest)
    pose = _mul(_t(parent_pose), child_pose)
    return _mul(_t(rest), pose)


def hinge_angle(rel) -> float:
    """蝶番の曲げ角（度）。子の Y 軸（骨の向き）が X 軸まわりに回った角。正が自然な曲げ"""
    y = (rel[0][1], rel[1][1], rel[2][1])
    return math.degrees(math.atan2(y[2], y[1]))


def swing_twist(rel) -> tuple[float, float]:
    """球の関節の振れ（骨の向きが変わった角）と、ねじれ（骨の向きを軸にした回転）。どちらも度で、向きは問わない"""
    y = (rel[0][1], rel[1][1], rel[2][1])
    swing = math.degrees(math.acos(max(-1.0, min(1.0, y[1]))))
    # ねじれ: 振れを打ち消したあとに残る、Y 軸まわりの回転。X 軸の行き先を、振れだけの回転で戻して測る
    x = (rel[0][0], rel[1][0], rel[2][0])
    axis = (y[2], 0.0, -y[0])          # 元の Y から今の Y へ振る軸（Y × y）
    n = math.hypot(axis[0], axis[2])
    if n < 1e-9:
        twist = math.degrees(math.atan2(-x[2], x[0])) if y[1] > 0 else 0.0
        return swing, abs(twist)
    k = (axis[0] / n, 0.0, axis[2] / n)
    c, s = math.cos(-math.radians(swing)), math.sin(-math.radians(swing))
    dot = k[0] * x[0] + k[2] * x[2]
    cross = (k[1] * x[2] - k[2] * x[1], k[2] * x[0] - k[0] * x[2], k[0] * x[1] - k[1] * x[0])
    xr = [x[i] * c + cross[i] * s + k[i] * dot * (1 - c) for i in range(3)]
    return swing, abs(math.degrees(math.atan2(-xr[2], xr[0])))


def judge(name: str, rel) -> list[str]:
    """1つの関節の角度を可動域と比べ、外れていれば理由を返す（空なら通る）"""
    j = ROM[name]
    tol = j.get("tolerance", 0)
    out = []
    if j["kind"] == "hinge":
        a = hinge_angle(rel)
        lo, hi = j["flex"]
        if a < lo - tol:
            out.append(f"{j['ja']}が逆に {lo - a:.0f} 度曲がっている（可動域 {lo}〜{hi}）")
        elif a > hi + tol:
            out.append(f"{j['ja']}が {a:.0f} 度まで曲がっている（可動域 {lo}〜{hi}）")
    elif j["kind"] == "ball":
        sw, tw = swing_twist(rel)
        if sw > j["swing"] + tol:
            out.append(f"{j['ja']}が {sw:.0f} 度振れている（上限 {j['swing']}）")
        if tw > j["twist"] + tol:
            out.append(f"{j['ja']}が {tw:.0f} 度ねじれている（上限 {j['twist']}）")
    return out


# ---- 人形から（Blender） ----

def _axes(m):
    """4x4 の行列（mathutils）から、骨の X・Y・Z 軸を列にした 3x3"""
    return [[m[i][j] for j in range(3)] for i in range(3)]


def check_rig(rig) -> list[str]:
    """人形の全部の関節を測る。休みの姿勢は骨の rest（bone.matrix_local）、今の姿勢は pose_bone.matrix"""
    out = []
    for name, j in ROM.items():
        if j["kind"] not in ("hinge", "ball"):
            continue
        for side, (pa, ch) in j["bones"].items():
            if pa not in rig.pose.bones or ch not in rig.pose.bones:
                continue
            rel = relative(_axes(rig.data.bones[pa].matrix_local), _axes(rig.data.bones[ch].matrix_local),
                           _axes(rig.pose.bones[pa].matrix), _axes(rig.pose.bones[ch].matrix))
            out += [f"{side}: {r}" if side != "C" else r for r in judge(name, rel)]
    return out


def _self_test():
    """自然な姿勢では何も出ず、わざと壊した姿勢では出ることを、人形で確かめる"""
    import os
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import bpy
    import human
    human.setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    h = HumanService.create_human(macro_detail_dict=TargetService.get_default_macro_info_dict())
    HumanService.add_builtin_rig(h, "default")
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")

    def pose(**rot):
        for pb in rig.pose.bones:
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = (0, 0, 0)
        for bone, (ax, deg) in rot.items():
            pb = rig.pose.bones[bone.replace("_", ".")]
            e = [0.0, 0.0, 0.0]
            e["xyz".index(ax)] = math.radians(deg)
            pb.rotation_euler = e
        bpy.context.view_layer.update()
        return check_rig(rig)

    cases = {
        "休みの姿勢": ({}, False),
        "肘を 90 度曲げる": ({"lowerarm01_L": ("x", 90)}, False),
        "膝を 100 度曲げる": ({"lowerleg01_R": ("x", 100)}, False),
        "首を 45 度ひねる": ({"head": ("y", 45)}, False),
        "肘の逆曲がり 40 度": ({"lowerarm01_L": ("x", -40)}, True),
        "膝が前へ 40 度曲がる": ({"lowerleg01_R": ("x", -40)}, True),
        "首が 170 度ひねる": ({"head": ("y", 170)}, True),
        "手首が甲の側へ 120 度": ({"wrist_R": ("x", -120)}, True),
    }
    ok = True
    for name, (rot, bad) in cases.items():
        got = pose(**rot)
        hit = bool(got)
        mark = "OK" if hit == bad else "NG"
        ok &= hit == bad
        print(f"{mark}  {name}: {'; '.join(got) if got else '外れなし'}")
    print("-- 全部合った" if ok else "-- 合わないものがある")
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
