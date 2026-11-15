"""絵の模型を実際に動かして確かめ、点（catalog.json の score）を 1 つ付ける。

    python -m chatdraw.verify_models list                       （確かめる模型。Actions の行列に渡す JSON）
    python -m chatdraw.verify_models draw  <repo> <置き場>       （同じ頼み・同じ種で描く）
    python -m chatdraw.verify_models score <repo> <置き場>       （検品して点を 1 つ付け、<置き場>/score.json に書く）
    python -m chatdraw.verify_models write <score.json>...       （目録 catalog.json に点を書き戻す）

描く頼みは、頼んだ通りに描けたかを測る台（adherebench）の 30 本から、決まった 5 本を同じ種で描く。模型どうしを同じ物差しで比べるため。
点 = 100 × 描けた語の割合 × 崩れの無い絵の割合。崩れは作画監督（handcheck）の外れ、人数の違い、真っ黒・一色の絵で、
描けなかった絵と検品できなかった絵も崩れとして数える（検品できない絵を「崩れが無い」と扱わない）。
重い（SDXL を CPU で 1 枚 10 分ほど）ので、手元ではなく GitHub Actions（model-verify.yml）で流す。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SEED = 7
SHARDS = 6        # 30 本を 6 つに分けた 1 組目（0, 6, 12, 18, 24 番）を描く
SHARD = 0
EXPECTED = 5
RUNNER_RAM_GB = 14   # Actions の機械（16GB）で描ける重さの上限。超える模型は確かめられないので行列に入れない
VERIFY_LIST = Path(__file__).resolve().parents[1] / "config" / "verify-models.txt"


def image_stats(im) -> dict:
    """真っ黒・一色・塗りつぶしを見つける数字。std は明るさのばらつき、mean は明るさ"""
    import numpy as np
    a = np.asarray(im.convert("L"), dtype=np.float32)
    return {"mean": round(float(a.mean()), 1), "std": round(float(a.std()), 1)}


def broken(stats: dict) -> str:
    if stats["mean"] < 8:
        return "真っ黒"
    if stats["std"] < 6:
        return "一色"
    return ""


def one_number(res: dict, flat: int = 0, expected: int = EXPECTED) -> int:
    """画面に出す 1 つの点（0〜100）。描けた語の割合 × 崩れの無い絵の割合。描けなかった絵は崩れとして数える"""
    if expected <= 0 or not res.get("images"):
        return 0
    bad = sum(1 for r in res.get("rows", []) if r.get("qc") or r.get("people")) + flat
    clean = max(0, min(res["images"], expected) - bad) / expected
    return max(0, min(100, round(100 * float(res.get("rate", 0.0)) * clean)))


def candidates() -> list[str]:
    """確かめる模型。点が 0 の物（確かめていない物）と、config/verify-models.txt に書いた物。外した物と、Actions の機械に入らない物は除く"""
    from chatdraw.models import IMAGES, heavy
    extra = [ln.strip() for ln in VERIFY_LIST.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")] if VERIFY_LIST.exists() else []
    by = {m.repo: m for m in IMAGES}
    out = []
    for repo in extra + [m.repo for m in IMAGES if m.score <= 0]:
        m = by.get(repo)
        if m is None or m.retired or repo in out:
            continue
        if heavy(m)[1] > RUNNER_RAM_GB + 2 or m.gb > 16:   # SDXL（6.9GB）は通る。20GB を超える新しい世代は読み込みで止まった（2026-11-14）
            continue
        out.append(repo)
    return out


def draw(repo: str, out: Path):
    from chatdraw import adherebench
    out.mkdir(parents=True, exist_ok=True)
    (out / "repo.txt").write_text(repo, encoding="utf-8")   # 点を付ける側が、置き場の名前から模型の名前を戻さなくて済むように
    t = time.time()
    try:
        adherebench.draw(out, repo, SHARD, SHARDS, SEED)
    except Exception as e:   # 読めない・メモリが足りない。描けなかった絵は score で崩れとして数える
        import traceback
        (out / "error.txt").write_text(traceback.format_exc()[-3000:], encoding="utf-8")
        print(f"描けない: {e}", flush=True)
    print(f"描いた: {time.time() - t:.0f} 秒", flush=True)


def score(repo: str, out: Path) -> dict:
    from PIL import Image
    from chatdraw import adherebench
    res = adherebench.score([out]) if any(out.rglob("*-s*.json")) else {"images": 0, "rate": 0.0, "rows": []}
    flat = 0
    for png in sorted(out.rglob("*-s*.png")):
        if broken(image_stats(Image.open(png))):
            flat += 1
    err = (out / "error.txt").read_text(encoding="utf-8")[-300:] if (out / "error.txt").exists() else ""
    n = one_number(res, flat)
    report = {"repo": repo, "score": n, "images": res.get("images", 0), "expected": EXPECTED, "rate": res.get("rate", 0.0),
              "qc_images": res.get("qc_images", 0), "people_wrong": res.get("people_wrong", 0), "flat": flat,
              "error": err, "seed": SEED, "rows": res.get("rows", [])}
    (out / "score.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def note_line(r: dict, run: str = "") -> str:
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))
    where = f"（実行 {run}）" if run else ""
    if not r.get("images"):
        return f"{day} 自動の検証{where}: 描けなかった → 点 0"
    return (f"{day} 自動の検証{where}: 頼み {r['images']}/{r['expected']} 件、描けた語 {round(100 * r['rate'])}%、"
            f"崩れのある絵 {r['qc_images'] + r['people_wrong'] + r['flat']} 枚 → 点 {r['score']}")


def write(reports: list[dict], catalog: Path | None = None, run: str = "") -> list[str]:
    """目録に点と経緯の 1 行を書き戻す。点が PASS に届かない物は一覧に出なくなる（models.shown）。目録から外す（retired）のは人が決める"""
    catalog = catalog or Path(__file__).with_name("catalog.json")
    items = json.loads(catalog.read_text(encoding="utf-8"))
    done = []
    for r in reports:
        for e in items:
            key = f"{e['repo']}/{e['file']}" if e.get("format") == "single" else e["repo"]
            if key != r["repo"]:
                continue
            e["score"] = int(r["score"])
            line = note_line(r, run)
            e["note"] = (e.get("note", "") + " / " + line) if e.get("note") else line
            done.append(f"{key}: {r['score']}")
    catalog.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return done


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        print(json.dumps(candidates()))
    elif cmd == "draw":
        draw(sys.argv[2], Path(sys.argv[3]))
    elif cmd == "score":
        r = score(sys.argv[2], Path(sys.argv[3]))
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}, ensure_ascii=False))
    elif cmd == "write":
        import os
        reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[2:]]
        for line in write(reports, run=os.environ.get("GITHUB_RUN_ID", "")):
            print(line)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
