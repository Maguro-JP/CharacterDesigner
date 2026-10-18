"""動物の周（animal_cycle.today_animal）と参考画像の棚（refsearch）の、模型と通信を使わない部分"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import animal_cycle  # noqa: E402
import refsearch  # noqa: E402


class TodayAnimal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = animal_cycle.DONE
        animal_cycle.DONE = Path(self.tmp.name) / "done.json"

    def tearDown(self):
        animal_cycle.DONE = self.saved
        self.tmp.cleanup()

    def test_same_day_same_animal_and_no_repeat(self):
        a = animal_cycle.today_animal("2026-10-18")
        self.assertEqual(animal_cycle.today_animal("2026-10-18"), a)
        seen = [a[0]] + [animal_cycle.today_animal(f"2026-11-{d:02d}")[0] for d in range(1, 8)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_next_day_avoids_the_same_group(self):
        a = animal_cycle.today_animal("2026-10-18")[0]
        b = animal_cycle.today_animal("2026-10-19")[0]
        groups = set(animal_cycle.GROUP.values())
        if len(groups) > 1:
            self.assertNotEqual(animal_cycle.GROUP[a], animal_cycle.GROUP[b])


class Refs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (refsearch.REFS, refsearch.INDEX)
        refsearch.REFS = Path(self.tmp.name) / "refs"
        refsearch.INDEX = refsearch.REFS / "index.jsonl"

    def tearDown(self):
        refsearch.REFS, refsearch.INDEX = self.saved
        self.tmp.cleanup()

    def test_safe_id_cannot_leave_the_folder(self):
        for rid in ("../../etc/passwd", "a/b", "x" * 200):
            s = refsearch._safe_id(rid)
            self.assertNotIn("/", s)
            self.assertNotIn(".", s)
            self.assertLessEqual(len(s), 64)

    def test_save_keeps_license_and_lists(self):
        refsearch.REFS.mkdir(parents=True)
        Image.new("RGB", (4, 4)).save(refsearch.REFS / "abc-1.jpg")   # 取り込み済みなら取りに行かない
        rec = refsearch.save({"id": "abc-1", "url": "http://example.invalid/x.jpg", "license": "cc0", "title": "t"})
        self.assertEqual(rec["license"], "cc0")
        self.assertEqual([r["id"] for r in refsearch.list_saved()], ["abc-1"])
        self.assertIsNotNone(refsearch.path_of("abc-1"))
        self.assertIsNone(refsearch.path_of("../abc-1x"))


if __name__ == "__main__":
    unittest.main()
