"""Setup.exe に入れる中身だけで、アプリの機能（おまかせ・検品・独自の作画監督・仕上げ・キャラクターデザイン）が呼べるかを見る。

手元のリポジトリには tools/gen が全部あるので、ほかの試験は配った版にしか無い欠け（入れ忘れた台本や設定）を見つけられなかった。
ここでは packaging/chatdraw/bundle_list.py の一覧だけを一時の置き場に出し、リポジトリの外から python -I で、
その置き場だけを読む道にして入口を呼ぶ。描く部品（torch、scipy）と模型は配らないので、それが無くて止まるのは良しとし、
リポジトリの中の物（台本・設定）が無くて止まったときだけ落とす。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import importlib, json, os, sys, tempfile, traceback
root, local, out_path = sys.argv[1], set(json.loads(sys.argv[2])), sys.argv[3]
libs = [p for p in sys.argv[4:] if p]
sys.path[:] = [root] + [p for p in sys.path if p and "site-packages" not in p and "dist-packages" not in p] + libs + \
              [p for p in sys.path if p and ("site-packages" in p or "dist-packages" in p)]
home = tempfile.mkdtemp()
os.environ.update(CD_HOME=os.path.join(home, "cd"), CD_FETCH="0", CHATDRAW_HOME=home, QT_QPA_PLATFORM="offscreen")
fails, notes = [], []

def chain(e):
    while e is not None:
        yield e
        e = e.__cause__ or e.__context__

def missing_local(e):
    """リポジトリの中の物が無くて止まったなら、その名前"""
    for x in chain(e):
        if isinstance(x, ModuleNotFoundError) and x.name and x.name.split(".")[0] in local:
            return f"module {x.name}"
        if isinstance(x, FileNotFoundError) and x.filename and str(x.filename).startswith(root):
            return f"file {os.path.relpath(str(x.filename), root)}"
        if "入っていません。アプリを入れ直して" in str(x):
            return str(x)
    return None

def call(label, fn, *a, **k):
    try:
        r = fn(*a, **k)
    except BaseException as e:
        why = missing_local(e)
        (fails if why else notes).append(f"{label}: {why or type(e).__name__ + ': ' + str(e)[:160]}")
        return None
    # 例外を飲み込んで訳だけを返す入口（handcheck の足・顔）も、リポジトリの中の物が無いなら落とす
    text = str(r)
    for name in local:
        if f"No module named '{name}'" in text or f"No module named \\'{name}\\'" in text:
            fails.append(f"{label}: 返りに module {name} が無いと出た")
    if root in text and ("No such file" in text or "FileNotFoundError" in text):
        fails.append(f"{label}: 返りに無いファイルが出た")
    return r

from PIL import Image
img = Image.new("RGB", (512, 512), (240, 220, 200))

# 1. 配った台本は全部読めること
for f in sorted(os.listdir(os.path.join(root, "chatdraw"))):
    if f.endswith(".py") and f != "__init__.py":
        call(f"import chatdraw.{f[:-3]}", importlib.import_module, f"chatdraw.{f[:-3]}")
gen = os.path.join(root, "tools", "gen")
if os.path.isdir(gen):
    sys.path.append(gen)
    for f in sorted(os.listdir(gen)):
        if f.endswith(".py"):
            call(f"import tools/gen/{f}", importlib.import_module, f[:-3])

# 2. 入口を呼ぶ
from chatdraw import omakase, handcheck, origqc, finishers, charadesign
p = call("omakase.plan", omakase.plan, "赤い髪の女の子", [])
if p is not None:
    notes.append(f"omakase.plan finish={p.finish}")
call("omakase.finishers", omakase.finishers)
call("omakase._default_check", omakase._default_check, img, "girl")
call("handcheck.check", handcheck.check, img, fetch=False)
call("handcheck._hands", handcheck._hands)
call("origqc._setup", origqc._setup)
call("origqc.check", origqc.check, img, "girl")
for t in call("finishers.available", finishers.available) or []:
    if not t["ready"]:
        if "入れ直して" in t["reason"]:
            fails.append(f"finishers.available {t['name']}: {t['reason']}")
        continue
    call(f"finishers.run {t['name']}", finishers.run, t["name"], img)
for name in ("retouch", "inking", "atmosphere", "materials", "upscale", "detail", "edit", "measure", "normlearn",
             "faceform", "facecheck", "feet", "hands", "bible", "tagger"):
    call(f"finishers._gen {name}", finishers._gen, name)
b = call("charadesign.bible", charadesign.bible, home=home)
info = call("charadesign.save_character", charadesign.save_character, "test", "red hair girl", img, home=home)
if info:
    ident = info.get("id") or info.get("ident") or charadesign.characters(home=home)[0]["id"]
    call("charadesign.turnaround_plan", charadesign.turnaround_plan, ident, home=home)
    call("charadesign.write_sheet", charadesign.write_sheet, ident, home=home)
call("charadesign.characters", charadesign.characters, home=home)
json.dump({"fails": fails, "notes": notes}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
'''


def bundle_files() -> list[str]:
    sys.path.insert(0, str(ROOT / "packaging" / "chatdraw"))
    try:
        import bundle_list
    finally:
        sys.path.pop(0)
    return bundle_list.collect()


def probe(files: list[str]) -> dict:
    """files だけを一時の置き場に写し、リポジトリの外から入口を呼んだ結果（fails と notes）"""
    local = sorted({Path(f).stem for f in subprocess.run(["git", "ls-files", "tools/gen", "chatdraw"], cwd=ROOT,
                                                          capture_output=True, text=True).stdout.split()
                    if f.endswith(".py")} | {"chatdraw", "tools"})
    with tempfile.TemporaryDirectory() as d:
        app = Path(d) / "app"
        for f in files:
            if f.startswith("chatdraw/tests/"):
                continue
            (app / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, app / f)
        script, out = Path(d) / "probe" / "probe.py", Path(d) / "out.json"
        script.parent.mkdir()
        script.write_text(PROBE, encoding="utf-8")
        # 描く部品は配らず初めの起動で取るので、手元にあれば読ませて、その先の入口まで通す（worktree では元のリポジトリの .cache）
        common = Path(subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT,
                                     capture_output=True, text=True).stdout.strip() or ROOT / ".git").parent
        libs = list(dict.fromkeys(str(b / p) for b in (ROOT, common) for p in (".cache/gen/lib", ".cache/simple/lib")
                                  if (b / p).is_dir()))
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        r = subprocess.run([sys.executable, "-I", str(script), str(app), json.dumps(local), str(out), *libs],
                           cwd=d, env=env, capture_output=True, text=True, timeout=600)
        if not out.exists():
            raise AssertionError(f"probe が終わらなかった:\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
        return json.loads(out.read_text(encoding="utf-8"))


class BundleTest(unittest.TestCase):
    def test_bundle_has_what_features_read(self):
        res = probe(bundle_files())
        self.assertEqual(res["fails"], [], "配る中身に無い物を読んでいる:\n" + "\n".join(res["fails"]))

    def test_build_uses_bundle_list(self):
        """build.sh が手で並べた一覧に戻っていないこと"""
        sh = (ROOT / "packaging" / "chatdraw" / "build.sh").read_text(encoding="utf-8")
        self.assertIn("bundle_list.py", sh)
        self.assertNotIn("tools/gen/hands.py tools/gen/cdhome.py", sh)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--files"]:   # 別の一覧（例: 直す前の build.sh の一覧）で流す
        print(json.dumps(probe(sys.argv[2:]), ensure_ascii=False, indent=1))
    elif sys.argv[1:2] == ["--list"]:  # 一覧のファイル（1 行に 1 つ）で流す
        print(json.dumps(probe(Path(sys.argv[2]).read_text(encoding="utf-8").split()), ensure_ascii=False, indent=1))
    else:
        unittest.main()
