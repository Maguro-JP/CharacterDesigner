"""人形の下ろした手だけを、指を離して開いた形で大きく撮り、奥行きの下絵にする（片手ずつ）。

絵の手の枠だけを描き直すとき、ControlNet の奥行きで指の本数と離れ方を縛るために使う。
骨組みの手の 21 点や、検品を通った手の移植では、下ろした手が指の分かれない塊になった（羊娘のポーズ）。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_hand.py <depth.png> --side L [--spread 14 --curl 10]
写る向きは正面から（yaw 0）。手首が上、指先が下。手の長さが絵の縦の約 7 割になるよう写す
"""
import os
import sys

import bpy  # noqa: F401
from mathutils import Vector

from pose_depth import args, argv, check, mannequin, shoot


def main(av):
    a = args(av, 0, [("--side", dict(choices=["L", "R"], required=True)),
                     ("--spread", dict(type=float, default=14.0)), ("--twist", dict(type=float, default=0.0)), ("--curl", dict(type=float, default=10.0))])
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, 15)
    human.relax_hands(rig, curl=a.curl, spread=a.spread)
    # 前腕をひねって手のひらか手の甲をカメラへ向ける。横向きのままでは指が重なり、奥行きでも 1 つの塊になった
    import math
    for b in (f"lowerarm01.{a.side}", f"lowerarm02.{a.side}"):
        pb = rig.pose.bones[b]
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, math.radians(a.twist / 2), 0)
    check(rig)
    bpy.context.view_layer.update()
    m = rig.matrix_world
    wrist = m @ rig.pose.bones[f"wrist.{a.side}"].head
    tip = m @ rig.pose.bones[f"finger3-3.{a.side}"].tail
    center = (wrist + tip) / 2
    frame = (wrist - tip).length / 0.7
    print("手首", tuple(round(v, 3) for v in wrist), "指先", tuple(round(v, 3) for v in tip))
    sys.stdout.flush()
    shoot(a.out, h, [], a.width, a.height, a.yaw, Vector(center), frame, 0.6)
    os._exit(0)


if __name__ == "__main__":
    main(argv())
