"""作画監督の基準の学習（tools/gen/normlearn.py）。記録は作り物を置き、絵を測らずに学び方だけを確かめる"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))

import measure  # noqa: E402
import normlearn  # noqa: E402


def rec(src, verdict, rms, reason="", by="checker", flagged=()):
    return {"src": src, "verdict": verdict, "by": by, "reason": reason, "topics": normlearn.topics_of(reason),
            "flagged": list(flagged), "measure": {"face": {"rms": rms}, "eyes": {"found": 2}},
            "unmeasured": verdict == "reject" and bool(reason) and not normlearn.topics_of(reason)}


class NormLearnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.old = (normlearn.RECORDS, normlearn.USER_NORMS, measure.USER_NORMS)
        normlearn.RECORDS = d / "records.jsonl"
        normlearn.USER_NORMS = measure.USER_NORMS = d / "norms.user.json"

    def tearDown(self):
        normlearn.RECORDS, normlearn.USER_NORMS, measure.USER_NORMS = self.old
        self.tmp.cleanup()

    def write(self, rows):
        normlearn.RECORDS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def face_rule(self):
        return next(c for c in measure.load_norms()["checks"] if c["path"] == "face.rms")

    def test_topics_in_both_languages(self):
        self.assertEqual(normlearn.topics_of("目の左右がおかしい"), ["face"])
        self.assertEqual(normlearn.topics_of("the shadow is brighter"), ["shadow"])
        self.assertEqual(normlearn.topics_of("ポーズが硬い"), [])

    def test_boundary_between_passed_and_rejected(self):
        self.write([rec("a", "pass", 0.02), rec("b", "pass", 0.05), rec("c", "reject", 0.09, "顔が歪む"), rec("d", "reject", 0.12, "目がずれている")])
        out = normlearn.learn()
        ch = {c["path"]: c for c in out["changed"]}
        self.assertTrue(0.05 < ch["face.rms"]["max"][1] < 0.09)
        self.assertTrue(0.05 < self.face_rule()["max"] < 0.09)   # 判定は利用者の基準を重ねて使う

    def test_unrelated_rejections_are_not_examples(self):
        # 剣が2本で戻された絵は、顔の形の手本に数えない（数えると顔の境が正しい顔の値まで締まった）
        self.write([rec("a", "pass", 0.02), rec("b", "pass", 0.05), rec("c", "reject", 0.09, "顔が歪む"), rec("d", "reject", 0.12, "目がずれている"),
                    rec("e", "reject", 0.01, "剣が2本ある")])
        ch = {c["path"]: c for c in normlearn.learn(dry=True)["changed"]}
        self.assertGreater(ch["face.rms"]["max"][1], 0.05)

    def test_overlap_keeps_base(self):
        self.write([rec("a", "pass", 0.10), rec("b", "pass", 0.02), rec("c", "reject", 0.03, "顔が歪む"), rec("d", "reject", 0.12, "目がずれている")])
        out = normlearn.learn()
        self.assertNotIn("face.rms", [c["path"] for c in out["changed"]])
        self.assertIn("face.rms", [k["path"] for k in out["kept"]])
        self.assertEqual(self.face_rule()["max"], 0.07)

    def test_too_few_examples_keep_base(self):
        self.write([rec("a", "pass", 0.02), rec("c", "reject", 0.09, "顔が歪む")])
        self.assertEqual(normlearn.learn()["changed"], [])

    def test_last_verdict_wins_and_unmeasured_is_listed(self):
        self.write([rec("a", "pass", 0.02), rec("a", "reject", 0.02, "ポーズが硬い", by="user")])
        recs = normlearn.records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["verdict"], "reject")
        self.assertEqual(normlearn.learn(dry=True)["unmeasured"][0]["reason"], "ポーズが硬い")

    def test_broken_user_norms_fall_back(self):
        measure.USER_NORMS.write_text("{壊れている", encoding="utf-8")
        self.assertEqual(self.face_rule()["max"], 0.07)


if __name__ == "__main__":
    unittest.main()
