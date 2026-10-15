"""人形を、両腕を体の脇に下ろし、手を開いて指を少し広げた立ち姿で撮り、形の下絵（奥行き）にする。

言葉だけで全身の立ち姿を描くと、手が小さく握られる・袖や腰の後ろに隠れる・指が溶けて数えられない、が続いた
（2026-10-14〜15 の夜、checker に回した4枚すべてが手で戻った）。後から手だけを描き直しても指は数えられる形に
ならなかった。手の位置と開き方を立体で先に決め、奥行きで縛って描く（剣の持ち方で効いた方法と同じ）。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_stand.py <depth.png> [--width 832] [--height 1216] [--yaw 0]
"""
import math

import bpy
from mathutils import Vector

from pose_depth import args, argv, check, mannequin, shoot

SPREAD = 8   # 指を互いに離す角度（度）。0 だと指が1枚の板に見え、絵でも指が溶けた


def open_hands(rig):
    """指をまっすぐ伸ばし、人差し指から小指を扇に少し広げる"""
    for side, sign in (("L", 1), ("R", -1)):
        for f, k in zip(range(2, 6), (-1.5, -0.5, 0.5, 1.5)):
            b = rig.pose.bones[f"finger{f}-1.{side}"]
            b.rotation_mode = "XYZ"
            b.rotation_euler = (0, 0, math.radians(SPREAD * k * sign))


def main(av):
    a = args(av, 0, [("--adduct", dict(type=float, default=35, help="腕を体の脇へ寄せる角度（度）"))])
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, a.adduct)
    open_hands(rig)
    check(rig)
    shoot(a.out, h, [], a.width, a.height, a.yaw, Vector((0, 0, 0.88)), 2.05, 0.35)


if __name__ == "__main__":
    main(argv())
