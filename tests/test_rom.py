"""関節の角度の計算（tools/engine/rom_check.py）の試験。Blender は使わない。"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "engine"))
import rom_check  # noqa: E402

I = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


class Angles(unittest.TestCase):
    def test_hinge_sign_and_size(self):
        rel = rom_check.relative(I, I, I, rot_x(90))
        self.assertAlmostEqual(rom_check.hinge_angle(rel), 90, places=6)
        self.assertAlmostEqual(rom_check.hinge_angle(rom_check.relative(I, I, I, rot_x(-30))), -30, places=6)

    def test_relative_removes_parent_motion(self):
        # 親ごと回っても、親から見た子の角度は変わらない
        p = rot_y(70)
        rel = rom_check.relative(I, I, p, rom_check._mul(p, rot_x(45)))
        self.assertAlmostEqual(rom_check.hinge_angle(rel), 45, places=6)

    def test_hinge_front_follows_parent_twist(self):
        # 前の向きが親の Z なら、X まわりの曲げがそのまま角になる。外への開き（Z まわり）は曲げに数えない
        front = [0, 0, 1]
        self.assertAlmostEqual(rom_check.hinge_front(rot_x(40), front), 40, places=6)
        self.assertAlmostEqual(rom_check.hinge_front(rot_x(-25), front), -25, places=6)
        self.assertAlmostEqual(rom_check.hinge_front(rot_y(70), front), 0, places=6)
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        self.assertAlmostEqual(rom_check.hinge_front([[c, -s, 0], [s, c, 0], [0, 0, 1]], front), 0, places=6)

    def test_swing_and_twist(self):
        sw, tw = rom_check.swing_twist(rot_y(120))
        self.assertAlmostEqual(sw, 0, places=6)
        self.assertAlmostEqual(tw, 120, places=4)
        sw, tw = rom_check.swing_twist(rot_x(50))
        self.assertAlmostEqual(sw, 50, places=6)
        self.assertAlmostEqual(tw, 0, places=4)

    def test_judge_uses_tolerance(self):
        self.assertEqual(rom_check.judge("elbow", rot_x(-5)), [])            # 過伸展 5 度は余裕の内
        self.assertTrue(rom_check.judge("elbow", rot_x(-40)))                # 逆曲がり 40 度は外れ
        self.assertTrue(rom_check.judge("knee", rot_x(170)))                 # 曲げすぎ
        self.assertEqual(rom_check.judge("neck", rot_y(60)), [])
        self.assertTrue(rom_check.judge("neck", rot_y(170)))                 # 首が真後ろ


if __name__ == "__main__":
    unittest.main()
