"""MakeHuman の体を白い無機質なマネキンにして、体型の描き分けを正面・横・背面から描く。

肌の画像・目の色・眉・髪を付けず、全身を白のつや消し一色で塗る（デッサン人形やお店のマネキンと同じ考え方）。
体型は MakeHuman の数字（体重・筋肉・胸の大きさ・張り）で振る。立ち姿は腕を下ろした直立だけにする。

前準備: sh tools/engine/setup.sh
使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/mannequin.py <出力フォルダ> [--gender 0.0] [--size 640]
出力: <体型>-<向き>.png と、全部を並べた sheet.png
"""
import argparse
import glob
import math
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import human  # noqa: E402  setup と腕を下ろす処理を使い回す

# 体型の組。値は MakeHuman の数字（0〜1、0.5 が平均）
BODIES = {
    "slim": {"ja": "細身", "weight": 0.2, "muscle": 0.4, "cupsize": 0.4, "firmness": 0.5},
    "standard": {"ja": "標準", "weight": 0.5, "muscle": 0.5, "cupsize": 0.5, "firmness": 0.5},
    "curvy": {"ja": "曲線的", "weight": 0.62, "muscle": 0.45, "cupsize": 0.75, "firmness": 0.6},
    "plump": {"ja": "肉付きが良い", "weight": 0.88, "muscle": 0.4, "cupsize": 0.6, "firmness": 0.4},
    "athletic": {"ja": "筋肉質", "weight": 0.45, "muscle": 0.9, "cupsize": 0.4, "firmness": 0.7},
}
VIEWS = {"front": 0, "side": 90, "back": 180}


def white(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.62, 0.62, 0.6, 1)
    bsdf.inputs["Roughness"].default_value = 0.65
    return m


def build(spec, gender, arms):
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    macro = TargetService.get_default_macro_info_dict()
    macro.update(gender=gender, age=0.5, **{k: v for k, v in spec.items() if k != "ja"})
    body = HumanService.create_human(macro_detail_dict=macro)
    HumanService.add_builtin_rig(body, "default")
    # 目が無いと眼窩が空洞に見えるので、眼球だけ付けて体と同じ白で塗る（彫像の目と同じ）
    HumanService.add_mhclo_asset(glob.glob(str(human.MPFB_DATA / "eyes" / "high-poly" / "*.mhclo"))[0], body,
                                 asset_type="Eyes", subdiv_levels=0)
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    human.lower_arms(rig, arms)
    mat = white("mannequin")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)
        for m in o.modifiers:
            m.show_viewport = True
        # 角張りを消す（マネキンの滑らかな面）
        sub = o.modifiers.new("smooth", "SUBSURF")
        sub.levels = sub.render_levels = 1
    flatten(body)
    return meshes


def flatten(body):
    """乳首と股の細かい凹凸を平らにならす（マネキンには無い）。

    体型は形の差分（shape key）と骨で後から上乗せされるので、元の形をならしても凹凸が戻った。
    姿勢と体型を形に焼き込み、その形の上で、区分（genitals、nipple）を周りへ広げた範囲の点をならす。"""
    import bmesh
    dg = bpy.context.evaluated_depsgraph_get()
    subs = [m for m in body.modifiers if m.type == "SUBSURF"]
    for m in subs:
        m.show_viewport = False
    dg.update()
    mesh = bpy.data.meshes.new_from_object(body.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    body.shape_key_clear()
    for m in [m for m in body.modifiers if m.type != "SUBSURF"]:
        body.modifiers.remove(m)
    body.data = mesh
    for m in subs:
        m.show_viewport = True
    radius = 0.07  # メートル
    for group, grow, steps in (("genitals", 0, 200), ("nipple", 3, 80), ("nippleTip", 3, 80)):
        if group not in body.vertex_groups:
            continue
        idx = set(range(len(mesh.vertices))) & set(i for i in [v.index for v in mesh.vertices
                                                              if any(g.group == body.vertex_groups[group].index
                                                                     for g in v.groups)])
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        picked = set(idx)
        for _ in range(grow):
            picked |= {e.other_vert(bm.verts[i]).index for i in list(picked) for e in bm.verts[i].link_edges}
        if group == "genitals":
            # 区分 genitals は体の側では0点だった（目に見えない補助の形にだけ入っている）。
            # 体の中心線（x≒0）で一番低い点が股なので、そこから少し上を中心に半径 radius の点をならす
            mid = [v for v in bm.verts if abs((body.matrix_world @ v.co).x) < 0.004]
            low = min(mid, key=lambda v: v.co.z)
            c = low.co.copy()
            c.z += 0.03
            picked |= {v.index for v in bm.verts if (v.co - c).length < radius}
        verts = [bm.verts[i] for i in picked]
        for _ in range(steps):
            bmesh.ops.smooth_vert(bm, verts=verts, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        print("ならした", group, "区分", len(idx), "点 / 範囲", len(picked), "点", flush=True)
        bm.to_mesh(mesh)
        bm.free()
    mesh.update()


def setup_scene(size):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.render.film_transparent = True  # 背景は透明で描き、一覧図で明るい灰色の台紙に載せる
    scene.render.resolution_x, scene.render.resolution_y = size // 2, size
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0.2, 0.2, 0.2)  # 周りからの弱い光
    for name, energy, rot in (("key", 2.2, (50, 0, -35)), ("fill", 0.6, (60, 0, 50)), ("rim", 1.0, (110, 0, 180))):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = energy
        lo = bpy.data.objects.new(name, light)
        scene.collection.objects.link(lo)
        lo.rotation_euler = tuple(math.radians(a) for a in rot)
    cam = bpy.data.cameras.new("cam")
    cam.type = "ORTHO"
    co = bpy.data.objects.new("cam", cam)
    scene.collection.objects.link(co)
    scene.camera = co
    return scene, co


def aim(co, meshes, deg):
    dg = bpy.context.evaluated_depsgraph_get()
    zs = []
    for o in meshes:
        ev = o.evaluated_get(dg)
        zs += [(ev.matrix_world @ v.co).z for v in ev.to_mesh().vertices]
        ev.to_mesh_clear()
    lo, hi = min(zs), max(zs)
    co.data.ortho_scale = (hi - lo) * 1.08
    a, d = math.radians(deg), 10
    # MakeHuman の体は -Y 向き（正面がカメラの -Y 側）
    co.location = (d * math.sin(a), -d * math.cos(a), (hi + lo) / 2)
    co.rotation_euler = (math.radians(90), 0, a)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--gender", type=float, default=0.0, help="0 が女性、1 が男性")
    ap.add_argument("--arms", type=float, default=70)
    ap.add_argument("--size", type=int, default=640, help="1枚の高さ（ドット）")
    ap.add_argument("--only", default="", help="描く体型を , で区切って限る")
    a = ap.parse_args(argv)
    human.setup()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = [k for k in BODIES if not a.only or k in a.only.split(",")]
    for key in keys:
        meshes = build(BODIES[key], a.gender, a.arms)
        scene, co = setup_scene(a.size)
        for view, deg in VIEWS.items():
            aim(co, meshes, deg)
            scene.render.filepath = str((out / f"{key}-{view}.png").resolve())
            bpy.ops.render.render(write_still=True)
            print("wrote", scene.render.filepath, flush=True)
    sheet(out, keys, a.size)


def sheet(out, keys, size):
    from PIL import Image, ImageDraw, ImageFont
    font = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
    w, h = size // 2, size
    im = Image.new("RGB", (w * 3, (h + 40) * len(keys)), (236, 236, 233))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(font, 22)
    for r, key in enumerate(keys):
        d.text((8, r * (h + 40) + 8), BODIES[key]["ja"], fill=(40, 40, 40), font=f)
        for c, view in enumerate(VIEWS):
            tile = Image.open(out / f"{key}-{view}.png").convert("RGBA")
            im.paste(tile, (c * w, r * (h + 40) + 40), tile)
    im.save(out / "sheet.png")
    print("wrote", out / "sheet.png")


if __name__ == "__main__":
    main(sys.argv[1:])
    sys.stdout.flush()
    os._exit(0)
