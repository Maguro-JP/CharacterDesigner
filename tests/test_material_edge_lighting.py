"""Material edge-lighting regression tests."""
import unittest

import numpy as np

from tools.gen.materials import _lit_side


class LitSideTests(unittest.TestCase):
    def test_shift_does_not_wrap_right_edge_to_left(self):
        alpha = np.zeros((12, 12), dtype=float)
        alpha[3:9, 10:12] = 1.0

        lit = _lit_side(alpha, 2, dx=-1, dy=0)

        # A circular roll creates a false highlight at the opposite (left) edge.
        self.assertFalse(lit[:, :2].any())
        self.assertTrue(lit[3:9, 10:12].any())

    def test_shift_does_not_wrap_bottom_edge_to_top(self):
        alpha = np.zeros((12, 12), dtype=float)
        alpha[10:12, 3:9] = 1.0

        lit = _lit_side(alpha, 2, dx=0, dy=-1)

        self.assertFalse(lit[:2, :].any())
        self.assertTrue(lit[10:12, 3:9].any())

    def test_empty_mask_stays_empty(self):
        alpha = np.zeros((8, 8), dtype=float)
        self.assertFalse(_lit_side(alpha, 3).any())


if __name__ == "__main__":
    unittest.main()
