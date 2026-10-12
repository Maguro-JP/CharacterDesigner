"""人形に剣を両手で握らせ、切っ先を床に付けた姿勢を撮り、形の下絵（奥行き）にする。

言葉だけで「両手で柄を握り、切っ先を床に」と頼むと、描き方を3通り変えても6枚とも守られなかった
（片手持ち、剣が2本、横に突き出す）。手と剣の位置は立体で先に決め、絵の生成には奥行きだけを渡す
（ControlNet）。奥行きは形だけを縛り、色と絵柄は言葉から来る。

腕は IK（手先の位置から肘と肩の曲げを逆算する）で、両手を柄の上下に重ねて置く。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_sword.py <depth.png> [--width 832] [--height 1216] [--yaw 20]
"""
import argparse
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import human  # noqa: E402
from pose_prop import empty, look_from  # noqa: E402

# 人形の座標: 前は -Y、右手は -X、身長はおよそ 1.7
HILT = Vector((0.0, -0.28, 0.88))      # 柄の中ほど。体の正面、腰の高さ（0.98 では柄頭が胸まで来て、柄が長く見えた）
GUARD_Z = 0.76                          # 鍔の高さ。ここから下が刃で、切っ先は床（z=0）
RIGHT_GRIP = HILT + Vector((0, 0, 0.05))   # 右手は柄の上（鍔から遠い側）
LEFT_GRIP = HILT + Vector((0, 0, -0.05))   # 左手はその下、鍔の近く
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


def sword():
    parts = []
    # 柄（鍔の上 0.26）
    bpy.ops.mesh.primitive_cylinder_add(radius=0.022, depth=0.26, location=(HILT.x, HILT.y, GUARD_Z + 0.13))
    parts.append(bpy.context.object)
    # 柄頭
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.035, location=(HILT.x, HILT.y, GUARD_Z + 0.27))
    parts.append(bpy.context.object)
    # 鍔: 横に長い板
    bpy.ops.mesh.primitive_cube_add(size=1, location=(HILT.x, HILT.y, GUARD_Z))
    g = bpy.context.object
    g.scale = (0.28, 0.04, 0.03)
    parts.append(g)
    # 刃: 鍔から床まで。切っ先へ細くなる
    bpy.ops.mesh.primitive_cone_add(radius1=0.035, radius2=0.004, depth=GUARD_Z, vertices=4,
                                    location=(HILT.x, HILT.y, GUARD_Z / 2))
    b = bpy.context.object
    b.rotation_euler = (math.pi, 0, math.radians(45))
    b.scale = (1.0, 0.25, 1.0)
    parts.append(b)
    return parts


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


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--yaw", type=float, default=20, help="正面から右手側へ回り込む角度（度）")
    ap.add_argument("--left-pole", default="0.45,-0.05,1.05", help="左肘を引き寄せる点（x,y,z）")
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
    human.adduct_arms(rig, 35)
    grip(rig, "R", RIGHT_GRIP, Vector((-0.45, -0.05, 1.05)))
    grip(rig, "L", LEFT_GRIP, Vector([float(v) for v in a.left_pole.split(",")]), a.left_angle)
    bpy.context.view_layer.update()
    import rom_check
    bad = rom_check.check_rig(rig)
    print("可動域:", "外れなし" if not bad else "; ".join(bad))
    parts = sword()

    scene = bpy.context.scene
    r = 4.8
    yaw = math.radians(a.yaw)
    frm = Vector((-math.sin(yaw) * r, -math.cos(yaw) * r, 1.0))
    look_from(scene, Vector((0, 0, 0.88)), frm, 2.05)
    dist = (frm - Vector((0, 0, 0.9))).length
    # 体の厚みは 0.4m ほどしかない。幅を広く取ると体全体が同じ灰色になり、奥行きの差が下絵に出なかった
    mat = depth_material(dist - 0.35, dist + 0.35)
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
