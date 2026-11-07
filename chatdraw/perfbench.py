"""描く処理の段階ごとの秒と GB を、本物の模型で 2 つの設定（前と後）について測る。Actions の perf-draw で動かす。

手元の機械は秒のぶれが 2 倍ほどあり、前と後を比べられなかった。同じ機械・同じ種・同じ頼みで 2 つの設定を続けて描き、
段階ごと（読み込み、描く本体、VAE の復号）の秒と RAM の山を JSON に残す。品質の差は、描いた絵を作画監督（tools/gen/measure.py）に
通した外れの数で示す。外れの数が後の設定で増えたら、その設定は採らない。

  python -m chatdraw.perfbench 出力の置き場
  環境変数: PERF_MODEL（模型）、PERF_STEPS（工程の数）、PERF_SIZE（幅x高さ）、PERF_SEED、PERF_CONFIGS（設定の名前をカンマで）
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


def run(out: Path):
    from chatdraw.engine import Painter
    out.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("PERF_MODEL", "cagliostrolab/animagine-xl-4.0")
    steps = int(os.environ.get("PERF_STEPS", "24"))
    w, h = (int(x) for x in os.environ.get("PERF_SIZE", "832x1216").split("x"))
    seed = int(os.environ.get("PERF_SEED", "7"))
    names = [n for n in os.environ.get("PERF_CONFIGS", "base,channels_last").split(",") if n in CONFIGS]
    result = {"model": model, "steps": steps, "size": [w, h], "seed": seed, "runs": []}
    for name in names:
        p = Painter(model, steps=steps)
        for k, v in CONFIGS[name].items():
            setattr(p, k, v)
        for i in (1, 2):   # 1 枚目は読み込みを含む。2 枚目は読んだ模型を使い回す
            t = time.perf_counter()
            img = p.paint(PROMPT, seed, size=(w, h))
            total = time.perf_counter() - t
            path = out / f"{name}-{i}.png"
            img.save(path)
            row = {"config": name, "image": i, "total_s": round(total, 2),
                   "stages": [dict(stage=n, s=s, ram_gb=r, vram_gb=v) for n, s, r, v in p.stages.rows]}
            print(json.dumps(row, ensure_ascii=False), flush=True)
            result["runs"].append(row)
        p.unload()
    for row in result["runs"]:
        if row["image"] == 2:
            row["quality"] = outliers(out / f"{row['config']}-2.png")
    (out / "perf.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    run(Path(sys.argv[1] if len(sys.argv) > 1 else "perf-out"))
