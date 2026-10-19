"""持ち物が途中で切れて、別々の物に描かれた矛盾を数える。

模型は長い持ち物（ほうき、杖、槍、傘）を、手に持った柄と床に置いた穂のように2つに分けて描くことがある。
部位分けもタグ読みも物のつながりを見ないので、文字で物を探す検出器（OWLv2、Apache-2.0）で
頼んだ物とその部品を探し、重ならない塊が2つ以上あれば「別々に描かれた」とする。

  python3 tools/gen/pieces.py check IMAGE "1girl, witch, holding broom"
"""
import cdhome
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 模型の置き場所（.cache/gen/hf）と取りに行かない既定を、diffusers・transformers を読む前に効かせる。
# 関数の中で design を読んでいたため、先に transformers を読んだ呼び出しでは ~/.cache/huggingface へ取りに行った
import design  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(cdhome.HOME / "gen" / "hf"))
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


_OWL = None


def _owl():
    """検出器は 1 回だけ読む（絵ごとに読み直すと 1 枚に読み込みの時間が足された）"""
    global _OWL
    if _OWL is None:
        from transformers import Owlv2ForObjectDetection, Owlv2Processor
        _OWL = (Owlv2Processor.from_pretrained(MODEL), Owlv2ForObjectDetection.from_pretrained(MODEL))
    return _OWL


def detect(src: str, queries: list[str], least: float = LEAST) -> list[tuple[str, float, list[float]]]:
    import torch
    from PIL import Image
    proc, model = _owl()
    im = Image.open(src).convert("RGB")
    with torch.no_grad():
        out = model(**proc(text=[queries], images=im, return_tensors="pt"))
    # OWLv2 は正方形に詰めて読むので、長い辺の正方形で座標を戻す
    s = max(im.size)
    r = proc.post_process_grounded_object_detection(out, threshold=least, target_sizes=torch.tensor([[s, s]]))[0]
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


# 頼んだ持ち物が 1 つのはずなのに、別の所に 2 つ以上描かれた崩れ（学生鞄が両手に 1 つずつ、8 枚中 3〜4 枚）
# 剣は刃と柄も聞く。1 本が途中で切れて柄と刃が離れて描かれた絵（アプリの通し確認の剣士）は「a sword」だけでは 1 か所に見え、
# 刃と柄も聞くと 2 か所に分かれた。騎士の 9 枚では、片手に短剣・もう片手に別の柄を描いた 1 枚だけが 2 か所になった
COUNT = {"bag": ["a bag", "a school bag"], "backpack": ["a backpack"], "sword": ["a sword", "a sword blade", "a sword hilt"], "cup": ["a cup"],
         "glass": ["a drinking glass"], "umbrella": ["an umbrella"], "book": ["a book"]}
MANY_WORDS = ("two ", "both", "pair", "multiple", "several", "dual", "2 ")
# 持ち物を名前に含む言い方（剣士は剣を 1 本持つ）
ALIAS = {"swordsman": "sword", "swordswoman": "sword", "swordsmaster": "sword", "katana": "sword"}


# 部品（刃と柄）に分けて聞く物は、箱が接していれば 1 つの物とする。騎士の 1 本の剣で、刃の箱と柄の箱が
# 重ならずに接していたため 2 か所と数えた（重なりの割合だけでは、つながった部品を別の物と見る）
TOUCH = {"sword"}
GAP = 0.03          # 長い辺に対するこの割合までの隙間は、接しているとみなす（分かれた剣士の柄と刃は 0.126 離れていた）


def _gap(a, b) -> float:
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return max(dx, dy)


def joined(groups: list[list[list[float]]], src: str) -> list[list[list[float]]]:
    """箱どうしが接している（隙間が長い辺の GAP 以内）塊をまとめる"""
    from PIL import Image
    near = GAP * max(Image.open(src).size)
    out: list[list[list[float]]] = []
    for g in groups:
        hit = [h for h in out if any(_gap(a, b) <= near for a in g for b in h)]
        out = [h for h in out if h not in hit] + [g + [x for h in hit for x in h]]
    return out


def count_extra(src: str, prompt: str, least: float = 0.2) -> list[str]:
    """頼んだ数え物（鞄・剣・器）が 1 つのはずなのに、重ならない 2 か所以上に見つかれば、その理由を返す。
    セーラー服で book bag を持たせた 8 枚で、目で見て 2 つの鞄を描いた絵のうち 3 枚に当たり、1 つの絵には当たらなかった"""
    low = prompt.lower()
    if any(w in low for w in MANY_WORDS):
        return []
    words = {w.strip(" ()") for t in low.split(",") for w in t.split()}
    words |= {ALIAS[w] for w in words if w in ALIAS}
    # 「book bag」の book は鞄の言い方の一部で、本を頼んではいない
    if "book bag" in low and "book," not in low + ",":
        words.discard("book")
    out = []
    for word, queries in COUNT.items():
        if word not in words:
            continue
        groups = clusters([b for _, _, b in detect(src, queries, least)])
        if word in TOUCH:
            groups = joined(groups, src)
        if len(groups) >= 2:
            out.append(f"{word} が {len(groups)} か所に描かれている（頼んだのは 1 つ。別々の物か、1 つが途中で切れて分かれた）")
    return out


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "check":
        print(json.dumps({"split": split_objects(sys.argv[2], sys.argv[3])}, ensure_ascii=False))
    else:
        print(__doc__)
