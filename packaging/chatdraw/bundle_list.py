"""Setup.exe に入れるファイルの一覧を、chatdraw/ から辿って集める。

    python3 packaging/chatdraw/bundle_list.py        1 行に 1 つ、リポジトリからの相対の道を出す

手で並べた一覧では、chatdraw が読む tools/gen の台本（feet.py、measure.py など）や設定（styles/、casts/）が
抜けたまま配り、配った版で検品・おまかせ・仕上げ・キャラクターデザインが import で落ちた。手元には全部あるので試験では気付けない。
そこで chatdraw/ の全部の .py から始めて、次を辿れるだけ辿る:
- import 文（tools/gen は sys.path に足して読むので、`import measure` は tools/gen/measure.py にも当てる）
- 文字列の定数のうち tools/gen の台本の名前と同じ物（importlib や _gen("retouch") で読む物）
- `ROOT / "styles" / "x.json"` の形の割り算の鎖と、"casts/body-plans.json" の形の文字列で、リポジトリにあるファイル
多めに入れる分には困らない。足りない分は tests/test_bundle.py が配る中身だけで動かして見つける。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = "tools/gen"
# 配らない物（試験と、アプリが読まない物）
SKIP_PREFIX = ("chatdraw/tests/",)
ALWAYS = ("VERSION", "LICENSE")


def tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return set(out.splitlines())


def _chain(node) -> list[str] | None:
    """a / "b" / "c" の文字列の部分を順に返す（文字列が 1 つも無ければ None）"""
    parts: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            parts.insert(0, node.right.value)
        else:
            return parts or None
        node = node.left
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        parts.insert(0, node.value)
    return parts or None


def refs(path: str, files: set[str], gen_mods: set[str]) -> set[str]:
    """1 つの .py から辿れるリポジトリのファイル"""
    src = (ROOT / path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    here = str(Path(path).parent)
    found: set[str] = set()

    def module(name: str, level: int = 0):
        if level:
            base = Path(here)
            for _ in range(level - 1):
                base = base.parent
            name = f"{base.as_posix().replace('/', '.')}.{name}" if name else base.as_posix().replace("/", ".")
        p = name.replace(".", "/")
        for c in (f"{p}.py", f"{p}/__init__.py", f"{GEN}/{p}.py", f"{here}/{p}.py"):
            if c in files:
                found.add(c)
        if name.split(".")[0] in gen_mods:
            found.add(f"{GEN}/{name.split('.')[0]}.py")

    def path_like(s: str):
        s = s.strip().lstrip("./")
        if not s or len(s) > 200:
            return
        if s in files:
            found.add(s)
        elif f"{here}/{s}" in files:   # Path(__file__).parent / "traits.json"
            found.add(f"{here}/{s}")
        elif s in gen_mods:
            found.add(f"{GEN}/{s}.py")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                module(a.name)
        elif isinstance(node, ast.ImportFrom):
            module(node.module or "", node.level)
            for a in node.names:   # from chatdraw import upscale / from . import x
                module(f"{node.module}.{a.name}" if node.module else a.name, node.level)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts = _chain(node)
            if parts:
                path_like("/".join(parts))
                for i in range(len(parts)):
                    path_like("/".join(parts[i:]))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            path_like(node.value)
    found.discard(path)
    return found


def collect() -> list[str]:
    files = tracked()
    gen_mods = {Path(f).stem for f in files if f.startswith(GEN + "/") and f.endswith(".py") and f.count("/") == 2}
    start = {f for f in files if f.startswith("chatdraw/") and not f.startswith(SKIP_PREFIX)}
    seen: set[str] = set()
    todo = sorted(start)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        if f.endswith(".py"):
            todo.extend(r for r in refs(f, files, gen_mods) if r not in seen and not r.startswith(SKIP_PREFIX))
    # tools/gen を package として読む所のために、途中の __init__.py も入れる
    for f in list(seen):
        parts = Path(f).parts
        for i in range(1, len(parts)):
            init = "/".join(parts[:i]) + "/__init__.py"
            if init in files:
                seen.add(init)
    seen.update(a for a in ALWAYS if a in files)
    return sorted(seen)


if __name__ == "__main__":
    sys.stdout.write("\n".join(collect()) + "\n")
