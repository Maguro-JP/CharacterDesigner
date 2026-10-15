"""持ち物が途中で切れて、別々の物に描かれた矛盾を数える。

模型は長い持ち物（ほうき、杖、槍、傘）を、手に持った柄と床に置いた穂のように2つに分けて描くことがある。
部位分けもタグ読みも物のつながりを見ないので、文字で物を探す検出器（OWLv2、Apache-2.0）で
頼んだ物とその部品を探し、重ならない塊が2つ以上あれば「別々に描かれた」とする。

  python3 tools/gen/pieces.py check IMAGE "1girl, witch, holding broom"
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
# 模型は既定で外から取りに行かない。呼んだ関数が手元に無い模型を指していると、数 GB を取りに行って
# ディスクを埋めた（2026-10-14 に 2 回）。初めて取るときだけ CD_FETCH=1 を付けて動かす
os.environ.setdefault("HF_HUB_OFFLINE", "0" if os.environ.get("CD_FETCH") == "1" else "1")
MODEL = "google/owlv2-base-patch16-ensemble"

# 頼んだ言葉 → 検出器に聞く言い方（本体と、分かれたときに出る部品）
QUERIES = {
    "broom": ["a broom", "a broom head", "a wooden stick", "a long stick"],
    "staff": ["a staff", "a wooden stick", "a long stick"],
    "spear": ["a spear", "a spearhead", "a long pole"],
    "umbrella": ["an umbrella", "an umbrella handle"],
}
# 自信の下限。床に分かれて置かれた魔女のほうきで、本体 0.65・柄 0.30・余分な重複 0.18 だった
LEAST = 0.18
# 片方の箱がもう片方にこれ以上入っていれば同じ物とみなす（手の柄と床の穂は 0.06 だった）
SAME = 0.3


def _inside(a, b):
    """箱 a のうち、箱 b に入っている割合"""
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1)
    return w * h / area


def clusters(boxes: list[list[float]]) -> list[list[list[float]]]:
    """重なる箱どうしを1つの物にまとめる。小さい方の箱が大きい方に SAME 以上入っていれば同じ物"""
    groups: list[list[list[float]]] = []
    for b in boxes:
        hit = [g for g in groups if any(max(_inside(b, x), _inside(x, b)) >= SAME for x in g)]
        merged = [b] + [x for g in hit for x in g]
        groups = [g for g in groups if g not in hit] + [merged]
    return groups


def ready() -> bool:
    """検出器を取ってあるか（取るのは `python3 tools/gen/pieces.py check` を1度走らせたとき）"""
    return (Path(os.environ["HF_HOME"]) / "hub" / ("models--" + MODEL.replace("/", "--"))).exists()


def asked(prompt: str) -> list[str]:
    words = {w for t in prompt.lower().split(",") for w in t.split()}
    return [k for k in QUERIES if k in words]


def detect(src: str, queries: list[str]) -> list[tuple[str, float, list[float]]]:
    import torch
    from PIL import Image
    from transformers import Owlv2ForObjectDetection, Owlv2Processor
    proc = Owlv2Processor.from_pretrained(MODEL)
    model = Owlv2ForObjectDetection.from_pretrained(MODEL)
    im = Image.open(src).convert("RGB")
    with torch.no_grad():
        out = model(**proc(text=[queries], images=im, return_tensors="pt"))
    # OWLv2 は正方形に詰めて読むので、長い辺の正方形で座標を戻す
    s = max(im.size)
    r = proc.post_process_grounded_object_detection(out, threshold=LEAST, target_sizes=torch.tensor([[s, s]]))[0]
    return [(queries[int(l)], float(c), [float(v) for v in b]) for c, l, b in zip(r["scores"], r["labels"], r["boxes"])]


def split_objects(src: str, prompt: str) -> list[str]:
    """頼んだ長い持ち物が、重ならない2か所以上に分かれて描かれていれば、その理由を返す"""
    out = []
    for word in asked(prompt):
        found = detect(src, QUERIES[word])
        groups = clusters([b for _, _, b in found])
        if len(groups) >= 2:
            out.append(f"{word} が {len(groups)} つに分かれて描かれている（柄と先が別々）")
    return out


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "check":
        print(json.dumps({"split": split_objects(sys.argv[2], sys.argv[3])}, ensure_ascii=False))
    else:
        print(__doc__)
