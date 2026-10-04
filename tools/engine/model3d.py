"""MakeHuman の人体を Blender で組み、スマホのブラウザで回して見られる 3D の形式（GLB）に書き出す。

頭身は変えない（写実の比率のまま）。肌・目・眉・まつ毛・髪・服・靴は MakeHuman の基本素材（CC0）。
GLB は Web 用の 3D の形式で、<model-viewer> などでそのまま表示できる。肌の質感は Web で描けるもの（GAMEENGINE）にする。

前準備: sh tools/engine/setup.sh
使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/model3d.py <out.glb> [--gender 0.0] [--age 0.5]
          [--muscle 0.5] [--weight 0.5] [--skin young_caucasian_female] [--hair long01] [--eyes brown]
          [--clothes female_casualsuit01,shoes02] [--arms 60]
--gender 0 が女性、1 が男性。--age 0.5 が 25 歳前後。--muscle と --weight は 0〜1。
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

DATA = human.MPFB_DATA


def asset(kind, name, ext):
    hits = glob.glob(str(DATA / kind / name / f"*.{ext}"))
    if not hits:
        raise SystemExit(f"{kind}/{name} が {DATA} に無い")
    return hits[0]


def bake_pose():
    """骨の姿勢と体型を形に焼き込み、骨とモディファイアを外す。この後の切り取りを、見たままの高さで行うため。"""
    dg = bpy.context.evaluated_depsgraph_get()
    for o in [o for o in bpy.data.objects if o.type == "MESH"]:
        mesh = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        o.modifiers.clear()
        o.shape_key_clear()
        o.data = mesh
        o.parent = None
        o.matrix_world = o.evaluated_get(dg).matrix_world.copy()
    for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        bpy.data.objects.remove(o)


def cut_under_trousers(wear_names, shoe_names, margin=0.02):
    """靴の、ズボンの裾より上の部分を消す。

    MakeHuman の靴は足首より上まで形があり、細いジーンズの内側から布を突き抜けて、すねに靴の色の欠けが出た。
    裾より上は布に隠れて見えない部分なので、消しても見た目は変わらない。"""
    import bmesh
    def meshes(names):
        return [o for o in bpy.data.objects if o.type == "MESH" and any(n.lower() in o.name.lower() for n in names)]
    wear, shoes = meshes(wear_names), meshes(shoe_names)
    if not wear or not shoes:
        return
    hem = min(min((o.matrix_world @ v.co).z for v in o.data.vertices) for o in wear)
    if hem > 0.4:  # 裾が膝より上（短いズボン・スカート）なら、靴は隠れないので消さない
        return
    for o in shoes:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        mw = o.matrix_world
        gone = [v for v in bm.verts if (mw @ v.co).z > hem + margin]
        bmesh.ops.delete(bm, geom=gone, context="VERTS")
        bm.to_mesh(o.data)
        bm.free()
        print("靴の裾より上を消した", o.name, len(gone), "点")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--gender", type=float, default=0.0)
    ap.add_argument("--age", type=float, default=0.5)
    ap.add_argument("--muscle", type=float, default=0.5)
    ap.add_argument("--weight", type=float, default=0.5)
    ap.add_argument("--skin", default="young_caucasian_female")
    ap.add_argument("--hair", default="long01")
    ap.add_argument("--eyes", default="brown")
    ap.add_argument("--eyebrows", default="eyebrow001")
    ap.add_argument("--eyelashes", default="eyelashes01")
    ap.add_argument("--clothes", default="female_casualsuit01,shoes02")
    ap.add_argument("--arms", type=float, default=60)
    ap.add_argument("--tex", type=int, default=1024, help="画像の長い辺の上限（ドット）")
    a = ap.parse_args(argv)
    human.setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    macro = TargetService.get_default_macro_info_dict()
    macro.update(gender=a.gender, age=a.age, muscle=a.muscle, weight=a.weight)
    body = HumanService.create_human(macro_detail_dict=macro)
    HumanService.set_character_skin(asset("skins", a.skin, "mhmat"), body, skin_type="GAMEENGINE")
    HumanService.add_mhclo_asset(asset("eyes", "high-poly", "mhclo"), body, asset_type="Eyes", subdiv_levels=0,
                                 material_type="GAMEENGINE")
    for kind, name, t in (("eyebrows", a.eyebrows, "Eyebrows"), ("eyelashes", a.eyelashes, "Eyelashes"),
                          ("hair", a.hair, "Hair")):
        if name:
            HumanService.add_mhclo_asset(asset(kind, name, "mhclo"), body, asset_type=t, subdiv_levels=0,
                                         material_type="GAMEENGINE")
    for name in filter(None, a.clothes.split(",")):
        HumanService.add_mhclo_asset(asset("clothes", name, "mhclo"), body, asset_type="Clothes", subdiv_levels=0,
                                     material_type="GAMEENGINE")
    HumanService.add_builtin_rig(body, "default")
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    human.lower_arms(rig, a.arms)
    # 肌や服の画像は 2048〜4096 四方あり、GLB が 19MB になった（公開できる上限 15MB）。
    # スマホで見るには 1024 四方で足りるので縮め、JPEG で書き出す
    for img in bpy.data.images:
        if img.size[0] > a.tex or img.size[1] > a.tex:
            k = a.tex / max(img.size)
            img.scale(max(1, int(img.size[0] * k)), max(1, int(img.size[1] * k)))
    # 口の中（歯・舌）や目の周りの補助の形を隠す設定（MASK）が画面表示では切られていて、書き出しに残った。
    # 口の外に赤い歯ぐきが透け、目の周りが崩れたので、書き出す前に全部有効にする
    for o in bpy.data.objects:
        for m in getattr(o, "modifiers", []):
            m.show_viewport = True
    bake_pose()
    names = [n for n in a.clothes.split(",") if n]
    cut_under_trousers([n for n in names if not n.startswith("shoes")], [n for n in names if n.startswith("shoes")])
    # 体・服・靴・目の素材が半透明として書き出され、体の裏が透けた（口の中の歯が唇の外に、背中の髪が胸の前に見えた）。
    # glTF の書き出しは素材の Alpha につながった線で半透明を決めるので、透けてはいけない素材は Alpha の線を外して 1 にする。
    # 髪・眉・まつ毛は透けを残す（毛先の形を透けで出しているため）
    # 目（表面の膜の下に瞳）と服（裾のほつれ）は、透けを全部外すと白く塗られた。透けをくっきり抜く（切り抜き）にする。
    # glTF の書き出しは Alpha の手前に「丸め」の計算を挟むと切り抜き（MASK、境 0.5）として書き出す
    soft = ("lash", "brow", a.hair.lower() if a.hair else "@@")
    clip = ("high-poly", "eye") + tuple(n.lower() for n in a.clothes.split(",") if n)
    for mat in bpy.data.materials:
        if not mat.use_nodes or any(k in mat.name.lower() for k in soft):
            continue
        nt = mat.node_tree
        for node in nt.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            links = list(node.inputs["Alpha"].links)
            if links and any(k in mat.name.lower() for k in clip):
                src = links[0].from_socket
                nt.links.remove(links[0])
                rnd = nt.nodes.new("ShaderNodeMath")
                rnd.operation = "ROUND"
                nt.links.new(src, rnd.inputs[0])
                nt.links.new(rnd.outputs[0], node.inputs["Alpha"])
            else:
                for link in links:
                    nt.links.remove(link)
                node.inputs["Alpha"].default_value = 1.0
    out = os.path.abspath(a.out)
    # 骨の姿勢を形に焼き込んで書き出す（見るだけなので骨は付けない。ファイルが小さく、どのビューアでも同じ姿勢）
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_apply=True, export_skins=False,
                              export_animations=False, export_yup=True, export_image_format="JPEG")
    print("wrote", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
    sys.stdout.flush()
    os._exit(0)
