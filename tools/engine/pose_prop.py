"""人形に長い道具を肩へ担がせた姿勢を描き、画像生成の下絵にする。

言葉だけで「大きなスパナを右肩に担ぐ」と頼むと、数と大きさは寄せられたが、手と柄のつながり
（どの手がどこを握り、柄がどこに載るか）が6枚とも崩れた。手と物の位置は立体で先に決めておき、
絵の生成にはその形を下絵として渡す。

腕は IK（手先の位置を決めると、肘と肩の曲げを逆算する仕組み）で動かす。骨を1本ずつ回すと、
手が柄に届く角度を探すのに試行が要るため。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_prop.py <out.png> [--length 1.5] [--width 832] [--height 1216]
"""
import argparse
import glob
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import human  # noqa: E402

# 人形の座標: 前は -Y、右手は -X、身長はおよそ 1.7
HAND = Vector((-0.20, -0.16, 1.36))   # 右手を置く所。右肩の前、鎖骨より少し下
SHOULDER = Vector((-0.17, 0.0, 1.46))  # 柄が載る所。右肩の上
SKIN, CLOTH = (240, 200, 170), (235, 120, 40)  # 下絵の色。設定資料の肌とつなぎに合わせる
CAMERA = Vector((-3.55, -3.15, 1.45))  # 正面から右手側へ回った目の高さ
CURL = 70  # 指の関節ごとの曲げ（度）
ELBOW_POLE = Vector((-0.45, -0.10, 1.00))  # 肘を外へ下ろす向き


def empty(name, at):
    e = bpy.data.objects.new(name, None)
    e.location = at
    bpy.context.scene.collection.objects.link(e)
    return e


def grip_right_hand(rig):
    """右手を HAND へ。肩から手首までの4本を一続きの腕として IK で曲げる。"""
    target, pole = empty("hand_target", HAND), empty("elbow_pole", ELBOW_POLE)
    c = rig.pose.bones["lowerarm02.R"].constraints.new("IK")
    c.target, c.pole_target, c.chain_count = target, pole, 4
    c.pole_angle = math.radians(-90)
    # 指を握りの形に曲げる。開いたままの手は、柄に添えているだけに見えた
    for f in range(2, 6):
        for j in range(1, 4):
            b = rig.pose.bones[f"finger{f}-{j}.R"]
            b.rotation_mode = "XYZ"
            b.rotation_euler = (math.radians(CURL), 0, 0)
    for j in (2, 3):
        b = rig.pose.bones[f"finger1-{j}.R"]
        b.rotation_mode = "XYZ"
        b.rotation_euler = (math.radians(CURL * 0.6), 0, 0)
    bpy.context.view_layer.update()


def palm(rig):
    """手のひらの中心（手首と中指の付け根の中ほど）。柄はここを通す。"""
    m = rig.matrix_world
    return (m @ rig.pose.bones["wrist.R"].head + m @ rig.pose.bones["finger3-1.R"].head) / 2


def box(name, size, at, along):
    """along の向きに長辺を合わせた直方体。"""
    bpy.ops.mesh.primitive_cube_add(size=1, location=at)
    o = bpy.context.object
    o.name = name
    o.scale = size
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(along)
    return o


def wrench(length, grip):
    """柄を手から肩の上へ通し、口（開いたあご）を背中側の上に出す。手より下には柄尻を少し残す。"""
    along = (SHOULDER - grip).normalized()
    butt = grip - along * 0.18
    parts = []
    bpy.ops.mesh.primitive_cylinder_add(radius=0.028, depth=length, location=butt + along * length / 2)
    shaft = bpy.context.object
    shaft.rotation_mode = "QUATERNION"
    shaft.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(along)
    parts.append(shaft)
    # 柄尻は丸く止める。端を切りっぱなしにすると、反対の端にも口を描かれ両口スパナになった
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.045, location=butt)
    parts.append(bpy.context.object)
    tip = butt + along * length
    # 頭の面はカメラに向ける。横から見える向きだと頭が細い板に写り、口が読めなかった
    view = (CAMERA - tip).normalized()
    side = along.cross(view - along * view.dot(along)).normalized()  # 口の幅の向き
    # 頭は円盤から口の溝を切り抜いた平らな形にする。箱を組んだ口は刃・フォーク・鉤として描かれた
    normal = along.cross(side).normalized()
    bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=0.06, location=tip + along * 0.05)
    head = bpy.context.object
    head.rotation_mode = "QUATERNION"
    head.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(normal)
    slot = box("slot", (0.13, 0.3, 0.3), tip + along * 0.2, along)
    q = slot.rotation_quaternion
    slot.rotation_quaternion = (q @ Vector((1, 0, 0))).rotation_difference(side) @ q
    cut = head.modifiers.new("slot", "BOOLEAN")
    cut.operation, cut.object = "DIFFERENCE", slot
    bpy.context.view_layer.objects.active = head
    bpy.ops.object.modifier_apply(modifier="slot")
    bpy.data.objects.remove(slot)
    parts.append(head)
    return parts


def tinted(name, rgb):
    m = human.flat_material(name, rgb, False)
    m.node_tree.nodes["Diffuse BSDF"].inputs["Color"].default_value = (*[(c / 255) ** 2.2 for c in rgb], 1)
    return m


def look_from(scene, at, frm, height):
    cam = bpy.data.cameras.new("cam")
    cam.type = "ORTHO"
    cam.ortho_scale = height
    co = bpy.data.objects.new("cam", cam)
    scene.collection.objects.link(co)
    co.location = frm
    co.rotation_mode = "QUATERNION"
    co.rotation_quaternion = (at - frm).to_track_quat("-Z", "Y")
    scene.camera = co


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--length", type=float, default=1.5)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    a = ap.parse_args(argv)
    human.setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    macro = TargetService.get_default_macro_info_dict()
    macro["gender"] = 1.0
    h = HumanService.create_human(macro_detail_dict=macro)
    HumanService.add_builtin_rig(h, "default")
    # 裸の人形は下絵にしない。作業着に近い一揃いを着せ、体の線を絵に持ち込まない
    clothed = []
    for name in ("male_worksuit01", "shoes01"):
        found = glob.glob(str(human.MPFB_DATA / "clothes" / name / "*.mhclo"))
        if found:
            before = set(bpy.data.objects)
            HumanService.add_mhclo_asset(found[0], h, asset_type="Clothes", subdiv_levels=0)
            clothed += [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    human.lower_arms(rig, 60)
    grip_right_hand(rig)
    parts = wrench(a.length, palm(rig))

    scene = bpy.context.scene
    # 正面から右手側へ 35 度回った目の高さ。担いだ柄と口が体に隠れない
    look_from(scene, Vector((-0.35, 0.45, 1.2)), CAMERA, 3.0)
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 3.5
    so = bpy.data.objects.new("sun", sun)
    scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(50), 0, math.radians(-40))
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0.35, 0.35, 0.35)
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = a.width, a.height
    # 下絵は設定の色で塗る。白い人形のまま描き換えを弱めると、白がそのまま服の色として残った
    human.assign([h], tinted("skin", SKIN))
    human.assign(clothed, tinted("cloth", CLOTH))
    metal = human.flat_material("metal", (90, 90, 90), False)
    metal.node_tree.nodes["Diffuse BSDF"].inputs["Color"].default_value = (0.15, 0.15, 0.17, 1)
    human.assign(parts, metal)
    scene.render.filepath = os.path.abspath(a.out)
    bpy.ops.render.render(write_still=True)
    # 生成の下絵は白地にする（透明のままだと黒地として読まれる）
    from PIL import Image
    im = Image.open(a.out).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    bg.convert("RGB").save(a.out)


if __name__ == "__main__":
    main(sys.argv[1:])
