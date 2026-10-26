"""顔の検品（tools/gen/facecheck.py）の試験。

判定の規則は模型なしで確かめる。絵を使う試験は、手元に絵と模型（VitPose、wd-vit-tagger-v3）があるときだけ動く。
誤りの警告（普通の顔を崩れにする）を避けるのが大事なので、普通の顔の絵は崩れ 0 件を確かめる。
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
sys.path.insert(0, str(ROOT))
import facecheck as face  # noqa: E402

# 試した絵の置き場（FACE_SAMPLES）と模型の置き場（FACE_HUB）。無ければ絵の試験は飛ばす
SAMPLES = Path(os.environ.get("FACE_SAMPLES", "/nonexistent"))
HUB = os.environ.get("FACE_HUB")
FACELESS = ["bk-3-pose-depth-s7.png"]
NORMAL = ["bk-comp.png", "cp-comp.png", "ts-1-composition.png", "anim-f-front.png", "anim-m-front.png", "anim-m-elf.png",
          "anim-f-old.png", "anim-m-old.png", "anim-f-dragon.png"]


class JudgeTest(unittest.TestCase):
    def test_closed_eyes_without_ask_is_bad(self):
        self.assertEqual(len(face.judge({"closed eyes": 0.95, "shading eyes": 0.87})), 1)

    def test_closed_eyes_asked_is_ok(self):
        self.assertEqual(face.judge({"closed eyes": 0.95}, asked="1girl, closed eyes, smile"), [])

    def test_open_eyes_ok(self):
        self.assertEqual(face.judge({"brown eyes": 0.8, "closed eyes": 0.07}), [])
        # 閉じた目が強めでも、目の色が読めれば崩れにしない
        self.assertEqual(face.judge({"closed eyes": 0.7, "blue eyes": 0.5}), [])

    def test_faceless(self):
        self.assertIn("目が描かれていない", face.judge({"faceless": 0.6})[0])


class BoxTest(unittest.TestCase):
    def test_no_face_points_is_unreadable(self):
        from PIL import Image
        res = face.check_face(Image.new("RGB", (256, 256), "white"), keypoints={"left_wrist": (10, 10)})
        self.assertFalse(res["readable"])
        self.assertEqual(res["bad"], [])

    def test_small_face_is_unreadable(self):
        self.assertIsNone(face.face_box({"nose": (100, 100), "left_eye": (103, 98), "right_eye": (97, 98)}, (800, 800)))

    def test_box_contains_face(self):
        b = face.face_box({"nose": (400, 160), "left_eye": (420, 140), "right_eye": (380, 140), "left_ear": (445, 150),
                           "right_ear": (355, 150)}, (832, 1216))
        self.assertTrue(b[0] < 380 and b[2] > 420 and b[1] < 140 and b[3] > 160)


@unittest.skipUnless(HUB and SAMPLES.is_dir(), "顔の試験の絵か模型がありません（FACE_SAMPLES と FACE_HUB）")
class ImageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import chatdraw.paths as paths
        paths.HUB = Path(HUB)

    def _run(self, name):
        p = SAMPLES / name
        if not p.exists():
            self.skipTest(f"{name} がありません")
        return face.check_face(p)

    def test_faceless_found(self):
        for n in FACELESS:
            res = self._run(n)
            self.assertTrue(res["readable"], n)
            self.assertTrue(res["bad"], n)

    def test_normal_faces_pass(self):
        for n in NORMAL:
            with self.subTest(n=n):
                self.assertEqual(self._run(n)["bad"], [])


if __name__ == "__main__":
    unittest.main()
