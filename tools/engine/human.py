"""MakeHuman の人体を Blender で作り、箱庭ドットの頭身に縮めて、見下ろしの角度から描く（試作）。

手描きの部品だけで体を組むと、顔の長さや髪の大きさが人間の比率から外れた。人体の形は
MakeHuman（体型を数字で変えられる人体モデル、素材は CC0）に任せ、頭身の縮め方と描き方だけを決める。
骨で脚を縮めると足が浮いて腰が沈んだので、頂点を高さで区切って伸縮する（描画器の transforms と同じ考え方）。

前準備: sh tools/engine/setup.sh
使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/human.py out.png [--head 2.2] [--leg 0.55] [--hair short02]
"""
import argparse
import glob
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "engine"
MPFB_DATA = Path.home() / ".config/blender/4.2/extensions/.user/user_default/mpfb/data"


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
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 4
    so = bpy.data.objects.new("sun", sun)
    scene.collection.objects.link(so)
    # 光は左上から（描画器の LIGHT と同じ向き）
    so.rotation_euler = (math.radians(45), 0, math.radians(-60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--head", type=float, default=2.2)
    ap.add_argument("--leg", type=float, default=0.55)
    ap.add_argument("--hair", default="short02")
    ap.add_argument("--size", type=int, default=256)
    a = ap.parse_args()
    setup()
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    human = HumanService.create_human()
    deform(human.data, a.head, a.leg)
    if a.hair:
        HumanService.add_mhclo_asset(glob.glob(str(MPFB_DATA / "hair" / a.hair / "*.mhclo"))[0], human,
                                     asset_type="Hair", subdiv_levels=0)
    zs = [v.co.z for v in human.data.vertices]
    scene = bpy.context.scene
    camera(scene, max(zs) - min(zs))
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = a.size
    scene.render.filepath = os.path.abspath(a.out)
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    sys.argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv
    main()
