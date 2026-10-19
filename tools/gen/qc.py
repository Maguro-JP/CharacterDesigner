"""検品の下ごしらえ: 検品担当（.claude/agents/checker.md）が目で見る前に、機械で拡大図と事実をそろえる。

検品担当が自分で切り出すと、座標がずれて顔や手が写らない回があり、画像の枚数を絞った回は指や足元が
「見ていない」のまま残った。宙に浮いた布や、設定で描かせないものも、毎回目だけで探していた。
ここでは、決まった形の検品図を1枚作り、数えられる事実を先に出す。判断（通す・戻す）はしない。

  python3 tools/gen/qc.py sheet   絵.png OUT.png               全体と顔の拡大（OUT）、人物を分けた2倍前後の拡大（OUT-detail）の検品図
  python3 tools/gen/qc.py facts   絵.png [--character knight]   端で切れていないか・部位の棚卸し・浮いた塊・肌の割合・描かせないもの・設定の言葉の欠け
  python3 tools/gen/qc.py compare 絵1.png 絵2.png ...           組（三面図・表情差分）で、部位ごとの色がずれていないか
  python3 tools/gen/qc.py scars   前.png 後.png 範囲.png         部分を描き直した範囲の縁で、前より輪郭が鈍った所（にじみの跡）
  python3 tools/gen/qc.py legs    絵.png                        人の脚が残っているか（下半身が人でない種族で、腰より下に膝と足首がある）
  python3 tools/gen/qc.py expr    基準.png OUT.jpg 表情1.png ...  表情差分の見比べ図（顔・眉と目・口を「ふだん」と並べる）

検品図は JPEG で書く（PNG だと1枚 数 MB になり、ディスクの空きが少ないとき検品担当が図を作れなかった）。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
# 部位分けの番号（tools/gen/edit.py の parts。ATR の並び）
HAIR, UPPER, SKIRT, PANTS, DRESS, LSHOE, RSHOE, FACE, LLEG, RLEG, LARM, RARM, SCARF = 2, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 17
SKIN = (FACE, LLEG, RLEG, LARM, RARM)
PART_JA = {HAIR: "髪", UPPER: "上着", SKIRT: "スカート", PANTS: "ズボン", DRESS: "ワンピース", FACE: "顔", SCARF: "襟巻き"}


# ---- 模型を使わない計算（試験はここを見る） ----

def figure_mask(rgb: np.ndarray, paper: int = 30) -> np.ndarray:
    """白地の絵で、地と違う画素（人物と物）。四隅の色を地とみなし、そこから paper 以上離れた画素"""
    corners = np.concatenate([rgb[:8, :8], rgb[:8, -8:], rgb[-8:, :8], rgb[-8:, -8:]]).reshape(-1, 3).astype(float)
    bg = np.median(corners, 0)
    return np.abs(rgb.astype(float) - bg).max(-1) > paper


def background_seams(rgb: np.ndarray, gap: int = 4, band: int = 12, flat: float = 4.0, least: float = 0.2,
                     agree: float = 0.7, step: float = 5.0, cap: float = 25.0, sharp: float = 3.0,
                     near: float = 20.0) -> list[dict]:
    """背景の色が、まっすぐな横線・縦線を境に急に変わる所。部分の描き直しの範囲の縁に出る継ぎ目。

    アラクネの下半身を描き直した絵で、範囲の上の縁（430 行目）を境に背景の青が 7 上がり、細かな粒が消えた。
    明るさだけを見ると差は 1 未満で拾えなかったので、3 色それぞれの差を見る。
    線の上下（左右）の帯（band 行、境から gap 行あける）が、どちらも平ら（ばらつき flat 未満）で
    四隅の色（背景）から near 以内の列だけを数える。翼の中の平らな羽の帯や人物の輪郭を拾わないため。
    差が step を超えて cap 未満、帯の中の変化の sharp 倍より大きい（なだらかな光のむらでない）、
    agree 以上の列で同じ向きに変わる、をすべて満たす行を継ぎ目とし、近い行は 1 本にまとめる。
    手元の 8 枚で、継ぎ目のある 1 枚だけを拾い、残り 7 枚は拾わなかった"""
    X = rgb.astype(float)
    corners = np.concatenate([X[:8, :8], X[:8, -8:], X[-8:, :8], X[-8:, -8:]]).reshape(-1, 3)
    bgc = np.median(corners, 0)
    out = []
    for name, M in (("row", X), ("col", X.transpose(1, 0, 2))):
        H, W, _ = M.shape
        hits = []
        for i in range(gap + band, H - gap - band):
            a, b = M[i - gap - band:i - gap], M[i + gap:i + gap + band]
            ok = ((a.std(0).max(-1) < flat) & (b.std(0).max(-1) < flat)
                  & (np.abs(a.mean(0) - bgc).max(-1) < near) & (np.abs(b.mean(0) - bgc).max(-1) < near))
            if ok.sum() < least * W:
                continue
            d = (b.mean(0) - a.mean(0))[ok]
            med = np.median(d, 0)
            c = int(np.abs(med).argmax())
            h = band // 2
            inner = (abs(np.median((a[h:].mean(0) - a[:h].mean(0))[ok][:, c]))
                     + abs(np.median((b[h:].mean(0) - b[:h].mean(0))[ok][:, c])))
            if (step < abs(med[c]) < cap and abs(med[c]) > sharp * inner
                    and (np.sign(d[:, c]) == np.sign(med[c])).mean() > agree):
                hits.append((i, float(abs(med[c])), float(ok.mean())))
        groups = []
        for r in hits:
            if groups and r[0] - groups[-1][-1][0] <= gap + band:
                groups[-1].append(r)
            else:
                groups.append([r])
        for g in groups:
            top = max(g, key=lambda r: r[1])
            out.append({"at": name, "pos": top[0], "step": round(top[1], 1), "width": round(top[2], 2)})
    return out

def repaint_scars(before: Image.Image, after: Image.Image, mask: Image.Image, width: int = 10, cell: int = 32,
                  drop: float = 0.5, contrast: float = 20.0) -> list[dict]:
    """部分を描き直した範囲（mask の白）の縁の帯で、描き直す前より輪郭が鈍った所（にじみ・ぼやけの跡）。

    絵全体から鈍い所を探すと、革の柔らかい光やしっぽのなだらかな塗りなど、わざと柔らかく描いた所も拾い、
    本物のにじみと分けられなかった（8 か所のうち本物 3）。描き直した範囲は分かっているので、その縁だけを前後で比べる。
    セルごとに「一番鋭い 1 画素の変化 ÷ 明暗の差」を測り、描き直した後が前（0.6 未満なら 0.6）の drop 倍を下回れば拾う。
    絵の外は範囲の内とみなす（範囲が絵の端に接すると、端の帯を縁と取り違えた）"""
    from scipy import ndimage
    m = np.asarray(mask.convert("L")) > 127
    ring = (ndimage.binary_dilation(m, iterations=width)
            & ~ndimage.binary_erosion(m, iterations=width, border_value=1))

    def gradient(im):
        lum = np.asarray(im.convert("RGB")).astype(float) @ np.array([0.299, 0.587, 0.114])
        return lum, np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8.0

    lb, gb = gradient(before)
    la, ga = gradient(after)
    h, w = m.shape
    out = []
    for y in range(0, h - cell + 1, cell // 2):
        for x in range(0, w - cell + 1, cell // 2):
            r = ring[y:y + cell, x:x + cell]
            if r.mean() < 0.2:
                continue
            ca = la[y:y + cell, x:x + cell][r]
            spread = np.percentile(ca, 95) - np.percentile(ca, 5)
            if spread < contrast:
                continue
            sa = ga[y:y + cell, x:x + cell][r].max() / spread
            cb = lb[y:y + cell, x:x + cell][r]
            sb = gb[y:y + cell, x:x + cell][r].max() / max(np.percentile(cb, 95) - np.percentile(cb, 5), contrast)
            # 前から柔らかかった所（前後とも同じ鋭さ）は跡ではない。前より 2 割以上鈍った所だけを拾う
            if sa < drop * max(sb, 0.6) and sa < 0.8 * sb:
                out.append({"x": x, "y": y, "size": cell, "sharp": round(float(sa), 2), "before": round(float(sb), 2)})
    return out

def hand_boxes(points: list[dict], least: float = 0.5, ahead: float = 0.35, size: float = 0.6, floor: float = 0.8) -> list[dict]:
    """骨格の点から、手ごとに切り出す枠と回す角度を決める。手首の確からしさが least 未満の手は読まない。
    手は肘→手首の向きの先にあるので、手首から前腕の長さの ahead 倍先を中心に、前腕の size 倍四方を切る。
    角度は指先（肘→手首の向き）が上になるまで反時計回りに回す度数（PIL の rotate と同じ向き）。
    hands.measure は指先が上の手で読む（下向きのまま読ませると点が手の外に散った）。
    手を腹の前で組むと前腕が奥へ縮んで写り、前腕だけで決めた枠は 26〜37 画素と手より小さくなった（3 枚中 2 枚）。
    肩の点があれば、前腕の長さを上腕の長さの floor 倍より短くしない"""
    p = {q["name"]: q for q in points}
    out = []
    for side in ("left", "right"):
        w, e = p.get(f"{side}_wrist"), p.get(f"{side}_elbow")
        if not w or not e or w["score"] < least:
            continue
        dx, dy = w["x"] - e["x"], w["y"] - e["y"]
        arm = math.hypot(dx, dy)
        if arm < 1:
            continue
        sh = p.get(f"{side}_shoulder")
        if sh:
            arm = max(arm, floor * math.hypot(e["x"] - sh["x"], e["y"] - sh["y"]))
        cx, cy = w["x"] + dx / math.hypot(dx, dy) * arm * ahead, w["y"] + dy / math.hypot(dx, dy) * arm * ahead
        half = arm * size / 2
        angle = (90 - math.degrees(math.atan2(-dy, dx))) % 360
        out.append({"side": side, "box": tuple(int(round(v)) for v in (cx - half, cy - half, cx + half, cy + half)),
                    "angle": round(angle, 1), "score": round(float(w["score"]), 2)})
    return out


def hands_auto(points: list[dict], im: Image.Image, presence_min: float = 0.5) -> dict:
    """手を切り出して hands.measure で測る。外れ（bad）が 1 つでもあれば崩れ。読める手が無ければ読めない。
    手らしさ（presence）が presence_min 未満の手は、枠に手が入っていない（体の陰に隠れた手、枠のずれ）ことが多く、
    実際の 3 枚では 4 手がそうだった。崩れには数えず、その手は読めないとする"""
    import hands
    boxes = hand_boxes(points)
    res = {"readable": False, "bad": False, "hands": []}
    for b in boxes:
        crop = im.crop(b["box"]).rotate(b["angle"], expand=True, fillcolor=im.getpixel((0, 0)))
        m, bad, _ = hands.measure(crop)
        seen = m.get("presence", 1.0) >= presence_min
        res["hands"].append({**b, "seen": seen, "measure": m, "outside": bad})
        res["readable"] = res["readable"] or seen
        res["bad"] = res["bad"] or (seen and bool(bad))
    return res


def human_legs(points: list[dict], height: int, least: float = 0.45, torso_max: float = 0.35, seen: float = 0.25,
               margin: float = 0.1) -> dict:
    """人の脚が残っているか（下半身が獣や蜘蛛の種族で、腰より下に人の膝と足首が描かれた崩れ）。
    骨格の点（tools/gen/joints.py の find）から、腰→足首の長さを胴（肩→腰）の長さで割り、膝と足首の確からしさの小さい方を掛ける。
    左右の大きい方が least 以上なら「ある」。部位分けの模型は蜘蛛の体をズボンや靴と読み、人の脚が無い絵で 49% をズボンとした。
    胴が絵の高さの torso_max を超えるときは、骨格の模型が人以外（蜘蛛の体、絵全体）を人と読んでいるので「読めない」と返す。
    アラクネ 12 枚（検品担当の判定が正解）で、読めた 9 枚のうち 8 枚が合い、ひざまずいた 1 枚（0.42）を見落とした。3 枚は読めない"""
    p = {q["name"]: q for q in points}
    hip = (p["left_hip"]["y"] + p["right_hip"]["y"]) / 2
    shoulder = (p["left_shoulder"]["y"] + p["right_shoulder"]["y"]) / 2
    torso = hip - shoulder
    if torso <= 0 or torso > torso_max * height:
        return {"readable": False, "legs": None, "score": None, "torso": round(torso / height, 2)}
    # 膝と足首が見つからない（確からしさ seen 未満）のは「脚が無い」ではない。蜘蛛の胴の上に立つ人の脚、獣にまたがる脚で
    # 確からしさが 0.10〜0.22 になり、「無い」と取り違えて通した（2 枚）。人の脚の無い絵では蜘蛛の脚を膝と読み 0.30〜0.49 になる
    conf = max(min(p[s + "_knee"]["score"], p[s + "_ankle"]["score"]) for s in ("left", "right"))
    if conf < seen:
        return {"readable": False, "legs": None, "score": None, "torso": round(torso / height, 2), "conf": round(float(conf), 2)}
    score = max(min(p[s + "_knee"]["score"], p[s + "_ankle"]["score"]) * (p[s + "_ankle"]["y"] - hip) / torso
                for s in ("left", "right"))
    # 線のすぐ上（least〜least+margin）は言い切らない。全身タイツの股のしわが 0.49、本当に脚のある絵が 0.54 で、
    # 差が 0.05 しかなかった。読めないとして落とし、検品担当の目に回す（脚の残った絵が通ることは無い）
    if least <= score < least + margin:
        return {"readable": False, "legs": None, "score": round(float(score), 2), "torso": round(torso / height, 2),
                "reason": "線の近くで言い切れない"}
    return {"readable": True, "legs": score >= least, "score": round(float(score), 2), "torso": round(torso / height, 2)}

def repaint_holes(before: Image.Image, after: Image.Image, mask: Image.Image, near: float = 30.0,
                  least: int = 100) -> list[dict]:
    """描き直した範囲の中で、前は体だった所が背景の色になった塊（体に開いた穴、背景色にぼけた光）。
    アラクネの腹の描き直しで、脚と腹の間に背景色の穴（201 画素）と、白くぼけた光の塊（1431 画素）が出た。
    どちらも輪郭の鋭さ（repaint_scars）では拾えず、検品担当が目で見つけた。背景の色は描き直す前の絵の四隅で決める。
    目を描き直すと、足された白目と瞳の光（53〜76 画素）を穴と取り違えた。本物の穴は 201 画素以上だったので下限を 100 にする"""
    from scipy import ndimage
    b = np.asarray(before.convert("RGB")).astype(float)
    a = np.asarray(after.convert("RGB")).astype(float)
    m = np.asarray(mask.convert("L")) > 127
    corners = np.concatenate([b[:8, :8], b[:8, -8:], b[-8:, :8], b[-8:, -8:]]).reshape(-1, 3)
    bg = np.median(corners, 0)
    hole = m & (np.abs(b - bg).max(-1) > near) & (np.abs(a - bg).max(-1) <= near)
    lab, n = ndimage.label(hole)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        size = int((lab[sl] == i).sum())
        if size >= least:
            out.append({"box": [sl[1].start, sl[0].start, sl[1].stop, sl[0].stop], "pixels": size})
    return out

def floating_blobs(rgb: np.ndarray, least: float = 0.0015) -> dict:
    """人物の塊から離れた塊（宙に浮いた布・煙・物）。地が平らでない絵（背景つき）は数えない。
    小さすぎる点（絵全体の least 未満）は、髪の跳ねや影の粒なので数えない"""
    from scipy import ndimage
    corners = np.concatenate([rgb[:8, :8], rgb[:8, -8:], rgb[-8:, :8], rgb[-8:, -8:]]).reshape(-1, 3).astype(float)
    if corners.std(0).max() > 12:
        return {"plain_background": False, "blobs": []}
    m = ndimage.binary_closing(figure_mask(rgb), iterations=2)
    lab, n = ndimage.label(m)
    if n == 0:
        return {"plain_background": True, "blobs": []}
    sizes = np.bincount(lab.ravel())[1:]
    main = int(sizes.argmax()) + 1
    total = rgb.shape[0] * rgb.shape[1]
    out = []
    for i, s in enumerate(sizes, 1):
        if i == main or s < least * total:
            continue
        ys, xs = np.nonzero(lab == i)
        out.append({"box": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "area": round(s / total, 4)})
    return {"plain_background": True, "blobs": sorted(out, key=lambda b: -b["area"])}


def part_colors(rgb: np.ndarray, parts: np.ndarray, least: int = 400) -> dict:
    """部位ごとの色の真ん中（画素が least 未満の部位は数えない）"""
    out = {}
    for k in PART_JA:
        m = parts == k
        if m.sum() >= least:
            out[k] = np.median(rgb[m].reshape(-1, 3).astype(float), 0)
    return out


def color_gaps(colors: list[dict], limit: float = 40.0) -> list[dict]:
    """組の中で、同じ部位の色がどれだけ離れたか（RGB の距離の最大）。limit を超えたものだけ返す。
    部位分けが取れなかった絵はその部位を比べない"""
    out = []
    for k, ja in PART_JA.items():
        got = [(i, c[k]) for i, c in enumerate(colors) if k in c]
        if len(got) < 2:
            continue
        worst = max(((float(np.linalg.norm(a - b)), i, j) for x, (i, a) in enumerate(got) for (j, b) in got[x + 1:]), default=None)
        if worst and worst[0] > limit:
            out.append({"part": ja, "distance": round(worst[0], 1), "between": [worst[1], worst[2]]})
    return out


# 顔の外接枠の中での帯（上からの割合）。アニメ絵の顔の部位分けは前髪の下から顎までで、眉と目・口はおおむねこの位置
BANDS = {"眉と目": (0.10, 0.58), "口": (0.60, 0.92)}


# 露出の度合いの上限（年齢区分 questionable + explicit）。子どもを表す言葉と並んだときだけ使う
RISKY = 0.5
# 頼んだ言葉に無ければ「設定に無い物」とする服飾のタグ。最後の語（hat、glasses）が頼んだ言葉にあれば数えない
UNASKED_WEAR = ("hat", "cowboy hat", "witch hat", "baseball cap", "beret", "top hat", "glasses", "sunglasses", "scarf",
                "headphones", "mask", "eyepatch", "cape", "gloves", "necktie", "bow",
                # 頼んでいない上着・刀・腕の布（白ビキニの描画確認で数枚に出た）
                "jacket", "open jacket", "coat", "hoodie", "cardigan", "katana", "sword", "arm warmers", "detached sleeves",
                "bandages", "armband")
# 服の柄・文字。plain の T シャツの胸に読めない文字が描かれた（基準の組、MeinaMix）。頼んだ言葉に柄・文字の言葉が無ければ崩れ
PRINTS = ("clothes writing", "print shirt", "english text", "logo")
PRINT_WORDS = ("print", "logo", "text", "writing", "letter", "graphic")


GROUP_WORDS = ("2girls", "2boys", "3girls", "multiple", "group", "couple", "crowd", "friends", "together with")


def not_solo(all_tags: dict, prompt: str, least: float = 0.5) -> dict | None:
    """1 人を頼んだのに 1 人に見えない（2 人の体が混ざる・余分な人物）。タグの solo の確からしさで見る。
    しゃがみの 1 枚で上下に 2 人の体が混ざった絵は solo 0.20、ほかの 1 人の絵は 0.98〜0.99 だった"""
    low = prompt.lower()
    if any(w in low for w in GROUP_WORDS):
        return None
    person = max(all_tags.get(t, 0) for t in ("1girl", "1boy", "1other"))
    solo = all_tags.get("solo", 0)
    if person >= least and solo < least:
        return {"solo": round(float(solo), 2), "multiple": round(float(max(all_tags.get("multiple girls", 0), all_tags.get("multiple boys", 0))), 2)}
    return None


def unasked_wear(tags: dict, prompt: str, least: float = 0.5) -> list[str]:
    """頼んだ言葉に無い服飾・持ち物（帽子、上着、刀、腕の布）と、柄・文字を頼んでいない服の柄・文字。
    基準の組の 46 枚で 10 枚に当たり、目で見た 3 枚（刀に見える白い布、黒い腕の布、胸の文字）はどれも描かれていた"""
    low = prompt.lower()
    out = [t for t in UNASKED_WEAR if tags.get(t, 0) >= least and t.split()[-1] not in low]
    if not any(w in low for w in PRINT_WORDS):
        out += [t for t in PRINTS if tags.get(t, 0) >= least]
    return sorted(out)


# 「holding X」のうち物でないもの（体・人・動き）。持ち物の数え方から外す
NOT_ITEMS = ("hands", "hair", "head", "arm", "breath", "behind back", "another's", "own", "heart", "leg", "foot", "wrist", "knees",
             "clothes", "skirt", "hat", "helmet", "footwear", "jacket")
# 同じ物を2つ以上描いたと読めるタグ。剣 2 本（knight 701）は dual wielding、カップ 2 個は multiple を含む言い方で出る
MANY = ("dual wielding", "multiple swords", "multiple weapons", "multiple cups", "multiple bottles", "multiple books")


# 体の部位の数の崩れと読めるタグ。頼んだ言葉に同じ言い方が無いときだけ崩れとする（九尾の狐なら multiple tails は頼んだもの）
EXTRA_PARTS = ("multiple tails", "extra ears", "multiple wings", "extra arms", "multiple horns", "multiple heads", "missing limb")
# 頼んだ部位と、それを描いた絵に出るべきタグ。翼を頼んで winged arms（腕が翼）と読めるのは、腕と別に翼を描いていない絵
PART_SWAPS = {"wings": ("winged arms",)}


def body_parts(tags: dict, prompt: str, least: float = 0.5) -> dict:
    """種族の特徴の数を数える検品（今は目で数えていた）。尾 1 本の狐の絵で multiple tails を 0.455 と読んだので、閾値は 0.5。数の崩れ（尾・耳・翼・腕・角・頭の多すぎ、手足の欠け）と、
    部位の取り違え（翼を頼んで腕が翼）を、絵から読んだタグで挙げる"""
    low = prompt.lower()
    extra = [t for t in EXTRA_PARTS if tags.get(t, 0) >= least and t not in low]
    swapped = [f"{want}→{got}" for want, alts in PART_SWAPS.items() if want in low
               for got in alts if got not in low and tags.get(got, 0) >= least]
    return {"extra": extra, "swapped": swapped}


# 頼んだ物と、模型が小さく描き替えやすい物
SMALLER = {"sword": ("dagger", "knife"), "greatsword": ("sword", "dagger"), "spear": ("dagger",), "staff": ("wand",)}


def held_items(tags: dict, prompt: str, least: float = 0.5) -> dict:
    """持ち物の検品: 頼んでいない持ち物（holding X の X が頼んだ言葉に無い）と、同じ物の数（2つ以上と読めるタグを、頼んでいないのに読んだ）。
    頼んでいない器（cup 0.56 で読めているのに印が付かない）とカップ・剣の重なりを、描画確認 回6 で拾えなかったため足した"""
    low = prompt.lower()
    unasked = []
    for t, v in tags.items():
        if v < least or not t.startswith("holding "):
            continue
        thing = t[len("holding "):].split(" (")[0]
        # weapon・food のような総称は、剣や菓子を頼んだ絵でも並んで読まれる（holding weapon 0.9 と holding sword 0.91）
        if any(w in thing for w in NOT_ITEMS) or thing in ("weapon", "food", "drink", "instrument", "object"):
            continue
        if thing.split()[-1] not in low:
            unasked.append(thing)
    # 大きさの取り違え: 剣を頼んだのに短剣・小刀と読める（回6 で 3/8 が短剣になった）。読みが頼んだ物より強いときだけ挙げる
    small = [f"{want}→{got}" for want, alts in SMALLER.items() if want in low
             for got in alts if got not in low and tags.get(got, 0) >= least and tags.get(got, 0) > tags.get(want, 0)]
    many = [t for t in MANY if tags.get(t, 0) >= least * 0.8 and t not in low and "two " not in low and "multiple" not in low]
    return {"unasked": sorted(unasked), "many": many, "small": small}


def heads_tall(seg: np.ndarray, rgb: np.ndarray, far: float = 40.0, points: list[dict] | None = None) -> float | None:
    """頭身: 人物の高さ ÷ 頭の高さ（頭のてっぺんからあごまで）。
    顔の部位（11）は首の肌まで含むので、下端をあごにすると頭を 2 割ほど大きく取った（頭身 6.2 の絵を 4.7 と測った）。
    幅が細くなる所（首に変わる所）をあごにする。
    髪の膨らみの分だけ頭を大きく取るので、作画の頭身より少し小さく出る。顔が読めなければ None"""
    # 人物の上端と下端は、人物の形（背景から分けた最も大きなつながった塊）で取る。色の違いだけで取ると、背景に描かれた
    # 文字の列（上から 11 画素目）を頭のてっぺんと取り、頭身 6 の絵を 4.1 と測った。部位分けの範囲で取ると、
    # 髪を読み落とした絵で頭のてっぺんが顔の上端になり 12.4 と測った（頭身の実験、2026-10-17）
    try:
        person = _largest(figure_mask(rgb))
    except Exception:
        person = np.abs(rgb.astype(int) - rgb[2, 2].astype(int)).sum(2) > far
    rows = np.nonzero(person.sum(1) > 3)[0]
    width = (seg == 11).sum(1)
    if len(rows) == 0 or width.max() < 10:
        return None
    # 上から下へ見て、顔が細くなり始めた後の一番細い行（その後また広がる＝首から胸へ移る手前）をあごにする。
    # 全体の最大で決めると、胸元の開いた服では胸の肌が顔より広く、あごを胸まで下げた。
    # 決まった割合（0.6 倍）で切ると、首の太い絵で切れずに頭身 6.4 を 4.9 と測った
    ys = np.nonzero(width)[0]
    chin, most, low, low_y = int(ys[-1]), 0, None, None
    for y in range(int(ys[0]), int(ys[-1]) + 1):
        w = int(width[y])
        most = max(most, w)
        if low is None:
            if most >= 10 and w < most * 0.85:
                low, low_y = w, y
            continue
        if w < low:
            low, low_y = w, y
        elif w > low * 1.15:
            chin = low_y
            break
    else:
        # 襟の高い服では首が隠れ、幅が広がり直さないまま細くなって終わる。あごの先（V の先）は幅が最大の 3 割を切る辺り
        half = [y for y in range(int(ys[0]), int(ys[-1]) + 1) if most >= 10 and width[y] < most * 0.3 and width[:y].max() >= most]
        if half:
            chin = half[0]
    top, bottom = rows[0], rows[-1]
    p = {q["name"]: q for q in points or [] if q.get("score", 0) >= 0.3}
    if all(k in p for k in ("nose", "left_eye", "right_eye")):
        # 関節の点があれば、あごは鼻から（目と鼻の間）の 3 倍下。目盛りを当てて目で見た 2 枚とも 3.0 倍だった。
        # 顔の部位の幅で取ると、首の肌や襟で外れ、頭身 5.7 の絵を 4.6、6.5 の絵を 11.5 と測った
        eye = (p["left_eye"]["y"] + p["right_eye"]["y"]) / 2
        chin = p["nose"]["y"] + 3.0 * max(p["nose"]["y"] - eye, 1.0)
    if chin <= top:
        return None
    return round(float((bottom - top) / (chin - top)), 2)


SEGMENTS = {
    "shoulder_width": ("left_shoulder", "right_shoulder"), "hip_width": ("left_hip", "right_hip"),
    "upper_arm_l": ("left_shoulder", "left_elbow"), "upper_arm_r": ("right_shoulder", "right_elbow"),
    "forearm_l": ("left_elbow", "left_wrist"), "forearm_r": ("right_elbow", "right_wrist"),
    "thigh_l": ("left_hip", "left_knee"), "thigh_r": ("right_hip", "right_knee"),
    "shin_l": ("left_knee", "left_ankle"), "shin_r": ("right_knee", "right_ankle"),
}


def proportions(points: list[dict], least: float = 0.3) -> dict:
    """関節の点から、部位の長さを胴の長さ（両肩の中点から両股の中点）で割った値。読めない点の部位は入れない"""
    p = {q["name"]: q for q in points if q.get("score", 1) >= least}

    def d(a, b):
        return float(np.hypot(p[a]["x"] - p[b]["x"], p[a]["y"] - p[b]["y"]))
    need = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    if not all(k in p for k in need):
        return {}
    sx = (p["left_shoulder"]["x"] + p["right_shoulder"]["x"]) / 2
    sy = (p["left_shoulder"]["y"] + p["right_shoulder"]["y"]) / 2
    hx = (p["left_hip"]["x"] + p["right_hip"]["x"]) / 2
    hy = (p["left_hip"]["y"] + p["right_hip"]["y"]) / 2
    torso = float(np.hypot(sx - hx, sy - hy))
    return {k: round(d(a, b) / torso, 3) for k, (a, b) in SEGMENTS.items() if a in p and b in p and torso > 0}


def structure(points: list[dict], top: float, bottom: float, least: float = 0.3, tolerance: float = 0.06) -> dict:
    """頭身によらない体の決まり（styles/genres.json の structure）からの外れ。値は身長に対する割合の差。
    股（両股の点の少し下）は身長の半分、腕を下ろした手首は股の高さ、肘は肩と手首の中ほど、膝は股と足首の中ほど。
    立ち姿で腕を下ろした絵だけに使う（腕を上げた絵では手首の決まりは当たらない）"""
    p = {q["name"]: q for q in points if q.get("score", 1) >= least}
    H = bottom - top
    out = {}
    if H <= 0 or not all(k in p for k in ("left_hip", "right_hip")):
        return {"values": out, "off": {}}
    hip = (p["left_hip"]["y"] + p["right_hip"]["y"]) / 2
    # 関節の点の股は脚の付け根の関節で、股の線より頭 0.25 個分ほど上にある
    crotch = hip + H * 0.03
    out["crotch_from_half"] = round((crotch - top) / H - 0.5, 3)
    for side in ("left", "right"):
        if f"{side}_wrist" in p:
            out[f"wrist_{side}_from_crotch"] = round((p[f"{side}_wrist"]["y"] - crotch) / H, 3)
        if all(f"{side}_{k}" in p for k in ("shoulder", "elbow", "wrist")):
            s_, e, w = (p[f"{side}_{k}"]["y"] for k in ("shoulder", "elbow", "wrist"))
            out[f"elbow_{side}_from_mid"] = round((e - (s_ + w) / 2) / H, 3)
        if all(f"{side}_{k}" in p for k in ("hip", "knee", "ankle")):
            h_, k_, a_ = (p[f"{side}_{k}"]["y"] for k in ("hip", "knee", "ankle"))
            out[f"knee_{side}_from_mid"] = round((k_ - (h_ + a_) / 2) / H, 3)
    return {"values": out, "off": {k: v for k, v in out.items() if abs(v) > tolerance}}


def shoe_pair(points: list[dict], im: Image.Image, least: float = 0.3) -> dict | None:
    """左右の足首の下を同じ大きさで切り出し、靴の平均の色の差（RGB の距離）と、塗られた面積の比を返す。
    左右で違う靴（片方だけ灰色）の絵で 35.5、そろった絵で 2〜6 だった。影で暗い奥の足や、ズボンの裾が入る絵でも
    15〜30 が出るので、崩れとは決めず、目で確かめる所の印に使う"""
    p = {q["name"]: q for q in points if q.get("score", 1) >= least}
    if not all(k in p for k in ("left_ankle", "right_ankle", "left_hip", "right_hip")):
        return None
    rgb = np.asarray(im.convert("RGB")).astype(float)
    bg = rgb[2, 2]
    r = max(12.0, abs(p["left_hip"]["x"] - p["right_hip"]["x"]) * 0.45)
    stats = []
    for s in ("left", "right"):
        x, y = p[f"{s}_ankle"]["x"], p[f"{s}_ankle"]["y"]
        box = rgb[max(0, int(y - r * 0.3)):int(y + r * 1.1), max(0, int(x - r * 0.6)):int(x + r * 0.6)]
        m = np.abs(box - bg).sum(2) > 40
        stats.append((box[m].mean(0) if m.any() else bg, int(m.sum())))
    return {"color_diff": round(float(np.linalg.norm(stats[0][0] - stats[1][0])), 1),
            "area_ratio": round(min(stats[0][1], stats[1][1]) / max(1, stats[0][1], stats[1][1]), 2)}


# 端の切れを数える部位: 顔・腕・脚・靴。髪・服・すそ・鞄が画面の外へ流れるのは構図として普通で、
# 背景が画面いっぱいの絵では服や背景の一部を人物と読み、32 枚ほぼ全部を「切れ」と出した（描画確認 回7）
LEG_LABELS = (5, 6, 7, 9, 10, 12, 13)
# 脚が重なって見えて当たり前の姿勢と、脚の下が入らない構図
LEGS_OVERLAP_OK = ("sitting", "seiza", "kneeling", "crouching", "squatting", "lying", "crossed legs", "legs together",
                   "cowboy shot", "upper body", "portrait", "close-up", "from side", "profile", "long dress", "long skirt", "gown")


def legs_fused(points: list[dict], seg: np.ndarray, prompt: str = "", apart: float = 0.09, least: float = 0.1,
               seen: float = 0.5) -> dict:
    """両脚が服の中で 1 本に溶けた崩れ。足首が絵の幅の apart 以上離れているのに、腰と足首の間（3 割〜9 割の高さ）で
    脚の部位（ズボン・スカート・脚・靴）が左右 2 つに分かれる行が least 未満しかない。
    基準の組の約 50 枚で、溶けた 1 枚（足首の差 0.103、分かれた行 0）だけが当たった。脚の重なりが当たり前の姿勢
    （座る・しゃがむ・横向き・膝上の構図）では見ない（しゃがんだ横向きの絵は足首が 0.26 離れて分かれた行が 0 だった）"""
    low = prompt.lower()
    p = {q["name"]: q for q in points}
    need = ("left_hip", "right_hip", "left_ankle", "right_ankle")
    if any(w in low for w in LEGS_OVERLAP_OK) or any(n not in p or p[n]["score"] < seen for n in need):
        return {"readable": False}
    h, w = seg.shape
    hip = (p["left_hip"]["y"] + p["right_hip"]["y"]) / 2
    ank = (p["left_ankle"]["y"] + p["right_ankle"]["y"]) / 2
    dx = abs(p["left_ankle"]["x"] - p["right_ankle"]["x"]) / w
    y0, y1 = int(hip + (ank - hip) * 0.3), min(h - 1, int(hip + (ank - hip) * 0.9))
    if y1 <= y0:
        return {"readable": False}
    m = np.isin(seg[y0:y1], LEG_LABELS).astype(int)
    runs = (np.diff(np.pad(m, ((0, 0), (1, 1))), axis=1) == 1).sum(1)
    split = float((runs >= 2).mean())
    return {"readable": True, "fused": dx >= apart and split < least, "ankle_apart": round(dx, 3), "split_rows": round(split, 2)}


EDGE_BODY = (11, 12, 13, 14, 15, 9, 10)


def edge_body(seg: np.ndarray) -> np.ndarray:
    return np.isin(seg, EDGE_BODY)


def person_mask(seg: np.ndarray) -> np.ndarray:
    """部位分けの「背景」以外を人物とする（髪・服・肌・持ち物の袋など）"""
    return seg > 0


def background_clutter(rgb: np.ndarray, seg: np.ndarray, far: float = 40.0, margin: int = 24) -> float:
    """無地のはずの背景に、背景の色と違う画素がどれだけあるか（人物の周り margin 画素を除いた背景の割合）。
    黄色の点の模様が背景一面に描かれた絵を、端の切れや浮いた塊の検品では拾えなかった"""
    from scipy import ndimage
    person = ndimage.binary_dilation(person_mask(seg), iterations=margin)
    bg = rgb[2, 2].astype(int)
    off = np.abs(rgb.astype(int) - bg).sum(2) > far
    area = (~person).sum()
    return round(float((off & ~person).sum() / max(1, area)), 4)


def glow_ring(rgb: np.ndarray, seg: np.ndarray, width: int = 6) -> float:
    """人物の輪郭のすぐ外側の帯の、背景からの色の離れ（彩度の高いにじみ）。輪郭の外にオレンジの光が付いた絵を拾うため。
    帯の画素の、背景の色との差の中央値を返す（光の無い絵では 0 に近い）"""
    from scipy import ndimage
    m = person_mask(seg)
    ring = ndimage.binary_dilation(m, iterations=width) & ~ndimage.binary_dilation(m, iterations=2)
    if not ring.any():
        return 0.0
    bg = rgb[2, 2].astype(int)
    return round(float(np.median(np.abs(rgb[ring].astype(int) - bg).sum(1))), 1)


def part_color(rgb: np.ndarray, seg: np.ndarray, labels: list[int]) -> list[float] | None:
    """部位分けの番号の画素の色の中央値（影や光に引っ張られにくいよう平均ではなく中央値）"""
    m = np.isin(seg, labels)
    if m.sum() < 200:
        return None
    return [float(v) for v in np.median(rgb[m], 0)]


def proportion_drift(base: dict, drawn: dict, tolerance: float = 0.15) -> dict:
    """下絵（体の寸法を合わせた人形）と描いた絵で、部位の長さの比べ。描く模型が肩幅や脚の長さを変えると、
    下絵で合わせた釣り合いが絵に残らない。tolerance（既定 15%）を超えた部位を挙げる"""
    ratio = {k: round(drawn[k] / base[k], 2) for k in base if k in drawn and base[k] > 0}
    return {"ratio": ratio, "off": {k: v for k, v in ratio.items() if abs(v - 1) > tolerance}}


def edge_cut(rgb: np.ndarray, margin: int = 2, far: float = 40.0, least: float = 0.02, win: int = 248,
             person: np.ndarray | None = None) -> list[str]:
    """人物が絵の端で切れているか（全身の絵で足先や頭が切れる欠損）。辺ごとに、端の帯の色を辺に沿った移動中央値（win 画素）と比べ、
    far 以上離れた画素が least を超える辺の名前を返す。
    四隅の色を地とすると、影や色の変わる背景で四辺とも「切れている」と出た（アラクネの候補 24 枚中 22 枚が読めなくなった）。
    辺に沿ってゆっくり変わる背景は移動中央値に乗り、人物がかかった所だけが外れる"""
    from scipy import ndimage
    x = rgb.astype(float)
    out = []
    for name, band in (("上", x[:margin]), ("下", x[-margin:]),
                       ("左", x[:, :margin].transpose(1, 0, 2)), ("右", x[:, -margin:].transpose(1, 0, 2))):
        line = band.mean(0)
        bg = np.stack([ndimage.median_filter(line[:, c], size=win, mode="nearest") for c in range(3)], -1)
        off = np.abs(line - bg).max(-1) > far
        if person is not None:
            # 人物（部位分けで背景でない所）にかかる画素だけを数える。背景の椰子の葉が端で切れているのを、
            # 人物が切れていると取り違えた（描画確認、2026-10-17）
            pm = {"上": person[:margin], "下": person[-margin:], "左": person[:, :margin].T, "右": person[:, -margin:].T}[name]
            off = off & pm.any(0)
        if off.mean() > least:
            out.append(name)
    return out


# 欠損の棚卸しで数える部位（部位分けの番号）。服で覆われた腕や脚は部位分けで取れないことがあるので、
# 「取れない」は欠損の証拠ではなく、目で確かめる所の印として出す
INVENTORY = {"髪": (HAIR,), "顔": (FACE,), "右腕（素肌）": (RARM,), "左腕（素肌）": (LARM,), "右脚（素肌）": (RLEG,),
             "左脚（素肌）": (LLEG,), "右の靴": (RSHOE,), "左の靴": (LSHOE,)}


def inventory(parts: np.ndarray, least: int = 150) -> dict:
    """部位ごとに、取れた画素の数と塊の数。塊が2つ以上ある部位は、途中で切れているか、別の物が重なっている印"""
    from scipy import ndimage
    out = {}
    for name, ks in INVENTORY.items():
        m = np.isin(parts, ks)
        n = int(m.sum())
        lab, k = ndimage.label(m)
        big = int((np.bincount(lab.ravel())[1:] >= least).sum()) if k else 0
        out[name] = {"pixels": n, "pieces": big, "found": n >= least}
    return out


def nouns_missing(words: str, got: dict, vocab: set, least: float = 0.2) -> list[str]:
    """読む模型の一覧に無い言い方（dark red cape）は、最後の名詞（cape）が一覧にあればそれで比べる。
    一覧に無い言い方を比べずに外すと、騎士の正面にマントが無いことを拾えなかった"""
    out = []
    for t in (x.strip().lower() for x in words.split(",")):
        if not t or t in vocab or " " not in t:
            continue
        # 前置詞より後ろは付け足し（long black skirt to the knees の knees は物ではない）。前で切って最後の名詞を取る
        head = re.split(r" (?:up to|to|with|behind|on|around|under|over|in|at|from) ", t)[0]
        if " " not in head and head in vocab:
            continue
        noun = head.rsplit(" ", 1)[-1]
        if noun in vocab and got.get(noun, 0.0) < least and not any(k.endswith(noun) and v >= least for k, v in got.items()):
            out.append(f"{t}（{noun} が読めない）")
    return out


# ---- 絵から ----

def _parts(path: str, im: Image.Image) -> np.ndarray:
    import edit
    return np.asarray(edit.parts(path).resize(im.size, Image.NEAREST))


def _largest(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage
    lab, n = ndimage.label(mask)
    if n == 0:
        return mask
    return lab == (int(np.bincount(lab.ravel())[1:].argmax()) + 1)


def _box(mask: np.ndarray, pad: float, shape) -> tuple | None:
    if mask.sum() < 50:
        return None
    ys, xs = np.nonzero(mask)
    h, w = ys.max() - ys.min(), xs.max() - xs.min()
    p = int(max(h, w) * pad) + 8
    return (max(xs.min() - p, 0), max(ys.min() - p, 0), min(xs.max() + p, shape[1]), min(ys.max() + p, shape[0]))


def tiles(box, rows: int = 3, cols: int = 2, overlap: float = 0.12) -> list[tuple]:
    """人物の外接枠を rows×cols に分けた枠（少し重ねる。境目にある手や持ち物が切れて見えないように）"""
    x0, y0, x1, y1 = box
    w, h = (x1 - x0) / cols, (y1 - y0) / rows
    ox, oy = w * overlap, h * overlap
    return [(int(max(x0 + c * w - ox, x0)), int(max(y0 + r * h - oy, y0)), int(min(x0 + (c + 1) * w + ox, x1)),
             int(min(y0 + (r + 1) * h + oy, y1))) for r in range(rows) for c in range(cols)]


def _face_from_joints(src: str, size: tuple[int, int], least: float = 0.3):
    """骨格の点で顔を囲む箱。鼻と両目が読めないときは None。幅は耳と目の広がりの 2.2 倍、髪まで入るよう上へ寄せる"""
    try:
        import joints
        p = {q["name"]: q for q in joints.find(src)}
    except Exception:
        return None
    pts = [p[n] for n in ("nose", "left_eye", "right_eye", "left_ear", "right_ear") if n in p and p[n]["score"] >= least]
    if not all(n in p and p[n]["score"] >= least for n in ("nose", "left_eye", "right_eye")):
        return None
    xs, ys = [q["x"] for q in pts], [q["y"] for q in pts]
    side = max((max(xs) - min(xs)) * 2.2, 48)
    cx, cy = p["nose"]["x"], p["nose"]["y"] - side * 0.1
    box = (int(max(cx - side / 2, 0)), int(max(cy - side / 2, 0)), int(min(cx + side / 2, size[0])), int(min(cy + side / 2, size[1])))
    return box if box[2] > box[0] and box[3] > box[1] else None


def sheet(src: str, out: str, zoom: float = 2.0, cell: int = 380) -> dict:
    """検品図を2枚書く。out は全体と顔の拡大、out の -detail は人物を分けた拡大（どの枚も zoom 倍前後）。
    どこも「見ていない」にならないよう、人物の全部をどれかの拡大に入れる。
    部位分けで手と足を探すと、籠手や鎧靴を手足と取らず見つからなかった。6つに分けるだけでは 0.8 倍にしかならなかった"""
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im)
    fig = figure_mask(rgb)
    fbox = _box(_largest(fig), 0.02, fig.shape) or (0, 0, im.width, im.height)
    try:
        face = _largest(_parts(src, im) == FACE)
        face_box = _box(face, 0.3, fig.shape) if face.sum() >= 200 else None
    except Exception:          # 部位分けの模型が無くても検品図は作る
        face_box = None
    note = []
    jbox = _face_from_joints(src, im.size)
    if face_box is not None and jbox is not None:
        # 部位分けは、水着で出た胴の肌を顔と取り、顔の拡大が胸を写した（水着の 4 枚中 4 枚）。鼻が箱に入らなければ骨格の点を使う
        nx, ny = (jbox[0] + jbox[2]) / 2, (jbox[1] + jbox[3]) / 2
        if not (face_box[0] <= nx <= face_box[2] and face_box[1] <= ny <= face_box[3]) or \
                (face_box[2] - face_box[0]) > 2 * (jbox[2] - jbox[0]) or \
                (face_box[2] - face_box[0]) > 0.4 * (fbox[2] - fbox[0]) + (jbox[2] - jbox[0]):
            face_box = jbox
            note.append("部位分けの顔が骨格の点と合わず、骨格の点を使った")
    if face_box is None:
        # 部位分けで顔が取れなければ骨格の点（鼻・両目・両耳）から顔を囲む。人物の上端の正方形は、背景を人物と取ると
        # 胸まで入る大きさになり、顔の拡大が胴を写していた（水着の 4 枚中 4 枚）
        face_box = jbox
        if face_box is not None:
            note.append("顔は部位分けで取れず、骨格の点を使った")
    if face_box is None:       # 骨格の点も取れなければ、人物の上端の正方形を顔の候補にする
        side = int((fbox[2] - fbox[0]) * 0.5)
        cx = (fbox[0] + fbox[2]) // 2
        face_box = (max(cx - side // 2, 0), fbox[1], min(cx + side // 2, im.width), fbox[1] + side)
        note.append("顔は部位分けで取れず、人物の上端を使った")
    font = ImageFont.truetype(FONT, 20) if Path(FONT).exists() else ImageFont.load_default()
    # 1枚目: 全体と顔
    full_h = 900
    full = im.resize((int(im.width * full_h / im.height), full_h))
    face_img = im.crop(face_box).resize((full_h, full_h), Image.LANCZOS)
    a = Image.new("RGB", (full.width + 20 + full_h, full_h + 30), "white")
    d = ImageDraw.Draw(a)
    a.paste(full, (0, 30))
    sx = full.width / im.width
    d.rectangle([face_box[0] * sx, 30 + face_box[1] * sx, face_box[2] * sx, 30 + face_box[3] * sx], outline="blue", width=2)
    d.text((4, 4), "全体（青い枠が右の顔）", fill="black", font=font)
    d.text((full.width + 24, 4), f"顔（{full_h / max(face_box[2] - face_box[0], 1):.1f} 倍）", fill="black", font=font)
    a.paste(face_img, (full.width + 20, 30))
    a.save(out, quality=88)
    # 2枚目: 人物を分けた拡大。1枚の範囲が cell/zoom 以下になる数に分ける
    span = cell / zoom
    cols = max(1, int(np.ceil((fbox[2] - fbox[0]) / span)))
    rows = max(1, int(np.ceil((fbox[3] - fbox[1]) / span)))
    boxes = tiles(fbox, rows, cols)
    detail = str(Path(out).with_name(Path(out).stem + "-detail.jpg"))
    b = Image.new("RGB", (cols * (cell + 10), rows * (cell + 34)), "white")
    d = ImageDraw.Draw(b)
    for i, bx in enumerate(boxes):
        r, c = divmod(i, cols)
        x, y = c * (cell + 10), r * (cell + 34)
        t = im.crop(bx)
        scale = min(cell / t.width, cell / t.height)
        b.paste(t.resize((max(int(t.width * scale), 1), max(int(t.height * scale), 1)), Image.LANCZOS), (x, y + 26))
        d.text((x, y + 2), f"{r + 1}段{c + 1}列（{scale:.1f} 倍、x{bx[0]}-{bx[2]} y{bx[1]}-{bx[3]}）", fill="black", font=font)
    b.save(detail, quality=88)
    return {"out": out, "detail": detail, "figure": [int(v) for v in fbox], "face": [int(v) for v in face_box],
            "grid": [rows, cols], "notes": note}


def eye_mismatch(eyes: dict, base: float = 2.0, per_yaw: float = 6.0) -> dict:
    """左右の目の大きさが違いすぎるか。measure.eyes の面積比を、顔の向きで許す上限（base + per_yaw×|向き|）と比べる。
    横を向くほど遠い目は小さく描かれるので、上限を広げる。崩れの無い 12 枚で面積比 1.04〜1.68（横向き 0.24 の 1 枚が 2.89）。
    アラクネの目の描き直しで、検品担当が「右目が 1.5〜2 倍」と戻した 2 枚は 2.52・4.21 で外れ、元の絵 1.57 は内に入った。
    三白眼のような形の崩れは、大きさでは拾えない"""
    if eyes.get("found") != 2:
        return {"readable": False, "reason": eyes.get("reason", "目が 2 つ読めない")}
    limit = base + per_yaw * abs(eyes.get("yaw_offset", 0.0))
    return {"readable": True, "mismatch": eyes["area_ratio"] > limit, "area_ratio": eyes["area_ratio"],
            "limit": round(limit, 2)}

def person_found(points: list[dict], least: float = 0.4) -> dict:
    """人が描かれているか。骨格の点のうち顔（鼻・両目）か両肩の確からしさの平均が least 以上なら見つかったとする。
    「引きで撮る、蜘蛛の体が全部入る」と頼むと、模型が人を落として蜘蛛だけを描いた（11 枚中 11 枚）。そのとき顔は 0.11〜0.30、
    肩は 0.03〜0.07。人のいる絵は顔 0.60〜0.69、肩 0.65〜0.83。頭の大きい崩れた人（顔 0.26〜0.36）も見つからない側に入るので、
    見つからないときは「人がいない」と言い切らず、読めないとして落とす"""
    p = {q["name"]: q["score"] for q in points}
    face = (p["nose"] + p["left_eye"] + p["right_eye"]) / 3
    shoulders = (p["left_shoulder"] + p["right_shoulder"]) / 2
    return {"found": face >= least or shoulders >= least, "face": round(float(face), 2), "shoulders": round(float(shoulders), 2)}

# 白っぽい髪の言葉。白飛びの検品から外す
LIGHT_HAIR = ("silver hair", "white hair", "platinum", "blonde", "grey hair", "gray hair")
# 白っぽい髪の白飛びの上限。検品担当が通した銀髪 0.031 と戻した銀髪 0.081 の間で、通した側に寄せた仮の値（判定の付いた絵 2 枚から）。
# 判定の付いた絵が増えたら normlearn で学び直す
LIGHT_HAIR_BLOWN_MAX = 0.06

# 下半身が人でない種族の言葉。頼んだ言葉にあれば、人の脚が残っていないかも数える
NON_HUMAN_LOWER = ("arachne", "drider", "taur", "centaur", "lamia", "naga", "mermaid", "scylla")


def eyes_by_tags(tags: dict, least: float = 0.35) -> bool:
    """絵のタグで目が描かれていると読めるか。目の色（purple eyes など）か closed eyes があり、mask が無いこと。
    目の測り方（暗い塊を 2 つ探す）は、閉じた目・細い目・白く飛んだ髪の顔で目を見つけず、4.0 の 8 枚のうち 5 枚を
    「読めない」と減点した（検品担当は 5 枚とも顔と目がはっきり描かれていると見た）。そのときタグは 5 枚とも目の色か
    closed eyes を 0.42 以上で読んだ。顔の無い絵には目のタグが付かず、顔が黒く塗れた絵には mask が 0.53 で付いた"""
    if tags.get("mask", 0) >= least:
        return False
    return any(v >= least and (k == "closed eyes" or (k.endswith(" eyes") and k.split()[0] in EYE_COLORS))
               for k, v in tags.items())


EXTRA_EYES = 0.4

EYE_COLORS = {"blue", "red", "green", "purple", "yellow", "brown", "black", "grey", "gray", "pink", "orange",
              "aqua", "white", "amber", "golden", "silver"}


SPIDER_WORDS = ("arachne", "drider", "spider body", "spider lower body")


def spider_legs(rgb, alpha, dark: float = 0.35, band: float = 0.08, least: int = 30) -> dict:
    """蜘蛛の脚の数を、体の下端の帯（体の高さの band）にある暗い塊で数える。床に届く脚の先は暗い塊で、地面の影は
    明るさ dark 以上なので外れる。検品担当が脚の先を数えた 7 枚で、6 本の 4 枚と 7 本の 1 枚は数が合い、7 本を 5 と
    読んだのが 1 枚、影と半透明の脚がつながって 8 本を 1 と読んだのが 1 枚。2 個以下はつながったとして「読めない」。
    前で折れて床に届かない脚は数えない（床に 6 本、前に 2 本の絵を 6 と読む）"""
    from scipy import ndimage
    m = alpha & (rgb.mean(-1) < dark)
    ys = np.nonzero(m.any(1))[0]
    if len(ys) == 0:
        return {"readable": False, "count": None}
    top, bot = ys.min(), ys.max()
    b = ndimage.binary_opening(m[int(bot - (bot - top) * band):bot + 1], iterations=1)
    lab, n = ndimage.label(b)
    count = int((ndimage.sum(b, lab, range(1, n + 1)) > least).sum()) if n else 0
    return {"readable": count > 2, "count": count}


def auto_check(src: str, prompt: str = "", heads_range: tuple[float, float] | None = None) -> dict:
    """描いた直後に必ず走らせる検品。崩れが 1 つでも、読めない検品が 1 つでもあれば ok を False にする。
    Claude は検品を呼ばないと走らせず、描かせた絵を検品なしで次へ回した。描く道具（free_text.draw、fix.py）から毎回呼ぶ。
    ok が True でも完成ではない。通す・戻すは検品担当（checker）が目で見て決める。
    ok が False でも絵は捨てない。機械の検品で落とした絵を隠すと、人が魅力を感じた絵まで消えた。
    外れは marks（直す所の印。何が・どこで・どう直すか）に並べ、直せる崩れは部分の描き直しで直す。
    指示や画風との違い（基準の kind が request）は崩れではないので differences に分け、ok と点数に入れない"""
    res = {"src": src, "problems": [], "unreadable": [], "differences": []}
    tags: dict = {}
    all_tags: dict = {}
    # 固定の制限は、ほかの検品が落ちても必ず走らせる（scipy が無く端の切れで落ちたとき、ここまで届かなかった）
    try:
        # 固定の制限（子どもを性的に描かない）を、頼んだ言葉だけでなく描けた絵でも確かめる。
        # 言葉で露出を頼んでいなくても、絵では露出が多く描かれた（アラクネの候補、検品担当の指摘）。
        # 絵をタグに読み、filters.fixed（言葉の判定と同じ決まり）にかける
        import filters
        import tagger
        # 1回だけ読み、絞る前の確からしさは measure（頼んだ色の照合）に渡し、res["tags"] でも返す。
        # 頼んだ言葉の欠けを調べる側（loop.py）が同じ絵をもう一度読まなくて済むようにする。絞った方を固定の制限とほかの検品に使う
        all_tags = tagger.read(src, 0.0)
        res["tags"] = all_tags
        tags = {k: v for k, v in all_tags.items() if v >= 0.35}
        # 低い確からしさまでのタグを返し、頼んだ言葉の欠けを調べる側（loop.py）が同じ絵をもう一度読まなくて済むようにする
        res["tags"] = {k: v for k, v in all_tags.items() if v >= 0.05}
        # 頼んでいない服飾（帽子など）。バーの男 8 枚中 7 枚に頼んでいないカウボーイハットが描かれ、検品が数えなかった（描画確認 回5）
        if prompt:
            low_p = prompt.lower()
            held = held_items(tags, prompt)
            extra = sorted(set(unasked_wear(tags, prompt)) | set(held["unasked"]))
            try:
                import pieces
                if pieces.ready():
                    extra_count = pieces.count_extra(src, prompt)
                    if extra_count:
                        res["problems"].append({"item_count": extra_count})
            except Exception as e:
                res["unreadable"].append({"item_count": f"{type(e).__name__}: {e}"})
            many = not_solo(all_tags, prompt)
            if many:
                res["problems"].append({"not_solo": many})
            if extra:
                res["problems"].append({"unasked_item": extra})
            if held["many"]:
                res["problems"].append({"item_count": held["many"]})
            if held["small"]:
                res["problems"].append({"item_size": held["small"]})
            parts = body_parts(tags, prompt)
            if parts["extra"] or parts["swapped"]:
                res["problems"].append({"body_parts": parts})
        # 目の範囲を描き直した絵で瞳が消え光る線だけになったのを、目の測り方が揺れて見つけたと読み通した（2026-10-16）。
        # タグは extra eyes を 0.53 で読んでいた。崩れの無い絵では 0.22〜0.30 だったので、EXTRA_EYES 以上を崩れに数える
        if tags.get("extra eyes", 0) >= EXTRA_EYES:
            res["problems"].append({"extra_eyes": round(float(tags["extra eyes"]), 2)})
        reason = filters.fixed(", ".join(tags))
        # 露出の度合い（年齢区分の questionable と explicit の和）。子どもを表す言葉が頼みごとか絵にあるとき、
        # 固定の制限の数字の裏付けとして使う。閾値 0.5 は較正していない（手本の絵が要る。ROADMAP 0.57）
        # 読めなくても、言葉による固定の制限（上の reason）は必ず効かせる
        try:
            res["rating"] = tagger.rating(src)
        except Exception as e:
            res["rating"] = {}
            res["unreadable"].append({"rating": f"{type(e).__name__}: {e}"})
        risky = res["rating"].get("questionable", 0) + res["rating"].get("explicit", 0)
        if not reason and risky >= RISKY and (filters.has_minor(prompt) or filters.has_minor(", ".join(tags))):
            reason = f"子どもを表す言葉のある絵で、露出の度合いが {risky:.2f}（{RISKY} 以上）。固定の制限で描き直す"
        # 宗教・文化の配慮（鉤十字、逆さ十字、着物の合わせなど）は崩れではないので problems に入れず、目で確かめる所として返す
        res["cultural"] = filters.cultural(", ".join(tags))
        if reason:
            res["problems"].append({"fixed_restriction": reason, "tags": sorted(tags, key=lambda t: -tags[t])[:20]})
    except Exception as e:
        res["unreadable"].append({"fixed_restriction": f"{type(e).__name__}: {e}"})
    try:
        im = Image.open(src).convert("RGB")
        rgb = np.asarray(im)
        # 頭身。ジャンルの範囲（styles/genres.json）を渡されたら外れを崩れに数える。写実の体にアニメの顔、
        # 2 頭身に写実の塗り、のようにジャンルに合わない組み合わせは、体と顔の釣り合いが崩れて見えた。
        # 測り方は髪の膨らみの分だけ小さく出るので、範囲の下を 0.4 広げて比べる
        try:
            import joints
            ht = heads_tall(_parts(src, im), rgb, points=joints.find(src))
            res["heads_tall"] = ht
            if heads_range and ht is not None and not (heads_range[0] - 0.4 <= ht <= heads_range[1]):
                res["problems"].append({"heads_tall": ht, "range": list(heads_range)})
        except ImportError as e:
            res["unreadable"].append({"heads_tall": str(e)})
        try:
            person = edge_body(_parts(src, im))
        except Exception:   # 部位分けの模型が無い環境では、これまでどおり色だけで見る
            person = None
        cut = edge_cut(rgb, person=person)
        import tagger
        if any(c in prompt.lower() for c in tagger.CROPPED):
            cut = [x for x in cut if x != "下"]   # 足元の入らない構図では下の切れは崩れではない
        if cut:
            res["problems"].append({"edge_cut": cut})
        seams = background_seams(rgb)
        if seams:
            res["problems"].append({"seams": seams})
        try:
            fl = floating_blobs(rgb)
            if fl.get("blobs"):
                res["problems"].append({"floating": fl["blobs"]})
        except ImportError as e:
            res["unreadable"].append({"floating": str(e)})
        import joints
        points = joints.find(src)
        person = person_found(points)
        # 見えない手足と目: 見えないのが当たり前（構図の外・隠す姿勢・物の陰）は通し、要るのに見えない・途中で無いものだけ落とす
        hand_pre = None
        if person["found"]:
            try:
                import occlusion
                # 手が見えるかは手首の確からしさでは決めない（頭の後ろに隠れた手を 0.77〜0.89 と読んだ）。手の模型の手らしさで見る
                hand_pre = hands_auto(points, Image.open(src).convert("RGB"))
                shown = {h["side"]: h["seen"] for h in hand_pre["hands"]}
                occ = occlusion.judge(points, _parts(src, Image.open(src).convert("RGB")), prompt, hands_shown=shown)
                res["occlusion"] = occ["parts"]
                if occ["problems"]:
                    res["problems"].append({"occlusion": occ["problems"]})
                fused = legs_fused(points, _parts(src, Image.open(src).convert("RGB")), prompt)
                if fused.get("fused"):
                    res["problems"].append({"legs_fused": fused})
            except Exception as e:
                res["unreadable"].append({"occlusion": f"{type(e).__name__}: {e}"})
        if not person["found"]:
            res["unreadable"].append({"person": person})
        import measure
        # タグは上で読んだもの（絞る前）を渡し、模型を2度走らせない
        m = measure.measure(src, points=points, prompt=prompt or None, tags=all_tags or None)
        # measure が基準から外れたと出した数字（瞳の色の差、髪の白飛び、影の順序など）は全部、判定に入れる。
        # 面積比だけを見て、measure が出していた瞳の色の差 0.105（基準 0.062）を捨てて通した（目の描き直し、2026-10-14）
        if measure.NORMS.exists():
            light_hair = any(w in prompt.lower() for w in LIGHT_HAIR)
            species = any(w in prompt.lower() for w in NON_HUMAN_LOWER)
            for bad in measure.judge(m):
                # 白っぽい髪は色そのものが明るく、白飛びの基準（茶や黒の髪で決めた）を外れる。銀髪のアラクネ 16 枚を
                # 白飛びで落としたが、拡大すると髪の色だった。白っぽい髪を頼んだ絵では上限を LIGHT_HAIR_BLOWN_MAX に上げる。
                # 丸ごと数えないと、検品担当が「頭頂が白く飛んで毛束が消えた」と戻した 0.081 の絵まで通した（2026-10-15）
                if light_hair and bad["path"] == "hair.blown" and bad["value"] <= LIGHT_HAIR_BLOWN_MAX:
                    res.setdefault("ignored", []).append({"measure": bad, "why": "白っぽい髪を頼んだ"})
                    continue
                # 白い肌や白い獣の体の隣に黒い蜘蛛の体が並ぶと、素材の色の明るさを光の向きと取り違えた（検品担当が 3 枚を
                # 目で見て、3 枚とも影の向きはそろっていた）。下半身が人でない種族では影の順序を崩れに数えない
                if species and bad["path"] == "light.inverted":
                    res.setdefault("ignored", []).append({"measure": bad, "why": "体の素材の色が部位で違う種族"})
                    continue
                # 目が見つからないのは崩れではなく「読めない」（顔の無い絵、小さすぎる顔）。どちらでも落とすが、分けて書く
                if bad["path"] == "eyes.found" and eyes_by_tags(tags):
                    res.setdefault("ignored", []).append({"measure": bad, "why": "目は描かれている（タグで読めた）"})
                    continue
                if bad.get("kind") == "request":
                    res["differences"].append({"measure": bad})
                    continue
                key = "unreadable" if bad["path"] == "eyes.found" else "problems"
                res[key].append({"measure": bad})
        eye = eye_mismatch(m["eyes"])
        if not eye["readable"] and eyes_by_tags(tags):
            res.setdefault("ignored", []).append({"eyes": eye, "why": "目は描かれている（タグで読めた）"})
        elif not eye["readable"]:
            res["unreadable"].append({"eyes": eye})
        elif eye["mismatch"]:
            res["problems"].append({"eyes": eye})
        # 手の数。胸の前に 3 本目の手が描かれた絵（描画確認 回5）を、手の形の検品は手ごとにしか見ないので拾わなかった。
        # 手のひらの模型（MediaPipe）が 3 つ以上の手を見つけたら崩れに数える
        try:
            import hands as _hands
            n_hands = len(_hands.detect_palms(im))
            res["hands_count"] = n_hands
            several = any(w in (prompt or "").lower() for w in ("2girls", "2boys", "multiple", "group", "couple"))
            if n_hands > 2 and not several:
                res["problems"].append({"extra_hands": n_hands})
        except Exception as e:   # 手のひらの模型が無い環境は、崩れと分けて「読めない」と書く
            unavailable = type(e).__name__ == "Unavailable"
            res["unreadable"].append({"hands_count": {"readable": False, "why": str(e) if unavailable else f"{type(e).__name__}: {e}"}})
        hand = hand_pre if hand_pre is not None else hands_auto(points, im)
        if not hand["readable"]:
            res["unreadable"].append({"hands": hand})
        elif hand["bad"]:
            res["problems"].append({"hands": hand})
        if any(w in prompt.lower() for w in SPIDER_WORDS):
            import design
            alpha = np.asarray(design.cut_background(im).getchannel("A")) > 0
            # 床に届く脚の先だけを数えるので、前で折れて床に届かない脚は入らない。検品担当が 8 本と通した 1 枚を 6 と読んだ。
            # 崩れには数えず、参考として残す（床に届かない脚を数える方法ができたら崩れに入れる）
            res["info"] = {"spider_legs": spider_legs(rgb.astype(np.float32) / 255.0, alpha)}
        if any(w in prompt.lower() for w in NON_HUMAN_LOWER):
            legs = human_legs(points, im.height)
            if not legs["readable"]:
                res["unreadable"].append({"human_legs": legs})
            elif legs["legs"]:
                res["problems"].append({"human_legs": legs})
    except Exception as e:  # 検品が落ちたことを、検品が通ったことにしない
        res["unreadable"].append({"error": f"{type(e).__name__}: {e}"})
    res["ok"] = not res["problems"] and not res["unreadable"]
    res["score"] = score(res)
    res["marks"] = marks(res)
    Path(src + ".qc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    if any("fixed_restriction" in x for x in res["problems"]):
        res["held"] = hold(src)
    return res


# 崩れの重さ（100 点から引く）。体のつながりや人そのものの崩れは直せないので重く、部分の直しで直せる崩れは軽くする
PENALTY = {"fixed_restriction": 100, "person": 60, "human_legs": 40, "edge_cut": 25, "eyes": 15, "extra_eyes": 15, "floating": 15, "hands": 15, "occlusion": 15, "legs_fused": 25, "not_solo": 40,
           "seams": 10, "measure": 8}


# 顔を描き直す（imgproc.face_fix）と直る崩れ。目の左右の色・大きさの違い、余分な目、正面に戻すと歪む顔
FACE_FIX = {"eyes", "extra_eyes", "eyes.iris_delta", "eyes.found", "face.rms"}
# 構図そのものの崩れ（人がいない・2人目、体が画面の端で切れた）。部分の描き直しでは直らないが、絵は捨てずに印だけ付ける
LAYOUT = {"edge_cut", "person"}


def marks(res: dict) -> list[dict]:
    """外れた項目を「直す所」の印にする。kind は fix（部分の描き直しで直す）か layout（構図の崩れ）。
    repair は直し方（face_fix は顔の描き直し、inpaint はその場所の描き直し、none は直しが無い）。
    where は外れた場所や数字（端の辺、瞳の色の差、影の逆転した部位など、検品が出したもの）"""
    out = []
    for group in ("problems", "unreadable"):
        for x in res.get(group, []):
            k = next(iter(x))
            if k == "fixed_restriction":
                continue
            what = x[k]["path"] if k == "measure" else k
            kind = "layout" if what in LAYOUT else "fix"
            repair = "face_fix" if what in FACE_FIX else "none" if kind == "layout" else "inpaint"
            out.append({"what": what, "kind": kind, "repair": repair, "where": x[k], "unreadable": group == "unreadable"})
    return out


def score(res: dict) -> int:
    """auto_check の結果に点数（0〜100）を付ける。落ちた絵どうしでも良し悪しを比べ、一番良い絵を土台に選べるようにする。
    「通す・落とす」の二択では、どれも落ちたときに次の土台を選べなかった。読めない検品は崩れの半分の重さで引く"""
    pts = 100.0
    for x in res.get("problems", []):
        k = next(iter(x))
        pts -= PENALTY.get(k, 10)
    for x in res.get("unreadable", []):
        k = next(iter(x))
        pts -= PENALTY.get(k, 10) / 2
    return max(0, int(round(pts)))

def hold(src: str) -> str:
    """固定の制限に当たった絵を、隣の held/ へ付随ファイルごと移す。見回りで手で移していたのを、描いた直後に行う。
    移した先には、見せる・保存する経路（.pass、library）から外れた名前だけが残る"""
    import shutil
    p = Path(src)
    dest = p.parent / "held"
    dest.mkdir(exist_ok=True)
    for f in p.parent.glob(p.name + "*"):
        shutil.move(str(f), str(dest / f.name))
    return str(dest / p.name)

def facts(src: str, character: str | None = None, prompt: str = "") -> dict:
    """数えられる事実。判断はしない（検品担当が、この数字を手がかりに目で確かめる）。
    prompt を渡すか、絵の隣の <絵>.json に prompt があれば、頼んだ言葉の欠けと持ち物の数も見る"""
    if ".parts." in Path(src).name:
        # 部位分けの控え（絵の隣の .parts.png）は絵ではない。一覧に混ざると部位分けの図をさらに部位分けした（描画確認 回7）
        raise ValueError(f"{src} は部位分けの控え。元の絵を渡す")
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im)
    parts = _parts(src, im)
    person = parts > 0
    # 端の切れは人物の画素だけで数える（背景が端まである絵で、全身が収まっているのに4辺切れと出た）
    import tagger
    side = Path(str(src) + ".json")
    try:
        asked = prompt or (json.loads(side.read_text(encoding="utf-8")).get("prompt", "") if side.exists() else "")
    except (OSError, ValueError):
        asked = prompt
    framed = any(c in asked.lower() for c in tagger.CROPPED)
    res = {"edge_cut": [x for x in edge_cut(rgb, person=edge_body(parts)) if not (framed and x == "下")], "inventory": inventory(parts),
           "floating": floating_blobs(rgb), "seams": background_seams(rgb),
           "skin_ratio": round(float(np.isin(parts, SKIN).sum() / max(person.sum(), 1)), 3)}
    import tagger
    got = tagger.read(src)
    res["tags"] = dict(sorted(got.items(), key=lambda x: -x[1])[:40])
    if character:
        import bible
        c = bible.load("characters", character)
        avoid = {w.strip().lower() for w in c.get("negative", "").split(",") if w.strip()}
        for it in c.get("items", []):
            avoid |= {w.strip().lower() for w in it.get("avoid", "").split(",") if w.strip()}
        res["avoided_but_seen"] = {t: p for t, p in got.items() if t in avoid}
        words = ", ".join(x for x in (c["look"], c.get("eyes", {}).get("tags", ""), c["outfit"]) if x)
        res["asked_but_missing"] = tagger.missing(words, got) + nouns_missing(words, got, tagger.vocabulary())
    else:
        # 設定資料の無い絵でも、描いたときの言葉（絵の隣の <絵>.json の prompt）があれば欠けを見る。
        # 付けないと見なかったため、ピースサイン 8/8 の欠け・剣の欠け・短パンが長ズボンになったのを拾えなかった
        side = Path(str(src) + ".json")
        try:
            words = prompt or (json.loads(side.read_text(encoding="utf-8")).get("prompt", "") if side.exists() else "")
        except (OSError, ValueError):
            words = prompt
        if words:
            res["asked_but_missing"] = tagger.missing(words, got) + nouns_missing(words, got, tagger.vocabulary())
            res["held_items"] = held_items(got, words)
    return res


def expr(base: str, out: str, srcs: list[str]) -> dict:
    """表情差分の見比べ図: 1行に1表情、左から顔・眉と目の帯（3倍）・口の帯（3倍）。先頭の行は「ふだん」（無ければ基準の絵）。
    どの絵も基準の絵の同じ枠で切るので、行ごとに位置がそろい、動いた所が目で追える。
    動きを数字で出すのはやめた: 画素の差は前髪の毛先の揺れでどの表情も目の帯が 21〜23 動いて見え、
    暗い画素を数えるやり方は部位分けの顔の広さが絵ごとに 2万7千〜3万5千画素と揺れ、照れの頬の赤みも口と数えた"""
    bi = Image.open(base).convert("RGB")
    face = _largest(_parts(base, bi) == FACE)
    box = _box(face, 0.0, face.shape) if face.sum() >= 200 else None
    if box is None:
        raise SystemExit("基準の絵で顔が見つからない")
    srcs = [s for s in srcs if ".parts." not in s]   # 部位分けの控え（絵の隣に置かれる）は表情の絵ではない
    ref = next((s for s in srcs if "neutral" in Path(s).stem), None)
    order = ([ref] if ref else [base]) + [s for s in srcs if s != ref]
    x0, y0, x1, y1 = box
    h = y1 - y0
    font = ImageFont.truetype(FONT, 18) if Path(FONT).exists() else ImageFont.load_default()
    face_w, zoom = 240, 3
    strips = {k: (y0 + int(h * t), y0 + int(h * u)) for k, (t, u) in BANDS.items()}
    widths = [face_w] + [(x1 - x0) * zoom for _ in strips]
    row_h = max(int(face_w * h / (x1 - x0)), max((b - a) * zoom for a, b in strips.values())) + 26
    sheet_ = Image.new("RGB", (sum(widths) + 10 * len(widths), row_h * len(order)), "white")
    d = ImageDraw.Draw(sheet_)
    for r, s in enumerate(order):
        im = Image.open(s).convert("RGB")
        y = r * row_h
        d.text((4, y + 2), Path(s).stem + ("（比べる相手）" if r == 0 else ""), fill="black", font=font)
        x = 0
        f = im.crop(box)
        sheet_.paste(f.resize((face_w, int(face_w * f.height / f.width))), (x, y + 24))
        x += face_w + 10
        for k, (a, b) in strips.items():
            st = im.crop((x0, a, x1, b))
            sheet_.paste(st.resize((st.width * zoom, st.height * zoom), Image.LANCZOS), (x, y + 24))
            if r == 0:
                d.text((x + 4, y + 2), f"{k}（{zoom}倍）", fill="red", font=font)
            x += st.width * zoom + 10
    sheet_.save(out, quality=85)
    return {"out": out, "face": [int(v) for v in box], "rows": [Path(s).name for s in order],
            "note": "動いたかは数字で決めない。行を上下に見比べて、眉・目・口のどれが動いたかを目で決める"}


def compare(srcs: list[str], limit: float = 40.0) -> dict:
    colors = []
    for s in srcs:
        im = Image.open(s).convert("RGB")
        colors.append(part_colors(np.asarray(im), _parts(s, im)))
    return {"files": srcs, "gaps": color_gaps(colors, limit),
            "parts_found": [[PART_JA[k] for k in c] for c in colors]}


def zoom_tiles(src: str, outdir: str, cols: int = 2, rows: int = 4, zoom: float = 3.0) -> dict:
    """絵全体を tiles の升目に切り、どれも zoom 倍に拡大して別々の画像に書く。検品はこの全部を1枚ずつ開いて見る。
    sheet の -detail は1枚の図にまとめるので約2倍にしかならず、選ぶ段と検品で、手の光る物・手の下に垂れる帯・
    左右で違う靴を見落とした（夜間の女性 10-13〜14）。部位分けに頼らず絵全体を切るのは、手を袖や服と取り違えても
    見る範囲から漏れないようにするため"""
    im = Image.open(src).convert("RGB")
    Path(outdir).mkdir(parents=True, exist_ok=True)
    stem = Path(src).stem
    out = []
    for i, box in enumerate(tiles((0, 0, im.width, im.height), rows, cols, overlap=0.15)):
        t = im.crop(box)
        p = str(Path(outdir) / f"{stem}-t{i // cols}{i % cols}.png")
        t.resize((int(t.width * zoom), int(t.height * zoom)), Image.LANCZOS).save(p)
        out.append({"file": p, "box": list(box)})
    return {"src": src, "zoom": zoom, "tiles": out,
            "note": "全部の升目を1枚ずつ開いて見る。開かなかった升目があれば、その範囲は確かめていないと書く"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet"); s.add_argument("src"); s.add_argument("out")
    f = sub.add_parser("facts"); f.add_argument("src"); f.add_argument("--character")
    f.add_argument("--prompt", default="", help="頼んだ言葉（無ければ絵の隣の <絵>.json の prompt）")
    c = sub.add_parser("compare"); c.add_argument("srcs", nargs="+"); c.add_argument("--limit", type=float, default=40.0)
    sc = sub.add_parser("scars"); sc.add_argument("before"); sc.add_argument("after"); sc.add_argument("mask")
    lg = sub.add_parser("legs"); lg.add_argument("src")
    e = sub.add_parser("expr"); e.add_argument("base"); e.add_argument("out"); e.add_argument("srcs", nargs="+")
    t = sub.add_parser("zoom"); t.add_argument("src"); t.add_argument("outdir"); t.add_argument("--zoom", type=float, default=3.0)
    a = ap.parse_args()
    r = {"sheet": lambda: sheet(a.src, a.out), "facts": lambda: facts(a.src, a.character, a.prompt),
         "compare": lambda: compare(a.srcs, a.limit), "expr": lambda: expr(a.base, a.out, a.srcs),
         "legs": lambda: human_legs(__import__("joints").find(a.src), Image.open(a.src).height),
         "scars": lambda: repaint_scars(*(Image.open(p) for p in (a.before, a.after, a.mask))),
         "zoom": lambda: zoom_tiles(a.src, a.outdir, zoom=a.zoom)}[a.cmd]()
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
