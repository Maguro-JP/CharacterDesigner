"""基準の組で、描き方を変えたときに崩れが増えないかを比べる。

  python3 tools/gen/bench.py make casts/bench-stage1.json library/feedback/check/2026-10-18/stage1-tee ...   # README から組を作る
  PYTHONPATH=.cache/gen/lib python3 tools/gen/bench.py score casts/bench-stage1.json OUT/base.json          # 置いてある基準の絵を検品
  PYTHONPATH=.cache/gen/lib python3 tools/gen/bench.py run casts/bench-stage1.json OUT/hires --hires 1.5     # 同じ言葉と種で描き直して検品
  python3 tools/gen/bench.py compare OUT/base.json OUT/hires/result.json                                  # 崩れの数を比べる（増えたら終了コード 1）

模型・解像度・描き方を変えるたびに、別の言葉や種で試すと、良くなったのか題材が易しかったのかが分からない。
同じ言葉と種の組で描き直し、検品（qc.auto_check）の崩れの数を基準と並べ、増えた変え方は採らない。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[2]
ROW = re.compile(r"^\| (\S+\.(?:jpg|png)) \| [^|]* \| ([^|]+) \| (\d+) \|")


def make(out: str, dirs: list[str]) -> list[dict]:
    """組ごとの README の表（絵・判定・言葉・種）から、描き直す組を作る"""
    cases = []
    for d in dirs:
        for line in (ROOT / d / "README.md").read_text(encoding="utf-8").splitlines():
            m = ROW.match(line)
            if m:
                cases.append({"id": Path(m[1]).stem, "image": f"{d}/{m[1]}", "prompt": m[2].strip(), "seed": int(m[3])})
    Path(out).write_text(json.dumps({"about": "描き方を変えたときに比べる基準の組（tools/gen/bench.py）。"
                                     "模型は MeinaMix V11（style anime）、LCM 6 段、512x768",
                                     "style": "anime", "steps": 6, "width": 512, "height": 768, "cases": cases},
                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return cases


def count(src: str, prompt: str) -> dict:
    import qc
    a = qc.auto_check(src, prompt)
    kinds = [next(iter(p)) for p in a["problems"]]
    return {"problems": len(kinds), "kinds": kinds, "unreadable": len(a["unreadable"])}


def score(bench: dict, out: str) -> dict:
    res = {"variant": "base", "cases": {}}
    for c in bench["cases"]:
        res["cases"][c["id"]] = count(str(ROOT / c["image"]), c["prompt"])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def run(bench: dict, outdir: str, style=None, width=None, height=None, steps=None, hires=0.0, strength=0.35, only=0) -> dict:
    import design  # noqa: F401  模型を勝手に取りに行かない設定を先に効かせる
    od = Path(outdir)
    od.mkdir(parents=True, exist_ok=True)
    st = style or bench["style"]
    res = {"variant": od.name, "style": st, "width": width or bench["width"], "height": height or bench["height"],
           "steps": steps or bench["steps"], "hires": hires, "cases": {}}
    old = od / "result.json"
    if old.exists():
        # 続きから描く（止まったあとに、描けた絵を描き直さない）
        res["cases"] = json.loads(old.read_text(encoding="utf-8"))["cases"]
    for c in bench["cases"][:only or None]:
        if c["id"] in res["cases"]:
            continue
        p = od / f"{c['id']}.png"
        t = time.time()
        design.draw(str(p), c["prompt"], c["seed"], 1, st, res["steps"], res["width"], res["height"])
        if hires:
            design.hires(str(p), c["prompt"], c["seed"], st, hires, strength, res["steps"])
        r = count(str(p), c["prompt"])
        r["seconds"] = round(time.time() - t, 1)
        res["cases"][c["id"]] = r
        (od / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{c['id']}: 崩れ {r['problems']}、{r['seconds']} 秒", flush=True)
    return res


def rescore(bench: dict, outdir: str) -> dict:
    """描き直した絵を、今の検品で数え直す（検品を直したあと、描き直さずに基準と同じ物差しにそろえる）"""
    od = Path(outdir)
    res = json.loads((od / "result.json").read_text(encoding="utf-8"))
    prompts = {c["id"]: c["prompt"] for c in bench["cases"]}
    for i, r in res["cases"].items():
        r.update(count(str(od / f"{i}.png"), prompts[i]))
    (od / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def compare(base: dict, new: dict) -> tuple[str, bool]:
    """同じ絵どうしで崩れの数を並べる。合計が増えたら採らない（worse=True）"""
    ids = [i for i in new["cases"] if i in base["cases"]]
    rows = ["| 絵 | 基準 | 変えた後 | 差 |", "|---|---|---|---|"]
    b = n = 0
    for i in ids:
        x, y = base["cases"][i]["problems"], new["cases"][i]["problems"]
        b, n = b + x, n + y
        rows.append(f"| {i} | {x} | {y} | {y - x:+d} |")
    sec = [new["cases"][i].get("seconds") for i in ids if new["cases"][i].get("seconds")]
    head = f"{new.get('variant')}: {len(ids)} 枚、崩れ {b} → {n}（{n - b:+d}）" + (f"、1 枚 平均 {sum(sec) / len(sec):.0f} 秒" if sec else "")
    return head + "\n\n" + "\n".join(rows), n > b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make"); m.add_argument("out"); m.add_argument("dirs", nargs="+")
    s = sub.add_parser("score"); s.add_argument("bench"); s.add_argument("out")
    r = sub.add_parser("run"); r.add_argument("bench"); r.add_argument("outdir")
    r.add_argument("--style"); r.add_argument("--width", type=int); r.add_argument("--height", type=int)
    r.add_argument("--steps", type=int); r.add_argument("--hires", type=float, default=0.0)
    r.add_argument("--strength", type=float, default=0.35); r.add_argument("--only", type=int, default=0, help="先頭の N 枚だけ（費用を先に測る）")
    q = sub.add_parser("rescore"); q.add_argument("bench"); q.add_argument("outdir")
    c = sub.add_parser("compare"); c.add_argument("base"); c.add_argument("new")
    a = ap.parse_args()
    if a.cmd == "make":
        print(f"{len(make(a.out, a.dirs))} 枚")
    elif a.cmd == "score":
        r_ = score(json.loads(Path(a.bench).read_text(encoding="utf-8")), a.out)
        print(f"{len(r_['cases'])} 枚、崩れ {sum(v['problems'] for v in r_['cases'].values())}")
    elif a.cmd == "run":
        run(json.loads(Path(a.bench).read_text(encoding="utf-8")), a.outdir, a.style, a.width, a.height, a.steps, a.hires, a.strength, a.only)
    elif a.cmd == "rescore":
        rescore(json.loads(Path(a.bench).read_text(encoding="utf-8")), a.outdir)
    else:
        text, worse = compare(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in (a.base, a.new)))
        print(text)
        sys.exit(1 if worse else 0)


if __name__ == "__main__":
    main()
