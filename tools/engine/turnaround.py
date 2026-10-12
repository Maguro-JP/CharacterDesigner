"""三面図の下絵: 腕を下ろした人形を、正面・横・後ろの3方向から同じ大きさで写す。

言葉だけで「横向き」「後ろ向き」と頼むと、横は斜め前、後ろは振り返って顔が見える絵になった（騎士で9枚中0枚）。
向きは立体で先に決めておき、絵の生成にはその形を下絵として渡す（tools/gen/bible.py draw --base）。

色は設定資料の大まかな配色で塗る。白い人形のまま描き換えを弱めると、白がそのまま服の色として残ったため。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/turnaround.py <出力の頭> [--skin R,G,B] [--top R,G,B] [--bottom R,G,B]
出力は <頭>-front.png, <頭>-side.png, <頭>-back.png
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
VIEWS = {"front": Vector((0, -4.6, 1.0)), "side": Vector((4.6, 0, 1.0)), "back": Vector((0, 4.6, 1.0))}


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
    human.lower_arms(rig, 70)
    human.assign([h], tinted("skin", a.skin))
    top, bottom = tinted("top", a.top), tinted("bottom", a.bottom)
    human.assign(clothed, top)
    # 腰から下は別の色にする。上下が1色だと、スカートと鎧の境目が絵に出なかった
    for o in clothed:
        o.data.materials.append(bottom)
        for f in o.data.polygons:
            if (o.matrix_world @ f.center).z < 0.95:
                f.material_index = len(o.data.materials) - 1

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
