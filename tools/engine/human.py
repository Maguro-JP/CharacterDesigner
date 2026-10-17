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


def adduct_arms(rig, degrees=35):
    """A の字に開いた腕を、体の脇へ寄せる（肩の内転）。上腕の骨を Z 軸で回す（左は負、右は正）。
    休みの姿勢の上腕は縦から約 48 度開いている。50 度寄せると肘が肩より内側に入り、胴にめり込んだので、既定は 35 度"""
    for side, sign in (("L", -1), ("R", 1)):
        b = rig.pose.bones[f"upperarm01.{side}"]
        b.rotation_mode = "XYZ"
        b.rotation_euler = (0, 0, math.radians(degrees * sign))
    bpy.context.view_layer.update()


def relax_hands(rig, curl=12, spread=6):
    """力を抜いて下ろした手の形: 指の関節を軽く曲げ、指どうしを少し離す。親指は浅く曲げる。
    指をまっすぐ開いて下に垂らした人形から描くと、指が溶けて 1 枚の刃のような手になった（両手とも、描き直し 3 回でも直らなかった）"""
    for side, sign in (("L", 1), ("R", -1)):
        for f, k in zip(range(2, 6), (-1.5, -0.5, 0.5, 1.5)):
            for j in range(1, 4):
                b = rig.pose.bones[f"finger{f}-{j}.{side}"]
                b.rotation_mode = "XYZ"
                b.rotation_euler = (math.radians(curl), 0, math.radians(spread * k * sign) if j == 1 else 0)
        for j in (2, 3):
            b = rig.pose.bones[f"finger1-{j}.{side}"]
            b.rotation_mode = "XYZ"
            b.rotation_euler = (math.radians(curl * 0.6), 0, 0)
    bpy.context.view_layer.update()


def lower_arms(rig, degrees):
    """上腕の骨を Y 軸（骨の向き）で左右逆向きに回す。名前は「下ろす」だが、実際は上腕のねじれ（肩の内旋・外旋）で、
    肘の位置は動かない（rom_check で振れ 0・ねじれ = degrees と測れた）。肘から先が回って手が下がって見えるだけ。
    体の脇へ寄せたいときは adduct_arms を使う。古い呼び出し（model3d、mannequin）の見た目を変えないため残している"""
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


def measure_body(h, rig) -> dict:
    """人形の体の部位の長さ・幅・太さを、頭の高さ（頭のてっぺんからあご）を 1 として返す。休みの姿勢（A の字）の形で測る。
    服は体の上に作るので、体の寸法がジャンルの目安から外れていると、服も同じだけ外れた形で描かれる"""
    import numpy as np
    bones = {b.name: b for b in rig.data.bones}
    names = {g.index: g.name for g in h.vertex_groups if g.name in bones}
    co = np.array([v.co[:] for v in h.data.vertices])
    # 体型（体重・筋肉など）は形の鍵で掛かっていて、頂点の座標そのものには入っていない。鍵の重みを足して実際の形にする
    if h.data.shape_keys:
        blocks = h.data.shape_keys.key_blocks
        basis = np.array([d.co[:] for d in blocks[0].data])
        co = basis.copy()
        for kb in blocks[1:]:
            if kb.value and not kb.mute:
                co += kb.value * (np.array([d.co[:] for d in kb.data]) - basis)
    main = []
    for v in h.data.vertices:
        gs = [g for g in v.groups if g.group in names]
        main.append(names[max(gs, key=lambda g: g.weight).group] if gs else "")
    main = np.array(main)

    def sw(prefixes):
        prefixes = (prefixes,) if isinstance(prefixes, str) else prefixes
        return np.array([n.startswith(prefixes) for n in main])
    body = np.isin(main, list(bones))

    def J(name, tail=False):
        b = bones[name]
        return np.array((b.tail_local if tail else b.head_local)[:])

    def width(mask):
        return float(co[mask, 0].max() - co[mask, 0].min()) if mask.any() else 0.0

    def thick(prefix):
        # 骨に直交する太さ: その骨が主の頂点の、骨の軸からの距離の中央値 × 2（上位で取ると肩の膨らみまで拾い、上腕を 2 倍に測った）
        m = sw(prefix) & np.array([n.endswith(".L") for n in main])
        b = [n for n in bones if n.startswith(prefix) and n.endswith(".L")][0]
        a, t = J(b), J(b, True)
        d = (t - a) / np.linalg.norm(t - a)
        r = co[m] - a
        dist = np.linalg.norm(r - np.outer(r @ d, d), axis=1)
        return float(np.median(dist) * 2)

    top = float(co[body, 2].max())
    floor = float(co[body, 2].min())
    head_v = np.isin(main, ["head", "jaw"])
    chin = float(co[head_v, 2].min())
    head = top - chin
    torso = sw(("spine", "pelvis", "breast", "clavicle", "shoulder", "upperleg01", "root"))
    sh_z = J("upperarm01.L")[2]
    waist_band = [width(torso & ~sw("upperleg") & (abs(co[:, 2] - z) < 0.01)) for z in
                  np.linspace(J("spine02")[2], J("spine04")[2], 12)]
    hip_z = J("upperleg01.L")[2]
    hips = (torso | sw("upperleg")) & (co[:, 2] > hip_z - 0.12) & (co[:, 2] < hip_z + 0.02)
    foot = sw(("foot.L", "toe")) & (co[:, 0] > 0)
    L = lambda a, b, ta=False, tb=False: float(np.linalg.norm(J(a, ta) - J(b, tb)))
    m = {
        "height": (top - floor),
        # 肩幅は左右の肩の関節の間＋上腕の太さ（外側の輪郭）。高さの帯で輪郭を取ると、A の字に開いた腕まで入って広く出た
        "shoulder_width": float(abs(J("upperarm01.L")[0] - J("upperarm01.R")[0])) + thick("upperarm01"),
        "waist_width": min(w for w in waist_band if w > 0),
        "hip_width": width(hips),
        "neck_length": float(chin - sh_z),
        "upper_arm": L("upperarm01.L", "lowerarm01.L"),
        "forearm": L("lowerarm01.L", "wrist.L"),
        "hand": L("wrist.L", "finger3-3.L", tb=True),
        "leg": float(hip_z - floor),
        "thigh": L("upperleg01.L", "lowerleg01.L"),
        "shin": L("lowerleg01.L", "foot.L"),
        "foot": float(co[foot, 1].max() - co[foot, 1].min()) if foot.any() else 0.0,
        "upper_arm_thick": thick("upperarm01"),
        "thigh_thick": thick("upperleg01"),
    }
    out = {k: round(v / head, 2) for k, v in m.items()}
    out["head_m"] = round(head, 3)
    return out


# 体の寸法を合わせるときに動かす形の鍵（MPFB の targets）。寸法の名前 → (鍵の置き場/名前の頭, 左右があるか)
FIT_TARGETS = {
    "shoulder_width": ("torso/measure-shoulder-dist", False),
    "waist_width": ("torso/measure-waist-circ", False),
    "hip_width": ("torso/measure-hips-circ", False),
    "upper_arm_thick": ("arms/measure-upperarm-circ", False),
    "thigh_thick": ("legs/measure-thigh-circ", False),
    "neck_length": ("neck/measure-neck-height", False),
    "upper_arm": ("arms/measure-upperarm-length", False),
    "forearm": ("arms/measure-lowerarm-length", False),
    "hand": ("hands/{s}-hand-scale", True),
    "foot": ("feet/{s}-foot-scale", True),
}


def _rig(h):
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        bpy.data.objects.remove(o)
    for m in [m for m in h.modifiers if m.type == "ARMATURE"]:
        h.modifiers.remove(m)
    HumanService.add_builtin_rig(h, "default")
    return next(o for o in bpy.data.objects if o.type == "ARMATURE")


def _set_target(h, key, weight):
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    path, sided = FIT_TARGETS[key]
    # 形の鍵は MPFB の本体の側（extensions/user_default）にあり、素材（extensions/.user）とは置き場が違う
    root = Path.home() / ".config/blender/4.2/extensions/user_default/mpfb/data/targets"
    for s in (("l", "r") if sided else ("",)):
        base = path.format(s=s)
        for end, w in (("incr", max(weight, 0.0)), ("decr", max(-weight, 0.0))):
            name = base.split("/")[-1] + "-" + end
            kb = h.data.shape_keys.key_blocks.get(name) if h.data.shape_keys else None
            if kb is None:
                if w == 0:
                    continue
                TargetService.load_target(h, str(root / f"{base}-{end}.target.gz"), weight=w, name=name)
            else:
                kb.value = w


def fit_body(h, goals: dict, rounds: int = 2) -> dict:
    """体の寸法（頭の高さを 1 とする）を goals に近づける。寸法ごとに形の鍵を ±1 で振って効き方を測り、直線で重みを決める。
    鍵どうしは少し影響し合うので rounds 回くり返す。返り値は合わせた後の寸法と、使った重み"""
    weights = {k: 0.0 for k in goals if k in FIT_TARGETS}
    for _ in range(rounds):
        for k in weights:
            now = measure_body(h, _rig(h))[k]
            _set_target(h, k, max(-1.0, min(1.0, weights[k] + 0.5)))
            probe = measure_body(h, _rig(h))[k]
            slope = (probe - now) / (max(-1.0, min(1.0, weights[k] + 0.5)) - weights[k]) if probe != now else 0.0
            if slope:
                weights[k] = max(-1.0, min(1.0, weights[k] + (goals[k] - now) / slope))
            _set_target(h, k, weights[k])
    return {"measure": measure_body(h, _rig(h)), "weights": {k: round(v, 2) for k, v in weights.items()}}


def thin_limb(h, rig, prefix: str, factor: float) -> None:
    """手足の太さを、骨の軸に向けて寄せて変える（factor 0.85 で 15% 細く）。形の鍵（measure-thigh-circ など）では
    太ももが 0.79 → 0.77 しか変わらなかった。骨の重みで寄せ方を混ぜ、関節の境で段が付かないようにする"""
    import numpy as np
    bones = [b for b in rig.data.bones if b.name.startswith(prefix)]
    groups = {g.name: g.index for g in h.vertex_groups}
    blocks = list(h.data.shape_keys.key_blocks) if h.data.shape_keys else []
    for b in bones:
        gi = groups.get(b.name)
        if gi is None:
            continue
        a, t = np.array(b.head_local[:]), np.array(b.tail_local[:])
        d = (t - a) / np.linalg.norm(t - a)
        for v in h.data.vertices:
            w = next((g.weight for g in v.groups if g.group == gi), 0.0)
            if w <= 0:
                continue
            k = 1 - (1 - factor) * w
            for co in [v.co] + [kb.data[v.index].co for kb in blocks]:
                p = np.array(co[:]) - a
                along = a + d * (p @ d)
                co[:] = tuple(along + (np.array(co[:]) - along) * k)
    h.data.update()
