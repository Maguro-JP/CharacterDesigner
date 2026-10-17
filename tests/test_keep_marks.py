"""機械の検品で外れた絵を捨てず、直す所の印を付けて残すことの試験。

機械の検品で絵を落として一覧から外すと、人が魅力を感じた絵まで消えた。基準は人で、検品は直す所を挙げる役。
"""
import json
import os
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

            def fix(src, out, prompt=""):
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

    def _one(self, t, before, after):
        a = Path(t) / "a.png"
        a.write_bytes(b"x")
        Path(str(a) + ".json").write_text(json.dumps({"prompt": "1girl, head tilt, gentle smile", "marks": []}))
        prompts = []

        def check(src, prompt):
            return {"ok": False, "marks": after if "facefix" in src else before}

        def fix(src, out, prompt=""):
            prompts.append(prompt)
            Path(out).write_bytes(b"y")
            return {"fixed": True, "box": [0, 0, 1, 1]}

        design.auto_face_fix([a], fix=fix, check=check)
        return a, json.loads(Path(str(a) + ".json").read_text()), prompts

    @staticmethod
    def _rms(v):
        return {"what": "face.rms", "kind": "fix", "repair": "face_fix", "where": {"path": "face.rms", "value": v, "min": None, "max": 0.07}}

    def test_worse_face_fix_is_not_adopted(self):
        # 7周目の 702: 0.091 → 0.181。悪くなった直しは採らず、元の絵を正として印に書く
        with tempfile.TemporaryDirectory() as t:
            a, meta, prompts = self._one(t, [self._rms(0.091)], [self._rms(0.181)])
            self.assertFalse(meta["facefix"]["adopted"])
            self.assertEqual(meta["facefix"]["file"], "a.facefix.rejected.png")
            self.assertFalse((Path(t) / "a.facefix.png").exists())
            self.assertTrue((Path(t) / "a.facefix.rejected.png").exists())
            self.assertEqual(meta["marks"][-1]["what"], "face_fix_rejected")
            self.assertIn("採らない", design.result_line(a))

    def test_better_face_fix_is_adopted(self):
        with tempfile.TemporaryDirectory() as t:
            a, meta, _ = self._one(t, [self._rms(0.133)], [self._rms(0.08)])
            self.assertTrue(meta["facefix"]["adopted"])
            self.assertTrue((Path(t) / "a.facefix.png").exists())

    def test_result_line_follows_marks(self):
        # 描いた直後の行は作画監督の検品より前。最後の結果の行は marks と合う
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "a.png"
            Path(str(a) + ".json").write_text(json.dumps({"marks": [self._rms(0.076), {"what": "eyes.found"}]}))
            self.assertIn("直す所 2（face.rms、eyes.found）", design.result_line(a))
            Path(str(a) + ".json").write_text(json.dumps({"marks": []}))
            self.assertIn("外れなし", design.result_line(a))


class FakeTok:
    """読点と単語を1トークンずつに数える代わりの読み手"""
    class R:
        def __init__(self, ids):
            self.input_ids = ids

    def __call__(self, text, add_special_tokens=False, verbose=True):
        return self.R([0 if w == "," else 1 for w in text.replace(",", " , ").split()])


class SplitTokensTest(unittest.TestCase):
    def test_cut_at_last_comma(self):
        # 7周目: 80 トークンの指示文が 75 個目で切れ、clean lineart が割れた
        text = ", ".join(["a b"] * 26) + ", clean lineart, white background"
        parts = design.split_tokens(FakeTok(), text)
        self.assertTrue(all(len(c) <= 75 for c in parts))
        self.assertEqual(sum(map(len, parts)), len(FakeTok()(text).input_ids))
        self.assertEqual(parts[0][-1], 0)  # 区切りは読点の直後
        self.assertEqual(design.split_tokens(FakeTok(), ""), [[]])


class HubDefaultsTest(unittest.TestCase):
    def test_constants_follow_even_if_hub_was_imported_first(self):
        import types
        fake = types.SimpleNamespace(HF_HOME="/root/.cache/huggingface", HF_HUB_CACHE="/root/.cache/huggingface/hub",
                                     HF_ASSETS_CACHE="x", HF_HUB_OFFLINE=False)
        keep = {k: os.environ.pop(k, None) for k in ("HF_HOME", "HF_HUB_OFFLINE", "HF_HUB_CACHE", "CD_FETCH")}
        old = sys.modules.get("huggingface_hub.constants")
        sys.modules["huggingface_hub.constants"] = fake
        try:
            design.hub_defaults()
            self.assertTrue(fake.HF_HUB_CACHE.endswith(os.path.join(".cache", "gen", "hf", "hub")))
            self.assertTrue(fake.HF_HUB_OFFLINE)
        finally:
            if old is None:
                sys.modules.pop("huggingface_hub.constants")
            else:
                sys.modules["huggingface_hub.constants"] = old
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
