"""人形に MakeHuman の姿勢（BVH）を当てて撮り、形の下絵（奥行き）にする。

言葉と打ち消しだけでは座る・しゃがむ姿勢が出ず（しゃがむを頼んだ 7 枚中 4 枚が立ったまま）、素材の棚に座る下絵も無かった。
姿勢そのものは人が作った CC0 のポーズ集（MakeHuman の asset pack「Poses 01」、`tools/engine/setup.sh` が
.cache/engine/poses01.zip に取る）から選び、この台本は人形に当てて撮るだけにする。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_bvh.py <depth.png> --pose callharvey3d_sittingdefault [--yaw 0] [--shelf sit-chair]

--shelf を付けると、関節が可動域に収まった姿勢だけを素材の棚（<CD_HOME>/assets/pose/<名前>.png と出典の .json）に置く。
外れた姿勢は棚に置かず、終了コード 3 で止める（人にできない姿勢は描いた絵にそのまま残るため）。
"""
import json
import os
import sys
import zipfile
from pathlib import Path

import bpy  # noqa: F401  mathutils は bpy を読んだあとに使える
from mathutils import Vector

from pose_depth import args, argv, check, mannequin, shoot

from human import CACHE as ENGINE  # noqa: E402  置き場所は human.py と同じ（CD_HOME）
PACKS = ("poses01.zip",)
# 姿勢の種類（撮った奥行きを目で見て分けた）。描く頼みの言葉から棚の下絵を選ぶとき（tools/gen/assets.py の pick_pose）に使う
KINDS = {"chair": ("anrico_sitting02", "anrico_sitting03", "anrico_sitting04", "anrico_sitting10", "callharvey3d_sittingdefault",
                   "callharvey3d_sittingnatural", "milkman_sit_01a", "milkman_swinging_01",
                   "sweetan008_sitting-pose"),
         "chair_legs_crossed": ("callharvey3d_sittinglegscrossed", "mindfront_sitting_in_armchair_holding_wine_glass"),
         "cross_legged": ("callharvey3d_lotus",),
         "floor": ("callharvey3d_sittingfloorstretch2", "elvs_what_have_i_done", "wolgade_sit_on_ground_01"),
         "hug_knees": ("callharvey3d_sittingfloor2", "xhado84_sitting_floor_3")}


def bvh_path(name: str) -> Path:
    """ポーズ集の zip から名前の BVH を取り出し、置いた場所を返す。無ければ選べる名前を出して止める"""
    names = []
    for pack in PACKS:
        z = ENGINE / pack
        if not z.exists():
            continue
        with zipfile.ZipFile(z) as f:
            for n in f.namelist():
                if n.endswith(".bvh"):
                    names.append(Path(n).stem)
                    if Path(n).stem == name:
                        out = ENGINE / "poses" / f"{name}.bvh"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(f.read(n))
                        return out
    sys.exit(f"姿勢「{name}」が無い（sh tools/engine/setup.sh で取る）。選べる名前: {', '.join(sorted(names)) or '無し'}")


def main(av):
    a = args(av, 0, [("--pose", dict(required=True, help="ポーズ集の BVH の名前（拡張子なし）")),
                     ("--shelf", dict(default="", help="外れが無ければ素材の棚にこの名前で置く"))])
    path = bvh_path(a.pose)
    h, rig = mannequin()
    from bl_ext.user_default.mpfb.services.animationservice import AnimationService
    bpy.ops.preferences.addon_enable(module="io_anim_bvh")
    bpy.context.view_layer.objects.active = rig
    AnimationService.import_bvh_file_as_pose(rig, str(path))
    bad = check(rig)
    if a.shelf and bad:
        print(f"棚に置かない（可動域の外れ {len(bad)} 件）", flush=True)
        os._exit(3)
    # 座ると頭の高さが下がるので、人形の外枠の中心を写す
    bpy.context.view_layer.update()
    zs = [(h.matrix_world @ v.co).z for v in h.data.vertices]
    mid = (max(zs) + min(zs)) / 2
    shoot(a.out, h, [], a.width, a.height, a.yaw, Vector((0, 0, mid)), (max(zs) - min(zs)) * 1.15, 0.45, done=not a.shelf)
    if a.shelf:
        shelve(a.out, a.shelf, a.pose)
    sys.stdout.flush()
    os._exit(0)


def shelve(src, name, pose):
    """外れの無い姿勢を素材の棚に置く。棚の形は tools/gen/assets.py の list_poses が読む形"""
    shelf = ENGINE.parent / "assets" / "pose"
    shelf.mkdir(parents=True, exist_ok=True)
    (shelf / f"{name}.png").write_bytes(Path(src).read_bytes())
    (shelf / f"{name}.json").write_text(json.dumps({"title": name, "source": f"MakeHuman asset pack Poses 01: {pose}.bvh",
                                                    "license": "CC0",
                                                    "kind": next((k for k, v in KINDS.items() if pose in v), "")}, ensure_ascii=False, indent=1))
    print(f"棚に置いた: {shelf / name}.png", flush=True)

if __name__ == "__main__":
    main(argv())
