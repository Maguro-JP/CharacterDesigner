"""人形に弓を引かせた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「弓を持った冒険者」を頼むと、弓が描かれず矢筒だけが出た（武器 8 種の描き分け、2026-10-13）。
弓・弦・矢と両手の位置を立体で先に決め、絵の生成には奥行きだけを渡す（ControlNet）。

左手（弓手）は肩の高さで横へ伸ばして弓の握りを持ち、右手（引き手）は弦を頬まで引く。
弓は握りを中心に縦に立て、上下の端（弓の先）は射手の側へ反る。弦は両端から右手へ張る。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_bow.py <depth.png> [--width 832] [--height 1216] [--yaw 15]
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

# 人形の座標: 前は -Y、右手は -X、左手は +X、身長はおよそ 1.7（肩の高さ 1.40 前後、あご 1.50 前後）
BOW_HAND = Vector((0.62, -0.18, 1.38))     # 左手: 肩の高さで左へ伸ばし、少し前へ
DRAW_HAND = Vector((-0.06, -0.10, 1.47))   # 右手: 弦を右の頬の横まで引く
LIMB = 0.52                                # 握りから弓の先までの高さ
BEND = 0.16                                # 弓の先が射手の側へ反る量


def rod(a, b, radius):
    """a から b へ伸びる細い円柱（弦・矢）"""
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=d.length, location=(a + b) / 2)
    o = bpy.context.object
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = d.to_track_quat("Z", "Y")
    return o


def bow():
    aim = (BOW_HAND - DRAW_HAND).normalized()          # 矢の向き（引き手から弓手へ）
    top = BOW_HAND - aim * BEND + Vector((0, 0, LIMB))
    bottom = BOW_HAND - aim * BEND - Vector((0, 0, LIMB))
    curve = bpy.data.curves.new("bow", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.014
    sp = curve.splines.new("BEZIER")
    sp.bezier_points.add(2)
    for p, at in zip(sp.bezier_points, (top, BOW_HAND, bottom)):
        p.co = at
        p.handle_left_type = p.handle_right_type = "AUTO"
    o = bpy.data.objects.new("bow", curve)
    bpy.context.scene.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    parts = [bpy.context.object]
    parts.append(rod(top, DRAW_HAND, 0.003))            # 弦（上）
    parts.append(rod(bottom, DRAW_HAND, 0.003))         # 弦（下）
    parts.append(rod(DRAW_HAND, BOW_HAND + aim * 0.12, 0.006))   # 矢: 弓の握りから少し先へ出る
    return parts


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--yaw", type=float, default=15, help="正面から右手側へ回り込む角度（度）")
    ap.add_argument("--draw-angle", type=float, default=0, help="引き手の IK の pole_angle（度）。0 で肘が肩の高さで横へ張る（90 は肘が頭の後ろ、180 は肩が 119 度ねじれた）")
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
    # 弓手は伸ばしきる。肘を引く点は下の外側に置き、肘がわずかに下へ逃げるようにする
    grip(rig, "L", BOW_HAND, Vector((0.45, 0.10, 0.95)))
    # 引き手の肘は肩の高さで、矢の線の延長（弓と反対の横）へ張る。肘を引く点を後ろの高い所に置くと、腕が頭の上を回った
    grip(rig, "R", DRAW_HAND, Vector((-0.60, -0.02, 1.42)), a.draw_angle)
    bpy.context.view_layer.update()
    import rom_check
    bad = rom_check.check_rig(rig)
    print("可動域:", "外れなし" if not bad else "; ".join(bad))
    parts = bow()

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
