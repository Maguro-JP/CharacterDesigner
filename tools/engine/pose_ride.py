"""人形を乗り物にまたがらせた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「機械の脚に乗る」を頼むと、人物は機械の脚の間に立ち、乗らなかった（乗り物の描き分け、2026-10-13）。
乗り物の大きさと、腰・足・手を置く場所を立体で先に決め、絵の生成には奥行きだけを渡す（ControlNet）。

mech: 4 本の機械の脚の上に箱の胴を置き、人形はその上の座席にまたがる。両足は胴の両脇の足掛け、両手は前の操縦桿。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_ride.py <depth.png> [--width 1216] [--height 832] [--yaw 30]
"""
import bpy
from mathutils import Vector

from pose_depth import args, argv, check, grip, mannequin, rod, shoot

LIFT = 1.0                      # 人形を持ち上げる高さ（機械の脚の長さ）。休みの姿勢の腰は 0.83
SEAT = 0.72 + LIFT              # 座席の上面（腰の少し下）
FOOTREST = 0.42 + LIFT          # 足掛けの高さ（膝を曲げて足を前へ）
STICK = Vector((0.0, -0.42, 1.10 + LIFT))   # 操縦桿の握り（左右は ±0.18）


def box(center, size):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    o = bpy.context.object
    o.scale = size
    return o


def mech():
    parts = [box(Vector((0, -0.05, SEAT - 0.30)), (0.55, 1.10, 0.55)),        # 胴
             box(Vector((0, -0.62, SEAT - 0.10)), (0.40, 0.20, 0.30))]        # 前の操縦盤
    for sx in (-1, 1):
        parts.append(box(Vector((sx * 0.32, -0.25, FOOTREST - 0.03)), (0.12, 0.30, 0.04)))   # 足掛け
        parts.append(rod(Vector((sx * 0.18, -0.55, SEAT + 0.05)), STICK + Vector((sx * 0.18, 0, 0)), 0.02))   # 操縦桿
        for sy in (-1, 1):
            hip = Vector((sx * 0.30, sy * 0.40 - 0.05, SEAT - 0.55))
            knee = Vector((sx * 0.55, sy * 0.55 - 0.05, SEAT - 0.95))
            parts.append(rod(hip, knee, 0.07))                                 # 太もも（外へ開く）
            parts.append(rod(knee, Vector((sx * 0.50, sy * 0.55 - 0.05, 0.05)), 0.06))   # すね
            parts.append(box(Vector((sx * 0.50, sy * 0.55 - 0.05, 0.04)), (0.25, 0.30, 0.08)))   # 足の裏
    return parts


def leg(rig, side, at, pole_at):
    """足先を at へ。腰から足首までを IK で曲げる"""
    from pose_prop import empty
    t, p = empty(f"foot_{side}", at), empty(f"knee_{side}", pole_at)
    c = rig.pose.bones[f"lowerleg02.{side}"].constraints.new("IK")
    c.target, c.pole_target, c.chain_count = t, p, 4
    import math
    c.pole_angle = math.radians(-90)


def main(av):
    a = args(av, 30)
    h, rig = mannequin()
    rig.location.z += LIFT
    h.location.z += 0 if h.parent == rig else LIFT
    bpy.context.view_layer.update()
    for side, sx in (("L", 1), ("R", -1)):
        leg(rig, side, Vector((sx * 0.32, -0.30, FOOTREST)), Vector((sx * 0.45, -1.2, SEAT)))
    grip(rig, "L", STICK + Vector((0.18, 0, 0)), Vector((0.45, 0.10, 1.10 + LIFT)))
    grip(rig, "R", STICK + Vector((-0.18, 0, 0)), Vector((-0.45, 0.10, 1.10 + LIFT)))
    check(rig)
    # 正射影の幅（ortho_scale）は絵の長い辺に掛かる。横長では 4.2 で縦が 2.9 ほど写り、足の裏から頭まで入る
    shoot(a.out, h, mech(), a.width, a.height, a.yaw, Vector((0, 0, 1.45)), 4.2, 0.9)


if __name__ == "__main__":
    main(argv())
