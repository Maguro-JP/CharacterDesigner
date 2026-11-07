"""描く処理の段階ごとの秒と GB を、本物の模型で 2 つの設定（前と後）について測る。Actions の perf-draw で動かす。

手元の機械は秒のぶれが 2 倍ほどあり、前と後を比べられなかった。同じ機械・同じ種・同じ頼みで 2 つの設定を続けて描き、
段階ごと（読み込み、描く本体、VAE の復号）の秒と RAM の山を JSON に残す。品質の差は、描いた絵を作画監督（tools/gen/measure.py）に
通した外れの数で示す。外れの数が後の設定で増えたら、その設定は採らない。

  python -m chatdraw.perfbench 出力の置き場
  環境変数: PERF_MODEL（模型）、PERF_STEPS（工程の数）、PERF_SIZE（幅x高さ）、PERF_IMAGES（設定ごとの枚数）、PERF_SEED、PERF_CONFIGS（設定の名前をカンマで）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = "1girl, solo, standing, full body, school uniform, looking at viewer, smile, simple background"

# 設定の名前 → Painter に足す属性。base が前（今の作り）
CONFIGS = {
    "base": {},
    "channels_last": {"channels_last": True},
}


def outliers(path: Path) -> dict:
    """作画監督（measure.py）の外れの数。測れなかったら理由を返す（測れないことを外れ 0 と読まない）"""
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen" / "measure.py"), str(path), "--json"],
                           capture_output=True, text=True, timeout=1800, cwd=str(ROOT))
        line = next((l for l in r.stdout.splitlines() if l.startswith("{")), "")
        if not line:
            return {"outliers": None, "error": (r.stderr or r.stdout)[-400:]}
        bad = json.loads(line).get("outliers", [])
        return {"outliers": len(bad), "paths": [b.get("path") for b in bad]}
    except Exception as e:   # noqa: BLE001
        return {"outliers": None, "error": f"{type(e).__name__}: {e}"}


def _env():
    model = os.environ.get("PERF_MODEL", "cagliostrolab/animagine-xl-4.0")
    steps = int(os.environ.get("PERF_STEPS", "8"))
    w, h = (int(x) for x in os.environ.get("PERF_SIZE", "768x768").split("x"))
    seed = int(os.environ.get("PERF_SEED", "7"))
    count = int(os.environ.get("PERF_IMAGES", "1"))
    return model, steps, (w, h), seed, count


def run(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    model, steps, size, seed, count = _env()
    names = [n for n in os.environ.get("PERF_CONFIGS", "base,channels_last").split(",") if n in CONFIGS]
    from chatdraw.engine import bf16_fast
    result = {"model": model, "steps": steps, "size": list(size), "seed": seed, "bf16_fast": bf16_fast(), "runs": []}
    dump = out / "perf.json"

    def save():   # 1 枚ごとに書き足す。打ち切られても測れた分が残る（前は全部描き終えてから書き、何も残らなかった）
        dump.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    for name in names:
        # 設定ごとに別の処理で描く。同じ処理で続けたら、前の設定の模型の RAM（11GB）が戻らず、後の設定が予算で止まった
        sub = subprocess.Popen([sys.executable, "-u", "-m", "chatdraw.perfbench", "--one", name, str(out)], cwd=str(ROOT),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        got = 0
        for line in sub.stdout:
            if line.startswith('{"config"'):
                row = json.loads(line)
                print(line.rstrip(), flush=True)
                result["runs"].append(row)
                got += 1
                save()
        err = sub.stderr.read()
        if sub.wait() and not got:
            result["runs"].append({"config": name, "image": 0, "error": err[-600:]})
            save()
    for row in result["runs"]:
        if row.get("image") == count:
            row["quality"] = outliers(out / f"{row['config']}-{count}.png")
            save()
    print(json.dumps(result, ensure_ascii=False, indent=1))


def one(name: str, out: Path):
    """1 つの設定を、この処理だけで描いて測る（run が別の処理で呼ぶ）"""
    from chatdraw.engine import Painter
    out.mkdir(parents=True, exist_ok=True)
    model, steps, size, seed, count = _env()
    p = Painter(model, steps=steps)
    for k, v in CONFIGS[name].items():
        setattr(p, k, v)
    for i in range(1, count + 1):   # 1 枚目は読み込みを含む。2 枚目からは読んだ模型を使い回す
        t = time.perf_counter()
        img = p.paint(PROMPT, seed, size=size)
        total = time.perf_counter() - t
        img.save(out / f"{name}-{i}.png")
        row = {"config": name, "image": i, "total_s": round(total, 2),
               "stages": [dict(stage=n, s=s, ram_gb=r, vram_gb=v) for n, s, r, v in p.stages.rows]}
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--one":
        one(sys.argv[2], Path(sys.argv[3]))
    else:
        run(Path(sys.argv[1] if len(sys.argv) > 1 else "perf-out"))
