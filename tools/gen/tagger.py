"""出来た絵からタグを読み、頼んだ描く言葉が描かれたかを突き合わせる（docs/app/PLAN.md の M8 の T1）。

模型は SmilingWolf/wd-vit-tagger-v3（Apache-2.0、約 380MB の ONNX）。アニメ絵を Danbooru のタグで読む。
描く模型（Animagine）も同じ Danbooru のタグで描くので、頼んだタグと読んだタグをそのまま比べられる。

置き場は .cache/assets/tagger（model.onnx と selected_tags.csv）。`sh tools/gen/setup.sh` が取る（単独では `python3 tools/gen/tagger.py setup`）。

  python3 tools/gen/tagger.py read 絵.png                 読んだタグ（確からしさ付き）
  python3 tools/gen/tagger.py check 絵.png "1girl, red scarf, knight"   頼んだうち描かれていないタグ
"""
from __future__ import annotations

import cdhome
import csv
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = cdhome.HOME / "assets" / "tagger"
REPO = "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main"
_SESSION = None
_TAGS = None

# 確かめないタグ。構図・光・画質・背景の言い方は絵から読みにくく、描けていても読めないことが多い
SKIP = ("lighting", "light", "shadow", "quality", "masterpiece", "aesthetic", "absurdres", "shot", "view", "body",
        "background", "solo", "contrast", "source", "focus", "detailed",
        # 塗りと見せ方の言葉（casts/paint-styles.json）。物ではなく描き方なので、絵から読めなくても描けていないとは言えない
        "coloring", "flat color", "shading", "lineart", "medium", "traditional", "sketch", "texture", "brushstroke", "painting",
        "colors", "monochrome", "greyscale", "screentone", "hatching", "ink", "outline", "page", "sheet", "views", "art",
        "composition", "pose", "angle", "perspective", "palette")


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
    # 年齢区分（category 9: general / sensitive / questionable / explicit）は絵のタグと混ぜず、別に控える。
    # 捨てていたため、露出の度合いを測る経路が無かった。rating() が同じ絵をもう一度読まずに返す
    _RATING[str(path)] = {t: round(float(p), 3) for (t, cat), p in zip(tags, probs) if cat == 9}
    return {t: round(float(p), 3) for (t, cat), p in zip(tags, probs) if cat != 9 and p >= threshold}


_RATING: dict = {}


def rating(path: str) -> dict:
    """年齢区分の確からしさ（general / sensitive / questionable / explicit）。read() を済ませた絵は読み直さない"""
    if str(path) not in _RATING:
        read(path)
    return dict(_RATING[str(path)])


def vocabulary() -> set:
    return {t for t, _ in _load()[1]}


# 歩く・走るなどの動きは、止まった絵のタグでは読み分けにくい（歩いている絵 2 枚で walking を「無い」と出した。描画確認 段階1）
MOTION = ("walking", "running", "jumping", "dancing", "standing", "turning")
# 足元が画面に入らない構図。この構図では足元の言葉の欠けを数えない（cowboy shot で靴の言葉が全部「無い」と出た）
CROPPED = ("cowboy shot", "upper body", "portrait", "close-up", "knee up", "half body", "bust")
FEET = ("shoes", "boots", "footwear", "socks", "sandals", "sneakers", "heels", "feet", "barefoot", "loafers", "thighhighs", "kneehighs")


def missing(prompt: str, got: dict, least: float = 0.2) -> list[str]:
    """頼んだタグのうち、絵から読めなかったもの。模型の知らない言い方（タグの一覧に無い）と、構図・光の言い方は数えない
    （数えられないものを落ちたことにすると、描き直しが止まらない）。動きの言葉と、足元の入らない構図での足元の言葉も数えない"""
    vocab = vocabulary()
    low = prompt.lower()
    cropped = any(c in low for c in CROPPED)
    out = []
    for t in (x.strip().lower() for x in prompt.split(",")):
        if not t or t not in vocab or any(w in t for w in SKIP) or t in MOTION or (cropped and any(f in t for f in FEET)):
            continue
        # 「holding lantern」が読めなくても lantern が読めれば描けている（持ち方の言い方は読み分けにくい）
        core = t.split(" ", 1)[1] if t.startswith(("holding ", "wearing ", "carrying ")) else t
        if max(got.get(t, 0.0), got.get(core, 0.0)) < least:
            out.append(t)
    return out


# 頼んでいないのに描かれやすい物（服と持ち物）。強く読めたのに頼みに無ければ、頼みと違う絵として描き直しの理由にする
# （白いビキニを頼んで、白い上着を羽織った絵が出た。Windows の描画 種 7）
EXTRA_WATCH = ("shirt", "jacket", "coat", "hoodie", "sweater", "cardigan", "vest", "skirt", "pants", "shorts", "jeans", "dress",
               "kimono", "apron", "cape", "sarong", "pareo", "shawl", "robe", "towel", "hat", "cap", "glasses", "sunglasses", "mask", "bag", "umbrella", "sword", "weapon",
               "gloves", "scarf", "necktie", "pantyhose", "thighhighs")


def extras(prompt: str, got: dict, least: float = 0.6) -> list[str]:
    """頼みに無い服・持ち物のうち、絵から強く読めたもの（確からしさ least 以上）。頼みに同じ語があれば数えない"""
    low = prompt.lower()
    out = []
    for t, p in sorted(got.items(), key=lambda kv: -kv[1]):
        if p < least or t in low:
            continue
        words = t.replace("_", " ").split()
        if words and words[-1] in EXTRA_WATCH and words[-1] not in low:
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
