"""頼んでいない、物理的にあり得ない絵の検品と、描く前の打ち消し。

模型は、指だけでなく腕・脚・頭・体を増やし、顔でない所（服の柄、丸い物）に目を描き、頼んでいない黄色い目を描いた。
手・足・顔の検品は枠の中しか見ないので、これらは描き直しに回らずに通っていた。ここでは
1. 描く前: 打ち消し（negative）に、余分な体の部位・顔の外の目・物理的にあり得ない形を足す。目の色を頼んでいなければ、
   模型が既定で寄せる黄色・金の目も打ち消す（頼んだ言葉にある物は打ち消さない）
2. 描いたあと: 人の数（RT-DETR）、部位分け（segformer の顔・腕・脚）の塊の数、顔を隠した絵のタグ（顔の外の目）、
   絵全体のタグ（extra arms、multiple heads、頼んでいない yellow eyes）で崩れを数える
を行う。数えられなかったときは「崩れが無い」ではなく readable を False にして返す。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# 描く前に必ず打ち消す物。余分な部位、顔の外の目、物の顔、物理的にあり得ない形
# SDXL の打ち消しは CLIP の 77 語で切れるので、短く、強く効く物だけにする（長くすると後ろの言葉が模型に届かない）
NEGATIVE = ("extra arms, extra legs, extra heads, extra bodies, conjoined, extra eyes, eyes on body, eyes on objects, "
            "floating limbs, impossible anatomy")
# 目の色を頼んでいないときだけ打ち消す色。模型はこの色に寄せやすかった。切れないよう、打ち消しの先頭に置く
UNASKED_EYE_COLORS = "yellow eyes, golden eyes"
EYE_COLORS = {"blue", "red", "green", "purple", "yellow", "brown", "black", "grey", "gray", "pink", "orange", "aqua", "white",
              "amber", "golden", "gold", "silver", "violet", "teal", "cyan", "crimson", "emerald", "azure", "hazel", "heterochromia",
              "glowing", "light blue", "dark blue"}

# 絵全体のタグで崩れとする物と下限。頼んだ言葉に同じ語があれば数えない（三つ目の妖怪の third eye は頼んだ物）
TAG_FLAWS = {"extra arms": ("腕が多い", 0.35), "multiple heads": ("頭が多い", 0.35), "extra faces": ("顔が多い", 0.35),
             "extra eyes": ("目が多い", 0.4), "third eye": ("額に 3 つ目の目", 0.4), "extra mouth": ("口が多い", 0.4),
             "eyeball": ("目玉だけの物", 0.5), "multiple legs": ("脚が多い", 0.5)}
OLD_TAG_FLAWS = tuple(TAG_FLAWS)   # 矛盾の検品を足す前からあった物（tools/gen/sanity_eval.py が前と後を比べる）
# 矛盾の検品。数・物理・左右・人数の食い違いを、絵全体のタグで読む。頼んだ言葉にある物は数えない。
# 下限は library の判定の付いた絵（tools/gen/sanity_eval.py）で、通した絵を落とさない所に置く
TAG_FLAWS.update({
    "extra ears": ("耳が多い", 0.5), "multiple legs": ("脚が多い", 0.5), "too many": ("数が多すぎる", 0.5),
    "bad anatomy": ("体の形があり得ない", 0.5), "bad hands": ("手の形があり得ない", 0.5), "bad feet": ("足の形があり得ない", 0.5),
    "bad proportions": ("体の釣り合いがあり得ない", 0.5),
    "disembodied limb": ("体から離れた手足", 0.4), "severed limb": ("途切れた手足", 0.4), "missing limb": ("足りない手足", 0.4),
    "amputee": ("途切れた手足", 0.5), "disembodied head": ("体から離れた頭", 0.4), "severed head": ("体から離れた頭", 0.4),
    "floating object": ("宙に浮く持ち物", 0.5), "floating weapon": ("宙に浮く持ち物", 0.5), "floating book": ("宙に浮く持ち物", 0.6),
})
# 左右で食い違う服や飾り。頼んだ言葉に同じ語か asymmetrical / single / mismatched があれば数えない
MISMATCH_TAGS = {t: 0.45 for t in (
    "mismatched legwear", "asymmetrical legwear", "single thighhigh", "single kneehigh", "single sock", "single leg pantyhose",
    "single glove", "single elbow glove", "single fingerless glove", "asymmetrical gloves", "mismatched gloves",
    "single shoe", "single boot", "single thigh boot", "mismatched footwear", "asymmetrical footwear",
    "single earring", "asymmetrical sleeves", "mismatched sleeves", "single sleeve", "single detached sleeve",
    "asymmetrical clothes", "single pauldron", "single gauntlet", "single wrist cuff")}
# 左右で違う目。頼んでいなければ崩れ
ODD_EYE_TAGS = {"heterochromia": 0.45, "mismatched pupils": 0.45, "mismatched sclera": 0.45, "uneven eyes": 0.5,
                "mismatched eyebrows": 0.5}
# 頼んだ人数と違うと読めるタグ（頼んだのが 1 人のとき）
MANY_TAGS = {"multiple girls": 0.5, "multiple boys": 0.5, "multiple others": 0.5, "multiple views": 0.5, "multiple persona": 0.5}
UNASKED_COLOR_TAGS = {"yellow eyes": 0.5, "glowing eyes": 0.5}
# 頼んだ色と違う目の色と読む下限（頼んだ色の確からしさがこれより低く、違う色がこれより高い）
OTHER_EYE = 0.6
# 顔を隠した絵で、目が描かれていると読める下限（顔の外の目）
OUTSIDE_EYES = 0.35

PERSON_MODEL = "PekingU/rtdetr_r50vd_coco_o365"   # Apache-2.0。人の枠を数える
FACE, LEGS, ARMS = 11, (12, 13), (14, 15)          # tools/gen/edit.py の LABELS


def _has(prompt: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", prompt.lower()) is not None


def eye_color_asked(prompt: str) -> bool:
    """頼みに目の色があるか（blue eyes、eyes are blue、heterochromia）"""
    low = prompt.lower()
    if "heterochromia" in low:
        return True
    for c in EYE_COLORS:
        if re.search(rf"\b{re.escape(c)}[- ](eyes?|iris|irises|pupils)\b", low) or re.search(rf"\beyes? (are|is) {re.escape(c)}\b", low):
            return True
    return False


def negative(prompt: str = "") -> str:
    """描く前の打ち消しに足す言葉。頼んだ言葉にある物（multiple arms の神像、third eye）は外す"""
    words = [w.strip() for w in NEGATIVE.split(",")]
    if not eye_color_asked(prompt):
        words = [w.strip() for w in UNASKED_EYE_COLORS.split(",")] + words
    return ", ".join(w for w in words if not _has(prompt, w))


def asked_people(prompt: str) -> int:
    """頼んだ人数。2girls や multiple なら多い数、決まりが無ければ 1"""
    low = prompt.lower()
    nums = [int(n) for n in re.findall(r"\b(\d)(?:girls|boys|others)\b", low)]
    if nums:
        return sum(nums)
    if any(w in low for w in ("multiple girls", "multiple boys", "group", "couple", "crowd", "twins", "multiple views")):
        return 9
    return 1


def from_tags(got: dict, prompt: str) -> list[str]:
    """絵全体のタグで読める崩れ（頼んでいない余分な部位と、頼んでいない黄色い目）"""
    out = []
    for tag, (word, least) in TAG_FLAWS.items():
        if got.get(tag, 0.0) >= least and not _has(prompt, tag):
            out.append(f"{word}（{tag} {got[tag]:.2f}）")
    if not eye_color_asked(prompt):
        for tag, least in UNASKED_COLOR_TAGS.items():
            if got.get(tag, 0.0) >= least and not _has(prompt, tag):
                out.append(f"頼んでいない目の色（{tag} {got[tag]:.2f}）")
    else:
        out += other_eye_color(got, prompt)
    low = prompt.lower()
    free = any(w in low for w in ("asymmetr", "single ", "mismatch", "uneven"))
    for tag, least in MISMATCH_TAGS.items():
        if got.get(tag, 0.0) >= least and not free and not _has(prompt, tag):
            out.append(f"左右で食い違う服や飾り（{tag} {got[tag]:.2f}）")
    for tag, least in ODD_EYE_TAGS.items():
        if got.get(tag, 0.0) >= least and not free and not _has(prompt, tag):
            out.append(f"左右で違う目（{tag} {got[tag]:.2f}）")
    if asked_people(prompt) == 1:
        many = [f"{t} {got[t]:.2f}" for t, least in MANY_TAGS.items() if got.get(t, 0.0) >= least and not _has(prompt, t)]
        if many:
            out.append("人数が違う（頼んだのは 1 人、" + "、".join(many) + "）")
    else:
        n = asked_people(prompt)
        if n < 9 and got.get("solo", 0.0) >= 0.6:
            out.append(f"人数が違う（頼んだのは {n} 人、solo {got['solo']:.2f}）")
    return out


def asked_eye_colors(prompt: str) -> set[str]:
    low = prompt.lower()
    return {c for c in EYE_COLORS if re.search(rf"\b{re.escape(c)}[- ](eyes?|iris|irises|pupils)\b", low)
            or re.search(rf"\beyes? (are|is) {re.escape(c)}\b", low)}


# 近い色は同じと見る（模型とタグの模型で呼び方が揺れる）
NEAR = {"aqua": {"blue", "light blue", "cyan", "teal", "green"}, "blue": {"aqua", "light blue", "dark blue", "azure", "purple"},
        "purple": {"violet", "pink", "blue"}, "red": {"crimson", "pink", "orange"}, "yellow": {"golden", "gold", "amber", "orange"},
        "brown": {"amber", "hazel", "orange", "black"}, "black": {"grey", "gray", "brown"}, "grey": {"silver", "black", "white"},
        "green": {"emerald", "aqua", "teal"}, "pink": {"red", "purple"}, "orange": {"amber", "red", "yellow", "brown"}}


def other_eye_color(got: dict, prompt: str) -> list[str]:
    """頼んだ目の色と違う色の目（blue eyes を頼んで red eyes が強く読める）"""
    asked = asked_eye_colors(prompt)
    if not asked or "heterochromia" in prompt.lower():
        return []
    near = set(asked)
    for c in asked:
        near |= NEAR.get(c, set())
    if any(got.get(f"{c} eyes", 0.0) >= 0.35 for c in asked):
        return []
    return [f"頼んでいない目の色（頼んだのは {'、'.join(sorted(asked))}、{t} {v:.2f}）" for t, v in got.items()
            if t.endswith(" eyes") and t[:-5] in EYE_COLORS and t[:-5] not in near and v >= OTHER_EYE]


def blobs(mask, least: float, join: int):
    """mask の塊の数。join 画素までの隙間（腕輪・靴下の縁）はつなぎ、面積 least 未満の塊は数えない"""
    import numpy as np
    from scipy import ndimage
    if join:
        mask = ndimage.binary_closing(mask, iterations=join)
    lab, n = ndimage.label(mask)
    if not n:
        return 0
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return int((np.asarray(sizes) >= least).sum())


def count_parts(seg, people: int = 1) -> dict:
    """部位分けの塊で、頭（顔）・腕・脚を数え、人の数の 1 / 2 / 2 倍より多い部位を返す"""
    import numpy as np
    h, w = seg.shape
    area = h * w
    join = max(2, int(min(h, w) * 0.012))
    n = {"頭": blobs(seg == FACE, area * 0.002, join),
         "腕": blobs(np.isin(seg, ARMS), area * 0.003, join),
         "脚": blobs(np.isin(seg, LEGS), area * 0.004, join)}
    # 頭（顔の塊）は数えるだけにする。部位分けは裸の胴の肌も顔と塗り（r21 の絵）、顔の塊の数では頭の数を言えなかった
    limit = {"頭": 10 ** 6, "腕": 2 * people, "脚": 2 * people}
    return {"counts": n, "extra": [f"{k}が多い（{n[k]} つ、人 {people} 人）" for k in n if n[k] > limit[k]]}


def stray_hands(im, least: float = 0.8) -> list[list[int]]:
    """どちらの手首（VitPose）からも離れた所にある手（手らしさ least 以上）の枠。腕が 3 本の絵では、3 本目の腕の先の手が
    手首から離れた所に描かれる。手の検品（handcheck.keep_hands）はそうした手を足と見て捨てていたので、崩れに数えなかった"""
    from chatdraw import handcheck
    hands = handcheck._hands()
    if not handcheck.ensure_models(False):
        raise RuntimeError("手の模型がありません")
    kp = handcheck._keypoints(im)
    w, h = im.size
    wrists = [(kp[f"{s}_wrist"], kp.get(f"{s}_elbow")) for s in ("left", "right") if f"{s}_wrist" in kp]
    if len(wrists) < 2:
        raise RuntimeError("手首が 2 つ読めない")
    ankles = [kp[k][1] for k in ("left_ankle", "right_ankle") if k in kp]
    floor = min(ankles) - 0.05 * h if ankles else 0.8 * h
    out = []
    for cx, cy, b in handcheck.find_hands(hands, im, keep=False):
        if cy >= floor:
            continue   # 足の指を手と読んだもの
        near = False
        for (wx, wy), el in wrists:
            reach = 1.5 * (((wx - el[0]) ** 2 + (wy - el[1]) ** 2) ** 0.5 if el else min(w, h) * 0.12)
            near = near or ((cx - wx) ** 2 + (cy - wy) ** 2) ** 0.5 <= max(reach, min(w, h) * 0.1)
        if near:
            continue
        box, ang = b.split(":")
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
        m, _bad, _ = hands.measure(hands.best_crop(im, (x0, y0, x1, y1), float(ang)))
        if m.get("presence", 0) >= least:
            out.append([x0, y0, x1, y1])
    return out


def _seg_dist(xs, ys, a, b):
    import numpy as np
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / max(dx * dx + dy * dy, 1e-6), 0, 1)
    return np.hypot(xs - (ax + t * dx), ys - (ay + t * dy))


def off_skeleton(seg, kp: dict, labels, chains, far: float = 1.0, least: float = 0.5) -> dict:
    """部位分けの腕（脚）の画素のうち、体の点の骨（肩-肘-手首、腰-膝-足首）のどれからも遠い塊。
    腕が 3 本の絵では、体の点は 2 本の腕にしか骨を引けず、3 本目の腕は骨から離れて残る（どちらの 2 本に骨を引いても、残りの 1 本が離れる）。
    far は骨の長さに対する遠さ、least は 1 本分の面積に対する塊の大きさ"""
    import numpy as np
    from scipy import ndimage
    bones = []
    for chain in chains:
        if not all(k in kp for k in chain):
            return {"readable": False}
        bones += [(kp[chain[i]], kp[chain[i + 1]]) for i in range(len(chain) - 1)]
    length = np.mean([np.hypot(a[0] - b[0], a[1] - b[1]) for a, b in bones])
    mask = np.isin(seg, labels)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or length < 4:
        return {"readable": False}
    d = np.min([_seg_dist(xs, ys, a, b) for a, b in bones], axis=0)
    off = np.zeros_like(mask)
    off[ys[d > far * length], xs[d > far * length]] = True
    off = ndimage.binary_opening(off, iterations=2)
    lab, n = ndimage.label(off)
    per = mask.sum() / len(chains)
    big = [int(a) for a in (ndimage.sum(off, lab, range(1, n + 1)) if n else []) if a >= least * per]
    return {"readable": True, "extra": len(big), "areas": big, "bone": round(float(length), 1)}


def bone_ratio(kp: dict, chain, most: float = 2.2) -> float | None:
    """骨の 2 本目と 1 本目の長さの比（前腕 / 上腕、すね / 太もも）。most を超えれば、体の点が 2 本の腕（脚）をまたいで
    骨を引いた印。腕が 3 本の絵（r21）では肩から上げた腕の肘へ、そこから垂れた 3 本目の腕の手首へ引き、比は 2.8 だった"""
    if not all(k in kp for k in chain):
        return None
    (ax, ay), (bx, by), (cx, cy) = (kp[k] for k in chain)
    first = max(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5, 1.0)
    return round(((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5 / first, 2)


BONE_MOST = 2.2


ARM_CHAINS = (("left_shoulder", "left_elbow", "left_wrist"), ("right_shoulder", "right_elbow", "right_wrist"))
LEG_CHAINS = (("left_hip", "left_knee", "left_ankle"), ("right_hip", "right_knee", "right_ankle"))


_DET = None


def count_people(im, least: float = 0.5, big: float = 0.3) -> int:
    """RT-DETR で人の枠を数える"""
    global _DET
    import torch
    from transformers import AutoImageProcessor, RTDetrForObjectDetection
    from chatdraw.paths import HUB
    if _DET is None:
        _DET = (AutoImageProcessor.from_pretrained(PERSON_MODEL, cache_dir=str(HUB), local_files_only=True),
                RTDetrForObjectDetection.from_pretrained(PERSON_MODEL, cache_dir=str(HUB), local_files_only=True).eval())
    proc, model = _DET
    small = im.copy()
    small.thumbnail((640, 640))   # 模型の入りの大きさ。大きいまま渡しても前処理で縮む
    with torch.no_grad():
        out = model(**proc(small, return_tensors="pt"))
    res = proc.post_process_object_detection(out, target_sizes=[small.size[::-1]], threshold=least)[0]
    boxes = [b for b, lab in zip(res["boxes"].tolist(), res["labels"]) if model.config.id2label[int(lab)] == "person"]
    if not boxes:
        return 0
    # 背景の通行人（遠くの小さな人影）は余分な体ではない。一番大きい人の枠の big 倍より小さい枠は数えない。
    # 雨の街の絵（r5-coat）で、背景の人影 3 つを数えて「人 4 人」とした
    return count_boxes(boxes, big)


def count_boxes(boxes, big: float = 0.3, inside: float = 0.8) -> int:
    """人の枠の数。背景の小さな人影（一番大きい枠の big 倍より小さい）と、大きい枠の中に inside 以上入る枠
    （同じ人の上半身だけを別の枠にした物）は数えない。library/feedback の 502 枚（Actions の people-count）で、
    入れ子の枠を除くと 1 人の絵で 2 人以上と数えた絵が 4 枚から 3 枚になった（スーツの男性の上半身と全身の枠）。
    残る 3 枚は動物 2 匹の絵と、三面図の設定資料（何人も描くのが正しい）。inside の 0.8 は私の推測の値"""
    area = lambda b: max(0.0, (b[2] - b[0]) * (b[3] - b[1]))
    keep = []
    for b in sorted(boxes, key=area, reverse=True):
        if all(max(0.0, min(b[2], k[2]) - max(b[0], k[0])) * max(0.0, min(b[3], k[3]) - max(b[1], k[1]))
               < inside * max(area(b), 1e-6) for k in keep):
            keep.append(b)
    if not keep:
        return 0
    most = max(area(b) for b in keep)
    return sum(area(b) >= big * most for b in keep)


def face_hidden(im, seg):
    """顔（部位分けの顔の塊を 1 割広げた枠）を灰で塗った絵。顔の外に目が描かれていれば、塗った絵でも目のタグが付く"""
    import numpy as np
    from PIL import ImageDraw
    from scipy import ndimage
    out = im.copy()
    d = ImageDraw.Draw(out)
    lab, n = ndimage.label(seg == FACE)
    for sl in ndimage.find_objects(lab):
        if sl is None:
            continue
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        if (y1 - y0) * (x1 - x0) < 64:
            continue
        py, px = int((y1 - y0) * 0.25), int((x1 - x0) * 0.25)
        d.rectangle([x0 - px, y0 - py, x1 + px, y1 + py], fill=(128, 128, 128))
    return out, int(n)


def eyes_outside(got: dict, prompt: str = "") -> list[str]:
    """顔を隠した絵のタグで、目が読めるもの（色の目、extra eyes、eyeball）"""
    out = []
    for t, v in got.items():
        if v < OUTSIDE_EYES or _has(prompt, t):
            continue
        if t in ("extra eyes", "eyeball", "third eye") or (t.endswith(" eyes") and t[:-5] in EYE_COLORS and t != "closed eyes"):
            out.append(f"{t} {v:.2f}")
    return out


def check(image, prompt: str = "", tags: dict | None = None) -> dict:
    """描いた絵（道か PIL）を検品する。bad は崩れの説明、avoid は次に描くときの打ち消しに足す言葉。
    部品が無ければ readable を False にして返す（見ていない絵を、通ったことにしない）"""
    from PIL import Image
    if os.environ.get("CD_CHECK") == "off":
        return {"readable": False, "bad": [], "avoid": [], "reason": "検品を止めています（CD_CHECK=off）"}
    import tempfile
    im = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    res: dict = {"readable": True, "bad": [], "avoid": [], "why": []}
    tmp = Path(tempfile.mkdtemp())
    src = str(image) if isinstance(image, (str, Path)) else str(tmp / "sanity.png")
    if not isinstance(image, (str, Path)):
        im.save(src)
    from chatdraw.paths import use_tools_gen
    use_tools_gen()
    try:
        import edit   # noqa: F401  部位分けの置き場（HF_HOME）を、transformers を読む前に決める
    except Exception:
        pass
    try:
        import tagger as tg
        if not (tg.DIR / "model.onnx").exists():
            from chatdraw.requestcheck import _tagger
            tg = _tagger(False)
        got = tags if tags is not None else tg.read(src)
        res["bad"] += from_tags(got, prompt)
    except Exception as e:
        tg, got = None, {}
        res["why"].append(f"タグ: {type(e).__name__}: {e}")
    people = asked_people(prompt)
    seg = None
    try:
        import numpy as np
        import edit
        seg = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
        parts = count_parts(seg, people)
        res["counts"] = parts["counts"]
        # 塊の数も記録だけにする。膝に置いた手で腕が 2 つに切れ、外れ 1・当たり 0 だった（library の 44 枚）
        res["info"] = list(parts["extra"])
        if tg is not None:
            hidden, faces = face_hidden(im, seg)
            if faces:
                p = tmp / "hidden.png"
                hidden.save(p)
                outside = eyes_outside(tg.read(str(p)), prompt)
                if outside:
                    res["bad"].append("顔の外に目（" + "、".join(outside) + "）")
            else:
                res["why"].append("顔が見つからず、顔の外の目を見ていない")
    except Exception as e:
        res["why"].append(f"部位分け: {type(e).__name__}: {e}")
    try:
        res["people"] = count_people(im)
        if res["people"] > people:
            res["bad"].append(f"体が多い（人 {res['people']} 人、頼んだのは {people} 人）")
    except Exception as e:
        res["why"].append(f"人の数: {type(e).__name__}: {e}")
    if people == 1 and seg is not None:
        try:
            from chatdraw import handcheck
            kp = handcheck._keypoints(im)
            if not kp:
                raise RuntimeError("体の点を読めない " + handcheck.KP_ERROR)
            for word, labels, chains in (("腕", ARMS, ARM_CHAINS), ("脚", LEGS, LEG_CHAINS)):
                o = off_skeleton(seg, kp, labels, chains)
                res.setdefault("off_skeleton", {})[word] = o
                # 骨から離れた塊は記録だけにする。library の 44 枚で、曲げた脚・膝に置いた手を 1 本と読み、外れ 1・当たり 0 だった
                if o.get("extra"):
                    res.setdefault("info", []).append(f"{word}: 骨から離れた塊 {o['extra']} つ")
                for chain in chains:
                    r = bone_ratio(kp, chain)
                    res.setdefault("bone_ratio", {})[chain[0]] = r
                    if r is not None and r > BONE_MOST:
                        res["bad"].append(f"{word}が多いか、つながりがあり得ない（{chain[0].split('_')[0]} の骨の比 {r}）")
        except Exception as e:
            res["why"].append(f"骨から離れた腕・脚: {type(e).__name__}: {e}")
    if people == 1:
        try:
            stray = stray_hands(im)
            res["stray_hands"] = stray
            # 記録だけにする。library の 44 枚で、物を持つ手・腰に当てた手を手首から離れたと読み、外れ 2・当たり 0 だった
            if stray:
                res.setdefault("info", []).append(f"手首から離れた手 {len(stray)} つ")
        except Exception as e:
            res["why"].append(f"手首から離れた手: {type(e).__name__}: {e}")
    res["readable"] = not res["why"]
    if not res["readable"]:
        res["reason"] = "；".join(res["why"])
    if any("目" in b for b in res["bad"]):
        res["avoid"] += ["extra eyes", "eyes on body", "eyes on objects"]
    if any(b.startswith(("腕", "脚", "頭", "体", "顔")) for b in res["bad"]):
        res["avoid"] += ["extra arms", "extra legs", "extra heads", "extra bodies"]
    if any("目の色" in b for b in res["bad"]):
        res["avoid"] += ["yellow eyes", "golden eyes"] if not eye_color_asked(prompt) else []
    res["avoid"] += avoid_words(res["bad"])
    return res


def avoid_words(bad: list[str]) -> list[str]:
    """矛盾の崩れから、次に描くときの打ち消しに足す言葉"""
    out = []
    for b in bad:
        if b.startswith("左右で食い違う"):
            out += ["asymmetrical clothes", "mismatched legwear", "single glove"]
        elif b.startswith("左右で違う目"):
            out += ["heterochromia", "mismatched pupils"]
        elif b.startswith(("体から離れた", "途切れた", "足りない手足")):
            out += ["disembodied limb", "severed limb", "missing limb"]
        elif b.startswith("宙に浮く"):
            out += ["floating object"]
        elif b.startswith("人数が違う（頼んだのは 1"):
            out += ["multiple girls", "multiple views"]
        elif b.startswith(("体の形", "手の形", "足の形", "体の釣り合い")):
            out += ["bad anatomy", "bad hands", "bad proportions"]
    return list(dict.fromkeys(out))


def summary(res: dict) -> str:
    if not res.get("readable") and not res.get("bad"):
        return f"検品（体の数と目）: 読めませんでした（{res.get('reason', '')}）"
    if res["bad"]:
        return "検品（体の数と目）: 崩れ " + str(len(res["bad"])) + " 件。" + "、".join(res["bad"])
    return "検品（体の数と目）: 余分な腕・脚・頭・体と、顔の外の目は見つかりませんでした"
