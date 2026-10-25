"""人形の下ろした手だけを、指を離して開いた形で大きく撮り、奥行きの下絵にする（片手ずつ）。

絵の手の枠だけを描き直すとき、ControlNet の奥行きで指の本数と離れ方を縛るために使う。
骨組みの手の 21 点や、検品を通った手の移植では、下ろした手が指の分かれない塊になった（羊娘のポーズ）。

使い方: PYTHONPATH=.cache/engine/bpy python3 tools/engine/pose_hand.py <depth.png> --side L [--spread 14 --curl 10]
写る向きは正面から（yaw 0）。手首が上、指先が下。手の長さが絵の縦の約 7 割になるよう写す
"""
import os
import sys

import bpy  # noqa: F401
from mathutils import Vector

from pose_depth import args, argv, check, mannequin, shoot


def _emit(name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def hand_mask_shot(out, h, side, width, height, center, frame):
    """手の骨（手首・手の甲・指）に重みのある面だけを白、ほかの体を灰で撮る。
    腰に当てた手は腰と同じ奥行きにあり、奥行きの絵では手と腰の境が出なかった"""
    import math as _m
    from pose_prop import look_from
    scene = bpy.context.scene
    look_from(scene, center, Vector((center.x, center.y - 4.8, center.z)), frame)
    groups = {g.index for g in h.vertex_groups if g.name.endswith("." + side) and g.name.startswith(("wrist", "finger", "metacarpal"))}
    mesh = h.data
    mesh.materials.clear()
    mesh.materials.append(_emit("body", (0.25, 0.25, 0.25, 1)))
    mesh.materials.append(_emit("hand", (1, 1, 1, 1)))
    hand_v = {v.index for v in mesh.vertices if sum(g.weight for g in v.groups if g.group in groups) > 0.5}
    for poly in mesh.polygons:
        poly.material_index = 1 if sum(i in hand_v for i in poly.vertices) * 2 > len(poly.vertices) else 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o is not h:
            o.hide_render = True
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 4
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0, 0, 0)
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("撮った（手だけ白）:", out, "手の頂点", len(hand_v))
    sys.stdout.flush()
    os._exit(0)


def main(av):
    a = args(av, 0, [("--side", dict(choices=["L", "R"], required=True)),
                     ("--spread", dict(type=float, default=14.0)), ("--twist", dict(type=float, default=0.0)), ("--hip", dict(action="store_true")), ("--range", dict(type=float, default=0.6)), ("--mask", dict(action="store_true")), ("--hip-at", dict(default="0.17,-0.03,0.93")), ("--curl", dict(type=float, default=10.0))])
    h, rig = mannequin()
    import human
    human.adduct_arms(rig, 15)
    if a.hip:
        # 腰に手を当てた形（pose_relaxed.py と同じ置き方を左右どちらにも）。肘を外へ張り、指は軽く曲げる
        from pose_depth import grip
        sgn = 1 if a.side == "L" else -1
        hx, hy, hz = (float(v) for v in a.hip_at.split(","))
        grip(rig, a.side, Vector((hx * sgn, hy, hz)), Vector((0.55 * sgn, 0.15, 1.05)))
    human.relax_hands(rig, curl=a.curl, spread=a.spread)
    # 前腕をひねって手のひらか手の甲をカメラへ向ける。横向きのままでは指が重なり、奥行きでも 1 つの塊になった
    import math
    for b in () if a.hip else (f"lowerarm01.{a.side}", f"lowerarm02.{a.side}"):
        pb = rig.pose.bones[b]
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, math.radians(a.twist / 2), 0)
    check(rig)
    bpy.context.view_layer.update()
    m = rig.matrix_world
    wrist = m @ rig.pose.bones[f"wrist.{a.side}"].head
    tip = m @ rig.pose.bones[f"finger3-3.{a.side}"].tail
    center = (wrist + tip) / 2
    frame = (wrist - tip).length / 0.7
    print("手首", tuple(round(v, 3) for v in wrist), "指先", tuple(round(v, 3) for v in tip))
    sys.stdout.flush()
    if a.mask:
        hand_mask_shot(a.out, h, a.side, a.width, a.height, Vector(center), frame)
    shoot(a.out, h, [], a.width, a.height, a.yaw, Vector(center), frame, a.range)
    os._exit(0)


if __name__ == "__main__":
    main(argv())
