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
        assert (ROOT / req["src"]).exists() and (ROOT / (req["src"] + ".parts.png")).exists()



if __name__ == "__main__":
    unittest.main()
