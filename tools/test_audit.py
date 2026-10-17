"""試験が正しく組めているかの見直し。定期的に（週に 1 回）流し、結果を docs/reports/test-audit.md に書く。

  python3 tools/test_audit.py

見るもの:
  - 飛ばされた試験の数と理由（部品が無い環境で黙って飛ばされ、落ちても気付かない試験）
  - 確かめ（assert）の無い試験関数（動くだけで何も確かめていない）
  - 試験が 1 本も無い道具（tools/gen の *.py のうち、どの試験からも読まれていないもの）
  - GitHub Actions の設定で、時間の上限・同時実行の打ち切りの無いもの（使用量の枠を溶かす元）
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def skipped() -> tuple[str, list[str]]:
    lib = ROOT / ".cache/gen/lib"
    env = {"PYTHONPATH": str(lib)} if lib.exists() else {}
    import os
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "tests"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, **env})
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
    return last, [l for l in r.stdout.splitlines() if l.startswith("SKIPPED")]


def no_assert() -> list[str]:
    out = []
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        t = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(t):
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test"):
                src = ast.unparse(n)
                if not re.search(r"\bassert|self\.assert|self\.fail|pytest\.raises", src):
                    out.append(f"{p.name}::{n.name}")
    return out


def untested() -> list[str]:
    tests = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
    return [p.name for p in sorted((ROOT / "tools/gen").glob("*.py"))
            if not re.search(rf"\b{p.stem}\b", tests) and p.stem not in ("__init__",)]


def actions() -> list[str]:
    out = []
    for p in sorted((ROOT / ".github/workflows").glob("*.yml")):
        s = p.read_text(encoding="utf-8")
        if "timeout-minutes" not in s:
            out.append(f"{p.name}: timeout-minutes が無い")
        if "concurrency" not in s:
            out.append(f"{p.name}: concurrency が無い")
        if re.search(r"^\s*push:", s, re.M) and re.search(r"^\s*pull_request:", s, re.M):
            out.append(f"{p.name}: push と pull_request の両方で走る（同じ変更で 2 回）")
    return out


def main():
    last, skips = skipped()
    rows = ["# 試験の見直し", "", f"- 結果: {last}", f"- 飛ばされた試験: {len(skips)} 件"]
    rows += [f"  - {s}" for s in skips]
    na = no_assert()
    rows += [f"- 確かめの無い試験関数: {len(na)} 件"] + [f"  - {x}" for x in na]
    ut = untested()
    rows += [f"- 試験から読まれていない道具（tools/gen）: {len(ut)} 件"] + [f"  - {x}" for x in ut]
    ac = actions()
    rows += [f"- GitHub Actions の設定の穴: {len(ac)} 件"] + [f"  - {x}" for x in ac]
    out = ROOT / "docs/reports/test-audit.md"
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
