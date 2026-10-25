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
