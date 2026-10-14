"""人形に弓を引かせた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「弓を持った冒険者」を頼むと、弓が描かれず矢筒だけが出た（武器 8 種の描き分け、2026-10-13）。
弓・弦・矢と両手の位置を立体で先に決め、絵の生成には奥行きだけを渡す（ControlNet）。

左手（弓手）は肩の高さで横へ伸ばして弓の握りを持ち、右手（引き手）は弦を頬まで引く。
弓は握りを中心に縦に立て、上下の端（弓の先）は射手の側へ反る。弦は両端から右手へ張る。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_bow.py <depth.png> [--width 832] [--height 1216] [--yaw 15]
"""
import bpy  # noqa: F401  （Blender の中で動く台本であることを示す）
from mathutils import Vector

from pose_depth import args, argv, check, curve_mesh, grip, mannequin, rod, shoot

# 人形の座標: 前は -Y、右手は -X、左手は +X、身長はおよそ 1.7（肩の高さ 1.40 前後、あご 1.50 前後）
BOW_HAND = Vector((0.62, -0.18, 1.38))     # 左手: 肩の高さで左へ伸ばし、少し前へ
DRAW_HAND = Vector((-0.06, -0.10, 1.47))   # 右手: 弦を右の頬の横まで引く
LIMB = 0.52                                # 握りから弓の先までの高さ
BEND = 0.16                                # 弓の先が射手の側へ反る量


def bow():
    aim = (BOW_HAND - DRAW_HAND).normalized()          # 矢の向き（引き手から弓手へ）
    top = BOW_HAND - aim * BEND + Vector((0, 0, LIMB))
    bottom = BOW_HAND - aim * BEND - Vector((0, 0, LIMB))
    parts = [curve_mesh("bow", (top, BOW_HAND, bottom), 0.014)]
    parts.append(rod(top, DRAW_HAND, 0.003))            # 弦（上）
    parts.append(rod(bottom, DRAW_HAND, 0.003))         # 弦（下）
    parts.append(rod(DRAW_HAND, BOW_HAND + aim * 0.12, 0.006))   # 矢: 弓の握りから少し先へ出る
    return parts


def main(av):
    a = args(av, 15, [("--draw-angle", dict(type=float, default=0, help="引き手の IK の pole_angle（度）。0 で肘が肩の高さで横へ張る（90 は肘が頭の後ろ、180 は肩が 119 度ねじれた）"))])
    h, rig = mannequin()
    # 弓手は伸ばしきる。肘を引く点は下の外側に置き、肘がわずかに下へ逃げるようにする
    grip(rig, "L", BOW_HAND, Vector((0.45, 0.10, 0.95)))
    # 引き手の肘は肩の高さで、矢の線の延長（弓と反対の横）へ張る。肘を引く点を後ろの高い所に置くと、腕が頭の上を回った
    grip(rig, "R", DRAW_HAND, Vector((-0.60, -0.02, 1.42)), a.draw_angle)
    check(rig)
    shoot(a.out, h, bow(), a.width, a.height, a.yaw, Vector((0.1, 0, 0.95)), 2.2, 0.45)


if __name__ == "__main__":
    main(argv())
