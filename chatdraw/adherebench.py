"""頼んだ通りに描けているかを測る台。頼みの文 30 本（chatdraw/tests/test_words.py の SENTENCES）を本物の経路で描かせ、
描いた絵からタグを読んで、頼んだ語のうち描けた語の割合と、作画監督（手・足・顔の検品）の外れの数を数える。

    python -m chatdraw.adherebench draw  <置き場> <模型> <組の番号> <組の数> [種]   （今のリポジトリの描く経路で描く）
    python -m chatdraw.adherebench score <置き場>...                               （描いた絵を読んで数える）
    python -m chatdraw.adherebench table <前の数字.json> <後の数字.json>           （前と後を並べる）

描く所は、言葉の模型の無いアプリと同じ（jaterms の表 → 書かれていない所を種で足す → Painter.paint）。
draw は前の版と後の版のリポジトリでそれぞれ流し（作業の置き場をその版にする）、score は同じ版の読み方で両方を数える。
描く言葉は Painter.paint の中で組む（質の決まり文句を頼みの後ろへ回す engine.lead_quality も通る）ので、前と後の差に頼みの並べ方も入る。
重い（SDXL を CPU で 1 枚 10 分ほど）ので、手元ではなく GitHub Actions（adhere-bench.yml）で流す。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SEED = 7


def sentences() -> list[str]:
    """試験の頼みの 30 本。試験の組を読むと PySide6 が要るので、文の表だけを読む（Actions の描く機械には画面の部品を入れない）"""
    import ast
    src = (Path(__file__).resolve().parent / "tests" / "test_words.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "SENTENCES" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise LookupError("SENTENCES が test_words.py にありません")


def draw(out: Path, repo: str, shard: int, shards: int, seed: int = SEED):
    """組の番号 shard（0 から）に当たる頼みを描く。作業の置き場の版の言葉の直しと描く経路をそのまま使う"""
    out.mkdir(parents=True, exist_ok=True)
    from chatdraw.engine import Painter, Words, vary_background
    from chatdraw.models import family as fam, image_model
    m = image_model(repo)
    painter = Painter(repo, steps=m.steps, size=fam(m.family).size, guidance=m.guidance)
    words = Words(Path(""))   # 言葉の模型は使わない（表の直しを測る。模型の訳は機械ごとに揺れる）
    for i, text in enumerate(sentences()):
        if i % shards != shard:
            continue
        prompt = words.to_prompt(text)
        try:
            prompt = vary_background(prompt, seed, tags=fam(m.family).tags, text=text)
        except TypeError:   # 0.5.17 より前の版は text を受けない（前の版と比べるときに落ちないように）
            prompt = vary_background(prompt, seed, tags=fam(m.family).tags)
        painter.avoid = ", ".join(words.negative)
        t = time.time()
        im = painter.paint(prompt, seed)
        name = f"{i:02d}-s{seed}"
        im.save(out / f"{name}.png")
        (out / f"{name}.json").write_text(json.dumps({"index": i, "text": text, "prompt": prompt, "negative": painter.avoid,
                                                      "seed": seed, "repo": repo, "seconds": round(time.time() - t, 1)},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {time.time() - t:.0f} 秒 {prompt}", flush=True)


def asked(text: str) -> list[str]:
    """数える語。頼みの文から読んだ語で、女性の基準の体の言葉（頼みではない）は除く。前と後で同じ物差しにするため、
    score を流す版の読み方で前の絵も数える"""
    from chatdraw import jaterms
    body = set(getattr(jaterms, "_BODY", ()))
    return [t for t in jaterms.tags_from(text) if t not in body]


def score_one(png: Path, meta: dict, tg) -> dict:
    got = tg.read(str(png), threshold=0.05)
    want = asked(meta["text"])
    measurable = [t for t in want if tg.missing(t, {})]   # 読めない語（タグの一覧に無い・構図の言い方）は数えない
    miss = tg.missing(", ".join(measurable), got)
    from chatdraw import handcheck, requestcheck
    try:
        hc = handcheck.check(png, fetch=True, asked=meta["prompt"])
        bad = list(hc.get("bad", []))
        if not hc.get("readable"):
            bad.append("手が読めない（検品できない絵は崩れとして数える）")
    except Exception as e:
        bad = [f"検品できない（{e}）"]
    return {"index": meta["index"], "text": meta["text"], "prompt": meta["prompt"], "asked": measurable, "missing": miss,
            "people": requestcheck.people(meta["prompt"], got), "qc": bad}


def score(dirs: list[Path]) -> dict:
    from chatdraw.requestcheck import _tagger
    tg = _tagger(fetch=True)
    rows = []
    for d in dirs:
        for meta_path in sorted(d.rglob("*-s*.json")):
            png = meta_path.with_suffix(".png")
            if png.exists():
                rows.append(score_one(png, json.loads(meta_path.read_text(encoding="utf-8")), tg))
    rows.sort(key=lambda r: r["index"])
    n_asked = sum(len(r["asked"]) for r in rows)
    n_miss = sum(len(r["missing"]) for r in rows)
    lost: dict[str, int] = {}
    for r in rows:
        for t in r["missing"]:
            lost[t] = lost.get(t, 0) + 1
    return {"images": len(rows), "asked": n_asked, "drawn": n_asked - n_miss,
            "rate": round((n_asked - n_miss) / n_asked, 3) if n_asked else 0.0,
            "people_wrong": sum(bool(r["people"]) for r in rows), "qc_bad": sum(len(r["qc"]) for r in rows),
            "qc_images": sum(bool(r["qc"]) for r in rows), "lost": dict(sorted(lost.items(), key=lambda kv: -kv[1])), "rows": rows}


def table(before: dict, after: dict) -> str:
    keys = [("images", "絵の数"), ("asked", "数えた語"), ("drawn", "描けた語"), ("rate", "描けた割合"),
            ("people_wrong", "人数の違う絵"), ("qc_bad", "作画監督の外れ"), ("qc_images", "外れのある絵")]
    lines = ["| 項目 | 前 | 後 |", "|---|---|---|"] + [f"| {j} | {before.get(k)} | {after.get(k)} |" for k, j in keys]
    lines += ["", "落ちた語（前）: " + "、".join(f"{t} {n}" for t, n in list(before["lost"].items())[:20]),
              "落ちた語（後）: " + "、".join(f"{t} {n}" for t, n in list(after["lost"].items())[:20])]
    return "\n".join(lines)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "draw":
        draw(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]) if len(sys.argv) > 6 else SEED)
    elif cmd == "score":
        res = score([Path(a) for a in sys.argv[2:]])
        print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))
        Path("score.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    elif cmd == "table":
        load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))   # noqa: E731
        print(table(load(sys.argv[2]), load(sys.argv[3])))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
