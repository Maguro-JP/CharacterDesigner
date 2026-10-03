"""MakeHuman の人体を Blender で作り、箱庭ドットの頭身に縮めて、見下ろしの角度から描く。

手描きの部品だけで体を組むと、顔の長さや髪の大きさが人間の比率から外れた。人体の形は
MakeHuman（体型を数字で変えられる人体モデル、素材は CC0）に任せ、頭身の縮め方と描き方だけを決める。
骨で脚を縮めると足が浮いて腰が沈んだので、頂点を高さで区切って伸縮する（描画器の transforms と同じ考え方）。

描き出すのは2枚。ドットへの変換は tools/engine/topixel.py が今の描画器の後半（build.finish）で行う。
  <out>.id.png    部位ごとに決まった色で塗った絵（光なし、縁のぼかしなし）。どの部位が見えているか
  <out>.light.png 全部位を白で塗って左上から光を当てた絵。明るさ
  <out>.json      部位の名前と塗り分けの色

前準備: sh tools/engine/setup.sh
使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/human.py <out> [--head 2.2] [--leg 0.55]
          [--hair short02] [--clothes male_casualsuit01,shoes01] [--gender 1.0] [--arms 60]
"""
import argparse
import glob
import json
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "engine"
MPFB_DATA = Path.home() / ".config/blender/4.2/extensions/.user/user_default/mpfb/data"

# 塗り分けの色。topixel.py はこの色で部位を見分ける
ID_COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255),
             (128, 0, 0), (0, 128, 0), (0, 0, 128), (128, 128, 0)]


def setup():
    bpy.ops.extensions.package_install_files(filepath=str(CACHE / "mpfb.zip"), repo="user_default",
                                             enable_on_install=True)
    if not (MPFB_DATA / "targets").exists():
        bpy.ops.mpfb.load_pack(filepath=str(CACHE / "sysassets.zip"))


def deform(me, head, leg):
    """首の付け根から上を head 倍、股から下を縦に leg 倍にする。形の鍵（体型の差分）にも同じ変形をかける。"""
    zs = [v.co.z for v in me.vertices]
    top, bot = max(zs), min(zs)
    H = top - bot
    # 写実の比率（頭は身長の 1/7.5、股は下から 0.47）から首の付け根と股の高さを取る
    neck = top - H / 7.5 * 1.15
    crotch = bot + H * 0.47

    def f(co):
        x, y, z = co
        if z > neck:
            return (x * head, y * head, neck + (z - neck) * head)
        if z < crotch:
            return (x, y, crotch - (crotch - z) * leg)
        return (x, y, z)

    blocks = list(me.shape_keys.key_blocks) if me.shape_keys else []
    for kb in blocks:
        for d in kb.data:
            d.co = f(tuple(d.co))
    for v in me.vertices:
        v.co = f(tuple(v.co))
    low = min(v.co.z for v in me.vertices)
    for kb in blocks:
        for d in kb.data:
            d.co.z -= low
    for v in me.vertices:
        v.co.z -= low
    me.update()


def lower_arms(rig, degrees):
    """A の字に開いた腕を体の脇へ下ろす。上腕の骨を Y 軸で左右逆向きに回す（試して決めた軸）。"""
    for side, sign in (("L", 1), ("R", -1)):
        b = rig.pose.bones[f"upperarm01.{side}"]
        b.rotation_mode = "XYZ"
        b.rotation_euler = (0, math.radians(degrees * sign), 0)
    bpy.context.view_layer.update()


def camera(scene, height):
    """箱庭ドットの視点: 正投影、30 度の見下ろし、左向きの 3/4。"""
    cam = bpy.data.cameras.new("cam")
    cam.type = "ORTHO"
    cam.ortho_scale = height * 1.2
    co = bpy.data.objects.new("cam", cam)
    scene.collection.objects.link(co)
    scene.camera = co
    el, az, d = math.radians(30), math.radians(-35), 10
    co.location = (d * math.sin(az) * math.cos(el), -d * math.cos(az) * math.cos(el), height / 2 + d * math.sin(el))
    co.rotation_euler = (math.radians(90) - el, 0, az)


def flat_material(name, rgb, emit):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if emit:
        sh = nt.nodes.new("ShaderNodeEmission")
        sh.inputs["Color"].default_value = (*[c / 255 for c in rgb], 1)
        sh.inputs["Strength"].default_value = 1.0
    else:
        sh = nt.nodes.new("ShaderNodeBsdfDiffuse")
        sh.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1)
    nt.links.new(sh.outputs[0], out.inputs["Surface"])
    return m


def assign(objs, mat):
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(mat)


def render(scene, path, ids):
    if ids:
        # 塗り分けは縁をぼかさない。混ざった色は部位として読めない
        scene.cycles.samples = 1
        scene.cycles.pixel_filter_type = "BOX"
        scene.cycles.filter_width = 0.01
        scene.view_settings.view_transform = "Standard"
        scene.world.use_nodes = False
        scene.world.color = (0, 0, 0)
    else:
        scene.cycles.samples = 32
        scene.cycles.pixel_filter_type = "BLACKMAN_HARRIS"
        scene.cycles.filter_width = 1.5
        scene.view_settings.view_transform = "Standard"
        scene.world.use_nodes = False
        scene.world.color = (0.12, 0.12, 0.12)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--head", type=float, default=2.2)
    ap.add_argument("--leg", type=float, default=0.55)
    ap.add_argument("--hair", default="short02")
    ap.add_argument("--clothes", default="male_casualsuit01,shoes01")
    ap.add_argument("--gender", type=float, default=1.0, help="0 が女性、1 が男性")
    ap.add_argument("--arms", type=float, default=60)
    ap.add_argument("--size", type=int, default=512)
    a = ap.parse_args(argv)
    setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    macro = TargetService.get_default_macro_info_dict()
    macro["gender"] = a.gender
    human = HumanService.create_human(macro_detail_dict=macro)
    deform(human.data, a.head, a.leg)
    HumanService.add_builtin_rig(human, "default")
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    regions = {"skin": [human]}
    if a.hair:
        before = set(bpy.data.objects)
        HumanService.add_mhclo_asset(glob.glob(str(MPFB_DATA / "hair" / a.hair / "*.mhclo"))[0], human,
                                     asset_type="Hair", subdiv_levels=0)
        regions["hair"] = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    for name in filter(None, a.clothes.split(",")):
        before = set(bpy.data.objects)
        HumanService.add_mhclo_asset(glob.glob(str(MPFB_DATA / "clothes" / name / "*.mhclo"))[0], human,
                                     asset_type="Clothes", subdiv_levels=0)
        regions[name] = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    lower_arms(rig, a.arms)

    scene = bpy.context.scene
    zs = [v.co.z for v in human.data.vertices]
    camera(scene, max(zs) - min(zs))
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 4
    so = bpy.data.objects.new("sun", sun)
    scene.collection.objects.link(so)
    # 光は左上から（描画器の LIGHT と同じ向き）
    so.rotation_euler = (math.radians(45), 0, math.radians(-60))
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = a.size
    out = os.path.abspath(a.out)

    names = list(regions)
    for i, n in enumerate(names):
        assign(regions[n], flat_material(f"id_{n}", ID_COLORS[i], True))
    render(scene, out + ".id.png", True)
    white = flat_material("white", (255, 255, 255), False)
    for n in names:
        assign(regions[n], white)
    render(scene, out + ".light.png", False)
    Path(out + ".json").write_text(json.dumps(
        {"regions": {n: list(ID_COLORS[i]) for i, n in enumerate(names)},
         "head": a.head, "leg": a.leg}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out + ".id.png", out + ".light.png")


if __name__ == "__main__":
    main(sys.argv[1:])
    # 描き終えた後の後片付けで bpy が落ちる（Segmentation fault）。書き出しは済んでいるので、ここで抜ける
    sys.stdout.flush()
    os._exit(0)
