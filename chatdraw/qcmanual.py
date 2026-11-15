"""手で呼ぶ検品。今の絵（AI が描いた絵でも、人が描いた絵でも）の手・足・顔を検品し、崩れた所を赤ペンの印にする。

検品と直しは別に動かす。検品は印と指示を置くだけで直さない。直すのは利用者が「囲んだ所を直す」を押したときだけ。
描く・検品・直しを繋げて回すと、検品が読み違え続けたときに止まらず、描けなくなった。
"""
from __future__ import annotations

KIND = {"hands": "手", "feet": "足", "faces": "顔"}


def inspect(image, asked: str = "") -> dict:
    """絵（PIL）を検品する。試験はこれを偽の検品に差し替える。
    asked は絵の模型に渡した言葉（分かるときだけ）。渡すと、頼んだ物が描かれたか・頼んでいない物が無いかも見る。
    「検品する」で頼みを見ていなかったため、頼んでいない腕輪や 2 本目の剣を書いた絵が、検品の台で 11 枚とも通っていた"""
    from chatdraw import handcheck, sanity
    res = handcheck.check(image, asked=asked)
    tags = None
    if asked:
        from chatdraw import requestcheck
        r = requestcheck.check(image, asked)
        res["request"] = {k: r.get(k) for k in ("readable", "missing", "extra", "people", "reason")}
        tags = r.get("read") if r.get("readable") else None
    try:
        odd = sanity.check(image, asked, tags=tags)
    except Exception as e:   # noqa: BLE001  体の検品が落ちても、手・足・顔の結果は返す
        odd = {"readable": False, "bad": [], "reason": f"体の検品で止まりました（{e}）"}
    res["body_bad"] = list(odd.get("bad", []))
    res["mirror"] = odd.get("mirror") or {}
    if not odd.get("readable", True) and odd.get("reason"):
        res["body_reason"] = odd["reason"]
    return res


def flaws(res: dict, offset: tuple[int, int] = (0, 0)) -> list[tuple[list[int], str]]:
    """崩れの見つかった所ごとの枠（絵の画素）と、指示の欄に書く崩れの中身"""
    ox, oy = offset
    out = []
    for key, name in KIND.items():
        for h in res.get(key, []) or []:
            if h.get("bad") and h.get("box"):
                x0, y0, x1, y1 = h["box"]
                said = "、".join(str(b) for b in h["bad"])
                out.append(([x0 + ox, y0 + oy, x1 + ox, y1 + oy], said if said.startswith(name) else f"{name}: {said}"))
    # 映り込みの矛盾（chatdraw/mirrorcheck.py）。言葉は「矛盾: 鏡の中の〜」で始まる
    for m in (res.get("mirror") or {}).get("flaws", []) or []:
        x0, y0, x1, y1 = m["box"]
        out.append(([x0 + ox, y0 + oy, x1 + ox, y1 + oy], "、".join(m["bad"])))
    return out


def unplaced(res: dict) -> list[str]:
    """場所の分からない崩れ（脚の本数、余分な腕など）。印は付けられないので、知らせに書く"""
    placed = {b for key in KIND for h in res.get(key, []) or [] for b in h.get("bad", [])}
    rest = [b for b in res.get("bad", []) if not any(str(b).endswith(str(p)) for p in placed)]
    req = res.get("request") or {}
    rest += [f"頼んだのに描かれていない: {m}" for m in req.get("missing") or []]
    rest += [f"頼んでいない物: {e}" for e in req.get("extra") or []]
    rest += [f"頼んだ人数と違う: {p}" for p in req.get("people") or []]
    return rest + list(res.get("body_bad", []))


def missed(res: dict) -> list[str]:
    """検品できなかった所。できなかった所を「崩れが無い」と読ませない"""
    out = []
    if res.get("reason"):
        out.append("手: " + res["reason"])
    elif not res.get("readable") and not res.get("hands"):
        out.append("手: 手を読めませんでした（写っていないか、隠れています）")
    if res.get("feet_reason"):
        out.append("足: " + res["feet_reason"])
    face = res.get("face") or {}
    if face and not face.get("readable") and not face.get("bad"):
        out.append("顔: " + (face.get("reason") or "顔を読めませんでした"))
    req = res.get("request") or {}
    if req and not req.get("readable"):
        out.append("頼んだ物: " + (req.get("reason") or "頼んだ物を読めませんでした"))
    if (res.get("mirror") or {}).get("reason"):
        out.append("映り込み: " + res["mirror"]["reason"])
    for k, name in (("legs_reason", "脚"), ("body_reason", "体")):
        if res.get(k):
            out.append(f"{name}: {res[k]}")
    return out
