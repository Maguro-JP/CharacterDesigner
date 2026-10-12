"""箱庭ドットの戦士の下絵: 人形に剣と盾を持たせ、素材ごとの色で斜め前から写す。使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/hd2d_warrior.py out.png"""
import sys, os, math, glob
sys.path.insert(0, "tools/engine")
import bpy, human, rom_check
from mathutils import Vector
from turnaround import tinted
from pose_prop import look_from
human.setup()
from bl_ext.user_default.mpfb.services.humanservice import HumanService
from bl_ext.user_default.mpfb.services.targetservice import TargetService
for o in list(bpy.data.objects): bpy.data.objects.remove(o)
macro = TargetService.get_default_macro_info_dict(); macro["gender"] = 1.0; macro["muscle"] = 0.7
h = HumanService.create_human(macro_detail_dict=macro)
HumanService.add_builtin_rig(h, "default")
clothed = []
for name in ("male_worksuit01", "shoes01"):
    f = glob.glob(str(human.MPFB_DATA / "clothes" / name / "*.mhclo"))
    if f:
        before = set(bpy.data.objects)
        HumanService.add_mhclo_asset(f[0], h, asset_type="Clothes", subdiv_levels=0)
        clothed += [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
# 髪は MPFB の髪の部品を付ける。肌の面を上の高さで塗り分けると、坊主頭に色が載るだけで髪型にならなかった
hair = []
f = glob.glob(str(human.MPFB_DATA / "hair" / "short02" / "*.mhclo"))
if f:
    before = set(bpy.data.objects)
    HumanService.add_mhclo_asset(f[0], h, asset_type="Hair", subdiv_levels=0)
    hair = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
print("髪:", len(hair))
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
human.adduct_arms(rig, 30)
# 両肘を少し曲げて、剣と盾を体の前へ（肘 40 度）
for s in ("L", "R"):
    pb = rig.pose.bones[f"lowerarm01.{s}"]; pb.rotation_mode = "XYZ"; pb.rotation_euler = (math.radians(40), 0, 0)
# 剣を持つ右腕は体の脇から少し開き、肘をほぼ伸ばして手を腰の外に置く。手が胴の前にあると、下ろした剣が脚に重なった（周10）
rig.pose.bones["upperarm01.R"].rotation_euler = (0, 0, math.radians(14))
rig.pose.bones["lowerarm01.R"].rotation_euler = (math.radians(10), 0, 0)
# 頭身は人形の側で作る（頭を大きく、脚を短く）。縮めた後に絵を変形すると、持ち物が手から離れた（周8）
rig.pose.bones["head"].scale = (2.0, 2.0, 2.0)
for s in ("L", "R"):
    rig.pose.bones[f"upperleg01.{s}"].scale = (1.0, 0.6, 1.0)
bpy.context.view_layer.update()
print("可動域:", rom_check.check_rig(rig) or "外れなし")
C = {"skin": (240, 196, 160), "hair": (120, 80, 50), "armor": (190, 196, 206), "armor_d": (120, 128, 142), "skirt": (178, 60, 50),
     "greave": (150, 158, 172), "boot": (110, 70, 45), "blade": (228, 234, 246), "gold": (226, 180, 84), "shield": (184, 68, 58)}
M = {k: tinted(k, v) for k, v in C.items()}
for o in [h] + clothed + hair:
    for k in M: o.data.materials.append(M[k])
names = list(M)
def idx(o, k): return len(o.data.materials) - len(names) + names.index(k)
for f in h.data.polygons:
    c = h.matrix_world @ f.center; n = (h.matrix_world.to_3x3() @ f.normal)
    f.material_index = idx(h, "hair" if (c.z > 1.60 and (n.z > 0.2 or n.y > 0.1)) else "skin")
for o in clothed:
    for f in o.data.polygons:
        z = (o.matrix_world @ f.center).z
        k = "boot" if z < 0.12 else "greave" if z < 0.62 else "skirt" if z < 0.98 else "armor"
        # 胸は光の当たる面と陰の面の2段に分ける。1色のままだと縮めた後に色の点が散って胴が読めなかった（周9）
        if k == "armor" and (o.matrix_world.to_3x3() @ f.normal).x > 0.25:
            k = "armor_d"
        f.material_index = idx(o, k)
for o in hair:
    for f in o.data.polygons: f.material_index = idx(o, "hair")
def palm(side):
    m = rig.matrix_world
    return (m @ rig.pose.bones[f"wrist.{side}"].head + m @ rig.pose.bones[f"finger3-1.{side}"].head) / 2
def box(name, size, loc, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=loc); o = bpy.context.object; o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2); o.rotation_euler = rot
    o.data.materials.append(M[mat]); return o
r = palm("R")
# 剣は切っ先を下ろし、体の外（右手の側）へ 25 度開く。刃はすね当てより明るい色にし、脚と同じ灰色系にしない（周10）。斜めに上げると大きな頭に接して一つの塊になった（周9）
from mathutils import Euler
tilt = Euler((0, math.radians(180 + 25), 0))
def along(d): v = Vector((0, 0, d)); v.rotate(tilt); return r + Vector((0, -0.02, 0)) + v
# 34 ドットに縮めると 1 ドットはおよそ 5cm。細い物は 2 ドット（10cm）以上の太さにしないと、途切れて手から浮いた
box("blade", (0.11, 0.03, 0.7), along(0.45), "blade", tilt)
box("guard", (0.3, 0.08, 0.08), along(0.07), "gold", tilt)
box("grip", (0.09, 0.09, 0.16), along(-0.03), "boot", tilt)
# 盾は左の前腕の外側に付ける（手より前に出さない）
m = rig.matrix_world
fa = (m @ rig.pose.bones["lowerarm01.L"].head + m @ rig.pose.bones["wrist.L"].head) / 2
box("shield", (0.30, 0.04, 0.40), fa + Vector((0.07, -0.06, 0.06)), "shield")
box("boss", (0.08, 0.03, 0.08), fa + Vector((0.07, -0.085, 0.06)), "gold")
scene = bpy.context.scene
sun = bpy.data.lights.new("sun", "SUN"); sun.energy = 3.0
so = bpy.data.objects.new("sun", sun); scene.collection.objects.link(so)
so.rotation_euler = (math.radians(45), 0, math.radians(-35))   # 光は左上
cam = Vector((-2.6, -4.0, 1.35))                                 # 左斜め前（人物は右手を絵の左に見せる）
look_from(scene, Vector((0, 0, 0.9)), cam, 2.2)
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"; scene.cycles.samples = 16
scene.view_settings.view_transform = "Standard"; scene.world.use_nodes = False; scene.world.color = (0.45, 0.45, 0.45)
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = 240, 400
scene.render.filepath = os.path.abspath(sys.argv[1]); bpy.ops.render.render(write_still=True)
sys.stdout.flush(); os._exit(0)
