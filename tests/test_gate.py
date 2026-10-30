"""関所（tools/gen/gate.py）が、わざと崩す工程を戻し、崩さない工程を受け入れるかの試験。模型は読まず、部位分けは色で決める偽物"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import gate  # noqa: E402
import photoreal  # noqa: E402

SKIN = (222, 182, 160)
HAIR = (25, 22, 22)


def fake_parts(img):
    a = np.asarray(img).astype(int)
    seg = np.zeros(a.shape[:2], np.uint8)
    seg[(np.abs(a - SKIN).sum(-1) < 40)] = 12
    seg[(a.max(-1) < 60)] = 2
    return seg


def figure():
    a = np.full((1152, 768, 3), 150, np.uint8)
    a[300:1100, 300:460] = SKIN                    # 体（脚）
    a[150:300, 320:440] = HAIR                     # 髪
    return Image.fromarray(a)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.img = figure()
        self.g = gate.Gate(fake_parts(self.img), log=lambda *x: None, parts_fn=fake_parts, face_fn=None, digits_fn=None, retries=0)

    def test_fakes_are_reverted(self):
        for kind in ("swell", "nohair", "whiteedge"):
            out = self.g.step(kind, self.img, lambda k, kd=kind: photoreal.fake_break(self.img, Image.fromarray(fake_parts(self.img)), kd))
            self.assertIs(out, self.img, kind)
        self.assertEqual([r["accepted"] for r in self.g.rows], [False, False, False])
        self.assertIn("contour_extra", self.g.rows[0]["worse"])
        self.assertIn("hair_loss", self.g.rows[1]["worse"])
        self.assertTrue({"halo", "halo_feet"} & set(self.g.rows[2]["worse"]))

    def test_harmless_step_is_accepted_and_report_written(self):
        out = self.g.step("same", self.img, lambda k: self.img.copy())
        self.assertIsNot(out, self.img)
        with tempfile.TemporaryDirectory() as d:
            self.g.write(Path(d))
            self.assertIn("受け入れ", (Path(d) / "report.md").read_text(encoding="utf-8"))

    def test_retry_until_good(self):
        g = gate.Gate(fake_parts(self.img), log=lambda *x: None, parts_fn=fake_parts, face_fn=None, digits_fn=None, retries=2)
        bad = photoreal.fake_break(self.img, Image.fromarray(fake_parts(self.img)), "nohair")
        out = g.step("draw", self.img, lambda k: bad if k < 2 else self.img.copy(), retry=True)
        self.assertIsNot(out, self.img)
        self.assertEqual(g.rows[0]["tries"], 3)


    def test_harmless_variants_keep_contour(self):
        # 粒と JPEG で輪郭の数字が戻す側に振れないこと（前の周は粒だけで contour_extra が 3.6 → 8.1 になり全部戻された）。
        # 偽の部位分けは色で決めるので明るさの変化は読めず、平らな絵は skin_vstep が粒で動くため、輪郭の数字だけを見る
        before = self.g.measure(self.img)
        for name, v in gate.harmless_variants(self.img).items():
            if name.startswith("bright"):
                continue
            bad = self.g.worse(before, self.g.measure(v))
            self.assertFalse({"contour_dev", "contour_extra", "hair_loss"} & set(bad), (name, bad))

    def test_tolerance_above_measured_jitter(self):
        measured = {"contour_dev": 12.4, "contour_extra": 8.9, "hair_loss": 0.028, "leg_de": 1.61, "skin_vstep": 0.57,
                    "halo": 0.03, "halo_feet": 0.014, "dark_blob_px": 40, "blown_skin": 0.013}
        for k, w in measured.items():
            self.assertGreater(gate.TOL[k], w, k)


    def test_untouched_face_keeps_face_value(self):
        # 顔に触れない工程で目の読みが揺れても、face_bad は前の値のまま（10/27 の周、縁と床の影の工程が face_bad 0 → 1 で戻された）
        seg = fake_parts(self.img).copy()
        seg[200:280, 340:420] = 11
        calls = iter([0, 1, 1])
        g = gate.Gate(seg, log=lambda *x: None, parts_fn=fake_parts, retries=0, digits_fn=None,
                      face_fn=lambda im: {"eyes": {"readable": next(calls) == 0}})
        a = np.asarray(self.img).copy()
        a[1120:1150, 0:100] = 140                  # 床の隅だけ変える
        self.assertIsNot(g.step("floor", self.img, lambda k: Image.fromarray(a)), self.img)
        b = np.asarray(self.img).copy()
        b[230:250, 360:400] = 200                  # 顔を変える
        self.assertIs(g.step("face", self.img, lambda k: Image.fromarray(b)), self.img)
        self.assertIn("face_bad", g.rows[1]["worse"])

    def test_more_broken_digits_are_reverted(self):
        n = iter([0, 1])
        g = gate.Gate(fake_parts(self.img), log=lambda *x: None, parts_fn=fake_parts, face_fn=None, retries=0,
                      digits_fn=lambda im: next(n))
        b = np.asarray(self.img).copy()
        b[1050:1100, 300:460] = (230, 190, 170)    # 足を変える
        self.assertIs(g.step("feet", self.img, lambda k: Image.fromarray(b)), self.img)
        self.assertIn("digits_bad", g.rows[0]["worse"])


if __name__ == "__main__":
    unittest.main()
