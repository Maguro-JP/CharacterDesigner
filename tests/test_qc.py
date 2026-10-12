"""検品の下ごしらえ（tools/gen/qc.py）の、模型を使わない計算の試験。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402

try:
    import scipy  # noqa: F401  描く部品（.cache/gen/lib）に入っている
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def canvas():
    a = np.full((200, 120, 3), 255, np.uint8)
    a[40:180, 40:80] = (60, 60, 70)          # 人物
    return a


@unittest.skipUnless(HAS_SCIPY, "描く部品（scipy）が無い")
class Floating(unittest.TestCase):
    def test_detached_cloth_is_found(self):
        a = canvas()
        a[20:40, 90:110] = (200, 40, 40)      # 人物から離れた布
        r = qc.floating_blobs(a)
        self.assertTrue(r["plain_background"])
        self.assertEqual(len(r["blobs"]), 1)
        self.assertEqual(r["blobs"][0]["box"], [90, 20, 109, 39])

    def test_attached_parts_and_specks_are_not_counted(self):
        a = canvas()
        a[60:62, 80:100] = (200, 40, 40)      # 体につながった布
        a[5, 5] = (0, 0, 0)                   # 1画素の点（影の粒）
        self.assertEqual(qc.floating_blobs(a)["blobs"], [])

    def test_busy_background_is_not_judged(self):
        a = (np.random.default_rng(0).random((200, 120, 3)) * 255).astype(np.uint8)
        self.assertFalse(qc.floating_blobs(a)["plain_background"])


class Tiles(unittest.TestCase):
    def test_tiles_cover_the_figure(self):
        box = (10, 20, 210, 420)
        ts = qc.tiles(box, rows=4, cols=2)
        self.assertEqual(len(ts), 8)
        cover = np.zeros((500, 300), bool)
        for x0, y0, x1, y1 in ts:
            cover[y0:y1, x0:x1] = True
        self.assertTrue(cover[20:420, 10:210].all())   # 人物の枠に見ていない所が無い


class Colors(unittest.TestCase):
    def test_gap_between_views_is_reported(self):
        hair = qc.HAIR
        a = {hair: np.array([120.0, 80, 50])}
        b = {hair: np.array([122.0, 82, 50])}
        c = {hair: np.array([40.0, 40, 40])}       # 髪が黒くなった絵
        self.assertEqual(qc.color_gaps([a, b]), [])
        gaps = qc.color_gaps([a, b, c])
        self.assertEqual(gaps[0]["part"], "髪")
        self.assertIn(2, gaps[0]["between"])

    def test_nouns_missing_uses_the_head_noun(self):
        vocab = {"cape", "skirt", "boots", "knees", "red scarf"}
        got = {"skirt": 0.9, "boots": 0.8}
        out = qc.nouns_missing("dark red cape, long black skirt to the knees, armored boots up to the knees, red scarf", got, vocab)
        self.assertEqual(len(out), 1)
        self.assertIn("cape", out[0])


if __name__ == "__main__":
    unittest.main()
