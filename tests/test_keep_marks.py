"""機械の検品で外れた絵を捨てず、直す所の印を付けて残すことの試験。

機械の検品で絵を落として一覧から外すと、人が魅力を感じた絵まで消えた。基準は人で、検品は直す所を挙げる役。
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import design  # noqa: E402
import measure  # noqa: E402
import qc  # noqa: E402


class RequestKindTest(unittest.TestCase):
    def test_style_color_background_are_requests(self):
        norms = json.loads(measure.NORMS.read_text(encoding="utf-8"))
        kinds = {c["path"]: c.get("kind", "flaw") for c in norms["checks"]}
        for p in ("style.realism", "colors.mismatch", "background.corner_lum", "background.corner_sat"):
            self.assertEqual(kinds[p], "request", p)
        for p in ("face.rms", "eyes.iris_delta", "light.inverted"):
            self.assertEqual(kinds[p], "flaw", p)

    def test_judge_carries_kind(self):
        norms = {"checks": [{"path": "style.realism", "max": 0.34, "means": "x", "kind": "request"},
                            {"path": "face.rms", "max": 0.07, "means": "y"}]}
        out = measure.judge({"style": {"realism": 0.9}, "face": {"rms": 0.2}}, norms)
        self.assertEqual([o.get("kind") for o in out], ["request", None])

    def test_user_norms_keep_base_kind(self):
        old = measure.USER_NORMS
        with tempfile.TemporaryDirectory() as t:
            measure.USER_NORMS = Path(t) / "u.json"
            measure.USER_NORMS.write_text(json.dumps({"checks": [{"path": "style.realism", "max": 0.1, "means": "学んだ"}]}))
            try:
                c = next(c for c in measure.load_norms()["checks"] if c["path"] == "style.realism")
            finally:
                measure.USER_NORMS = old
        self.assertEqual((c["max"], c["kind"]), (0.1, "request"))


class MarksTest(unittest.TestCase):
    def test_marks_split_fix_and_layout(self):
        res = {"problems": [{"edge_cut": ["下"]}, {"measure": {"path": "eyes.iris_delta", "value": 0.1}},
                            {"measure": {"path": "light.inverted", "value": 2}}, {"fixed_restriction": "x"}],
               "unreadable": [{"person": {"found": False}}]}
        got = {(m["what"], m["kind"], m["repair"]) for m in qc.marks(res)}
        self.assertEqual(got, {("edge_cut", "layout", "none"), ("eyes.iris_delta", "fix", "face_fix"),
                               ("light.inverted", "fix", "inpaint"), ("person", "layout", "none")})

    def test_person_marks_from_inspect(self):
        m = design.person_marks(["人物と離れた物がある（塊が 2 つ）", "腕が無い", "体が画面の端で切れている"])
        self.assertEqual([x["kind"] for x in m], ["layout", "fix", "layout"])


class KeepPicturesTest(unittest.TestCase):
    def test_machine_failures_stay_in_the_list(self):
        with tempfile.TemporaryDirectory() as t:
            # 以前の道具が書いた auto_rejected.json が残っていても、一覧から外さない
            (Path(t) / "auto_rejected.json").write_text(json.dumps({"h-7.png": "腕が無い"}))
            cast = {"n": 2, "characters": [{"id": "h", "full_prompt": "a knight"}]}
            shots = [p.name for _, s in design.cast_paths(cast, t) for p, _, _ in s]
        self.assertEqual(shots, ["h-7.png", "h-8.png"])

    def test_check_person_keeps_picture_and_marks(self):
        calls = []
        fake = types.SimpleNamespace(inspect=lambda p: ["人物と離れた物がある（塊が 2 つ）"],
                                     clean_background=lambda p: calls.append(p))
        old = sys.modules.get("edit")
        sys.modules["edit"] = fake
        try:
            with tempfile.TemporaryDirectory() as t:
                p = Path(t) / "h-7.png"
                p.write_bytes(b"x")
                reasons, marks = design.check_person(p)
                self.assertTrue(p.exists() and (Path(t) / "h-7.raw.png").exists())
        finally:
            if old is None:
                sys.modules.pop("edit")
            else:
                sys.modules["edit"] = old
        self.assertEqual(marks[0]["kind"], "layout")
        self.assertEqual(calls, [])  # 2人目のいる絵は背景を消さない（消すと片方が消える）

    def test_face_flaws_are_fixed_automatically(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / "a.png", Path(t) / "b.png"
            for p in (a, b):
                p.write_bytes(b"x")
                Path(str(p) + ".json").write_text(json.dumps({"prompt": "1girl", "marks": []}))
            eye = {"what": "eyes.iris_delta", "kind": "fix", "repair": "face_fix", "where": {}}

            def check(src, prompt):
                bad = src.endswith("a.png")
                return {"ok": not bad, "marks": [eye] if bad else [], "differences": [{"measure": {"path": "style.realism"}}]}

            fixed = []

            def fix(src, out):
                fixed.append(src)
                Path(out).write_bytes(b"y")
                return {"fixed": True, "box": [0, 0, 1, 1]}

            done = design.auto_face_fix([a, b], fix=fix, check=check)
            meta = json.loads(Path(str(a) + ".json").read_text())
            self.assertEqual(fixed, [str(a)])
            self.assertEqual(list(done), [str(a)])
            self.assertEqual(meta["facefix"]["file"], "a.facefix.png")
            self.assertTrue(a.exists())  # 元の絵は残す
            self.assertEqual(meta["marks"], [eye])
            self.assertIn("differences", meta)


if __name__ == "__main__":
    unittest.main()
