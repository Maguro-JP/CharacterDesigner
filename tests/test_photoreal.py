"""写真級の描き直し（tools/gen/photoreal.py）の、模型を読まない部分の試験。"""
import json
import tempfile
import unittest
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import photoreal  # noqa: E402


def _pair(tmp_path):
    tmp_path = Path(tmp_path)
    a = np.full((120, 80, 3), 200, np.uint8)
    p = np.zeros((120, 80), np.uint8)
    p[20:110, 25:55] = 12                    # 肌
    a[20:110, 25:55] = (230, 190, 170)
    p[60:100, 55:62] = 7                     # 服の暗い帯
    a[60:100, 55:62] = 10
    src = tmp_path / "x.png"
    Image.fromarray(a).save(src)
    Image.fromarray(p).save(str(src) + ".parts.png")
    return src


class PhotorealTest(unittest.TestCase):
    def test_band_filled_from_background(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            src = _pair(tmp_path)
            im, parts = photoreal.load_source(src, 80, 120)
            out, px = photoreal.clean_band(im, parts)
            o = np.asarray(out)
            assert px > 0
            assert o[60:100, 55:62].max(2).min() > 150          # 帯が背景の明るさで埋まる
            assert (o[30:100, 30:50] == (230, 190, 170)).all()  # 肌には触らない

    def test_blob_scaled_by_width(self):
        a = np.full((400, 768, 3), 200, np.float32)
        a[100:120, 100:120] = 10                      # 400 画素の浮いた塊
        a[300:302, 300:302] = 10                      # 4 画素の点は外す
        self.assertEqual(int(photoreal.find_blobs(a).sum()), 400)
        b = np.full((800, 1536, 3), 200, np.float32)
        b[200:240, 200:240] = 10                      # 2 倍の幅では 1600 画素で同じ塊
        b[600:610, 600:610] = 10                      # 100 画素は 768 幅の 25 画素相当で外す
        self.assertEqual(int(photoreal.find_blobs(b).sum()), 1600)

    def test_hfmix_keeps_low_from_stage2(self):
        from PIL import Image as I
        s1 = I.fromarray(np.random.default_rng(0).integers(0, 255, (64, 64, 3), dtype=np.uint8))
        s2 = I.new("RGB", (96, 96), (120, 120, 120))
        o = np.asarray(photoreal.hfmix(s1, s2)).astype(float)
        self.assertLess(abs(o.mean() - 120), 6)
        self.assertGreater(o.std(), 3)

    def test_tiles_cover_edges(self):
        xs = photoreal.tiles(1152, 768, 128)
        assert xs[0] == 0 and xs[-1] == 1152 - 768
        assert photoreal.tiles(500, 768, 128) == [0]

    def test_dry_run_writes_without_models(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            src = _pair(tmp_path)
            out = tmp_path / "out"
            assert photoreal.main([str(src), str(out), "--width", "80", "--height", "120", "--dry-run"]) == 0
            assert (out / "x-0-clean.png").exists() and (out / "x-0-lineart.png").exists()
            assert json.loads((out / "times.json").read_text())["band_px"] > 0

    def test_request_points_at_tracked_image(self):
        req = json.loads((ROOT / "config" / "photoreal-request.json").read_text())
        assert not req["src"].startswith(".worklog")
        assert (ROOT / req["src"]).exists()   # .parts.png は git に入れないので、無ければ台本が作る



if __name__ == "__main__":
    unittest.main()
