"""模型を読む部品は、上の段で design を読み、模型の置き場所と取りに行かない既定を先に効かせる。
関数の中だけで読むと、先に transformers を読んだ呼び出しで ~/.cache/huggingface へ取りに行った"""
import re
import unittest
from pathlib import Path

GEN = Path(__file__).resolve().parents[1] / "tools" / "gen"
LOADS = re.compile(r"from_pretrained|hf_hub_download|snapshot_download|pipeline\(\"")


class HubDefaults(unittest.TestCase):
    def test_model_loaders_import_design_at_top(self):
        missing = []
        for f in sorted(GEN.glob("*.py")):
            if f.name == "design.py":
                continue
            s = f.read_text(encoding="utf-8")
            if LOADS.search(s) and not re.search(r"^import design\b", s, re.M):
                missing.append(f.name)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
