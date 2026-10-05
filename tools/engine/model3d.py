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


# アニメ寄りの顔: 目を大きく、鼻・口・あごを小さく。MakeHuman の顔の形の差分（target）の重ね合わせ。
# 写実の顔は「気持ち悪い」と言われた。顔の形は道具の数字で寄せ、塗り（陰2段と輪郭線）は表示の側で行う
FACES = {
    "anime": {"eyes/r-eye-scale-incr": 1.0, "eyes/l-eye-scale-incr": 1.0,
              "eyes/r-eye-height1-incr": 1.0, "eyes/l-eye-height1-incr": 1.0,
              "eyes/r-eye-height2-incr": 1.0, "eyes/l-eye-height2-incr": 1.0,
              "eyes/r-eye-height3-incr": 1.0, "eyes/l-eye-height3-incr": 1.0,
              "nose/nose-volume-decr": 0.8, "nose/nose-scale-vert-decr": 0.5, "nose/nose-scale-depth-decr": 0.6,
              "mouth/mouth-scale-horiz-decr": 0.5, "mouth/mouth-scale-vert-decr": 0.3,
              "chin/chin-width-decr": 0.5, "chin/chin-height-decr": 0.4, "head/head-round": 0.4,
              # 目の高さを上げると眉との間が詰まり、怒った顔に見えた。眉の内側を上げ（angle-up。angle-down は余計に怒った顔になった）、全体も上げる
              "eyebrows/eyebrows-angle-up": 0.8, "eyebrows/eyebrows-trans-up": 0.6},
}


def shape_face(body, preset):
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    # 形の差分は、拡張の置き場所（.user の付かない側）に入っている
    root = Path.home() / ".config/blender/4.2/extensions/user_default/mpfb/data/targets"
    for name, w in FACES[preset].items():
        TargetService.load_target(body, str(root / f"{name}.target.gz"), weight=w, name=name.split("/")[1])


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


def split_outfits(body, outfits):
    """服の組ごとに、体と服を別の形として複製する（名前は「体__組」「服__組」）。

    MakeHuman は服ごとに、服の下に隠れる体の点を消す設定（MASK）を体に付ける。全部の服を付けたまま書き出すと、
    どの組を着せても、ほかの服の分まで体に穴が開いている。組ごとに、その組の服の MASK だけを残した体を作る。
    同じ靴を2つの組で使うときも組ごとに複製する（ズボンの裾に合わせて靴を切るため）。"""
    made = []
    for key, items in outfits.items():
        b = body.copy()
        b.name = f"body__{key}"
        bpy.context.scene.collection.objects.link(b)
        for m in list(b.modifiers):
            if m.type == "MASK" and m.name.startswith("Delete.") and m.name[len("Delete."):] not in items:
                b.modifiers.remove(m)
        made.append(b)
        for item in items:
            src = next(o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith("." + item))
            c = src.copy()
            c.name = f"{item}__{key}"
            bpy.context.scene.collection.objects.link(c)
            made.append(c)
    originals = [body] + [o for o in bpy.data.objects if o.type == "MESH" and any(o.name.endswith("." + i)
                                                                                  for v in outfits.values() for i in v)]
    return made, originals


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
    ap.add_argument("--face", default="", choices=["", *FACES], help="顔の形の組。anime はアニメ寄り")
    ap.add_argument("--head", type=float, default=1.0, help="頭の大きさの倍率。アニメ調は 1.1〜1.2")
    ap.add_argument("--outfits", default="", help="着せ替えの組。例: casual=female_casualsuit01,shoes02;sport=female_sportsuit01,shoes05")
    ap.add_argument("--tex", type=int, default=1024, help="画像の長い辺の上限（ドット）")
    a = ap.parse_args(argv)
    outfits = {k: [i for i in v.split(",") if i] for k, v in (t.split("=") for t in a.outfits.split(";") if t)}
    if outfits:
        a.clothes = ",".join(dict.fromkeys(i for v in outfits.values() for i in v))
    human.setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    macro = TargetService.get_default_macro_info_dict()
    macro.update(gender=a.gender, age=a.age, muscle=a.muscle, weight=a.weight)
    body = HumanService.create_human(macro_detail_dict=macro)
    if a.face:
        shape_face(body, a.face)
    if a.head != 1.0:
        human.deform(body.data, a.head, 1.0)  # 髪・目・服は後から体の点に合わせて付くので、先に縮める
    # 骨は服より先に付ける。後から付けると服に骨の重みが入らず、長袖が腕を下ろしても A の字のまま残った
    HumanService.add_builtin_rig(body, "default")
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
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
    originals = []
    if outfits:
        _, originals = split_outfits(body, outfits)
    bake_pose()
    for o in originals:
        bpy.data.objects.remove(o)
    for key, names in (outfits or {"": [n for n in a.clothes.split(",") if n]}).items():
        tag = f"__{key}" if key else ""
        cut_under_trousers([n + tag for n in names if not n.startswith("shoes")],
                           [n + tag for n in names if n.startswith("shoes")])
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
