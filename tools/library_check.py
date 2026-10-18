"""絵の置き場所を整えたまま保つ: 置き方の決まり・壊れた参照・どこからも使われていない絵を調べ、絵の目録（library/INDEX.md）を書く。

  python3 tools/library_check.py            # 調べて目録を書き直す。決まりに外れた絵か壊れた参照があれば終了コード 1
  python3 tools/library_check.py --check    # 目録を書かずに調べるだけ（試験 tests/test_structure.py が使う）

置き方の決まり（docs/STRUCTURE.md）:
  - 見本の絵は library/samples/<題目>/<名前>.png（題目ごとのフォルダ。平らに並べると 80 枚を超えて探せなかった）
  - 比べた記録の絵は library/progress/<YYYY-MM-DD>/<名前>.png
  - 日ごとの作例は library/daily/<YYYY-MM-DD>/
  - 名前は英小文字・数字・ハイフン・点・下線だけ
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
TEXT = (".md", ".json", ".py", ".ts", ".tsx", ".html", ".sh", ".txt")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
RULES = [
    (re.compile(r"^library/samples/[^/]+$"), "見本の絵は library/samples/<題目>/ に置く"),
    (re.compile(r"^library/progress/(?!\d{4}-\d{2}-\d{2}/)[^/]+\.(png|jpe?g|gif|webp)$"), "比べた記録の絵は library/progress/<日付>/ に置く"),
    (re.compile(r"^library/daily/(?!\d{4}-\d{2}-\d{2}/)"), "日ごとの作例は library/daily/<日付>/ に置く"),
]
REF = re.compile(r"((?:library|docs/images|bible|designs)/[\w./-]+\.(?:png|jpe?g|gif|webp))")


def tracked() -> list[str]:
    return subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()


def check() -> dict:
    files = tracked()
    images = [f for f in files if f.lower().endswith(IMAGES)]
    misplaced = []
    for f in images:
        for rx, why in RULES:
            if rx.match(f):
                misplaced.append(f"{f}: {why}")
        if not NAME.match(Path(f).name):
            misplaced.append(f"{f}: 名前は英小文字・数字・ハイフンにする")
    have = set(images)
    broken, used = [], set()
    for f in files:
        if not f.endswith(TEXT) or f in ("tools/library_check.py", "library/INDEX.md"):
            continue
        try:
            s = (ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in REF.findall(s):
            used.add(m)
            # 作業場所や設定で作る絵（.cache、<名前> の型）は数えない
            if m not in have and m.isascii() and "<" not in m and "*" not in m and not (ROOT / m).exists():
                broken.append(f"{f}: {m}")
        # 同じフォルダからの相対の参照（README の ![...](名前.png)）
        base = Path(f).parent
        for m in re.findall(r"\]\(([\w./-]+\.(?:png|jpe?g|gif|webp))\)", s):
            used.add(str((base / m)).replace("\\", "/"))
        if Path(f).name == "README.md":
            # 同じフォルダの README に名前だけ書いた絵（表の 1 行に 1 枚）も使われているとみなす
            used.update(i for i in images if Path(i).parent == base and Path(i).name in s)
    orphans = sorted(set(images) - used)
    return {"images": len(images), "misplaced": misplaced, "broken": sorted(set(broken)), "orphans": orphans}


TOPIC_JA = {"samples": "見本の絵", "progress": "比べた記録", "daily": "日ごとの作例", "feedback": "フィードバックの成果物", "book": "作例集",
            "eyes": "目の資料集", "sheets": "職業の一覧（箱庭ドット）",
            "bible": "設定資料集の人物・場所の絵", "designs": "依頼された作品の決定稿", "docs": "README・アプリの案内の画面"}


def index(res: dict) -> Path:
    """絵の目録。置き場ごとに見出しと縮小画を並べる（GitHub の画面でそのまま絵が見える）"""
    groups = defaultdict(list)
    for f in sorted(f for f in tracked() if f.lower().endswith(IMAGES)):
        parts = f.split("/")
        key = "/".join(parts[:3]) if parts[0] == "library" and len(parts) > 3 else "/".join(parts[:-1])
        groups[key].append(f)
    orphan = set(res["orphans"])
    lines = ["# 絵の目録", "",
             "`python3 tools/library_check.py` が書く。手で直さない。置き方の決まりは [docs/STRUCTURE.md](../docs/STRUCTURE.md)。", "",
             f"全 {res['images']} 枚（置き場 {len(groups)} か所）。どこからも参照されていない絵 {len(orphan)} 枚には「未参照」と付ける。", "",
             "## 置き場の一覧", "", "| 置き場 | 何の絵か | 枚数 |", "|---|---|---|"]
    for k in sorted(groups):
        top = k.split("/")[1] if k.startswith("library/") and "/" in k else k.split("/")[0]
        lines.append(f"| [`{k}/`](#{re.sub(r'[^a-z0-9-]', '', k.replace('/', '-'))}) | {TOPIC_JA.get(top, top)} | {len(groups[k])} |")
    for k in sorted(groups):
        lines += ["", f'<a id="{re.sub(r"[^a-z0-9-]", "", k.replace("/", "-"))}"></a>', f"## {k}/", ""]
        cells = []
        for f in groups[k]:
            rel = "../" + f if not f.startswith("library/") else f[len("library/"):]
            mark = "（未参照）" if f in orphan else ""
            cells.append(f'<a href="{rel}"><img src="{rel}" width="150" alt="{Path(f).name}"></a><br><sub>{Path(f).name}{mark}</sub>')
        for i in range(0, len(cells), 6):
            row = cells[i:i + 6]
            if i == 0:
                lines += ["| " + " | ".join([" "] * len(row)) + " |", "|" + "---|" * len(row)]
            lines.append("| " + " | ".join(row) + " |")
    p = ROOT / "library" / "INDEX.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    res = check()
    if not a.check:
        print(index(res))
    print(f"絵 {res['images']} 枚、決まりに外れた絵 {len(res['misplaced'])}、壊れた参照 {len(res['broken'])}、参照されていない絵 {len(res['orphans'])}")
    for x in res["misplaced"] + res["broken"]:
        print("  -", x)
    sys.exit(1 if res["misplaced"] or res["broken"] else 0)


if __name__ == "__main__":
    main()
