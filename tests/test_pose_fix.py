"""ポーズの絵をそろえる手順（tools/gen/pose_fix.py）。模型は使わず、段の飛ばし方と止め方を確かめる。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import pose_fix  # noqa: E402


class PoseFix(unittest.TestCase):
    def test_stops_after_redraw_without_hands_and_skips_done_steps(self):
        calls = []
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "o"
            cfg = Path(t) / "c.json"
            cfg.write_text(json.dumps({"src": "x.png", "pose": "wave", "ref": "r.png", "words": "w.txt", "out": str(out)}))

            def fake(c, o):
                calls.append(1)
                p = o / "1-redraw.png"
                p.write_bytes(b"x")
                return p
            old = pose_fix.step_redraw
            pose_fix.step_redraw = fake
            try:
                self.assertEqual(pose_fix.run(str(cfg)).name, "1-redraw.png")
            finally:
                pose_fix.step_redraw = old
            # 2 回目は出力があるので描かない
            self.assertTrue(pose_fix._done(out / "1-redraw.png"))
        self.assertEqual(calls, [1])


class MirrorEye(unittest.TestCase):
    def test_bad_eye_gets_mirrored_good_eye(self):
        from PIL import Image
        im = Image.new("RGB", (100, 60), "white")
        for x in range(20, 30):
            for y in range(20, 40):
                im.putpixel((x, y), (200, 120, 40) if x < 25 else (255, 255, 255))   # 左半分が橙、右半分が白（ハイライト）
        out = pose_fix.mirror_eye(im, (25, 30), (75, 30), rx=5, ry=8, feather=0.1)
        # 反転して置くので、橙は右半分に来る
        self.assertEqual(out.getpixel((77, 30)), (200, 120, 40))
        self.assertEqual(out.getpixel((73, 30)), (255, 255, 255))
        self.assertEqual(out.getpixel((95, 5)), (255, 255, 255))
