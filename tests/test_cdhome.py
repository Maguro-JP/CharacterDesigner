"""置き場所（CD_HOME）を組み立てるのは tools/gen/cdhome.py だけ。ほかで .cache を組むと、替えたときに片方だけ残る。"""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 部品を入れる前に動く起動台本と、tools/gen を読まない engine は同じ式を自分で持つ
SAME_RULE = {"tools/gen/cdhome.py", "tools/engine/human.py"}


class CdHomeTest(unittest.TestCase):
    def test_only_one_place_builds_cache(self):
        files = subprocess.run(["git", "ls-files", "tools"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        bad = [f for f in files if f.endswith(".py") and "/tests/" not in f and f not in SAME_RULE
               and re.search(r'/ "\.cache"', (ROOT / f).read_text(encoding="utf-8"))]
        self.assertEqual(bad, [])

    def test_default_and_override(self):
        code = "import cdhome, tagger; print(cdhome.HOME); print(tagger.DIR)"
        env = {k: v for k, v in os.environ.items() if k != "CD_HOME"}
        env["PYTHONPATH"] = str(ROOT / "tools" / "gen")
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, [str(ROOT / ".cache"), str(ROOT / ".cache" / "assets" / "tagger")])
        out = subprocess.run([sys.executable, "-c", code], env={**env, "CD_HOME": "/elsewhere"}, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["/elsewhere", "/elsewhere/assets/tagger"])


if __name__ == "__main__":
    unittest.main()
