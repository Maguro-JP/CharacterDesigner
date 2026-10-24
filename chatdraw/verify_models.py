"""絵の模型を実際に動かして確かめる。catalog.json の点（score）を付けるための材料を作る。

    python -m chatdraw.verify_models <repo> <出力の置き場>

頼み 2 件を新規で、1 件をラフ（棒人形）から描き、絵と数字（report.json）を残す。
数字で落とすのは、読み込めない・真っ黒や一色の絵・ラフの部品と組めない、の 3 つ。絵の出来は、残した絵を見て決める。
重い（1 枚 数分）ので、手元ではなく GitHub Actions（model-verify.yml）で流す。
"""
from __future__ import annotations

import json
import resource
import sys
import time
import traceback
from pathlib import Path

PROMPTS = [
    ("girl", "1girl, solo, red hair, green eyes, school uniform, smile, full body, standing, simple background, white background"),
    ("knight", "1boy, solo, armor, cape, holding sword, full body, standing, simple background, white background"),
]
ROUGH = ("rough", "1girl, solo, waving hand, full body, simple background, white background")
SEED = 7


def stick_figure(size):
    """ラフの代わりの棒人形（白地に黒の線）。ラフから描く部品と組めるかを見るだけの物"""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    cx, line = w // 2, max(4, w // 120)
    d.ellipse((cx - w * 0.08, h * 0.08, cx + w * 0.08, h * 0.08 + w * 0.16), outline="black", width=line)
    top, hip = h * 0.08 + w * 0.16, h * 0.55
    d.line((cx, top, cx, hip), fill="black", width=line)
    d.line((cx, top + h * 0.05, cx - w * 0.22, top - h * 0.08), fill="black", width=line)   # 振る手
    d.line((cx, top + h * 0.05, cx + w * 0.18, top + h * 0.2), fill="black", width=line)
    d.line((cx, hip, cx - w * 0.12, h * 0.92), fill="black", width=line)
    d.line((cx, hip, cx + w * 0.12, h * 0.92), fill="black", width=line)
    return im


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


def fetch(repo: str):
    """アプリと同じ取り方（catalog.json の形式）で先に取る。読み込みはその置き場から行う"""
    from huggingface_hub import snapshot_download
    from chatdraw.models import image_model
    from chatdraw.paths import HUB
    m = image_model(repo)
    t = time.time()
    snapshot_download(repo, cache_dir=str(HUB), **m.files)
    from chatdraw.engine import SKETCH
    sk, files, _ = SKETCH[m.family]
    snapshot_download(sk, cache_dir=str(HUB), **files)
    return round(time.time() - t, 1)


def run(repo: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    fetched = fetch(repo)
    from chatdraw.models import image_model
    from chatdraw.engine import Painter
    m = image_model(repo)
    size = (832, 1216) if m.family == "sdxl" else (512, 768)
    report = {"repo": repo, "fetch_s": fetched, "family": m.family, "steps": m.steps, "size": size, "images": [], "errors": []}
    painter = Painter(repo, steps=m.steps, size=size, guidance=m.guidance)
    t = time.time()
    try:
        painter.load()
    except Exception:
        report["errors"].append("読み込めない: " + traceback.format_exc()[-1500:])
        return report
    report["load_s"] = round(time.time() - t, 1)
    jobs = [(name, (m.prefix + ", " if m.prefix else "") + p, None) for name, p in PROMPTS]
    jobs.append((ROUGH[0], (m.prefix + ", " if m.prefix else "") + ROUGH[1], stick_figure(size)))
    for name, prompt, base in jobs:
        t = time.time()
        try:
            im = painter.paint(prompt, SEED, base=base, strength=0.8 if base is not None else 1.0)
        except Exception:
            report["errors"].append(f"{name}: " + traceback.format_exc()[-1500:])
            continue
        took = time.time() - t
        path = out / f"{name}-s{SEED}.png"
        im.save(path)
        st = image_stats(im)
        report["images"].append({"name": name, "prompt": prompt, "seconds": round(took, 1),
                                 "per_step_s": round(took / m.steps, 2), "file": path.name, **st, "broken": broken(st)})
        print(f"{name}: {took:.0f} 秒", flush=True)
    report["peak_rss_gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1)
    report["auto"] = "落とす" if report["errors"] or any(i["broken"] for i in report["images"]) or len(report["images"]) < 3 \
        else "絵を見て決める"
    return report


def main():
    repo, out = sys.argv[1], Path(sys.argv[2])
    report = run(repo, out)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "images"}, ensure_ascii=False))
    print(f"exit=0 auto={report.get('auto', '落とす')}")


if __name__ == "__main__":
    main()
