"""体のつくりが人と違う種族の形の下絵（奥行き）を、人形に部品を足して撮る。

ケンタウロスやハーピーは、言葉だけでは人の脚・人の腕で描かれた（夜間の一枚、docs/knowledge/demihuman-anatomy.md）。
人の部分は人形のまま、人と違う部分（馬の胴と 4 本の脚、翼の腕と鳥の脚）を立体で足し、絵の生成には奥行きだけを渡す（ControlNet）。

centaur: 人形の脚を縮めて隠し、腰の後ろに馬の胴（楕円の塊）、前後 2 本ずつの脚、尾を付ける。人の上半身は馬の胸の上に立つ
harpy:   人形の両腕を横へ広げ、腕に沿って羽を垂らす。足の先に鉤爪を足す
arachne: 人形の脚を縮めて隠し、腰の下に蜘蛛の頭胸部と腹部、左右 4 本ずつの脚を付ける

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_demi.py <depth.png> --kind centaur [--width 1216] [--height 832] [--yaw 60]
"""
import bpy
from mathutils import Vector

from pose_depth import args, argv, check, curve_mesh, grip, mannequin, rod, shoot


def ellipsoid(center, size):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=center, segments=24, ring_count=12)
    o = bpy.context.object
    o.scale = size
    return o


def hide_legs(rig):
    """人の脚を腰の付け根で縮める（骨の大きさを 0.02 倍）。馬の胴の中に隠れる"""
    for side in ("L", "R"):
        b = rig.pose.bones[f"upperleg01.{side}"]
        b.scale = (0.02, 0.02, 0.02)
    bpy.context.view_layer.update()


def centaur(lift):
    """馬の胴は人の腰（休みの姿勢で z 0.83）の後ろ下に置く。前が -Y なので、胴は +Y へ伸ばす"""
    hip = 0.83 + lift
    body = Vector((0, 0.55, hip - 0.20))
    parts = [ellipsoid(body, (0.32, 0.75, 0.33)),                                 # 馬の胴
             ellipsoid(Vector((0, -0.02, hip - 0.12)), (0.24, 0.26, 0.28))]       # 人の腰と馬の胸のつなぎ
    for y in (0.0, 1.05):                                                         # 前脚・後脚
        for sx in (-1, 1):
            top = Vector((sx * 0.17, y, hip - 0.35))
            knee = Vector((sx * 0.18, y + (0.05 if y == 0 else -0.08), hip - 0.75))
            hoof = Vector((sx * 0.18, y, 0.04))
            parts += [rod(top, knee, 0.075), rod(knee, hoof, 0.05)]
            parts.append(ellipsoid(hoof + Vector((0, -0.02, 0.0)), (0.07, 0.09, 0.05)))   # 蹄
    parts.append(curve_mesh("tail", (body + Vector((0, 0.72, 0.15)), body + Vector((0, 0.95, -0.05)),
                                     body + Vector((0, 1.00, -0.45))), 0.06))          # 尾
    return parts


def harpy(rig):
    """腕を横へ広げ、肩から手の先の外まで翼の板を付ける。板は腕の下へ垂れる（風切り羽）。足先に前 3 本・後ろ 1 本の鉤爪"""
    parts = []
    m = rig.matrix_world
    for side, sx in (("L", 1), ("R", -1)):
        sh = m @ rig.pose.bones[f"upperarm01.{side}"].head
        hand = m @ rig.pose.bones[f"wrist.{side}"].tail if f"wrist.{side}" in rig.pose.bones else m @ rig.pose.bones[f"lowerarm02.{side}"].tail
        tip = hand + (hand - sh).normalized() * 0.45
        span = tip - sh
        for k in range(7):                      # 羽を 7 枚並べ、先ほど長く垂らす
            t = (k + 0.5) / 7
            root = sh + span * t + Vector((0, 0.04, 0))
            length = 0.35 + 0.45 * t
            parts.append(rod(root, root + Vector((sx * 0.06 * t, 0.05, -length)), 0.045 + 0.02 * (1 - t)))
        parts.append(rod(sh, tip, 0.05))       # 翼の前の縁
        foot = m @ rig.pose.bones[f"foot.{side}"].tail
        for dx, dy in ((-0.05, -0.10), (0.0, -0.12), (0.05, -0.10), (0.0, 0.08)):
            parts.append(rod(foot, foot + Vector((dx, dy, -0.03)), 0.015))     # 鉤爪
    return parts


def arachne(lift):
    """人の腰の下に蜘蛛の頭胸部、その後ろに大きな腹部。脚 8 本は頭胸部から左右 4 本ずつ、膝を高く上げて外へ広げ、先を床に着ける"""
    import math
    hip = 0.83 + lift
    ceph = Vector((0, 0.05, hip - 0.18))
    parts = [ellipsoid(ceph, (0.30, 0.34, 0.20)),                                 # 頭胸部（人の腰とつながる）
             ellipsoid(Vector((0, 0.70, hip - 0.05)), (0.42, 0.55, 0.38))]       # 腹部
    for sx in (-1, 1):
        for k, ang in enumerate((-50, -15, 15, 50)):                            # 前から後ろへ 4 本
            a = math.radians(ang)
            root = ceph + Vector((sx * 0.22, 0.15 * math.sin(a), 0))
            out = Vector((sx * math.cos(a), math.sin(a), 0))
            # 脚を長く広げると蜘蛛が絵の大半を占め、人の上半身が消えた（2 回）。外への広がりを 0.7 倍にする
            knee = root + out * 0.40 + Vector((0, 0, 0.28))   # 0.50 に上げると脚が金属の柱、胴が布になった（4 回目）
            foot = root + out * 0.75 + Vector((0, 0, -(hip - 0.18)))
            foot.z = 0.03
            parts += [rod(root, knee, 0.045), rod(knee, foot, 0.035)]
    return parts


def main(av):
    a = args(av, 60, [("--kind", dict(default="centaur", choices=["centaur", "harpy", "arachne"], help="種族"))])
    h, rig = mannequin()
    if a.kind == "harpy":
        import human
        human.adduct_arms(rig, -40)            # 休みの姿勢（下へ約 48 度）から上げて、腕を横へ広げる
        check(rig)
        # 正面に近い向き（15 度）から撮ると、左右の翼が重ならない
        shoot(a.out, h, harpy(rig), a.width, a.height, 15 if a.yaw == 60 else a.yaw, Vector((0, 0, 1.0)), 3.6, 0.8)
    if a.kind == "arachne":
        lift = 0.40                                      # 蜘蛛の脚の膝の高さの分だけ持ち上げる
        rig.location.z += lift
        bpy.context.view_layer.update()
        hide_legs(rig)
        import human
        human.adduct_arms(rig, 35)
        check(rig)
        # 斜め前（35 度）から、人の上半身に寄せて撮る。縦長（832x1216）では長い辺の縦に 2.4 が掛かる
        shoot(a.out, h, arachne(lift), a.width, a.height, 35 if a.yaw == 60 else a.yaw, Vector((0, 0.2, 1.15)), 2.4, 1.0)
    lift = 0.55                                          # 馬の脚の分だけ人形を持ち上げる
    rig.location.z += lift
    bpy.context.view_layer.update()
    hide_legs(rig)
    import human
    human.adduct_arms(rig, 35)
    check(rig)
    # 横に近い向き（60 度）から撮ると、馬の胴と 4 本の脚の前後が重ならない
    shoot(a.out, h, centaur(lift), a.width, a.height, a.yaw, Vector((0, 0.45, 1.15)), 3.4, 1.0)


if __name__ == "__main__":
    main(argv())
