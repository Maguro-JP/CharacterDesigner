"""日本語の頼みごと（「白い狐の巫女」）を、亜人の種の設定（casts/demi3d.json の1件）に組む。

API キーを使わず、辞書（casts/demi-words.json）だけで組む。辞書に無い言葉は推測で埋めず、使わなかった言葉として返す。
組んだ設定は demi.validate_case で確かめてから返す（描き始めてから部品の名前違いで落ちないように）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import demi

WORDS = Path(__file__).resolve().parents[2] / "casts" / "demi-words.json"
# 白い部品は白い背景に溶けて検品で消えたと数えられた。明るい部品の種は薄い灰の背景で描く（demi3d.json の _doc）
LIGHT_BG = "#c9ced6"


def _load():
    return json.loads(WORDS.read_text())


def _luma(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def tokenize(text, d):
    """左から最長一致で辞書の言葉に切る。どの言葉にも当たらない文字は続けて1つの「不明」にまとめる。"""
    vocab = {}
    for s in d["species"]:
        for w in s["words"]:
            vocab[w] = ("species", s["id"])
    for w in d["colors"]:
        vocab[w] = ("color", w)
    for w, en in d["hair_styles"].items():
        vocab[w] = ("style", en)
    for w in d["hair_words"]:
        vocab[w] = ("hair", w)
    for w in d["eye_words"]:
        vocab[w] = ("eye", w)
    for w in d["part_words"]:
        vocab[w] = ("part", w)
    for w in d["not_drawn"]["words"]:
        vocab[w] = ("not_drawn", w)
    for w in d["skip"]:
        vocab.setdefault(w, ("skip", w))
    keys = sorted(vocab, key=len, reverse=True)
    out, i, unknown = [], 0, ""
    while i < len(text):
        hit = next((k for k in keys if text.startswith(k, i)), None)
        if hit is None:
            unknown += text[i]
            i += 1
            continue
        if unknown:
            out.append(("unknown", unknown, unknown))
            unknown = ""
        kind, val = vocab[hit]
        out.append((kind, val, hit))
        i += len(hit)
    if unknown:
        out.append(("unknown", unknown, unknown))
    return out


def parse(text):
    """日本語から種の設定を組む。返り値: {name, case, used, unused, notes}。種が分からなければ case は None。"""
    d = _load()
    species = {s["id"]: s for s in d["species"]}
    toks = [t for t in tokenize(text.strip(), d) if t[0] != "skip"]
    used, unused, notes = [], [], []
    sp, sp_color, hair_color, eye_color, styles = None, None, None, None, []
    for i, (kind, val, word) in enumerate(toks):
        nxt = toks[i + 1][0] if i + 1 < len(toks) else None
        if kind == "species":
            if sp is None:
                sp = species[val]
                used.append(word)
            else:
                unused.append(word)
                notes.append(f"種が2つある。最初の「{sp['words'][0]}」で組み、「{word}」は使わなかった")
        elif kind == "color":
            c = d["colors"][val]
            # 色は、すぐ後の言葉に掛ける（「銀の髪」「赤い目」「白い狐」）。後に何も無ければ種に掛ける
            if nxt == "hair":
                hair_color = c
            elif nxt == "eye":
                eye_color = c
            else:
                sp_color = c
            used.append(word)
        elif kind == "style":
            styles.append(val)
            used.append(word)
        elif kind in ("hair", "eye", "part"):
            used.append(word)
        elif kind == "not_drawn":
            unused.append(word)
            notes.append(f"「{word}」は設定資料では描かない（素体の水着と立ち姿で、部品の付け根を見る絵のため）")
        else:
            unused.append(word)
    if sp is None:
        names = "、".join(s["words"][0] for s in d["species"])
        return {"name": None, "case": None, "used": used, "unused": unused,
                "notes": notes + [f"種が分からない。使える種: {names}"]}
    if sp.get("approx"):
        notes.append(sp["approx"])
    c_en = (sp_color["en"] + " ") if sp_color else ""
    # 種に色を付けたら、髪も同じ色にする（「白い狐」は白い耳と尾に白い髪）。髪の色を言われたらそちらを優先
    hair = hair_color or sp_color
    hair_en = hair.get("hair_en", hair["en"]) if hair else sp["hair"]   # 金の髪は golden より blonde の方が髪の色として効く
    hair_hex = hair["hex"] if hair else sp["hair_hex"]
    eyes = eye_color["en"] if eye_color else sp["eyes"]
    style = ", ".join(styles) if styles else "long twintails"
    case = {
        "ja": text.strip()[:20],
        "parts": dict(sp["parts"]),
        "tags": sp["tags"].format(c=c_en),
        "hair": f"{hair_en} hair, {style}, {eyes} eyes",
        "negative": sp["negative"],
        "anatomy": sorted({"ears": "animal_ears", "tail": "tail", "wings": "wings"}[s] for s in sp["parts"] if s in ("ears", "tail", "wings")),
        "hair_color": hair_hex,
    }
    part_hex = sp_color["hex"] if sp_color else (sp["color"] if sp.get("approx") else None)
    if part_hex:
        case["parts"]["color"] = {slot: part_hex for slot in sp["parts"]}
    if _luma(part_hex or sp["color"]) > 200:
        case["background"] = LIGHT_BG
    if "strength" in sp:
        case["strength"] = sp["strength"]
    errs = demi.validate_case(case)
    if errs:
        raise ValueError(f"辞書から組んだ設定が検査を通らない: {errs}")
    name = re.sub(r"[^a-z0-9]+", "-", f"{sp_color['en'] if sp_color else ''} {sp['id']}".strip()).strip("-")
    return {"name": name, "case": case, "used": used, "unused": unused, "notes": notes}


if __name__ == "__main__":
    import sys
    print(json.dumps(parse(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
