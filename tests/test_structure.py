"""置き場所の決まり（docs/STRUCTURE.md）が崩れていないかを見る。ほかのセッションが資料を別の場所に置き始めたら落ちる"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_TOP = {"ROADMAP.md", "STRUCTURE.md", "models.md", "references.md", "record-policy.md", "release-plan.md", "filters.md"}
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def tracked():
    return subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()


class StructureTest(unittest.TestCase):
    def test_docs_top_is_guides_only(self):
        extra = [f for f in tracked() if f.startswith("docs/") and f.count("/") == 1 and Path(f).name not in DOCS_TOP]
        self.assertEqual(extra, [], "docs/ 直下は使う人向けの案内だけ。知見は docs/knowledge/、置き場は docs/STRUCTURE.md")

    def test_one_decisions_file(self):
        found = [f for f in tracked() if Path(f).name == "decisions.md"]
        self.assertEqual(found, ["docs/knowledge/decisions.md"])

    def test_images_in_their_places(self):
        ok = ("library/", "bible/", "designs/", "characters/", "docs/images/", "app/", "templates/", "tools/", "packaging/")
        bad = [f for f in tracked() if f.lower().endswith(IMAGES) and not f.startswith(ok)]
        self.assertEqual(bad, [], "絵は library/（見本・作例・比べ）か docs/images/（案内の画面）などの決まった場所へ")


if __name__ == "__main__":
    unittest.main()


class LibraryCheck(unittest.TestCase):
    def test_images_follow_layout_and_references_resolve(self):
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "tools/library_check.py", "--check"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
