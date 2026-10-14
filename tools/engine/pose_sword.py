"""人形に剣を両手で握らせ、切っ先を床に付けた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「両手で柄を握り、切っ先を床に」と頼むと、描き方を3通り変えても6枚とも守られなかった
（片手持ち、剣が2本、横に突き出す）。手と剣の位置は立体で先に決め、絵の生成には奥行きだけを渡す
（ControlNet）。奥行きは形だけを縛り、色と絵柄は言葉から来る。

腕は IK（手先の位置から肘と肩の曲げを逆算する）で、両手を柄の上下に重ねて置く。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_sword.py <depth.png> [--width 832] [--height 1216] [--yaw 20]
"""
import math

import bpy
from mathutils import Vector

from pose_depth import args, argv, check, grip, mannequin, shoot

# 人形の座標: 前は -Y、右手は -X、身長はおよそ 1.7
HILT = Vector((0.0, -0.28, 0.88))      # 柄の中ほど。体の正面、腰の高さ（0.98 では柄頭が胸まで来て、柄が長く見えた）
GUARD_Z = 0.76                          # 鍔の高さ。ここから下が刃で、切っ先は床（z=0）
# 両手は鍔のすぐ上に上下に重ねる。手と鍔の間が空くと、絵では柄が長く描かれた
LEFT_GRIP = Vector((HILT.x, HILT.y, GUARD_Z + 0.05))   # 左手は鍔のすぐ上
RIGHT_GRIP = Vector((HILT.x, HILT.y, GUARD_Z + 0.13))  # 右手はその上
def sword():
    parts = []
    # 柄（鍔の上 0.2。両手の幅だけ）
    bpy.ops.mesh.primitive_cylinder_add(radius=0.022, depth=0.2, location=(HILT.x, HILT.y, GUARD_Z + 0.1))
    parts.append(bpy.context.object)
    # 柄頭
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.035, location=(HILT.x, HILT.y, GUARD_Z + 0.21))
    parts.append(bpy.context.object)
    # 鍔: 横に長い板
    bpy.ops.mesh.primitive_cube_add(size=1, location=(HILT.x, HILT.y, GUARD_Z))
    g = bpy.context.object
    g.scale = (0.28, 0.04, 0.03)
    parts.append(g)
    # 刃: 鍔から床まで。切っ先へ細くなる
    bpy.ops.mesh.primitive_cone_add(radius1=0.035, radius2=0.004, depth=GUARD_Z, vertices=4,
                                    location=(HILT.x, HILT.y, GUARD_Z / 2))
    b = bpy.context.object
    b.rotation_euler = (math.pi, 0, math.radians(45))
    b.scale = (1.0, 0.25, 1.0)
    parts.append(b)
    return parts


def main(av):
    a = args(av, 20, [("--left-pole", dict(default="0.45,-0.05,1.05", help="左肘を引き寄せる点（x,y,z）")),
                      ("--left-angle", dict(type=float, default=-90, help="左腕の IK の pole_angle（度）"))])
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, 35)
    grip(rig, "R", RIGHT_GRIP, Vector((-0.45, -0.05, 1.05)))
    grip(rig, "L", LEFT_GRIP, Vector([float(v) for v in a.left_pole.split(",")]), a.left_angle)
    check(rig)
    # 体の厚みは 0.4m ほどしかない。幅を広く取ると体全体が同じ灰色になり、奥行きの差が下絵に出なかった
    shoot(a.out, h, sword(), a.width, a.height, a.yaw, Vector((0, 0, 0.88)), 2.05, 0.35)


if __name__ == "__main__":
    main(argv())
