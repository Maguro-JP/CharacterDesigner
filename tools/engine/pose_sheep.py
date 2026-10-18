"""羊娘の設定画のポーズ 3 種を人形で撮り、形の下絵（奥行き）にする。

basket : 左の前腕に籠を掛け（前腕を腰の高さで前へ）、右手で糸玉を胸の前へ持ち上げる。斜め前
hands  : 両手を下腹の前で軽く重ね、首を少しかしげる。正面
wave   : 斜め後ろから撮り、首を振り返らせて右手を肩の横で小さく振る。膝上

下絵は ControlNet の奥行きにだけ使う（img2img の土台にすると裸の体の形が出る）。
使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_sheep.py <depth.png> --pose basket
"""
import math
import os
import sys

import bpy  # noqa: F401  mathutils は bpy を読み込んでから使える
from mathutils import Vector

from pose_depth import args, argv, check, grip, mannequin, shoot

POSES = {
    # 手先の位置、肘の向き。x は -（右手側）/ +（左手側）、y は -（前）、z は高さ（m）
    "basket": dict(yaw=25, look=(0, 0, 0.88), frame=2.05,
                   R=((-0.12, -0.30, 1.28), (-0.55, 0.15, 0.95)),
                   L=((0.14, -0.32, 1.00), (0.35, 0.35, 0.90))),
    "hands": dict(yaw=0, look=(0, 0, 0.88), frame=2.05, tilt=8,
                  R=((-0.02, -0.17, 0.93), (-0.50, 0.20, 1.00)),
                  L=((0.03, -0.18, 0.95), (0.50, 0.20, 1.00))),
    "wave": dict(yaw=150, look=(0, 0, 1.15), frame=1.35, turn=-45,
                 R=((-0.34, -0.12, 1.40), (-0.50, 0.10, 0.85)),
                 L=None),
}


def main(av):
    a = args(av, 0, [("--pose", dict(choices=list(POSES), required=True))])
    p = POSES[a.pose]
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, 15)
    for side in ("R", "L"):
        if p[side]:
            grip(rig, side, Vector(p[side][0]), Vector(p[side][1]))
            for f in range(2, 6):
                for j in range(1, 4):
                    rig.pose.bones[f"finger{f}-{j}.{side}"].rotation_euler = (math.radians(20), 0, 0)
    human.relax_hands(rig)
    head = rig.pose.bones.get("head")
    if head is not None:
        head.rotation_mode = "XYZ"
        # 首をかしげる（tilt）、振り返る（turn）
        head.rotation_euler = (0, math.radians(p.get("turn", 0)), math.radians(p.get("tilt", 0)))
    check(rig)
    yaw = a.yaw if a.yaw else p["yaw"]
    shoot(a.out, h, [], a.width, a.height, yaw, Vector(p["look"]), p["frame"], 0.35)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main(argv())
