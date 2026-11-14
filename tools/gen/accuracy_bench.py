"""機能ごとの精度の台を流し、docs/knowledge/accuracy.md の表を書き直す。

    python tools/gen/accuracy_bench.py [--only 機能,機能] [--write] [--json 出力.json]

表の「前の数字」は、書き直す前の表の「数字」。下がった物には ▼ を付ける（目立たせて、入れる前に気づくため）。
流さなかった機能の行は前のまま残す。台は BENCHES に並べる。前に読んでいた chatdraw/accuracy.py は 0.5.23 で
描く仕組みを戻したときに外れたので、今の main にある台（検品単体の台 tools/gen/qcbench.py）だけを流す。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DOC = ROOT / "docs" / "knowledge" / "accuracy.md"
HEAD = """# 機能ごとの精度

`tools/gen/accuracy_bench.py` が台を流して書く表。数字は 0〜100 で、高いほど良い。
前の数字より下がった物には ▼ を付ける。直す順番は、この表で一番低い機能から。今流せる台は `tools/gen/accuracy_bench.py` の BENCHES に並べる。
日付の古い行は、0.5.23 で外れた台（chatdraw/accuracy.py）で測った前の数字で、今は流していない。

| 機能 | 数字 | 前の数字 | 日付（日本時間） |
|---|---|---|---|
"""


def read_table(text: str) -> dict:
    rows = {}
    for line in text.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == 4 and c[0] not in ("機能", "---") and not c[0].startswith("-"):
            try:
                rows[c[0]] = dict(score=float(c[1].replace("▼", "").strip()), prev=c[2], date=c[3])
            except ValueError:
                continue
    return rows


def render(old: dict, new: dict, when: str) -> str:
    order = list(dict.fromkeys(list(new) + list(old)))
    lines = []
    for k in order:
        if k in new:
            s = new[k]["score"]
            p = old.get(k, {}).get("score")
            mark = " ▼" if p is not None and s < p else ""
            lines.append(f"| {k} | {s}{mark} | {'' if p is None else p} | {when} |")
        else:
            o = old[k]
            lines.append(f"| {k} | {o['score']} | {o['prev']} | {o['date']} |")
    return HEAD + "\n".join(lines) + "\n"


def qc_single() -> dict:
    """検品単体の台。数字は人が崩れと書いた部位を取りこぼさなかった割合"""
    sys.path.insert(0, str(ROOT / "tools" / "gen"))
    import qcbench
    rows = qcbench.truth()
    results = {}
    for r in rows:
        try:
            results[r["path"]] = qcbench.run_one(ROOT / r["path"])
        except Exception as e:   # noqa: BLE001  落ちた絵は数えない（qcbench と同じ）
            print(f"落ちた: {r['path']}: {e}", flush=True)
    sc = qcbench.score(rows, results)
    return {"score": sc["caught"], **{k: v for k, v in sc.items() if k not in ("caught", "missed")}}


BENCHES = {"検品単体": qc_single}


def run(names=None) -> dict:
    unknown = [n for n in names or [] if n not in BENCHES]
    if unknown:
        raise SystemExit("台がありません: " + "、".join(unknown) + "（あるのは " + "、".join(BENCHES) + "）")
    return {n: BENCHES[n]() for n in (names or BENCHES)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    names = [x for x in a.only.split(",") if x] or None
    res = run(names)
    for k, v in res.items():
        print(f"{k}: {v['score']}  " + json.dumps({x: y for x, y in v.items() if x != "score"}, ensure_ascii=False)[:400], flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    old = read_table(DOC.read_text(encoding="utf-8")) if DOC.exists() else {}
    when = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    down = [k for k, v in res.items() if k in old and v["score"] < old[k]["score"]]
    if a.write:
        # 表の下の節（「## 」から後。検品と描き直しの秒など、台の外で測った数字）は書き直さずに残す
        text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        tail = text[text.index("\n## "):] if "\n## " in text else ""
        DOC.write_text(render(old, res, when) + tail, encoding="utf-8")
    if down:
        print("▼ 下がった: " + "、".join(down))
    return 1 if down else 0


if __name__ == "__main__":
    sys.exit(main())
