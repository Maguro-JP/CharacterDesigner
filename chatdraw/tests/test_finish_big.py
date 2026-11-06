"""拡大のあとの大きな絵でも加工が必ず終わること（区画に分ける・進みを出す・止められる）と、
加工のあとの崩れの検品（崩れた所は元に戻し、崩れが広ければ採らない）を、本物の加工で確かめる"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402


def big(size=(2000, 1600)) -> Image.Image:
    im = Image.new("RGB", size, (240, 230, 220))
    d = ImageDraw.Draw(im)
    for i in range(0, size[0], 150):
        d.ellipse((i, 200, i + 120, 1400), fill=(200, 80 + i % 100, 80), outline=(20, 20, 20), width=4)
    for y in range(0, size[1], 9):
        d.point([(x, y) for x in range(0, size[0], 7)], fill=(120, 120, 120))
    return im


class BigTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.engine import STOP
        STOP.clear()

    def test_big_image_is_tiled_with_progress_and_same_size(self):
        from chatdraw import finishers
        src = big()
        said = []
        out = finishers.run("clean", src, say=said.append)
        self.assertEqual(out.size, src.size)
        self.assertGreaterEqual(len([s for s in said if "/" in s]), 4)   # 2000×1600 は 1024 の区画で 4 つ
        self.assertIsNotNone(ImageChops.difference(src, out).getbbox())

    def test_tiles_match_whole_image_away_from_edges(self):
        """区画に分けても、糊代のおかげで区画の継ぎ目に段が出ない（区画に分けない掛け方と同じ画素になる）"""
        import numpy as np
        from PIL import ImageFilter
        from chatdraw import finishers
        src = big()
        fn = lambda im: im.filter(ImageFilter.MedianFilter(5))   # noqa: E731
        whole = np.asarray(fn(src), int)
        tiles = np.asarray(finishers.tiled(fn, src), int)
        self.assertEqual(int(np.abs(whole - tiles).max()), 0)

    def test_stop_between_tiles(self):
        from chatdraw import finishers
        from chatdraw.engine import STOP, Stopped
        src = big()
        seen = []

        def say(text):
            seen.append(text)
            if len(seen) == 2:
                STOP.set()
        with self.assertRaises(Stopped):
            finishers.run("clean", src, say=say)
        self.assertLess(len(seen), 5)
        STOP.clear()

    def test_mask_on_big_image_only_touches_inside(self):
        from chatdraw import finishers
        src = big()
        mask = Image.new("L", src.size, 0)
        ImageDraw.Draw(mask).rectangle((100, 100, 600, 500), fill=255)
        said = []
        out = finishers.run("retouch", src, mask, say=said.append)
        diff = ImageChops.difference(src, out).getbbox()
        if diff is not None:
            self.assertTrue(diff[0] >= 100 and diff[1] >= 100 and diff[2] <= 601 and diff[3] <= 501, diff)
        self.assertTrue(any("選んで" in s for s in said))   # 工程は縮めた写しで選ぶ

    def test_effect_at_work_size_keeps_lines(self):
        """光は作業の大きさで掛け、足した分だけを広げる。元の線の画素はぼけない（変わりは光の分だけ）"""
        import numpy as np
        from chatdraw import finishers
        src = big((2600, 1600))
        out = finishers.run("air_haze", src)
        self.assertEqual(out.size, src.size)
        a, b = np.asarray(src, float), np.asarray(out, float)
        self.assertGreater(np.abs(a - b).mean(), 0.5)


class GuardTest(unittest.TestCase):
    def test_broken_cells_go_back_and_others_stay(self):
        import numpy as np
        from chatdraw import finishers
        src = big((640, 640))
        out = src.point(lambda v: min(255, v + 6))   # 全体の明るさの直し（崩れではない）
        ImageDraw.Draw(out).rectangle((64, 64, 127, 127), fill=(0, 0, 0))   # 黒い塊（崩れ）
        got = finishers.guard("clean", src, out)
        q = finishers.LAST_QC
        self.assertGreaterEqual(q["broken"], 4)
        self.assertFalse(q["rejected"])
        self.assertEqual(got.getpixel((96, 96)), src.getpixel((96, 96)))   # 塊は元に戻る
        self.assertEqual(got.getpixel((500, 500)), out.getpixel((500, 500)))   # ほかの直しは残る
        self.assertIn("元の絵に戻しました", finishers.qc_note())
        self.assertTrue(np.array_equal(np.asarray(finishers.guard("clean", src, src)), np.asarray(src)))
        self.assertEqual(finishers.LAST_QC["broken"], 0)

    def test_wide_breakage_is_rejected(self):
        from chatdraw import finishers
        src = big((640, 640))
        out = src.copy()
        ImageDraw.Draw(out).rectangle((0, 0, 639, 400), fill=(0, 0, 0))
        got = finishers.guard("retouch", src, out)
        self.assertTrue(finishers.LAST_QC["rejected"])
        self.assertIsNone(ImageChops.difference(src, got).getbbox())
        self.assertIn("掛けずに元の絵のまま", finishers.qc_note())

    def test_lost_lines_are_breakage(self):
        from chatdraw import finishers
        src = big((640, 640))
        out = src.copy()
        ImageDraw.Draw(out).rectangle((140, 190, 280, 330), fill=(240, 230, 220))   # 線を塗りつぶして消す
        finishers.guard("clean", src, out)
        self.assertGreater(finishers.LAST_QC["line"] + finishers.LAST_QC["color"], 0)

    def test_effects_and_ink_are_not_checked(self):
        from chatdraw import finishers
        src = big((320, 320))
        out = Image.new("RGB", src.size, (255, 255, 255))
        self.assertIs(finishers.guard("ink", src, out), out)
        self.assertEqual(finishers.LAST_QC, {})


if __name__ == "__main__":
    unittest.main()
