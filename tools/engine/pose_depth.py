"""姿勢の下絵（奥行き）を撮る人形の共通部品。剣・弓・大鎌の台本（pose_sword.py ほか）が使う。

人形（MPFB の女性の素体）を作り、両手を IK（手先の位置から肘と肩の曲げを逆算する仕組み）で持ち物へ置き、
可動域の検査（rom_check）を通してから、カメラからの距離を白（近い）〜黒（遠い）に塗って撮る。
"""
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import human  # noqa: E402
from pose_prop import empty, look_from  # noqa: E402

CURL = 75


def grip(rig, side, at, pole_at, pole_angle=-90):
    t, p = empty(f"hand_{side}", at), empty(f"pole_{side}", pole_at)
    c = rig.pose.bones[f"lowerarm02.{side}"].constraints.new("IK")
    c.target, c.pole_target, c.chain_count = t, p, 4
    c.pole_angle = math.radians(pole_angle)
    for f in range(2, 6):
        for j in range(1, 4):
            b = rig.pose.bones[f"finger{f}-{j}.{side}"]
            b.rotation_mode = "XYZ"
            b.rotation_euler = (math.radians(CURL), 0, 0)
    for j in (2, 3):
        b = rig.pose.bones[f"finger1-{j}.{side}"]
        b.rotation_mode = "XYZ"
        b.rotation_euler = (math.radians(CURL * 0.6), 0, 0)


def rod(a, b, radius):
    """a から b へ伸びる細い円柱（弦・矢）"""
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=d.length, location=(a + b) / 2)
    o = bpy.context.object
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = d.to_track_quat("Z", "Y")
    return o


def curve_mesh(name, points, bevel):
    """点を通るなめらかな曲線に太さを付けた形（弓の弧、大鎌の刃）"""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = bevel
    sp = curve.splines.new("BEZIER")
    sp.bezier_points.add(len(points) - 1)
    for p, at in zip(sp.bezier_points, points):
        p.co = at
        p.handle_left_type = p.handle_right_type = "AUTO"
    o = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    return bpy.context.object


def mannequin():
    """女性の素体と骨組みを作り、(素体, 骨組み) を返す"""
    human.setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    macro = TargetService.get_default_macro_info_dict()
    macro["gender"] = 0.0
    h = HumanService.create_human(macro_detail_dict=macro)
    HumanService.add_builtin_rig(h, "default")
    return h, next(o for o in bpy.data.objects if o.type == "ARMATURE")


def check(rig):
    bpy.context.view_layer.update()
    import rom_check
    bad = rom_check.check_rig(rig)
    print("可動域:", "外れなし" if not bad else "; ".join(bad))
    return bad


def depth_material(near, far):
    """カメラからの距離を白（近い）〜黒（遠い）に塗る。ControlNet の奥行きの下絵と同じ向き"""
    m = bpy.data.materials.new("depth")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    cam = nt.nodes.new("ShaderNodeCameraData")
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = near, far
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 1.0, 0.0
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(cam.outputs["View Z Depth"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def shoot(out, h, parts, width, height, yaw_deg, look_at, frame, depth, done=True):
    """正射影のカメラで、正面から右手側へ yaw_deg 回り込んで撮る。frame は写す縦の長さ、depth は奥行きの白黒を付ける幅（前後）"""
    scene = bpy.context.scene
    r = 4.8
    yaw = math.radians(yaw_deg)
    frm = Vector((-math.sin(yaw) * r, -math.cos(yaw) * r, 1.0))
    look_from(scene, look_at, frm, frame)
    dist = (frm - Vector((0, 0, 0.9))).length
    mat = depth_material(dist - depth, dist + depth)
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
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("撮った:", out)
    sys.stdout.flush()
    if done:  # 撮ったあとに続きのある台本（pose_bvh の棚置き）は done=False で戻る
        os._exit(0)


def args(argv, yaw, extra=()):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--yaw", type=float, default=yaw, help="正面から右手側へ回り込む角度（度）")
    for name, kw in extra:
        ap.add_argument(name, **kw)
    return ap.parse_args(argv)


def argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
