"""赤ペンの直しを本物の絵の模型で確かめる。同じ絵・同じ囲みに違う指示を出し、渡った言葉と結果の絵を残す。
手元の試験は偽の模型なので、指示どおりに絵が変わるかはここでしか見られない（.github/workflows/fix-verify.yml）。
使い方: python -m chatdraw.fix_verify 絵.png 出す所 "左,上,右,下" 指示1 指示2 ..."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    from PIL import Image
    from chatdraw import requestcheck
    from chatdraw.engine import Painter, Studio, Words
    src, out, box, notes = Path(argv[0]), Path(argv[1]), [int(v) for v in argv[2].split(",")], argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    try:
        requestcheck._tagger(True)   # 記録の無い絵は絵からタグを読むので、読む部品を先に取る
    except Exception as e:
        print("絵を読む部品を取れませんでした:", e)
    image = Image.open(src).convert("RGB")
    mask = Image.new("L", image.size, 0)
    mask.paste(255, tuple(box))
    studio = Studio(Words(Path("")), Painter(), out / "saved")   # 言葉の模型なし（辞書の訳の経路）
    strength = float(os.environ.get("FIX_STRENGTH", "0.75"))
    log = []
    for i, note in enumerate(notes, 1):
        said: list[str] = []
        seed = random.randrange(0, 2_000_000_000)   # 種を固定しないときの画面と同じく、押すたびに新しい種
        t0 = time.time()
        _prompts, path = studio.fix(image, [(mask, note)], seed, on_status=said.append, strength=strength)
        layer = Image.open(path).convert("RGBA")
        done = image.convert("RGBA")
        done.alpha_composite(layer)
        name = f"fix-{i}.png"
        done.convert("RGB").save(out / name)
        row = {"note": note, "seed": seed, "strength": strength, "seconds": round(time.time() - t0, 1), "file": name,
               "said": [s for s in said if s.startswith(("渡した言葉", "赤ペンの指示のうち", "元の絵の言葉"))]}
        log.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (out / "fix-verify.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
