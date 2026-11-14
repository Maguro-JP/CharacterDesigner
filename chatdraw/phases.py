"""人の描き方の工程に分けて描く（構図 → 線画 → 塗り → 仕上げ）。工程の調べは docs/knowledge/drawing-phases.md。

人は 1 回で描き上げず、アタリ・ラフで構図を決めて見直し、下描き・線画で形を決めて見直し、塗りで色を決めて見直し、
最後に全体を見直して仕上げる。前の工程で決めた物は次の工程で動かさないので、見直す物が工程ごとに少なく済む。

設計の決まり:
- 工程の数は決まっていて（PHASES）、各工程は「描く → 検品 → 見つけた崩れを 1 回だけ直す → 次の工程へ」で必ず終わる。
  検品が通るまで回す形にしない（0.5.20 でそうしたら終わらなくなり、描けなくなった）
- 直しで崩れが増えたら、直す前の絵を次の工程に渡す（直しが絵を壊すことがあった）
- 模型に渡す言葉は、頼みを訳した言葉と、その工程の描き方の指示（手・足・顔の直しの言葉）だけ。頼んでいない物を足さない。
  渡した言葉は工程ごとに知らせに出す
- 各工程の絵と検品の結果はファイルに残し、アプリは途中の絵を隠したレイヤーとして置く（利用者が見比べられる）
- 止める旗が立ったら、その工程の区切りで止まる
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# 工程の名前、決める物、検品で確かめる物。描き方は draw() の中で工程ごとに分ける
PHASES = [
    ("構図", "人数・姿勢・配置（アタリとラフ）", "人数、余分な腕・脚・頭、頼んだ物が描かれているか"),
    ("線画", "形（顔・手・指・足の形）", "手と指の数と形、足、顔"),
    ("塗り", "色と頼んだ物", "頼んだ色と物が描かれているか、頼んでいない物"),
    ("仕上げ", "全体の崩れ", "手・足・顔と体の崩れの全部"),
]
ROUGH_STEPS = 0.5     # 構図は工程の数を半分にして早く描く（ラフ）。私の推測の値で、本物の模型の比べで見直す
LINE_STRENGTH = 0.8   # 線画: 構図の線に沿う強さ（T2I-Adapter の効き）
REPAINT = 0.35        # 塗りの直し: 描かれていない物を足すときの描き直しの強さ（形は線画のまま残す）
FIX = 0.55            # 線画・仕上げの直し: 崩れた所の枠の中だけを描き直す強さ


class Checks:
    """工程ごとの検品。試験はこの組を偽物に差し替える"""

    @staticmethod
    def request(image, prompt):
        from chatdraw import requestcheck
        return requestcheck.check(image, prompt)

    @staticmethod
    def body(image, prompt, tags=None):
        from chatdraw import sanity
        return sanity.check(image, prompt, tags=tags)

    @staticmethod
    def hands(image, prompt):
        from chatdraw import handcheck
        return handcheck.check(image, asked=prompt)


def abilities(painter) -> tuple[bool, bool]:
    """(線に沿って描けるか, 枠の中だけ直せるか)。偽の模型は abilities を持てる"""
    own = getattr(painter, "abilities", None)
    if own is not None:
        return tuple(own)
    from chatdraw.models import family, image_model
    f = family(image_model(getattr(painter, "model", "")).family)
    return bool(f.sketch), bool(f.inpaint)


def _composition_flaws(req: dict, body: dict) -> list[str]:
    out = []
    if req.get("readable"):
        out += [f"人数が違う: {p}" for p in req.get("people", [])] + list(req.get("body", []))
        out += [f"描かれていない: {m}" for m in req.get("missing", [])]
    if body.get("readable"):
        out += list(body.get("bad", []))
    return out


def _color_flaws(req: dict) -> list[str]:
    if not req.get("readable"):
        return []
    return [f"描かれていない: {m}" for m in req.get("missing", [])] + [f"頼んでいない: {e}" for e in req.get("extra", [])]


def _mask(image, regions):
    from PIL import Image, ImageDraw
    mask = Image.new("L", image.size, 0)
    d = ImageDraw.Draw(mask)
    for (x0, y0, x1, y1), _kind in regions:
        cx, cy, rr = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.6
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    return mask


def draw(painter, prompt: str, seed: int, size, keep: Path, say=lambda m: None, on_step=None, checks=Checks) -> dict:
    """4 つの工程で 1 枚を描く。返り値は {"image": 最後の絵, "phases": 工程ごとの記録, "left": 残った崩れ, "checked": 検品できたか}。
    工程ごとに描くのは 1 回、直すのは崩れが見つかったときに 1 回だけ。どの工程も必ず終わる"""
    from chatdraw.engine import Stopped, emphasize
    from chatdraw import handcheck
    keep.mkdir(parents=True, exist_ok=True)
    can_line, can_fix = abilities(painter)
    rows, checked = [], True

    def stop():
        if getattr(painter, "stop", False) is True:
            raise Stopped("止めました")

    def record(i, image, found, fixed, after, words, t0, note=""):
        name = PHASES[i][0]
        path = keep / f"{i + 1}-{name}.png"
        image.save(path)
        row = {"phase": name, "decides": PHASES[i][1], "checks": PHASES[i][2], "image": str(path), "found": found,
               "fixed": fixed, "after": after, "words": words, "seconds": round(time.time() - t0, 1)}
        if note:
            row["note"] = note
        rows.append(row)
        left = after if fixed else found
        say(f"工程 {i + 1}/{len(PHASES)}「{name}」の検品: " + ("崩れは見つかりませんでした" if not left else "残った崩れ " + "、".join(left[:4])))

    def fix_regions(image, res, s, words_used):
        """手・足・顔の崩れた枠の中だけを 1 回描き直す。崩れが増えたら直す前の絵を返す"""
        regions = handcheck.bad_regions(res)
        if not regions or not can_fix:
            return image, res, False
        words = f"{prompt}, " + ", ".join(dict.fromkeys(handcheck.FIX_WORDS[k] for _b, k in regions))
        say(f"崩れた所を 1 回だけ直しています（{len(regions)} か所）。渡す言葉: {words}")
        words_used.append(words)
        tried = painter.redraw(words, s, image, _mask(image, regions), strength=FIX)
        again = checks.hands(tried, prompt)
        if again.get("readable") and len(again.get("bad", [])) <= len(res.get("bad", [])):
            return tried, again, True
        say("直しで崩れが減らなかったので、直す前の絵を次の工程に渡します")
        return image, res, True

    # 1. 構図: 工程の数を減らしたラフで、人数・姿勢・配置を決める
    stop()
    t0 = time.time()
    say(f"工程 1/{len(PHASES)}「構図」を描いています。渡す言葉: {prompt}")
    steps0 = getattr(painter, "steps", None)
    try:
        if isinstance(steps0, int):
            painter.steps = max(4, int(steps0 * ROUGH_STEPS))
        image = painter.paint(prompt, seed, on_step=on_step, size=size)
        req, body = checks.request(image, prompt), checks.body(image, prompt)
        found = _composition_flaws(req, body)
        fixed, after, words = False, [], [prompt]
        if found:   # 構図の崩れは枠では直せないので、種を変えて構図だけを 1 回描き直し、崩れの少ない方を使う
            stop()
            say("構図の崩れを直すため、種を変えて構図を 1 回だけ描き直しています")
            words.append(prompt)
            again = painter.paint(prompt, seed + 1, on_step=on_step, size=size)
            req2, body2 = checks.request(again, prompt), checks.body(again, prompt)
            after = _composition_flaws(req2, body2)
            fixed = True
            if len(after) < len(found):
                image, req, body = again, req2, body2
            else:
                after = found
    finally:
        if isinstance(steps0, int):
            painter.steps = steps0
    checked = checked and bool(req.get("readable")) and bool(body.get("readable"))
    record(0, image, found, fixed, after, words, t0)

    # 2. 線画: 構図の線に沿って、形を描き込む。手・指・足・顔の崩れは枠の中だけを 1 回直す
    stop()
    t0 = time.time()
    words, note = [], ""
    if can_line:
        say(f"工程 2/{len(PHASES)}「線画」を描いています（構図の線に沿う）。渡す言葉: {prompt}")
        words.append(prompt)
        image = painter.paint(prompt, seed, on_step=on_step, base=image, strength=LINE_STRENGTH, size=size)
    else:
        note = "この模型は線に沿って描けないので、構図の絵のまま形を検品しました"
        say(note)
    res = checks.hands(image, prompt)
    found = list(res.get("bad", []))
    image, res2, fixed = fix_regions(image, res, seed + 77, words)
    after = list(res2.get("bad", []))
    checked = checked and bool(res.get("readable"))
    record(1, image, found, fixed, after, words, t0, note)

    # 3. 塗り: 頼んだ色と物を確かめる。描かれていない物があれば、形を残す弱さで 1 回だけ描き直す
    stop()
    t0 = time.time()
    words, note = [], ""
    req = checks.request(image, prompt)
    found = _color_flaws(req)
    fixed, after = False, []
    missing = list(req.get("missing", [])) if req.get("readable") else []
    if missing and can_fix:
        stop()
        again_words = emphasize(prompt, missing)
        say(f"描かれていない物（{'、'.join(missing)}）を 1 回だけ描き足しています。渡す言葉: {again_words}")
        words.append(again_words)
        from PIL import Image
        tried = painter.redraw(again_words, seed + 131, image, Image.new("L", image.size, 255), strength=REPAINT)
        req2 = checks.request(tried, prompt)
        after = _color_flaws(req2)
        fixed = True
        if len(after) <= len(found):
            image = tried
        else:
            after = found
            say("描き足しで崩れが増えたので、前の絵を次の工程に渡します")
    elif missing:
        note = "この模型は描き直しができないので、描かれていない物を直さずに次へ進みました"
    record(2, image, found, fixed, after, words, t0, note)

    # 4. 仕上げ: 全体の崩れ（手・足・顔と体）を見直し、手・足・顔は 1 回だけ直す。最後の検品の結果を残った崩れにする
    stop()
    t0 = time.time()
    words = []
    res = checks.hands(image, prompt)
    body = checks.body(image, prompt)
    found = list(res.get("bad", [])) + (list(body.get("bad", [])) if body.get("readable") else [])
    image, res2, fixed = fix_regions(image, res, seed + 191, words)
    after = list(res2.get("bad", [])) + (list(body.get("bad", [])) if body.get("readable") else [])
    checked = checked and bool(res.get("readable")) and bool(body.get("readable"))
    record(3, image, found, fixed, after, words, t0)
    left = rows[-1]["after"] if rows[-1]["fixed"] else rows[-1]["found"]
    (keep / "phases.json").write_text(json.dumps({"phases": rows, "left": left, "checked": checked}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return {"image": image, "phases": rows, "left": left, "checked": checked}
