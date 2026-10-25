"""手と足の切り出しの指の数を、手元で動く小さな画像と言葉の模型（VLM）に数えさせる。

手の色の筋で数える方法（hands.py の count_fingers）はアニメの手ではほとんど数えられず、
手の関節 21 点の模型はいつも指を 5 本置くので、指が足りない・多い手を見逃した。
ここでは切り出しを大きくして模型に数えさせ、言い方を変えた問いを何度か聞いて多数決にする。
小さな模型は「指は 5 本」と答えがちなことが知られているので、数のほかに「崩れているか」も別に聞く。

模型は CD_VLM_MODEL（既定 Qwen/Qwen2.5-VL-3B-Instruct）。torch と transformers が無ければ ImportError。
評価: python3 tools/gen/vlmcount.py eval tests/fixtures/fingercount  （.github/workflows/fingercount-eval.yml）
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

MODEL = os.environ.get("CD_VLM_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct")
SIDE = int(os.environ.get("CD_VLM_SIDE", "448"))   # 切り出しの短い辺をこの大きさまで拡げる

PROMPTS = {
    "hand": [
        "This is a close-up of a hand in an anime illustration. How many fingers, including the thumb, are visible? Answer with a single number.",
        "Count the visible digits of this drawn hand one by one (thumb, index, middle, ring, little), then give the total as 'TOTAL: n'.",
    ],
    "foot": [
        "This is a close-up of a bare foot in an anime illustration. How many toes are visible? Answer with a single number.",
        "Count the visible toes of this drawn foot one by one from the big toe, then give the total as 'TOTAL: n'.",
    ],
}
ODD = {
    "hand": "Look carefully. Is this drawn hand anatomically wrong: extra fingers, missing fingers, or fingers fused together? Answer yes or no.",
    "foot": "Look carefully. Is this drawn foot anatomically wrong: extra toes, missing toes, or toes fused together? Answer yes or no.",
}

_m = None


def _load():
    """模型は 1 度だけ読む"""
    global _m
    if _m is None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        proc = AutoProcessor.from_pretrained(MODEL)
        model = AutoModelForImageTextToText.from_pretrained(MODEL, torch_dtype=torch.bfloat16).eval()
        _m = (proc, model)
    return _m


def _ask(im, text: str) -> str:
    import torch
    proc, model = _load()
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}]
    prompt = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inp = proc(text=[prompt], images=[im], return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=80, do_sample=False)
    return proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


def _number(ans: str):
    m = re.search(r"TOTAL:\s*(\d+)", ans) or re.search(r"\b(\d+)\b", ans)
    if m:
        return int(m.group(1))
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    for w, n in words.items():
        if re.search(rf"\b{w}\b", ans.lower()):
            return n
    return None


def _enlarge(im):
    from PIL import Image
    im = im.convert("RGB")
    s = SIDE / min(im.size)
    return im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS) if s > 1 else im


def count_digits(crop, kind: str = "hand") -> dict:
    """切り出し（PIL か道）の指の数。count は多数決（割れたら None）、odd は模型が崩れと答えたか。
    verdict: too_many（6 以上）/ odd（崩れと答えた）/ ok / unreadable。5 未満は隠れているだけのことが多いので too_few にしない"""
    from PIL import Image
    im = Image.open(crop) if isinstance(crop, (str, Path)) else crop
    im = _enlarge(im)
    answers = [_ask(im, p) for p in PROMPTS[kind]]
    votes = [_number(a) for a in answers]
    c = Counter(v for v in votes if v is not None).most_common()
    count = c[0][0] if c and (len(c) == 1 or c[0][1] > c[1][1]) else None
    odd_ans = _ask(im, ODD[kind])
    odd = odd_ans.lower().startswith("yes")
    if count is not None and count > 5:
        verdict = "too_many"
    elif odd:
        verdict = "odd"
    elif count is None:
        verdict = "unreadable"
    else:
        verdict = "ok"
    return {"count": count, "votes": votes, "odd": odd, "verdict": verdict, "answers": answers + [odd_ans]}


def evaluate(folder: str) -> list[dict]:
    """正解（truth.json）と比べる。flag は崩れと出したか（too_many か odd）"""
    import resource
    d = Path(folder)
    truth = json.loads((d / "truth.json").read_text())
    rows = []
    for name, t in truth.items():
        if name.startswith("_"):
            continue
        t0 = time.time()
        r = count_digits(d / f"{name}.png", t["kind"])
        sec = time.time() - t0
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        flag = r["verdict"] in ("too_many", "odd")
        rows.append({"name": name, "kind": t["kind"], "truth": t.get("visible"), "bad": t["bad"], **r,
                     "flag": flag, "hit": flag == t["bad"], "sec": round(sec, 1), "rss_mb": rss})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    return rows


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "eval":
        t0 = time.time()
        rows = evaluate(sys.argv[2])
        out = {"model": MODEL, "side": SIDE, "rows": rows, "hits": sum(r["hit"] for r in rows), "n": len(rows),
               "total_sec": round(time.time() - t0, 1)}
        Path(sys.argv[3] if len(sys.argv) > 3 else "fingercount.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(out["hits"], "/", out["n"])
    else:
        print(json.dumps(count_digits(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "hand"), ensure_ascii=False))
