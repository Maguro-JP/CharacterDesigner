"""矛盾の検品（chatdraw/sanity.py）の当たりと外れを、利用者の判定の付いた絵で数える。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/sanity_eval.py tags --out tags.json    # 絵全体のタグを 1 回だけ読む
  PYTHONPATH=.cache/gen/lib python3 tools/gen/sanity_eval.py score tags.json         # タグで読める崩れの前と後
  PYTHONPATH=.cache/gen/lib python3 tools/gen/sanity_eval.py full --out full.json    # sanity.check を全部通す（重い。Actions で流す）

戻した絵: library/feedback の README で判定が「戻す」の絵。通した絵: library/samples の .png（作風の手本として残した絵）と、
判定が「採用」の絵。戻した絵で崩れを挙げなかった枚数が見逃し、通した絵で崩れを挙げた枚数が誤って落とした数。
タグは 1 回だけ読んで使い回す（同じ絵を前と後で 2 度読まない）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def labeled() -> list[dict]:
    """[{path, verdict: reject|pass, prompt}]。README の表の「判定」と「描かせた言葉」の列を読む"""
    out = []
    for readme in sorted((ROOT / "library/feedback").rglob("README.md")):
        head = None
        for line in readme.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                head = None
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if head is None:
                head = cells
                continue
            if set("".join(cells)) <= set("-: "):
                continue
            row = dict(zip(head, cells))
            name, verdict = cells[0], row.get("判定", "")
            if verdict.startswith("戻す"):
                v = "reject"
            elif verdict.startswith("採用"):
                v = "pass"
            else:
                continue
            p = readme.parent / name
            if p.suffix.lower() in (".jpg", ".png") and p.exists():
                out.append({"path": str(p.relative_to(ROOT)), "verdict": v, "prompt": row.get("描かせた言葉", "")})
    for p in sorted((ROOT / "library/samples").rglob("*.png")):
        out.append({"path": str(p.relative_to(ROOT)), "verdict": "pass", "prompt": ""})
    return out


def prompt_of(row: dict) -> str:
    """頼みの言葉。「同じ絵に…」のような日本語だけの欄は頼みが無いのと同じに扱う"""
    p = row.get("prompt", "")
    return p if re.search(r"[a-z]{3}", p) else ""


def score(rows: list[dict], flaws) -> dict:
    """flaws(row) が崩れの list を返す。戻した絵の見逃しと、通した絵の誤って落とした数"""
    rej = [r for r in rows if r["verdict"] == "reject"]
    ok = [r for r in rows if r["verdict"] == "pass"]
    hit = sum(1 for r in rej if flaws(r))
    false = sum(1 for r in ok if flaws(r))
    return {"reject": len(rej), "hit": hit, "missed": len(rej) - hit, "pass": len(ok), "false_reject": false}


def before(row: dict) -> list[str]:
    """足す前の絵全体のタグの検品（腕・頭・顔・目が多い、頼んでいない黄色い目）"""
    from chatdraw import sanity
    got, prompt = row["tags"], prompt_of(row)
    out = []
    for tag, (word, least) in sanity.TAG_FLAWS.items():
        if tag in sanity.OLD_TAG_FLAWS and got.get(tag, 0.0) >= least and not sanity._has(prompt, tag):
            out.append(word)
    if not sanity.eye_color_asked(prompt):
        out += [t for t, least in sanity.UNASKED_COLOR_TAGS.items() if got.get(t, 0.0) >= least]
    return out


def after(row: dict) -> list[str]:
    from chatdraw import sanity
    return sanity.from_tags(row["tags"], prompt_of(row))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tags", "score", "full"])
    ap.add_argument("src", nargs="?")
    ap.add_argument("--out", default="sanity-eval.json")
    a = ap.parse_args()
    if a.mode == "score":
        rows = json.loads(Path(a.src).read_text(encoding="utf-8"))
        res = {"before": score(rows, before), "after": score(rows, after)}
        res["after_kinds"] = {}
        for r in rows:
            for f in after(r):
                k = f.split("（")[0]
                res["after_kinds"].setdefault(k, {"reject": 0, "pass": 0})[r["verdict"]] += 1
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    rows, t0 = labeled(), time.time()
    if a.mode == "tags":
        from chatdraw.requestcheck import _tagger
        tg = _tagger(True)
        for r in rows:
            r["tags"] = tg.read(str(ROOT / r["path"]), threshold=0.2)
    else:
        from chatdraw import sanity
        for r in rows:
            res = sanity.check(ROOT / r["path"], prompt_of(r))
            r.update(bad=res["bad"], readable=res["readable"], reason=res.get("reason", ""), info=res.get("info", []))
            print(r["verdict"], len(r["bad"]), r["path"], flush=True)
        print(json.dumps({"full": score(rows, lambda r: r["bad"] or not r["readable"]),
                          "full_bad_only": score(rows, lambda r: r["bad"])}, ensure_ascii=False))
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(rows), "枚", round(time.time() - t0), "秒")


if __name__ == "__main__":
    main()
