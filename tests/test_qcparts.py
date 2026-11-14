"""検品の部品の目録が、読む側（検品のコード）と同じ模型の名前を指しているか。名前がずれると、取った物を読む側が見つけられない"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def const(path, name):
    m = re.search(rf'^{name}\s*=\s*"([^"]+)"', (ROOT / path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


class NamesTest(unittest.TestCase):
    def test_names_match_readers(self):
        src = (ROOT / "chatdraw" / "qcparts.py").read_text(encoding="utf-8")
        for name, path, var in (("SEG", "tools/gen/edit.py", "SEG_MODEL"), ("PERSON", "chatdraw/sanity.py", "PERSON_MODEL"),
                                ("TAGGER", "chatdraw/requestcheck.py", "REPO"), ("POSE", "chatdraw/twostage.py", "POSE")):
            ours = re.search(rf'^{name}\s*=\s*"([^"]+)"', src, re.M).group(1)
            self.assertEqual(ours, const(path, var), f"{name} と {path} の {var}")

    def test_table_lists_every_part(self):
        doc = (ROOT / "docs" / "knowledge" / "qc-parts.md").read_text(encoding="utf-8")
        for repo in re.findall(r'^[A-Z]+\s*=\s*"([^"]+)"', (ROOT / "chatdraw" / "qcparts.py").read_text(encoding="utf-8"), re.M):
            self.assertIn(repo, doc)

    def test_new_models_in_verify_list_with_zero_score(self):
        import json
        cat = json.loads((ROOT / "chatdraw" / "catalog.json").read_text(encoding="utf-8"))
        verify = (ROOT / "config" / "verify-models.txt").read_text(encoding="utf-8")
        new = [m for m in cat if isinstance(m, dict) and m.get("added") == "2026-11-14"]
        self.assertTrue(new)
        for m in new:
            self.assertEqual(m.get("score", 0), 0, m["repo"])
            self.assertIn(m["repo"].split("/")[0] + "/" + m["repo"].split("/")[1], verify)


if __name__ == "__main__":
    unittest.main()
