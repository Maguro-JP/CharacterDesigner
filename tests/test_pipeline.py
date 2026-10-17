import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import pipeline  # noqa: E402


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.fail = {}
        self.run_ = dict(pipeline.RUN)
        self.check = dict(pipeline.CHECK)
        for ph in pipeline.PHASES:
            pipeline.RUN[ph] = lambda i, o, v, s, st, ph=ph: self.calls.append((ph, s)) or {"file": f"{ph}-{s}.png"}
            pipeline.CHECK[ph] = lambda r, i, v, st, ph=ph: ["崩れ"] if self.fail.get(ph, 0) > 0 and not self.fail.update({ph: self.fail[ph] - 1}) else []

    def tearDown(self):
        pipeline.RUN.update(self.run_)
        pipeline.CHECK.update(self.check)

    def test_only_failed_phase_is_redone(self):
        self.fail = {"hands": 2}
        with tempfile.TemporaryDirectory() as d:
            st = pipeline.run("x", d)
            self.assertNotIn("stopped", st)
            self.assertEqual([c for c in self.calls if c[0] == "draw"], [("draw", 0)])   # 体は描き直さない
            self.assertEqual([c for c in self.calls if c[0] == "hands"], [("hands", 0), ("hands", 1), ("hands", 2)])
            self.assertEqual(st["phases"]["hands"]["tries"][0]["bad"], ["崩れ"])          # 落ちた試しも残す

    def test_stop_and_resume_from_phase(self):
        self.fail = {"face": 5}
        with tempfile.TemporaryDirectory() as d:
            st = pipeline.run("x", d, tries=2)
            self.assertEqual(st["stopped"], "face")
            self.assertNotIn("hands", st["phases"])                                        # 崩れた絵の上に描かない
            self.fail = {}
            self.calls.clear()
            st = pipeline.run("x", d, start="face")
            self.assertEqual([c[0] for c in self.calls], ["face", "hands", "check"])
            self.assertEqual(st["phases"]["face"]["tries"][-1]["seed"], 2)                  # 種は前の続きから
            self.assertTrue(json.loads((Path(d) / "state.json").read_text())["phases"]["check"]["ok"])


if __name__ == "__main__":
    unittest.main()
