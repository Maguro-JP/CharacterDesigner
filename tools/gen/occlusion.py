"""隠す構図の検品。見えない部位を全部落とさず、3 つに分ける。

  - hidden: 見えないのが当たり前（構図の外、後ろ向き、手を隠す姿勢、裾や物の陰）→ 通す
  - must_see: 見えないとおかしい（頼んだ動作に要る、全身の構図）→ 落とす
  - absent: 無い（手前に隠す物も絵の端も無いのに、肘や膝から先が背景の中で途切れている）→ 落とす

見えないことだけで落とすと、ポケットに手を入れた絵や膝上の構図を手足の欠けとして落とした。逆に「見えない＝隠れた」と
決めると、途中で消えた腕を通す。骨格の模型は見えない関節にも位置を出すので、その位置に何があるか（絵の外、
体や服や物、背景）で隠れたか無いかを分ける。決まりの言葉は styles/occlusion.json。
"""
from __future__ import annotations

import json
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parents[2] / "styles" / "occlusion.json").read_text(encoding="utf-8"))
SEEN = 0.5      # 関節の確からしさがこれ以上なら見えている
PARENT = 0.5    # 根元の関節がこれ以上なら、その先が続いているはず
EDGE = 0.03     # 絵の端からこの割合の内は、構図で切れたとみなす
NEAR = 4        # 関節の周りの何画素四方で、何が重なっているかを見る


def _words(prompt: str, rules: list[dict]) -> list[dict]:
    low = prompt.lower()
    return [r for r in rules if any(w in low for w in r["words"])]


def _under(seg, x: float, y: float, own: list[int]) -> str:
    """関節の推定位置にあるもの: out（絵の外か端）、own（その部位）、cover（ほかの体・服・物）、bg（背景）"""
    h, w = seg.shape
    if x < w * EDGE or y < h * EDGE or x > w * (1 - EDGE) or y > h * (1 - EDGE):
        return "out"
    xi, yi = int(x), int(y)
    patch = seg[max(0, yi - NEAR):yi + NEAR + 1, max(0, xi - NEAR):xi + NEAR + 1]
    vals = set(int(v) for v in patch.ravel())
    if vals & set(own):
        return "own"
    if vals - {0}:
        return "cover"
    return "bg"


def judge(points: list[dict], seg, prompt: str = "") -> dict:
    """部位ごとに seen / hidden / must_see / absent を決める。problems は落とす部位だけ"""
    p = {q["name"]: q for q in points}
    hide = _words(prompt, RULES["hide"])
    need = _words(prompt, RULES["need"])
    parts = {}
    for name, d in RULES["parts"].items():
        j, par = p.get(d["joint"]), p.get(d["parent"])
        if not j:
            continue
        if j["score"] >= SEEN:
            parts[name] = {"state": "seen"}
            continue
        where = _under(seg, j["x"], j["y"], d["seg"])
        if where == "own":
            # 部位分けでは見えている（関節の模型が自信を持てないだけ）
            parts[name] = {"state": "seen", "by": "seg"}
            continue
        parts[name] = {"state": "unseen", "where": where, "group": d["group"],
                       "parent_seen": bool(par and par["score"] >= PARENT)}
    problems = []
    for g in {d["group"] for d in RULES["parts"].values()}:
        unseen = [n for n, v in parts.items() if v.get("group") == g]
        if not unseen:
            continue
        # 対の部位で片方だけ隠してよい決まり（横向き、片目の髪）は、両方見えないときに 1 つだけを許す
        ok_all = [r for r in hide if g in r["groups"] and not r.get("one")]
        ok_one = [r for r in hide if g in r["groups"] and r.get("one")]
        need_all = [r for r in need if g in r["groups"] and not r.get("one")]
        need_one = [r for r in need if g in r["groups"] and r.get("one")]
        pair = len([n for n, d in RULES["parts"].items() if d["group"] == g and n in parts])
        # 構図の要り用（全身）は、姿勢の隠す決まり（座ると奥の足が体の陰）より弱い。動作の要り用（手を振る）は強い
        hard = [r for r in need_all if not r.get("soft")]
        allowed = 0 if hard else pair if ok_all else 1 if ok_one else 0
        if need_one and len(unseen) >= pair:
            allowed = min(allowed, pair - 1)
        for i, n in enumerate(sorted(unseen)):
            v = parts[n]
            if i < allowed:
                v.update(state="hidden", why=(ok_all or ok_one)[0]["why"])
            elif v["where"] == "out" and not (need_all or need_one):
                v.update(state="hidden", why="絵の端で切れた（構図）")
            elif v["where"] == "cover" and not (need_all or need_one):
                v.update(state="hidden", why="体・服・物の陰")
            elif v["where"] == "bg" and v["parent_seen"]:
                v.update(state="absent", why="根元はあるのに、隠す物の無い背景の中で途切れている")
            else:
                v.update(state="must_see", why=((need_all or need_one)[0]["why"] if (need_all or need_one) else "隠す理由が無い"))
            if v["state"] in ("absent", "must_see"):
                problems.append({"part": n, "state": v["state"], "why": v["why"]})
    return {"parts": parts, "problems": problems}
