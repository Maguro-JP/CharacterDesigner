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

REST_FOOT_Z = 0.055  # 立った人形の足首の高さ（m）。傾けた後に低い方の足をこの高さへ戻す
SPREAD = 8   # 指を互いに離す角度（度）。0 だと指が1枚の板に見え、絵でも指が溶けた


def open_hands(rig):
    """指をまっすぐ伸ばし、人差し指から小指を扇に少し広げる"""
    for side, sign in (("L", 1), ("R", -1)):
        for f, k in zip(range(2, 6), (-1.5, -0.5, 0.5, 1.5)):
            b = rig.pose.bones[f"finger{f}-1.{side}"]
            b.rotation_mode = "XYZ"
            b.rotation_euler = (0, 0, math.radians(SPREAD * k * sign))


def curl_hands(rig, deg):
    """力を抜いて下ろした手の形にする。指の各関節を同じ角度だけ内へ曲げ、親指は半分だけ曲げる。
    開いて伸ばした手は、全身の大きさでは指が板に溶けた（周15）"""
    for side in ("L", "R"):
        for f in range(1, 6):
            for j in (1, 2, 3):
                n = f"finger{f}-{j}.{side}"
                if n in rig.pose.bones:
                    b = rig.pose.bones[n]
                    b.rotation_mode = "XYZ"
                    x, y, z = b.rotation_euler
                    b.rotation_euler = (x + math.radians(deg * (0.5 if f == 1 else 1)), y, z)


def contrapposto(rig, deg):
    """左足に体重を載せる。骨盤を傾け、胸と首を逆へ傾けて肩と腰の線を逆向きにし、右膝を緩める。
    両足を伸ばしたまま並べると、肩と腰が水平な棒立ちになり、絵でも硬く見えた（周7の検品）"""
    def rot(name, x=0.0, y=0.0, z=0.0):
        b = rig.pose.bones[name]
        b.rotation_mode = "XYZ"
        b.rotation_euler = (math.radians(x), math.radians(y), math.radians(z))
    rot("root", y=deg)                   # 骨盤を傾ける（骨盤の横倒しは root の y。z はねじれになった）
    rot("upperleg01.L", z=deg)           # 両脚を骨盤と逆へ戻し、足を首の下の左右に置く
    rot("upperleg01.R", x=-6, z=deg)
    rot("lowerleg01.R", x=28)            # 遊ぶ脚の膝を緩め、かかとを浮かせる
    import bpy
    bpy.context.view_layer.update()
    foot = min((rig.matrix_world @ rig.pose.bones[f"foot.{s}"].head).z for s in ("L", "R"))
    rig.pose.bones["root"].location = (0, 0, 0)
    rig.location.z -= foot - REST_FOOT_Z   # 低い方の足を床へ戻す（傾けると体が浮いた）
    rot("spine03", z=-deg * 2)          # 胸を骨盤と逆へ傾ける（この骨の横倒しは z。y では肩が骨盤と同じ向きに傾いた）
    rot("neck01", z=deg * 0.8)           # 頭は肩と逆へ少し戻す


def main(av):
    a = args(av, 0, [("--adduct", dict(type=float, default=35, help="腕を体の脇へ寄せる角度（度）")),
                     ("--twist", dict(type=float, default=0, help="上腕をねじる角度（度）。手のひらを前へ向ける")),
                     ("--hand", dict(default="", help="L か R。その手だけを大きく撮る（手の測り方の較正用）")),
                     ("--curl", dict(type=float, default=0, help="指を軽く曲げる角度（度、関節ごと）。0 なら開いた手")),
                     ("--contra", dict(type=float, default=0, help="片足に体重を載せる立ち方（コントラポスト）の腰の傾き（度）"))])
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, a.adduct)
    if a.twist:
        human.lower_arms(rig, a.twist)
    open_hands(rig)
    if a.curl:
        curl_hands(rig, a.curl)
    if a.contra:
        contrapposto(rig, a.contra)
    check(rig)
    if a.hand:
        b = rig.pose.bones[f"wrist.{a.hand}"] if f"wrist.{a.hand}" in rig.pose.bones else rig.pose.bones[f"hand.{a.hand}"]
        at = rig.matrix_world @ b.tail
        shoot(a.out, h, [], a.width, a.height, a.yaw, Vector(at), 0.32, 0.15)
    shoot(a.out, h, [], a.width, a.height, a.yaw, Vector((0, 0, 0.88)), 2.05, 0.35)


if __name__ == "__main__":
    main(argv())
