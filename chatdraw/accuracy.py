"""全部の機能の精度を、同じ形（0〜100、高いほど良い）で測る台。

機能ごとに「測る物」と「正解」を決め、数字を 1 つにまとめる。前の数字と並べて、下がった物を見つけるためのもの。
直す順番は、この台で一番低い機能から（推測で選ばない）。

軽い物（言葉の表・チャットの読み取り・場所・サボりの検品・赤ペンの直し・加工）は手元の試験（chatdraw/tests/test_accuracy.py）で流す。
重い物（拡大の模型、数字の検品の部位分け）は GitHub Actions（.github/workflows/accuracy.yml）で流す。
自動選択（模型の選び方）は別の台が受け持つので、ここでは測らない。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "library" / "eyes" / "eyes-blue.jpg"   # 顔の寄りの絵。赤ペンと加工の土台
FEEDBACK = ROOT / "library" / "feedback"
# 背景つきの全身の絵。加工の土台（顔の寄りの絵は顔を守る印が絵のほとんどを覆い、加工の効きを測れない）
SCENE = FEEDBACK / "check" / "2026-10-17" / "r2-bartender-scene" / "r2-bartender-scene-s24.jpg"

# ---- 描く言葉: 頼みの語が模型に届いたか（Words.to_prompt は模型に渡す前の言葉。言葉の模型が無いときの経路） ----
# (頼み, 届くべき語, 届いてはいけない語)
WORDS = [
    ("青い髪の女の子", ["1girl", "blue hair"], []),
    ("赤い目の少年", ["1boy", "red eyes"], []),
    ("傘を持った女の子", ["1girl", "umbrella", "holding"], []),
    ("剣を持つ侍", ["sword", "samurai"], []),
    ("本を読んでいる少女", ["1girl", "book", "reading"], []),
    ("猫耳の女の子が笑っている", ["1girl", "cat ears", "smile"], []),
    ("眼鏡をかけた男性", ["1boy", "glasses"], []),
    ("黒いドレスの魔女", ["witch", "black dress"], []),
    ("帽子なしの女の子", ["1girl"], ["hat"]),
    ("二人の女の子", ["2girls"], ["1girl"]),
    ("白い背景で全身の女の子", ["1girl", "full body", "white background"], []),
    ("金髪のポニーテールの少女", ["1girl", "blonde hair", "ponytail"], []),
    ("ウインクしている女の子", ["1girl", "wink"], []),
    ("横顔の少年", ["1boy", "profile"], []),
    ("緑の目のエルフ", ["green eyes", "elf"], []),
    ("花を持った女の子", ["1girl", "flower", "holding"], []),
    ("制服の女の子", ["1girl", "school uniform"], []),
    ("銀髪の長い髪の女の子", ["1girl", "silver hair", "long hair"], []),
    ("泣いている女の子", ["1girl", "crying"], []),
    ("腕を組んだ男の子", ["1boy", "crossed arms"], []),
]

# ---- 場所の言葉: 場所の頼みから、ふさわしい場所の語を選んだか ----
PLACES = [
    ("海辺の女の子", "beach"), ("森の中の少女", "forest"), ("教室にいる男の子", "classroom"), ("夜の街の女の子", "city"),
    ("図書館で本を読む少女", "library"), ("カフェの女の子", "cafe"), ("神社の巫女", "shrine"), ("雪の中の少女", "snow"),
    ("桜の下の女の子", "cherry blossoms"), ("屋上の少年", "rooftop"), ("駅のホームの女の子", "train station"),
    ("砂漠を歩く旅人", "desert"), ("草原の少女", "grassland"), ("夕焼けの海の女の子", "sunset"), ("城の前の騎士", "castle"),
    ("部屋の中の女の子", "indoors"), ("公園の男の子", "park"), ("山の上の少女", "mountain"), ("川辺の女の子", "river"),
    ("宇宙の少女", "space"), ("水中の人魚", "underwater"), ("寝室の女の子", "bedroom"), ("台所で料理する女の子", "kitchen"),
    ("学校の廊下の少年", "school"), ("雨の街の女の子", "rain"),
]

# ---- チャットの読み取り: (一言, 絵があるか, 正解の (kind, arg) か None) ----
CHAT = [
    ("4枚ずつ描くようにして", True, ("count", 4)), ("枚数を3にして", True, ("count", 3)), ("２枚ずつ", True, ("count", 2)),
    ("五枚ずつ描いて", True, ("count", 5)), ("猫を4枚描いて", True, None),
    ("大きさを1024にして", True, ("size", "正方形")), ("縦長にして", True, ("size", "縦")), ("横長の絵にして", True, ("size", "横")),
    ("サイズを832x1216にして", True, ("size", "縦")), ("正方形で描くようにして", True, ("size", "正方形")),
    ("水彩風にして", True, ("finisher", "style_watercolor")), ("厚塗りにして", True, ("finisher", "style_thick")),
    ("アニメ調にして", False, ("style", "アニメ")), ("線画にして", True, ("finisher", "style_lineart")),
    ("綺麗にして", True, ("finisher", "retouch")), ("きれいにして", True, ("finisher", "retouch")),
    ("画風を水彩にして", True, None), ("女の子を描いて", True, None),
    ("6枚で描くようにして", True, ("count", 6)), ("縦向きにして", True, ("size", "縦")),
    ("この絵を綺麗にして", True, ("finisher", "retouch")), ("セル画風にして", True, ("finisher", "style_cel")),
    ("水彩で描いて", False, None), ("横にして", True, ("size", "横")),
]


def _clamp(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 1)


def words() -> dict:
    from chatdraw.engine import Words
    w = Words(Path(""))
    hit = total = extra = 0
    missed = []
    for text, want, never in WORDS:
        got = [t.strip().lower() for t in w.to_prompt(text).split(",")]
        for t in want:
            total += 1
            if t in got:
                hit += 1
            else:
                missed.append(f"{text}: {t}")
        extra += sum(1 for t in never if t in got)
    score = 100.0 * hit / total - 5 * extra
    return dict(score=_clamp(score), hit=hit, total=total, extra=extra, missed=missed)


def places() -> dict:
    from chatdraw.engine import Words, has_background
    w = Words(Path(""))
    ok, missed = 0, []
    for text, want in PLACES:
        p = w.to_prompt(text)
        got = [t.strip().lower() for t in p.split(",")]
        if any(want == g or want in g.split() or g.startswith(want) for g in got) and has_background(p):
            ok += 1
        else:
            missed.append(f"{text}: {want}（{p}）")
    return dict(score=_clamp(100.0 * ok / len(PLACES)), ok=ok, total=len(PLACES), missed=missed)


def chat() -> dict:
    from chatdraw import chatintent
    ok, missed = 0, []
    for text, has_image, want in CHAT:
        it = chatintent.parse(text, has_image=has_image)
        got = None if it is None else (it.kind, it.arg)
        if got == want:
            ok += 1
        else:
            missed.append(f"{text}: {got} ≠ {want}")
    return dict(score=_clamp(100.0 * ok / len(CHAT)), ok=ok, total=len(CHAT), missed=missed)


def _feedback_images(limit: int = 40) -> list[Path]:
    return sorted(FEEDBACK.rglob("*.jpg"))[:limit]


def slack() -> dict:
    """見本の絵（描いた絵）を誤って落とした数と、絵になっていない物（単色・ノイズ・ぼかし）を落とせた数"""
    import random
    from PIL import Image, ImageFilter
    from chatdraw import director
    false_drop = []
    pics = _feedback_images()
    for p in pics:
        im = Image.open(p).convert("RGB")
        if director.slack(im)["bad"]:
            false_drop.append(p.name)
    base = Image.open(SAMPLE).convert("RGB")
    rnd = random.Random(1)
    noise = Image.frombytes("RGB", (256, 256), bytes(rnd.randrange(256) for _ in range(256 * 256 * 3)))
    blanks = [Image.new("RGB", (512, 512), (240, 230, 220)), noise.resize((512, 512), Image.NEAREST),
              base.filter(ImageFilter.GaussianBlur(24))]
    caught = sum(1 for b in blanks if director.slack(b)["bad"])
    n = len(pics) + len(blanks)
    score = 100.0 * ((len(pics) - len(false_drop)) + caught) / n
    return dict(score=_clamp(score), false_drop=len(false_drop), pictures=len(pics), caught=caught, blanks=len(blanks),
                missed=false_drop + [f"絵でない物を通した {len(blanks) - caught} 件"] * (caught < len(blanks)))


def _redpen_case():
    """顔の寄りの絵の髪の所を囲み、模型が色と明るさを少しずらして描いた形の直しを作る"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    before = Image.open(SAMPLE).convert("RGB")
    mask = Image.new("L", before.size, 0)
    ImageDraw.Draw(mask).ellipse((300, 60, 460, 220), fill=255)
    drift = ImageEnhance.Brightness(before.filter(ImageFilter.GaussianBlur(1.2))).enhance(1.12)
    a = np.asarray(drift, np.float32) + np.float32([8, -4, 6])
    drift = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return before, Image.composite(drift, before, mask), mask


def redpen() -> dict:
    """赤ペンの直しの経路（囲みを線の際まで広げる → 境目を合わせる → 囲みの外を元に戻す）を通し、
    囲みの外の変化・境目の色の差・線のずれ・境目の SSIM・目の所の変化を測る"""
    import numpy as np
    from chatdraw import finishers, seamfix
    before, after, asked = _redpen_case()
    mask = seamfix.adjust_mask(before, asked, reach=6)
    out, _ = seamfix.settle(before, after, mask)
    out = finishers.keep_outside(before, out, mask)
    b, o = np.asarray(before, np.int16), np.asarray(out, np.int16)
    m = np.asarray(mask) > 127
    outside = int((np.abs(b - o).sum(-1)[~m] > 0).sum())
    eye = float(np.abs(b[230:330, 120:400] - o[230:330, 120:400]).mean())   # 目の所（囲みの外）
    got = seamfix.measure(before, out, mask)
    score = 0.0 if outside or eye else 100 - 8 * got["color"] - 15 * got["shift"] - 200 * max(0.0, 0.95 - got["ssim"])
    return dict(score=_clamp(score), outside=outside, eye=round(eye, 2), **{k: got[k] for k in ("color", "shift", "ssim")})


FINISH = ("face", "retouch", "clean", "detail")


def finish() -> dict:
    """模型を使わない加工を元の大きさで掛け、効いた量（変わった色の平均）・崩れの増え・形（SSIM）・目の色の差を測る"""
    import numpy as np
    from chatdraw import finishers
    src = Image_open(SCENE)
    a = np.asarray(src, np.float32)
    rows, total = {}, 0.0
    f0 = finishers.flaws(np.asarray(src))
    for name in FINISH:
        try:
            out = finishers.run(name, src).convert("RGB")
        except Exception as e:   # 使えない加工は 0 点（掛けられない物は効いていない）
            rows[name] = dict(score=0.0, error=f"{type(e).__name__}: {e}")
            continue
        b = np.asarray(out, np.float32)
        effect = float(np.abs(a - b).mean())
        df = finishers.flaws(np.asarray(out)) - f0
        sc = finishers.scores(src, out)
        feat = (finishers.LAST_QC.get("features") or {}).get("after") or {}
        eye = float(feat.get("eye", 99.0))   # 目の色の差（facefeat の RGB の距離）。測れなければ 0 点
        s = (40 * min(1.0, effect / 0.5) + 30 * (1.0 if df <= 0 else max(0.0, 1 - df / 20))
             + 20 * max(0.0, min(1.0, ((sc["ssim"] or 0) - 0.9) / 0.09)) + 10 * max(0.0, 1 - eye / 6))
        rows[name] = dict(score=_clamp(s), effect=round(effect, 2), flaws=int(df), ssim=sc["ssim"], eye=round(eye, 2))
        total += rows[name]["score"]
    return dict(score=_clamp(total / len(FINISH)), **rows)


def Image_open(p):
    from PIL import Image
    return Image.open(p).convert("RGB")


# ---- 重い物（Actions） ----

def upscale() -> dict:
    """拡大の模型で 2 倍にし、元の大きさに縮め戻したときの色の差と、主線の重なり"""
    from PIL import Image
    from chatdraw import finishers
    from chatdraw import upscale as up
    import os
    if not up.ready() and os.environ.get("CD_FETCH") == "1":
        up.fetch()
    if not up.ready():
        return dict(score=0.0, error="拡大の重みが無い")
    src = Image_open(SAMPLE).resize((256, 256), Image.LANCZOS)
    big = up.upscale(src, 2)
    back = big.resize(src.size, Image.LANCZOS)
    sc = finishers.scores(src, back)
    s = 50 * max(0.0, 1 - sc["color"] / 10) + 50 * sc["line"]
    return dict(score=_clamp(s), color=sc["color"], line=sc["line"], ssim=sc["ssim"])


def _verdicts() -> list[tuple[Path, bool]]:
    """library/feedback の README の表から、1 枚ずつの判定（通す / 戻す）を読む"""
    import re
    out = []
    for rd in sorted(FEEDBACK.rglob("README.md")):
        for line in rd.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or not re.search(r"\.(jpg|png)$", cells[0]):
                continue
            v = cells[1]
            if v.startswith("通す") or v.startswith("戻す"):
                p = rd.parent / cells[0]
                if p.exists():
                    out.append((p, v.startswith("戻す")))
    return out


def qc(limit: int = 0) -> dict:
    """数字の検品（origqc.check）を、利用者の判定に当てる。見逃し（戻すのに崩れ 0）と誤った落とし（通すのに崩れあり）を数える"""
    from chatdraw import origqc
    cases = _verdicts()
    if limit:
        cases = cases[:limit]
    hit = miss = false = 0
    for p, reject in cases:
        r = origqc.check(Image_open(p))
        flagged = bool(r.get("bad")) or not r.get("readable", True)
        if reject and flagged or not reject and not flagged:
            hit += 1
        elif reject:
            miss += 1
        else:
            false += 1
    n = max(1, len(cases))
    return dict(score=_clamp(100.0 * hit / n), hit=hit, miss=miss, false_drop=false, total=len(cases))


LIGHT = {"描く言葉": words, "場所の言葉": places, "チャットの読み取り": chat, "担当編集者のサボりの検品": slack,
         "赤ペンの直し": redpen, "加工": finish}
HEAVY = {"拡大": upscale, "検品": qc}


def run(names=None, heavy: bool = False) -> dict:
    table = dict(LIGHT, **(HEAVY if heavy else {}))
    return {k: fn() for k, fn in table.items() if names is None or k in names}
