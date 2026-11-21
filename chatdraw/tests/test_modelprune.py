"""模型の剪定（一覧に出す物）と、自動の検証の点の付け方の試験。模型は読まない"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chatdraw import models, verify_models


class ShownTest(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch("chatdraw.ratings._load", return_value={})
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_unrated_are_listed_and_only_retired_hidden(self):
        """0.5.33 で推奨と取得済みだけにしたら、まだ点の付いていない新しい模型を取れなくなった。外すのは retired だけ"""
        good = next(m for m in models.IMAGES if m.score >= models.PASS and not m.retired)
        untested = [m for m in models.IMAGES if m.score <= 0 and not m.retired]
        retired = next(m for m in models.IMAGES if m.retired)
        self.assertTrue(untested)
        got = {m.repo for m in models.listed(models.IMAGES)}
        self.assertIn(good.repo, got)
        self.assertTrue({m.repo for m in untested} <= got)
        self.assertNotIn(retired.repo, got)
        self.assertEqual(got, {m.repo for m in models.IMAGES if not m.retired})
        # 手元にある物は、外した物でも「取得済み」として出す（ファイルは消さない）
        self.assertIn(retired.repo, {m.repo for m in models.listed(models.IMAGES, {retired.repo})})

    def test_recommended_come_first_and_unrated_filter(self):
        shown = models.pick(models.listed(models.IMAGES))
        rec = [models._recommended(m) for m in shown]
        self.assertTrue(rec[0])
        self.assertEqual(rec, sorted(rec, reverse=True))   # 推奨が全部、未評価より上
        un = models.pick(models.IMAGES, "未評価")
        self.assertTrue(un)
        self.assertTrue(all(m.score <= 0 and not m.retired for m in un))

    def test_retired_only_for_broken_drawings(self):
        """目録から外すのは、検証で崩れた絵しか描けなかった物だけ（同じ重みの 2 つ目は例外）"""
        for m in models.IMAGES:
            if m.retired:
                self.assertTrue("検証で落とした" in m.retired or "2 つ目は要らない" in m.retired, (m.repo, m.retired))

    def test_retired_have_reasons_and_never_offered(self):
        for m in models.IMAGES:
            if m.retired:
                self.assertGreater(len(m.retired), 8, m.repo)
        offered = {m.repo for m in models.offered_images()} | {m.repo for m in models.verified_images()}
        self.assertFalse(offered & {m.repo for m in models.IMAGES if m.retired})

    def test_catalog_keys_are_unique(self):
        keys = [m.repo for m in models.IMAGES]
        self.assertEqual(len(keys), len(set(keys)))


class ScoreTest(unittest.TestCase):
    def test_one_number(self):
        rows = [{"qc": [], "people": ""}] * 4 + [{"qc": ["指が 6 本"], "people": ""}]
        self.assertEqual(verify_models.one_number({"images": 5, "rate": 0.9, "rows": rows}), 72)
        self.assertEqual(verify_models.one_number({"images": 0, "rate": 0.0, "rows": []}), 0)
        # 描けなかった絵（5 本のうち 3 本だけ）も崩れとして数える
        self.assertEqual(verify_models.one_number({"images": 3, "rate": 1.0, "rows": [{"qc": []}] * 3}), 60)
        # 真っ黒・一色の絵も崩れ
        self.assertEqual(verify_models.one_number({"images": 5, "rate": 1.0, "rows": [{"qc": []}] * 5}, flat=1), 80)

    def test_candidates_skip_retired_and_heavy(self):
        got = verify_models.candidates()
        by = {m.repo: m for m in models.IMAGES}
        self.assertTrue(got)
        for r in got:
            self.assertFalse(by[r].retired, r)
            self.assertLessEqual(by[r].gb, 16, r)
        self.assertIn("wssdaas/nova-anime-xl-ilv-19.0", got)   # 足した物は点 0 なので拾われる

    def test_write_back_keeps_other_entries(self):
        with tempfile.TemporaryDirectory() as d:
            cat = Path(d) / "catalog.json"
            cat.write_text(json.dumps([{"repo": "a/b", "format": "full", "score": 0},
                                       {"repo": "c/d", "format": "single", "file": "x.safetensors", "score": 10, "note": "前"}]),
                           encoding="utf-8")
            r = {"repo": "c/d/x.safetensors", "score": 66, "images": 5, "expected": 5, "rate": 0.8,
                 "qc_images": 1, "people_wrong": 0, "flat": 0}
            self.assertEqual(verify_models.write([r], cat, run="1"), ["c/d/x.safetensors: 66"])
            items = json.loads(cat.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["score"], 0)
            self.assertEqual(items[1]["score"], 66)
            self.assertIn("前 / ", items[1]["note"])
            self.assertIn("点 66", items[1]["note"])


if __name__ == "__main__":
    unittest.main()
