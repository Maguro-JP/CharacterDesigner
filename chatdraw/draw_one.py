"""頼み 1 件を、指定の模型で 1 枚描く（GitHub Actions の draw-one.yml で流す）。

    python -m chatdraw.draw_one <置き場>   （頼みは config/draw-request.json）

手元に置けない大きな模型（FLUX、Z-Image など）を、描く仕組み（Painter）と同じ経路で試すために使う。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    req = json.loads(Path("config/draw-request.json").read_text(encoding="utf-8"))
    if req.get("mode") == "twostage":
        from chatdraw.twostage import draw
        t = time.time()
        im = draw(req["prompt"], req["tags"], req.get("seed", 7), req["compose"], req["render"], size=tuple(req.get("size", (832, 1216))),
                  say=lambda m: print(m, flush=True), keep=out)
        (out / "request.json").write_text(json.dumps(dict(req, seconds=round(time.time() - t)), ensure_ascii=False, indent=1), encoding="utf-8")
        print("exit=0")
        return
    from huggingface_hub import snapshot_download
    from chatdraw.models import image_model
    from chatdraw.paths import HUB
    m = image_model(req["repo"])
    t = time.time()
    snapshot_download(m.repo, cache_dir=str(HUB), **m.files)
    print(f"取った: {time.time() - t:.0f} 秒", flush=True)
    from chatdraw.engine import Painter
    p = Painter(m.repo, steps=req.get("steps", m.steps), size=tuple(req.get("size", (832, 1216))), guidance=req.get("guidance", m.guidance))
    t = time.time()
    im = p.paint(req["prompt"], req.get("seed", 7), on_step=lambda i, n: print(f"描いています {i}/{n}", flush=True))
    name = f"{m.repo.replace('/', '_')}-s{req.get('seed', 7)}.png"
    im.save(out / name)
    (out / "request.json").write_text(json.dumps(dict(req, seconds=round(time.time() - t), size_out=list(im.size)), ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print(f"描いた: {name} {im.size} {time.time() - t:.0f} 秒")
    print("exit=0")


if __name__ == "__main__":
    main()
