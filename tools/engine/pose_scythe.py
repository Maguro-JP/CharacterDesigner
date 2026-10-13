"""人形に大鎌を両手で持たせた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「大鎌を両手で」と頼むと、大きな斧の形の刃になった（武器 8 種の描き分け、2026-10-13）。
柄と刃の形、両手の位置を立体で先に決め、絵の生成には奥行きだけを渡す（ControlNet）。

柄は体の右前でほぼ縦に立て、右手は柄の上の方、左手は下の方を握る。
刃は柄の上端から頭の上を越えて反対の側へ、弧を描いて下向きに伸びる。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_scythe.py <depth.png> [--width 832] [--height 1216] [--yaw 15]
"""
import argparse
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import human  # noqa: E402
from pose_prop import look_from  # noqa: E402
from pose_sword import depth_material, grip  # noqa: E402

# 人形の座標: 前は -Y、右手は -X、左手は +X、身長はおよそ 1.7
FOOT = Vector((-0.20, -0.30, 0.02))        # 柄の下端（床、右足の前）
TOP = Vector((-0.36, -0.30, 1.78))         # 柄の上端（頭より少し上、右）
RIGHT_AT, LEFT_AT = 0.70, 0.55             # 右手・左手が柄のどこを握るか（下端 0 〜 上端 1）
BLADE = 0.75                               # 刃の長さ


def rod(a, b, radius):
    """a から b へ伸びる細い円柱（弦・矢）"""
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=d.length, location=(a + b) / 2)
    o = bpy.context.object
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = d.to_track_quat("Z", "Y")
    return o


def scythe():
    shaft = TOP - FOOT
    parts = [rod(FOOT, TOP, 0.018)]
    out = Vector((1.0, 0, 0))     # 刃は柄の上端から頭の上を越えて左へ伸びる（大鎌の見分けが付く形）。左手が届くよう柄は体に寄せる（肩から 0.8 離すと届かなかった）
    tip = TOP + out * BLADE + Vector((0, 0, -0.35))
    curve = bpy.data.curves.new("blade", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.03
    sp = curve.splines.new("BEZIER")
    sp.bezier_points.add(2)
    mid = TOP + out * (BLADE * 0.55) + Vector((0, 0, 0.05))
    for p, at in zip(sp.bezier_points, (TOP, mid, tip)):
        p.co = at
        p.handle_left_type = p.handle_right_type = "AUTO"
    o = bpy.data.objects.new("blade", curve)
    bpy.context.scene.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    o = bpy.context.object
    o.scale = (1.0, 0.35, 1.0)        # 刃は薄い
    parts.append(o)
    return parts


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--yaw", type=float, default=15, help="正面から右手側へ回り込む角度（度）")
    ap.add_argument("--right-angle", type=float, default=-90, help="右腕の IK の pole_angle（度）")
    ap.add_argument("--left-angle", type=float, default=-90, help="左腕の IK の pole_angle（度）")
    a = ap.parse_args(argv)
    human.setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    macro = TargetService.get_default_macro_info_dict()
    macro["gender"] = 0.0
    h = HumanService.create_human(macro_detail_dict=macro)
    HumanService.add_builtin_rig(h, "default")
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    shaft = TOP - FOOT
    grip(rig, "R", FOOT + shaft * RIGHT_AT, Vector((-0.55, 0.05, 1.10)), a.right_angle)
    grip(rig, "L", FOOT + shaft * LEFT_AT, Vector((0.45, 0.05, 0.95)), a.left_angle)
    bpy.context.view_layer.update()
    import rom_check
    bad = rom_check.check_rig(rig)
    print("可動域:", "外れなし" if not bad else "; ".join(bad))
    parts = scythe()

    import math
    scene = bpy.context.scene
    r = 4.8
    yaw = math.radians(a.yaw)
    frm = Vector((-math.sin(yaw) * r, -math.cos(yaw) * r, 1.0))
    look_from(scene, Vector((0.1, 0, 0.95)), frm, 2.2)
    dist = (frm - Vector((0, 0, 0.9))).length
    mat = depth_material(dist - 0.45, dist + 0.45)
    for o in [h] + parts + [c for c in bpy.data.objects if c.type == "MESH"]:
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(mat)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 4
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0, 0, 0)
    scene.render.film_transparent = False
    scene.render.resolution_x, scene.render.resolution_y = a.width, a.height
    scene.render.filepath = os.path.abspath(a.out)
    bpy.ops.render.render(write_still=True)
    print("撮った:", a.out)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
