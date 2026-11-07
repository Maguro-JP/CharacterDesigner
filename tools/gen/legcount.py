"""床に着いた脚の本数を数え、下絵（奥行き）の本数と突き合わせる。

読み取りの模型（tagger）は「しっぽが有る」は読めるが、本数は読めなかった（docs/ROADMAP.md 0.56）。
ケンタウロスの 4 本・アラクネの 8 本・ハーピーの 2 本は、体の一番下の帯を横に切ったとき、
人物の範囲が何か所に分かれるか（切れ目の数）で数えられる。下絵も同じ方法で数えれば、種族ごとの正解を書かずに済む。

使い方: python3 tools/gen/legcount.py <絵.png> [<下絵.png>]
       python3 tools/gen/legcount.py --quadruped <絵.png>   （四足の動物。4 本読めるか）
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BAND = 0.10      # 人物の高さに対する、数える帯の厚さ（足先から上へ）。0.06 では鉤爪の先だけを数えた
MIN_WIDTH = 0.004  # 絵の幅に対する、脚とみなす最小の幅（細い影や毛先を数えない）
GAP = 0.008     # 絵の幅に対する、埋める隙間の幅。0.02 では下絵のケンタウロスの前脚 2 本がつながった
REACH = 0.9      # 描いた絵の足先が、下絵の足先の高さのこの割合より上で終わったら、足元を読めないとする


def runs(row: np.ndarray, min_px: int) -> int:
    """1 行の中で、続いて立っている区間のうち min_px 以上の幅のものを数える"""
    n, width = 0, 0
    for v in list(row) + [False]:
        if v:
            width += 1
        else:
            n += width >= min_px
            width = 0
    return n


def count(mask: np.ndarray) -> dict:
    """mask は人物の範囲（True）。足先から BAND の帯の中の各行で切れ目を数え、多数決で本数にする。
    1 行だけで数えると、床に着く高さの差（前脚と後脚）で 1 本ずつ取りこぼした"""
    ys = np.nonzero(mask.any(axis=1))[0]
    if len(ys) == 0:
        return {"legs": 0, "rows": []}
    top, bottom = ys[0], ys[-1]
    band = max(3, int((bottom - top) * BAND))
    min_px = max(2, int(mask.shape[1] * MIN_WIDTH))
    mask = close_gaps(mask, int(mask.shape[1] * GAP))
    per_row = [runs(mask[y], min_px) for y in range(bottom - band, bottom + 1)]
    legs = int(np.bincount(per_row).argmax())
    return {"legs": legs, "rows": per_row, "bottom": int(bottom) / mask.shape[0]}


LOW = 0.45      # 四足: 体の高さの下からこの割合の中で脚を探す（胴の下から足先まで）
PERSIST = 0.05  # 四足: その本数がこの高さ（体の高さの割合）以上続いたときだけ数える（影の縁・毛先の一瞬の切れを数えない）


def quadruped(mask: np.ndarray) -> dict:
    """四足の脚の本数を数える。count() の足先の帯は、四足の絵では床の影（横に長い楕円）が人物の範囲に入り、
    帯がほぼ影だけになって 36 枚中 34 枚で 1〜2 本と読んだ（動物図鑑のカピバラ）。
    影は 1 つの塊、脚は胴の下で縦に並ぶので、下の LOW の範囲で「n 本以上に分かれた行」が PERSIST 以上
    続く一番大きい n を本数にする。横向きの絵では奥の脚が手前の脚に重なるので、正しい絵でも 3 本と出る"""
    ys = np.nonzero(mask.any(axis=1))[0]
    if len(ys) == 0:
        return {"legs": 0}
    top, bottom = ys[0], ys[-1]
    h = bottom - top
    min_px = max(2, int(mask.shape[1] * MIN_WIDTH))
    mask = close_gaps(mask, int(mask.shape[1] * GAP))
    rows = [runs(mask[y], min_px) for y in range(int(bottom - h * LOW), bottom + 1)]
    need = max(2, int(h * PERSIST))
    legs = 1
    for n in range(2, 9):
        streak = best = 0
        for c in rows:
            streak = streak + 1 if c >= n else 0
            best = max(best, streak)
        if best >= need:
            legs = n
    return {"legs": legs, "rows_hit": need}


def holes_open(image, mask: np.ndarray, dist: float = 40.0) -> np.ndarray:
    """端からの塗りつぶしで抜いた範囲（drawn_mask）から、背景と同じ色の画素を抜き直す。
    床の影が脚の先どうしをつなぐと、脚の間の背景が端から届かない穴になり、範囲に残る（脚の間が埋まって 1 本に読めた）。
    背景の色は絵の四辺の中央値。image は絵の道か PIL の絵"""
    im = image if isinstance(image, Image.Image) else Image.open(image)
    rgb = np.asarray(im.convert("RGB")).astype(float)
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(edge, axis=0)
    return mask & (np.linalg.norm(rgb - bg, axis=-1) > dist)


# 四足の題材の語（頼んだ言葉にあれば脚を数える）。人の上半身が付く種族（ケンタウロス）は count() と下絵で見る
QUADRUPED_WORDS = ("cat", "dog", "puppy", "kitten", "horse", "pony", "wolf", "fox", "capybara", "rabbit", "bear",
                   "deer", "cow", "pig", "sheep", "goat", "lion", "tiger", "leopard", "raccoon", "hamster", "quadruped")


def is_quadruped(prompt: str) -> bool:
    import re
    low = (prompt or "").lower()
    # 猫耳の少女（1girl, cat ears）など、人の絵に動物の語が混ざる。語の頭で見る（manga の man で動物の絵を外さない）
    if re.search(r"(?<![a-z])(girls?|boys?|wom[ae]n|m[ae]n|humans?|person|people)\b|taur", low):
        return False
    return any(re.search(r"\b" + w + r"s?\b", low) for w in QUADRUPED_WORDS)


def quadruped_judge(image, expected: int = 4) -> dict:
    """四足の題材で脚を数える。expected 本読めれば ok。少なければ欠けか重なりか見分けられないので「読めない」で返し、
    検品担当の目に回す（読めない足を通すと崩れが検品を逃れる）。動物図鑑のカピバラ 36 枚（どれも脚 4 本の絵）では
    4 本以上 17 枚、3 本 9 枚、1〜2 本 10 枚と読んだ。脚の欠けた絵の手本が無く、欠けを見つける割合はまだ測れていない"""
    got = quadruped(holes_open(image, drawn_mask(image)))["legs"]
    res = {"image": str(image) if not isinstance(image, Image.Image) else "", "legs": got, "expected": expected}
    if got >= expected:
        res.update(ok=True, readable=True)
    else:
        res.update(ok=False, readable=False, reason=f"脚が {got} 本しか読めない（{expected} 本のはず。重なりか欠けかを目で確かめる）")
    return res


def close_gaps(mask: np.ndarray, k: int) -> np.ndarray:
    """横に k 画素以下の隙間を埋める（横に広げてから縮める）"""
    from PIL import ImageFilter
    if k < 2:                 # 幅 1 の MaxFilter は浮動小数の例外でプロセスごと落ちた
        return mask
    im = Image.fromarray(mask.astype("uint8") * 255)
    size = k | 1
    im = im.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))
    return np.asarray(im) > 0


def drawn_mask(image) -> np.ndarray:
    """人物（動物）の範囲。image は絵の道か PIL の絵（アプリは描いた絵を道にせず渡す）"""
    sys.path.insert(0, str(Path(__file__).parent))
    if isinstance(image, Image.Image):
        import design
        return np.asarray(design.keep_largest(design.cut_background(image.convert("RGB"))).getchannel("A")) > 0
    import edit
    return np.asarray(edit.foreground(image)) > 0


def depth_mask(path: str) -> np.ndarray:
    """下絵は黒が何も無い所、明るいほど手前"""
    return np.asarray(Image.open(path).convert("L")) > 8


def judge(image: str, underlay: str = "") -> dict:
    got = count(drawn_mask(image))
    res = {"image": image, "legs": got["legs"]}
    if underlay:
        want = count(depth_mask(underlay))
        res["expected"] = want["legs"]
        if got["bottom"] < want["bottom"] * REACH:
            # 暗い脚が暗い背景と一緒に抜けると、足元が人物の範囲に入らない（アラクネ 3 回目）。数えずに戻す
            res.update(ok=False, reason="足元を読めない（描いた絵の足先が下絵より上で終わる）")
        else:
            res["ok"] = got["legs"] == want["legs"]
    return res


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--quadruped":
        print(json.dumps(quadruped_judge(sys.argv[2]), ensure_ascii=False))
    else:
        print(json.dumps(judge(*sys.argv[1:3]), ensure_ascii=False))
