"""道具どうしが呼んでいる関数が、相手に本当にあるか。枝を取り込むときに片方の関数が抜け、呼ぶ側だけが残った
（qc._face_from_joints、2026-10-17）。試験は呼ぶ側を動かすまで気付かなかった"""
import ast
import re
import unittest
from pathlib import Path

GEN = Path(__file__).resolve().parents[1] / "tools" / "gen"


class CrossRefTest(unittest.TestCase):
    def test_module_attributes_exist(self):
        mods = {p.stem: p for p in GEN.glob("*.py")}
        defined = {}
        for name, p in mods.items():
            t = ast.parse(p.read_text(encoding="utf-8"))
            defined[name] = {n.name for n in t.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} | \
                {t.id for n in t.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)} | \
                {a.asname or a.name for n in t.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        bad = []
        for name, p in mods.items():
            text = p.read_text(encoding="utf-8")
            # 外の部品を同じ名前で読んでいるもの（from skimage import measure）は道具どうしの呼び出しではない
            foreign = set(re.findall(r"from [\w.]+ import [^\n]*?\b([a-z_]+)\b", text))
            for mod, attr in re.findall(r"\b([a-z_]+)\.([A-Za-z_][A-Za-z0-9_]*)\(", text):
                if mod in defined and mod != name and mod not in foreign and attr not in defined[mod]:
                    bad.append(f"{name}.py → {mod}.{attr}")
        self.assertEqual(sorted(set(bad)), [])


if __name__ == "__main__":
    unittest.main()
