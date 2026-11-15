"""1 回で描く形と工程に分けて描く形（chatdraw/phases.py）を、本物の模型・同じ頼み・同じ種で比べる。Actions の phase-bench で動かす。

どちらの絵も、最後に同じ検品（手・足・顔、体、頼んだ物）に通して崩れの数を数え、かかった秒を残す。
工程に分けた回は、12 の工程ごとの絵（phases/s<種>/01-サムネイル.png 〜 12-仕上げ.png）と、工程ごとの見る物・判定の数字・
秒・常駐のメモリ（MB）・戻った回数を bench.json と phases.json に残す（Actions の artifact で見る）。

  python -m chatdraw.phasebench 出力の置き場
  環境変数: BENCH_MODEL、BENCH_PROMPT、BENCH_SEED、BENCH_STEPS、BENCH_SIZE（幅x高さ）、BENCH_WAYS（one,phases）
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


class Words:
    """頼みは英語のタグで渡すので、訳さずにそのまま描く言葉にする（言葉の模型の差を比べに混ぜない）"""
    untranslated, negative = [], []

    def ready(self):
        return True

    def to_prompt(self, text, tags=True):
        return text


def final_check(path: Path, prompt: str) -> dict:
    from chatdraw import handcheck, requestcheck, sanity
    hands = handcheck.check(path, asked=prompt)
    req = requestcheck.check(path, prompt, fetch=True)
    body = sanity.check(path, prompt, tags=req.get("read") if req.get("readable") else None)
    bad = list(hands.get("bad", [])) + list(body.get("bad", []))
    if req.get("readable"):
        bad += [f"描かれていない: {m}" for m in req["missing"]] + [f"人数が違う: {p}" for p in req.get("people", [])]
    return {"bad": bad, "count": len(bad), "readable": {"hands": hands.get("readable"), "request": req.get("readable"),
                                                        "body": body.get("readable")}}


def run(out: Path):
    from chatdraw.engine import Painter, Studio
    from chatdraw import handcheck, requestcheck
    out.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("BENCH_MODEL", "cagliostrolab/animagine-xl-4.0")
    prompt = os.environ.get("BENCH_PROMPT", "1girl, solo, standing, full body, waving, red scarf, school uniform, looking at viewer")
    seed = int(os.environ.get("BENCH_SEED", "7"))
    steps = int(os.environ.get("BENCH_STEPS", "20"))
    w, h = (int(x) for x in os.environ.get("BENCH_SIZE", "832x1216").split("x"))
    ways = os.environ.get("BENCH_WAYS", "one,phases").split(",")
    from huggingface_hub import snapshot_download
    from chatdraw import twostage
    from chatdraw.paths import HUB
    pose_files = dict(twostage.PARTS)[twostage.POSE]
    for fetch in (lambda: snapshot_download(twostage.POSE, cache_dir=str(HUB), allow_patterns=pose_files),
                  lambda: requestcheck._tagger(True), lambda: handcheck.ensure_models(True), lambda: handcheck.ensure_feet_model(True)):
        try:
            fetch()   # 検品の部品を先に取る（取らないと検品できず、崩れ 0 と読み違える）
        except Exception as e:   # noqa: BLE001
            print("検品の部品を取れませんでした:", e, flush=True)
    result = {"model": model, "prompt": prompt, "seed": seed, "steps": steps, "size": [w, h], "runs": []}
    painter = Painter(model, steps=steps)
    for way in ways:
        studio = Studio(Words(), painter, out / way)
        studio.way = way
        t = time.perf_counter()
        said = []
        used, path = studio.draw(prompt, seed, on_status=lambda m: (said.append(m), print(f"[{way}] {m}", flush=True)), size=(w, h))
        secs = round(time.perf_counter() - t, 1)
        shutil.copy(path, out / f"{way}-s{seed}.png")
        row = {"way": way, "seconds": secs, "prompt_used": used, "final": final_check(path, prompt), "said": said[-40:]}
        if studio.last_phases:
            row["phases"] = studio.last_phases
            row["per_phase"] = [{"phase": r["phase"], "seconds": r["seconds"], "mem_mb": r.get("mem_mb"), "numbers": r.get("numbers"),
                                 "left": r["after"] if r["fixed"] else r["found"]} for r in studio.last_phases]
            each = out / "phases" / f"s{seed}"
            each.mkdir(parents=True, exist_ok=True)
            for r in studio.last_phases:
                if r.get("image"):
                    shutil.copy(r["image"], each / Path(r["image"]).name)
            src = Path(studio.last_phases[-1]["image"] or "").parent / "phases.json"
            if src.exists():
                shutil.copy(src, each / "phases.json")
        result["runs"].append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "said"}, ensure_ascii=False), flush=True)
        (out / "bench.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    run(Path(sys.argv[1] if len(sys.argv) > 1 else "phase-out"))
