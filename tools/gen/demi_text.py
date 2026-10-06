"""日本語の頼みごと（「白い狐の巫女」）を、亜人の種の設定（casts/demi3d.json の1件）に組む。

環境変数 ANTHROPIC_API_KEY があれば Claude に読ませ、無ければ辞書（casts/demi-words.json）だけで読む。
辞書に無い言葉は推測で埋めず、使わなかった言葉として返す。どちらで読んでも、設定を組むのは辞書（build）。
組んだ設定は demi.validate_case で確かめてから返す（描き始めてから部品の名前違いで落ちないように）。
"""
from __future__ import annotations

import json
import os
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


def read_words(text, d=None):
    """辞書で頼みごとを読む。返り値は「読み取ったこと」（種・色・髪型・使わなかった言葉）で、設定はまだ組まない。"""
    d = d or _load()
    species = {s["id"]: s for s in d["species"]}
    toks = [t for t in tokenize(text.strip(), d) if t[0] != "skip"]
    got = {"species": None, "species_color": None, "hair_color": None, "eye_color": None, "hair_styles": [],
           "used": [], "unused": [], "notes": []}
    for i, (kind, val, word) in enumerate(toks):
        nxt = toks[i + 1][0] if i + 1 < len(toks) else None
        if kind == "species":
            if got["species"] is None:
                got["species"] = val
                got["used"].append(word)
            else:
                got["unused"].append(word)
                got["notes"].append(f"種が2つある。最初の「{species[got['species']]['words'][0]}」で組み、「{word}」は使わなかった")
        elif kind == "color":
            # 色は、すぐ後の言葉に掛ける（「銀の髪」「赤い目」「白い狐」）。後に何も無ければ種に掛ける
            key = {"hair": "hair_color", "eye": "eye_color"}.get(nxt, "species_color")
            got[key] = val
            got["used"].append(word)
        elif kind == "style":
            got["hair_styles"].append(val)
            got["used"].append(word)
        elif kind in ("hair", "eye", "part"):
            got["used"].append(word)
        elif kind == "not_drawn":
            got["unused"].append(word)
            got["notes"].append(f"「{word}」は設定資料では描かない（素体の水着と立ち姿で、部品の付け根を見る絵のため）")
        else:
            got["unused"].append(word)
    return got


def build(text, got, d=None):
    """読み取ったことから種の設定を組む。辞書を読むときも Claude に読ませるときも、組むのはここだけ（部品の取り違えを1か所で防ぐ）。"""
    d = d or _load()
    species = {s["id"]: s for s in d["species"]}
    notes = list(got["notes"])
    sp = species.get(got["species"]) if got["species"] else None
    if sp is None:
        names = "、".join(s["words"][0] for s in d["species"])
        return {"name": None, "case": None, "used": got["used"], "unused": got["unused"],
                "notes": notes + [f"種が分からない。使える種: {names}"]}
    if sp.get("approx"):
        notes.append(sp["approx"])
    color = lambda key: d["colors"][got[key]] if got.get(key) in d["colors"] else None
    sp_color, hair_color, eye_color = color("species_color"), color("hair_color"), color("eye_color")
    c_en = (sp_color["en"] + " ") if sp_color else ""
    # 種に色を付けたら、髪も同じ色にする（「白い狐」は白い耳と尾に白い髪）。髪の色を言われたらそちらを優先
    hair = hair_color or sp_color
    hair_en = hair.get("hair_en", hair["en"]) if hair else sp["hair"]   # 金の髪は golden より blonde の方が髪の色として効く
    hair_hex = hair["hex"] if hair else sp["hair_hex"]
    eyes = eye_color["en"] if eye_color else sp["eyes"]
    styles = [s for s in got["hair_styles"] if s in d["hair_styles"].values()]
    case = {
        "ja": text.strip()[:20],
        "parts": dict(sp["parts"]),
        "tags": sp["tags"].format(c=c_en),
        "hair": f"{hair_en} hair, {', '.join(styles) or 'long twintails'}, {eyes} eyes",
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
    return {"name": name, "case": case, "used": got["used"], "unused": got["unused"], "notes": notes}


def read_with_claude(text, client, d=None):
    """Claude に頼みごとを読ませる。答えは辞書の選択肢（種の id、色の言葉、髪型）からしか選べない形にする。
    設定そのものは書かせない。部品の組は build が辞書から決める（Claude が部品の名前を作り出して取り違えないように）"""
    d = d or _load()
    colors = sorted(d["colors"])
    styles = sorted(set(d["hair_styles"].values()))
    nullable = lambda enum: {"anyOf": [{"type": "string", "enum": enum}, {"type": "null"}]}
    schema = {
        "type": "object",
        "properties": {
            "species": nullable([s["id"] for s in d["species"]]),
            "species_color": nullable(colors),
            "hair_color": nullable(colors),
            "eye_color": nullable(colors),
            "hair_styles": {"type": "array", "items": {"type": "string", "enum": styles}},
            "used": {"type": "array", "items": {"type": "string"}},
            "unused": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["species", "species_color", "hair_color", "eye_color", "hair_styles", "used", "unused"],
        "additionalProperties": False,
    }
    guide = "\n".join(f"- {s['id']}: {'、'.join(s['words'])}" for s in d["species"])
    system = (
        "亜人のキャラクターの頼みごと（日本語）を読み、決められた選択肢に当てはめる。\n"
        f"種（species）は次の id から選ぶ。どれにも当たらなければ null。\n{guide}\n"
        "色は、種・髪・目のどれに掛かるかを読み分け、色の言葉の一覧から一番近いものを選ぶ。言われていなければ null。\n"
        "服・職業・表情・持ち物など、選択肢に無いことは unused に原文のまま入れる。当てはめた言葉は used に入れる。推測で埋めない。"
    )
    response = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": text}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"Claude が読み切らなかった（{response.stop_reason}）")
    got = json.loads(next(b.text for b in response.content if b.type == "text"))
    got["notes"] = [f"「{w}」は設定資料では描かない、または辞書の選択肢に無い" for w in got["unused"]]
    return got


def parse(text, client=None):
    """日本語から種の設定を組む。返り値: {name, case, used, unused, notes, reader}。種が分からなければ case は None。
    client（Anthropic のクライアント）を渡すと Claude に読ませ、失敗したら辞書で読む。"""
    d = _load()
    if client is not None:
        try:
            r = build(text, read_with_claude(text, client, d), d)
            r["reader"] = "claude"
            return r
        except Exception as e:   # 鍵の誤り・通信の失敗・拒否でも、辞書で組んで返す（頼みごとを止めない）
            r = build(text, read_words(text, d), d)
            r["reader"] = "words"
            r["notes"].insert(0, f"Claude で読めなかったので辞書で読んだ（{type(e).__name__}）")
            return r
    r = build(text, read_words(text, d), d)
    r["reader"] = "words"
    return r


def claude_client():
    """環境変数 ANTHROPIC_API_KEY があるときだけ Claude のクライアントを作る。鍵はリポジトリにも画面にも置かない。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic()


if __name__ == "__main__":
    import sys
    print(json.dumps(parse(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
