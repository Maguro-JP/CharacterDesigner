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
import json
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


def a_bias() -> dict:
    p = Path(__file__).resolve().parents[2] / "styles" / "draw-bias.json"
    return json.loads(p.read_text())["bias"] if p.exists() else {}


def head_scale(heads: float, real: float = 7.5) -> float:
    """写実の人形（real 頭身）の頭を何倍にすれば heads 頭身になるか。身長 H・頭 h として (H - h + h*k) / (h*k) = heads を解く"""
    return (real - 1) / (heads - 1)


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
    ap.add_argument("--clothes", default="female_casualsuit01,shoes01",
                    help="着せる服の型（MPFB の clothes の名前をカンマ区切り）。布に厚みと縫い目のある型を着せる")
    ap.add_argument("--hair", help="髪の型（MPFB の hair の名前、例 bob01）。省くと坊主頭")
    ap.add_argument("--hair-color", type=rgb, default=(60, 40, 30))
    ap.add_argument("--thickness", type=float, default=0.004, help="布の厚み（m）。0 で厚みを付けない")
    ap.add_argument("--heads", type=float, help="頭身。人形は写実の約 7.5 頭身で、アニメの顔を描かせると体と顔の釣り合いが崩れた。首から上を大きくして合わせる")
    ap.add_argument("--no-fit", action="store_true", help="体の部位の釣り合いを合わせない（写実の人形のまま）")
    ap.add_argument("--measure", help="体の部位の寸法（頭の高さを 1 とする）を JSON に書き出す先")
    ap.add_argument("--boots-height", type=float, default=0.5, help="靴の色を塗る高さ（m）。既定 0.5 は膝下までの鎧靴。短いブーツは 0.15")
    ap.add_argument("--keep", action="append", default=[], metavar="服:above|below:高さ",
                    help="服の型の一部だけ使う（例 female_elegantsuit01:above:0.93 で上着だけ）。型は上下が一組で、上と下を別の型から取るため")
    ap.add_argument("--split", type=float, default=0.95, help="上と下の布の色を分ける高さ（m）。裾の長い上着は下げる")
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
    if not a.no_fit:
        # 体の部位の釣り合いを、作画の資料の間で一致している決まりに合わせる（女性は腰の幅≒肩幅、手≒顔の大きさ、足≒前腕）。
        # 写実の人形は肩幅が腰より 1 割広く、その上に描いた服も肩の張った形で描かれた
        m0 = human.measure_body(h, human._rig(h))
        goals = {"shoulder_width": m0["hip_width"], "hand": 0.75, "foot": m0["forearm"]}
        # 描く模型は下絵より腕を長く描く癖があった（前腕 1.24〜1.30 倍、上腕 1.08〜1.18 倍、3 枚とも同じ向き）。
        # 癖の分だけ人形の腕を先に短くし、描いた絵で目安の長さになるようにする（癖は styles/draw-bias.json、描いた絵から学び直す）
        for k, b in a_bias().items():
            goals[k] = m0[k] / b
        print("体の釣り合い:", json.dumps(human.fit_body(h, goals), ensure_ascii=False))
        for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
            bpy.data.objects.remove(o)
        for mod in [mod for mod in h.modifiers if mod.type == "ARMATURE"]:
            h.modifiers.remove(mod)
    if a.heads:
        # 人形の頭身は体型で 6.9〜7.5 と揺れ、7.5 と決め打ちで倍率を出すと 7 頭身を頼んで 6.5 になった。
        # 測った頭身から倍率を出し、もう一度測って合わせる
        for _ in range(2):
            now = human.measure_body(h, human._rig(h))["height"]
            human.deform(h.data, head_scale(a.heads, now), 1.0)
    # 骨は形を変え終えてから付け直す（古い骨と骨の設定を残すと、形を変える前の位置で体が曲がる）
    human._rig(h)
    clothed = []
    import glob
    for name in a.clothes.split(","):
        found = glob.glob(str(human.MPFB_DATA / "clothes" / name / "*.mhclo"))
        if found:
            before = set(bpy.data.objects)
            HumanService.add_mhclo_asset(found[0], h, asset_type="Clothes", subdiv_levels=0)
            clothed += [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    hair = []
    if a.hair:
        # 坊主頭の人形から描くと、額に眉が塊で描かれ、髪の生え際と顔の大きさが毎回変わった
        found = glob.glob(str(human.MPFB_DATA / "hair" / a.hair / "*.mhclo"))
        before = set(bpy.data.objects)
        HumanService.add_mhclo_asset(found[0], h, asset_type="Hair", subdiv_levels=0)
        hair = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if a.keep:
        import bmesh
        for spec in a.keep:
            name, side, z = spec.split(":")
            for o in clothed:
                if name.lower() not in o.name.lower():
                    continue
                bm = bmesh.new()
                bm.from_mesh(o.data)
                gone = [f for f in bm.faces if ((o.matrix_world @ f.calc_center_median()).z < float(z)) == (side == "above")]
                bmesh.ops.delete(bm, geom=gone, context="FACES")
                bm.to_mesh(o.data)
                bm.free()
    if a.thickness > 0:
        # 型の布は厚みの無い 1 枚の面で、襟や裾の縁が線にしかならなかった。厚みを付けて、縁と重なりを立体にする
        for o in clothed:
            mod = o.modifiers.new("thickness", "SOLIDIFY")
            mod.thickness = a.thickness
            mod.offset = 1.0
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if a.measure:
        Path(a.measure).write_text(json.dumps(human.measure_body(h, rig), ensure_ascii=False, indent=1))
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
    if hair:
        human.assign(hair, tinted("hair", a.hair_color))
    # 腰から下は別の色にする。上下が1色だと、スカートと鎧の境目が絵に出なかった
    for o in clothed:
        o.data.materials.append(bottom)
        for f in o.data.polygons:
            if (o.matrix_world @ f.center).z < a.split:
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
                if (o.matrix_world @ f.center).z < a.boots_height:
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
    sun.energy = 2.0
    # 光の広がりを大きくして影の境目をぼかす。強い影の境目（手の影、脚の明暗の境）を、描く模型が服の色の境目として描いた
    sun.angle = math.radians(60)
    so = bpy.data.objects.new("sun", sun)
    scene.collection.objects.link(so)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0.7, 0.7, 0.7)
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
