"""検品の升目（qc.tiles）。どの画素も少なくとも1つの升目に入り、升目は拡大されているかを見る"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
try:
    import qc  # noqa: E402
    HAS_QC = True
except ImportError:   # 画像生成の部品が無い環境では飛ばす
    HAS_QC = False


@unittest.skipUnless(HAS_QC, "qc の読み込みに要る部品が無い（sh tools/gen/setup.sh）")
class TilesTest(unittest.TestCase):
    def test_tiles_cover_every_pixel_and_are_zoomed(self):
        with tempfile.TemporaryDirectory() as d:
            src = str(Path(d) / "w.png")
            Image.new("RGB", (768, 1344), "white").save(src)
            r = qc.tiles(src, str(Path(d) / "t"), zoom=3.0)
            seen = np.zeros((1344, 768), bool)
            for t in r["tiles"]:
                x0, y0, x1, y1 = t["box"]
                seen[y0:y1, x0:x1] = True
                self.assertEqual(Image.open(t["file"]).size, (int((x1 - x0) * 3), int((y1 - y0) * 3)))
            self.assertTrue(seen.all())


if __name__ == "__main__":
    unittest.main()
