"""人形に大鎌を両手で持たせた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「大鎌を両手で」と頼むと、大きな斧の形の刃になった（武器 8 種の描き分け、2026-10-13）。
柄と刃の形、両手の位置を立体で先に決め、絵の生成には奥行きだけを渡す（ControlNet）。

柄は体の右前でほぼ縦に立て、右手は柄の上の方、左手は下の方を握る。
刃は柄の上端から頭の上を越えて反対の側へ、弧を描いて下向きに伸びる。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_scythe.py <depth.png> [--width 832] [--height 1216] [--yaw 15]
"""
import bpy  # noqa: F401  （Blender の中で動く台本であることを示す）
from mathutils import Vector

from pose_depth import args, argv, check, curve_mesh, grip, mannequin, rod, shoot

# 人形の座標: 前は -Y、右手は -X、左手は +X、身長はおよそ 1.7
FOOT = Vector((-0.20, -0.30, 0.02))        # 柄の下端（床、右足の前）
TOP = Vector((-0.36, -0.30, 1.78))         # 柄の上端（頭より少し上、右）
RIGHT_AT, LEFT_AT = 0.70, 0.55             # 右手・左手が柄のどこを握るか（下端 0 〜 上端 1）
BLADE = 0.75                               # 刃の長さ


def scythe():
    shaft = TOP - FOOT
    parts = [rod(FOOT, TOP, 0.018)]
    out = Vector((1.0, 0, 0))     # 刃は柄の上端から頭の上を越えて左へ伸びる（大鎌の見分けが付く形）。左手が届くよう柄は体に寄せる（肩から 0.8 離すと届かなかった）
    tip = TOP + out * BLADE + Vector((0, 0, -0.35))
    mid = TOP + out * (BLADE * 0.55) + Vector((0, 0, 0.05))
    o = curve_mesh("blade", (TOP, mid, tip), 0.03)
    o.scale = (1.0, 0.35, 1.0)        # 刃は薄い
    parts.append(o)
    return parts


def main(av):
    a = args(av, 15, [("--right-angle", dict(type=float, default=-90, help="右腕の IK の pole_angle（度）")),
                      ("--left-angle", dict(type=float, default=-90, help="左腕の IK の pole_angle（度）"))])
    h, rig = mannequin()
    shaft = TOP - FOOT
    grip(rig, "R", FOOT + shaft * RIGHT_AT, Vector((-0.55, 0.05, 1.10)), a.right_angle)
    grip(rig, "L", FOOT + shaft * LEFT_AT, Vector((0.45, 0.05, 0.95)), a.left_angle)
    check(rig)
    shoot(a.out, h, scythe(), a.width, a.height, a.yaw, Vector((0.1, 0, 0.95)), 2.2, 0.45)


if __name__ == "__main__":
    main(argv())
