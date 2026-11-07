"""綺麗にする加工の段階ごとの秒と最大メモリ（GB）を、設定を並べて測る（GitHub Actions の finish-bench で流す）。

    python -m chatdraw.bench_finish <絵> [<前の版の置き場>]

段階ごとに別の処理で流し、その処理の最大メモリを測る（同じ処理で続けると、前の段階の分が混ざる）。
前の版の置き場（git worktree で取り出した前の版）を渡すと、同じ絵で前の版の綺麗にするも測り、並べて出す。
部位分けは 512・fp32（今の形）、512・bf16、384・fp32 を並べ、顔の印が今の形とどれだけ重なるかも出す。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD = r'''
import json, resource, sys, time
sys.path.insert(0, sys.argv[1])
from PIL import Image
stage, path, scale = sys.argv[2], sys.argv[3], int(sys.argv[4])
im = Image.open(path).convert("RGB")
if scale > 1:
    im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
out = {}
t = time.time()
if stage.startswith("seg:"):
    import numpy as np, torch
    sys.path.insert(0, sys.argv[1] + "/tools/gen")
    import edit
    from transformers import AutoModelForSemanticSegmentation
    side, dt = stage.split(":")[1:]
    dtype = torch.bfloat16 if dt == "bf16" else torch.float32
    m = AutoModelForSemanticSegmentation.from_pretrained(edit.SEG_MODEL, torch_dtype=dtype).eval()
    out["load"] = round(time.time() - t, 2)
    def seg(side, dtype):
        a = np.asarray(im.resize((side, side), Image.BILINEAR), dtype=np.float32) / 255.0
        a = (a - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
        with torch.inference_mode():
            lg = m(pixel_values=torch.tensor(a.transpose(2, 0, 1)[None], dtype=dtype)).logits.float()
        return torch.nn.functional.interpolate(lg, size=(im.height, im.width), mode="bilinear").argmax(1)[0].numpy() == 11
    t = time.time()
    face = seg(int(side), dtype)
    np.save(sys.argv[5], face)
else:
    from chatdraw import finishers as F
    F.run_chain(stage.split("+"), im)
out["seconds"] = round(time.time() - t, 2)
out["gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 3)
print("RESULT " + json.dumps(out))
'''


def one(root: str, stage: str, path: str, scale: int = 1, save: str = "") -> dict:
    r = subprocess.run([sys.executable, "-c", CHILD, root, stage, path, str(scale), save or "/dev/null"],
                       capture_output=True, text=True, cwd=root)
    for line in r.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    return {"error": (r.stderr or r.stdout)[-800:]}


def main():
    import numpy as np
    path = str(Path(sys.argv[1]).resolve())
    old = sys.argv[2] if len(sys.argv) > 2 else ""
    rows = []
    ref = None
    for side, dt in (("512", "fp32"), ("512", "bf16"), ("384", "fp32")):
        save = f"/tmp/face-{side}-{dt}.npy"
        r = one(str(ROOT), f"seg:{side}:{dt}", path, 1, save)
        if "error" not in r:
            f = np.load(save)
            ref = f if ref is None else ref
            r["face_iou"] = round(float((f & ref).sum() / max(1, (f | ref).sum())), 3)
        rows.append(dict(stage=f"部位分け {side}・{dt}", **r))
    for scale in (1, 2):
        for stage in ("clean", "retouch", "retouch_full", "clean+retouch_full"):
            for name, root in (("前", old), ("後", str(ROOT))):
                if root:
                    rows.append(dict(stage=f"{stage} ×{scale}（{name}）", **one(root, stage, path, scale)))
    for r in rows:
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
