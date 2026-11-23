"""描いたキャラデザから骨付きの 3D（VRM と glTF）を作る道（tools/engine/chara3d.py）の試験。
本物と同じ道を通すため、手で描いた三面図の人形を絵として渡し、書き出した .vrm を読み戻して確かめる。"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "engine"))
sys.path.insert(0, str(ROOT))
import chara3d  # noqa: E402

REQUIRED = ["hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm",
            "rightHand", "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot"]


def figure(side=False, w=200, h=400, col=(200, 60, 60)):
    """白地に、頭・胴・離れた腕・2 本の脚の人形を描く。顔は白にして、穴埋めが効くかも見る"""
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    cx = w // 2
    if side:
        d.ellipse((cx - 25, 10, cx + 25, 70), fill=col)
        d.rectangle((cx - 22, 70, cx + 22, 230), fill=col)
        d.rectangle((cx - 15, 230, cx + 15, 395), fill=(40, 40, 60))
        return im
    d.ellipse((cx - 30, 10, cx + 30, 70), fill=col)
    d.ellipse((cx - 15, 25, cx + 15, 55), fill="white")          # 白い顔（背景と同じ色）
    d.rectangle((cx - 35, 70, cx + 35, 220), fill=col)
    for s in (-1, 1):
        d.rectangle((min(cx + s * 55, cx + s * 72), 75, max(cx + s * 55, cx + s * 72), 210), fill=(60, 60, 200))
        d.rectangle((min(cx + s * 5, cx + s * 30), 220, max(cx + s * 5, cx + s * 30), 395), fill=(40, 40, 60))
    return im


class Chara3DTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        sheet = Image.new("RGB", (600, 400), "white")
        sheet.paste(figure(), (0, 0))
        sheet.paste(figure(side=True), (200, 0))
        sheet.paste(figure(col=(60, 160, 60)), (400, 0))
        cls.src = cls.tmp / "doll.png"
        sheet.save(cls.src)
        cls.info = chara3d.make(cls.src, cls.tmp / "out", grid=64)

    def test_files(self):
        for k in ("vrm", "glb", "shot_front", "shot_side", "shot_back", "shot_pose"):
            self.assertTrue(Path(self.info[k]).stat().st_size > 1000, k)
        self.assertEqual(self.info["views"], 3)

    def test_vrm_humanoid_and_mtoon(self):
        g, acc = chara3d.read_glb(Path(self.info["vrm"]))
        self.assertIn("VRMC_vrm", g["extensionsUsed"])
        self.assertEqual(len(g["buffers"]), 1)   # 無いと外の道具で読めなかった
        self.assertTrue(all(v["byteOffset"] + v["byteLength"] <= g["buffers"][0]["byteLength"] for v in g["bufferViews"]))
        bones = g["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
        for b in REQUIRED:
            self.assertIn(b, bones)
        self.assertIn("VRMC_materials_mtoon", g["materials"][0]["extensions"])
        self.assertEqual(len(g["skins"][0]["joints"]), len(chara3d.BONES))

    def test_weights(self):
        g, acc = chara3d.read_glb(Path(self.info["glb"]))
        a = g["meshes"][0]["primitives"][0]["attributes"]
        w, j = acc(a["WEIGHTS_0"]), acc(a["JOINTS_0"])
        pos = acc(a["POSITION"])
        self.assertTrue(np.allclose(w.sum(1), 1, atol=1e-4))
        self.assertLess(j.max(), len(chara3d.BONES))
        idx = acc(g["meshes"][0]["primitives"][0]["indices"])
        self.assertLess(idx.max(), len(pos))
        self.assertAlmostEqual(float(pos[:, 1].max()), chara3d.HEIGHT, delta=0.05)
        # 顔（首より上）は頭だけに付く。顔が骨で歪まないように
        head = chara3d.BONES.index("head")
        top = pos[:, 1] > chara3d.HEIGHT * 0.9
        self.assertTrue((j[top, 0] == head).all())

    def test_arm_moves_alone(self):
        """腕を上げたとき、腕は動き、脚と頭は動かない（重みが区分の中に閉じている）"""
        pos, uv, tris, part = chara3d.build_shape(*self._masks(), 64)
        joints = chara3d.place_bones(pos, part)
        ji, jw = chara3d.skin_weights(pos, joints, part)
        moved = chara3d.pose_vertices(pos, joints, ji, jw, {"leftUpperArm": ((0, 0, 1), 70)})
        d = np.linalg.norm(moved - pos, axis=1)
        self.assertGreater(d[part == 1].mean(), 0.1)
        self.assertLess(d[(part == 3) | (part == 4)].max(), 1e-6)
        self.assertTrue((part == 1).any() and (part == 2).any() and (part == 3).any())

    def _masks(self):
        f = chara3d.crop_view(figure())[1]
        s = chara3d.crop_view(figure(side=True))[1]
        return f, s

    def test_holes_filled(self):
        f = chara3d.crop_view(figure())[1]
        self.assertTrue(f[f.shape[0] // 10, f.shape[1] // 2])   # 白い顔の所も人物に入る

    def test_single_image(self):
        info = chara3d.make(self._single(), self.tmp / "one",
                            grid=48, do_shoot=False)
        self.assertEqual(info["views"], 1)
        self.assertTrue(Path(info["vrm"]).exists())

    def _single(self):
        p = self.tmp / "single.png"
        figure().save(p)
        return p

    def test_dialog_helper(self):
        from atelier.ai.to_3d import make_character
        info = make_character(self._single(), self.tmp / "dlg")
        self.assertTrue(Path(info["sheet"]).exists())
        self.assertEqual(Image.open(info["sheet"]).width, 480 * 4)


    def test_orient_recovers_front(self):
        """外の模型の形が横向き・鏡写しでも、正面の絵と同じ向きに戻す（TripoSR の形は前の軸が違った）"""
        sheet = Image.open(self.src)
        front, fm = chara3d.crop_view(chara3d.split_views(sheet, 3)[0])
        pos, uv, tris, _ = chara3d.build_shape(fm, None, 64)
        # 左右で色を変え、鏡写しを色で見分けられるようにする
        color = np.where(pos[:, :1] > 0, [[0.9, 0.2, 0.2]], [[0.2, 0.2, 0.9]]).astype(np.float32)
        img = Image.new("RGBA", front.size, (0, 0, 0, 0))
        a = np.array(img)
        a[..., 3] = fm * 255
        a[:, a.shape[1] // 2:, :3] = [230, 51, 51]
        a[:, :a.shape[1] // 2, :3] = [51, 51, 230]
        turned = (pos @ chara3d._rot((0, 1, 0), 90).T) * [-1, 1, 1]
        back, t2, info = chara3d.orient(turned.astype(np.float32), color, tris[:, ::-1].copy(), Image.fromarray(a), fm)
        self.assertGreater(info["iou"], 0.6)
        self.assertTrue(np.allclose(back[:, 0], pos[:, 0], atol=1e-4), info)

    def test_texture_uses_side_view(self):
        """横を向いた面には横の絵を貼る（前と後ろだけだと横から見て真ん中で割れた）"""
        g, acc = chara3d.read_glb(Path(self.info["glb"]))
        uv = acc(g["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"])
        panels = np.floor(uv[:, 0] * 3).astype(int)
        self.assertEqual(set(np.unique(panels)) >= {0, 1, 2}, True)

    def test_smooth_rounds_stairs(self):
        """ならすと縁の階段が減る（隣の点との高さの差の合計が小さくなる）"""
        f = chara3d.crop_view(figure())[1]
        pos, _uv, tris, _ = chara3d.build_shape(f, None, 64)
        def rough(p):
            e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]]])
            return float(np.abs(np.diff(p[e][:, :, 0], axis=1)).sum())
        self.assertLess(rough(chara3d.smooth(pos, tris)), rough(pos))


if __name__ == "__main__":
    unittest.main()
