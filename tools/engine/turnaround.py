"""三面図の下絵: 腕を下ろした人形を、正面・横・後ろの3方向から同じ大きさで写す。

言葉だけで「横向き」「後ろ向き」と頼むと、横は斜め前、後ろは振り返って顔が見える絵になった（騎士で9枚中0枚）。
向きは立体で先に決めておき、絵の生成にはその形を下絵として渡す（tools/gen/bible.py draw --base）。

色は設定資料の大まかな配色で塗る。白い人形のまま描き換えを弱めると、白がそのまま服の色として残ったため。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/turnaround.py <出力の頭> [--skin R,G,B] [--top R,G,B] [--bottom R,G,B]
出力は <頭>-front.png, <頭>-side.png, <頭>-back.png, <頭>-right.png
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
from pose_prop import look_from, tinted  # noqa: E402

# 人形の座標: 前は -Y、右手は -X。横は本人の左側から写す（絵の中で左を向く）
# side は画面の左を向く横顔、right は画面の右を向く横顔（四面図。持ち物や髪の結び目が左右で違うので、裏返して作らない）
VIEWS = {"front": Vector((0, -4.6, 1.0)), "side": Vector((4.6, 0, 1.0)), "back": Vector((0, 4.6, 1.0)), "right": Vector((-4.6, 0, 1.0))}


def rgb(text):
    return tuple(int(v) for v in text.split(","))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--skin", type=rgb, default=(240, 200, 170))
    ap.add_argument("--top", type=rgb, default=(170, 170, 180), help="胴と腕の布の色")
    ap.add_argument("--bottom", type=rgb, default=(40, 40, 45), help="腰から下の布の色")
    ap.add_argument("--cape", type=rgb, help="背中のマントの色。省くとマントを付けない")
    ap.add_argument("--boots", type=rgb, help="膝から下の色（鎧靴など）。省くと下の布の色")
    ap.add_argument("--long-sleeves", action="store_true", help="腕を手首まで上の布の色にする（長袖の上着）")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
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
    clothed = []
    import glob
    for name in ("female_casualsuit01", "shoes01"):
        found = glob.glob(str(human.MPFB_DATA / "clothes" / name / "*.mhclo"))
        if found:
            before = set(bpy.data.objects)
            HumanService.add_mhclo_asset(found[0], h, asset_type="Clothes", subdiv_levels=0)
            clothed += [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    human.adduct_arms(rig, 35)
    human.relax_hands(rig)
    # 関節が可動域を超えていないかを数える（下絵の崩れは絵にそのまま残る。docs/knowledge/joints-and-motion.md）
    import rom_check
    bpy.context.view_layer.update()
    bad = rom_check.check_rig(rig)
    print("可動域:", "外れなし" if not bad else "; ".join(bad))
    human.assign([h], tinted("skin", a.skin))
    top, bottom = tinted("top", a.top), tinted("bottom", a.bottom)
    human.assign(clothed, top)
    # 腰から下は別の色にする。上下が1色だと、スカートと鎧の境目が絵に出なかった
    for o in clothed:
        o.data.materials.append(bottom)
        for f in o.data.polygons:
            if (o.matrix_world @ f.center).z < 0.95:
                f.material_index = len(o.data.materials) - 1

    if a.long_sleeves:
        # 人形の服は半袖で、長袖の上着を頼んでも半袖に描かれた（赤いジャケットが半袖になった）。
        # 人形の服（半袖）を袖だけ伸ばすと、半袖の裾の段が絵で肩から脇への縫い目に描かれ、肩が落ちて見えた。
        # 袖の面だけ消すと、肩の布が硬い板のまま残って割れた。腰より上は服を外し、体の面そのものを上の布の色にする（体に沿う長袖）。
        # 頂点の組には骨の重みのほかに body・Right などの重み 1 の目印の組があるので、骨の名前の組だけで比べる
        import bmesh
        bones = {b.name for b in rig.data.bones}
        torso = ("spine", "clavicle", "shoulder", "breast", "pectoral", "upperarm", "lowerarm", "chest")
        bone_ids = {g.index for g in h.vertex_groups if g.name in bones}
        upper = {g.index for g in h.vertex_groups if g.name in bones and g.name.lower().startswith(torso)}

        def main_bone(o, ids, v):
            gs = [g for g in o.data.vertices[v].groups if g.group in ids]
            return max(gs, key=lambda g: g.weight).group if gs else None
        h.data.materials.append(top)
        idx = len(h.data.materials) - 1
        n = 0
        for f in h.data.polygons:
            if (h.matrix_world @ f.center).z > 0.95 and all(main_bone(h, bone_ids, v) in upper for v in f.vertices):
                f.material_index = idx
                n += 1
        cut = 0
        for o in clothed:
            bm = bmesh.new()
            bm.from_mesh(o.data)
            gone = [f for f in bm.faces if (o.matrix_world @ f.calc_center_median()).z > 0.95]
            bmesh.ops.delete(bm, geom=gone, context="FACES")
            bm.to_mesh(o.data)
            bm.free()
            cut += len(gone)
        # 服を着せると、服の下の体の面を隠す設定（MASK、頂点の組 Delete.<服>）が付く。服を外した胴が消えたので、
        # 腰より上の頂点だけを隠す組から外す（設定ごと外すと、ズボンの下の脚の肌が布を突き抜けて出た）
        for g in [g for g in h.vertex_groups if g.name.startswith("Delete.")]:
            g.remove([v.index for v in h.data.vertices if (h.matrix_world @ v.co).z > 0.95])
        print("長袖にした体の面:", n, "外した服の面:", cut)
    if a.boots:
        boots = tinted("boots", a.boots)
        for o in clothed:
            o.data.materials.append(boots)
            for f in o.data.polygons:
                if (o.matrix_world @ f.center).z < 0.5:
                    f.material_index = len(o.data.materials) - 1
    if a.cape:
        # 下絵に無い物は絵に出なかった（マントの代わりに襟巻きが長く垂れた）ので、背中に板で置く
        bpy.ops.mesh.primitive_cube_add(location=(0, 0.14, 0.93))
        cape = bpy.context.object
        cape.scale = (0.2, 0.012, 0.4)  # 肩の高さから膝の上まで
        cape.rotation_euler = (math.radians(-5), 0, 0)  # 裾を少し後ろへ
        human.assign([cape], tinted("cape", a.cape))

    scene = bpy.context.scene
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 3.0
    so = bpy.data.objects.new("sun", sun)
    scene.collection.objects.link(so)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0.4, 0.4, 0.4)
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = a.width, a.height
    from PIL import Image
    for view, cam in VIEWS.items():
        # 光は毎回カメラの斜め上から当てる。後ろから写すときに前から当てると、背中が真っ黒になった
        so.rotation_euler = (math.radians(50), 0, math.atan2(cam.x, -cam.y) + math.radians(30))
        look_from(scene, Vector((0, 0, 0.88)), cam, 1.9)
        out = os.path.abspath(f"{a.out}-{view}.png")
        scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        im = Image.open(out).convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        bg.convert("RGB").save(out)
        print(out)


if __name__ == "__main__":
    main(sys.argv[1:])
    # 描き終えた後の後片付けで bpy が落ちる（Segmentation fault）。書き出しは済んでいるので、ここで抜ける
    # （落ちたまま返すと、呼んだ側が失敗と取って止まった）
    sys.stdout.flush()
    os._exit(0)
