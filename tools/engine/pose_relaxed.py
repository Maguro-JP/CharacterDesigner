"""人形を、自然な立ち姿（右手を腰に当て、左腕は脇に下ろして手を軽く開く）で撮り、形の下絵（奥行き）にする。

両腕を横に開いた立ち姿（pose_stand）は手を測りやすいが、設定画としては不自然で見栄えがしなかった。
手の位置を立体で先に決める考え方はそのままにして、片手を腰に当てた、設定画でよく使う立ち方にした。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_relaxed.py <depth.png> [--yaw 15]
"""
import math
import os
import sys

import bpy
from mathutils import Vector

from pose_depth import args, argv, check, grip, mannequin, shoot

HIP_R = Vector((-0.17, -0.03, 0.93))     # 右手を当てる腰の横（骨盤の高さより少し上）
ELBOW_POLE_R = Vector((-0.55, 0.15, 1.05))  # 肘を外へ張る向き
HAND_CURL = 20                            # 腰に当てた手の指の曲げ（度）。握り拳にしない


def main(av):
    a = args(av, 15, [])
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, 15)
    grip(rig, "R", HIP_R, ELBOW_POLE_R)
    for f in range(2, 6):
        for j in range(1, 4):
            b = rig.pose.bones[f"finger{f}-{j}.R"]
            b.rotation_euler = (math.radians(HAND_CURL), 0, 0)
    human.relax_hands(rig)
    check(rig)
    shoot(a.out, h, [], a.width, a.height, a.yaw, Vector((0, 0, 0.88)), 2.05, 0.35)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main(argv())
