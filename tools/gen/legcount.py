"""床に着いた脚の本数を数え、下絵（奥行き）の本数と突き合わせる。

読み取りの模型（tagger）は「しっぽが有る」は読めるが、本数は読めなかった（docs/ROADMAP.md 0.56）。
ケンタウロスの 4 本・アラクネの 8 本・ハーピーの 2 本は、体の一番下の帯を横に切ったとき、
人物の範囲が何か所に分かれるか（切れ目の数）で数えられる。下絵も同じ方法で数えれば、種族ごとの正解を書かずに済む。

使い方: python3 tools/gen/legcount.py <絵.png> [<下絵.png>]
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


def close_gaps(mask: np.ndarray, k: int) -> np.ndarray:
    """横に k 画素以下の隙間を埋める（横に広げてから縮める）"""
    from PIL import ImageFilter
    if k < 2:                 # 幅 1 の MaxFilter は浮動小数の例外でプロセスごと落ちた
        return mask
    im = Image.fromarray(mask.astype("uint8") * 255)
    size = k | 1
    im = im.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))
    return np.asarray(im) > 0


def drawn_mask(path: str) -> np.ndarray:
    sys.path.insert(0, str(Path(__file__).parent))
    import edit
    return np.asarray(edit.foreground(path)) > 0


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
    print(json.dumps(judge(*sys.argv[1:3]), ensure_ascii=False))
