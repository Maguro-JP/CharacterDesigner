"""出来た絵からタグを読み、頼んだ描く言葉が描かれたかを突き合わせる（docs/app/PLAN.md の M8 の T1）。

模型は SmilingWolf/wd-vit-tagger-v3（Apache-2.0、約 380MB の ONNX）。アニメ絵を Danbooru のタグで読む。
描く模型（Animagine）も同じ Danbooru のタグで描くので、頼んだタグと読んだタグをそのまま比べられる。

置き場は .cache/assets/tagger（model.onnx と selected_tags.csv）。取るのは `sh tools/gen/setup.sh` の後に
`python3 tools/gen/tagger.py setup`。

  python3 tools/gen/tagger.py read 絵.png                 読んだタグ（確からしさ付き）
  python3 tools/gen/tagger.py check 絵.png "1girl, red scarf, knight"   頼んだうち描かれていないタグ
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / ".cache" / "assets" / "tagger"
REPO = "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main"
_SESSION = None
_TAGS = None

# 確かめないタグ。構図・光・画質・背景の言い方は絵から読みにくく、描けていても読めないことが多い
SKIP = ("lighting", "light", "shadow", "quality", "masterpiece", "aesthetic", "absurdres", "shot", "view", "body",
        "background", "solo", "contrast", "source", "focus", "detailed")


def setup():
    DIR.mkdir(parents=True, exist_ok=True)
    for name in ("model.onnx", "selected_tags.csv"):
        if not (DIR / name).exists():
            tmp = DIR / (name + ".part")
            urllib.request.urlretrieve(f"{REPO}/{name}", tmp)
            tmp.replace(DIR / name)
    return str(DIR)


def _load():
    global _SESSION, _TAGS
    if _SESSION is None:
        import onnxruntime as ort
        _SESSION = ort.InferenceSession(str(DIR / "model.onnx"), providers=["CPUExecutionProvider"])
        with open(DIR / "selected_tags.csv", newline="") as f:
            # category: 0 一般、4 キャラクター、9 年齢区分
            _TAGS = [(r["name"].replace("_", " "), int(r["category"])) for r in csv.DictReader(f)]
    return _SESSION, _TAGS


def read(path: str, threshold: float = 0.35) -> dict:
    """絵のタグと確からしさ。白で正方形に埋め、模型の大きさ（448）に縮め、BGR の 0〜255 で渡す（模型の作りの決まり）"""
    import numpy as np
    from PIL import Image
    sess, tags = _load()
    inp = sess.get_inputs()[0]
    size = inp.shape[1]
    im = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", im.size, (255, 255, 255, 255))
    canvas.alpha_composite(im)
    im = canvas.convert("RGB")
    side = max(im.size)
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    x = np.asarray(sq.resize((size, size), Image.BICUBIC), dtype=np.float32)[:, :, ::-1][None]
    probs = sess.run(None, {inp.name: np.ascontiguousarray(x)})[0][0]
    return {t: round(float(p), 3) for (t, cat), p in zip(tags, probs) if cat != 9 and p >= threshold}


def vocabulary() -> set:
    return {t for t, _ in _load()[1]}


def missing(prompt: str, got: dict, least: float = 0.2) -> list[str]:
    """頼んだタグのうち、絵から読めなかったもの。模型の知らない言い方（タグの一覧に無い）と、構図・光の言い方は数えない
    （数えられないものを落ちたことにすると、描き直しが止まらない）"""
    vocab = vocabulary()
    out = []
    for t in (x.strip().lower() for x in prompt.split(",")):
        if not t or t not in vocab or any(w in t for w in SKIP):
            continue
        if got.get(t, 0.0) < least:
            out.append(t)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        print(setup())
    elif cmd == "read":
        print(json.dumps(dict(sorted(read(sys.argv[2]).items(), key=lambda x: -x[1])), ensure_ascii=False, indent=1))
    elif cmd == "check":
        got = read(sys.argv[2], threshold=0.05)
        print(json.dumps({"missing": missing(sys.argv[3], got)}, ensure_ascii=False))
    else:
        print(__doc__)
