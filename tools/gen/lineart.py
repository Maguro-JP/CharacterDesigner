"""線画を最初に描かせる（そのあとに色を置く）。

元の絵（塗りの絵）から線を取り出すと、影の境目や髪の陰影まで線に拾い、線が二重になったり途切れたりした
（XDoG、色の境目、墨の線の拾い出し、模型での描き直し 0.55〜0.88 を騎士で比べた。docs/knowledge/lineart.md）。
塗りの絵はもともと線画を持たないので、取り出すのでなく、最初から線画として描かせる。

  python3 tools/gen/lineart.py draw "1girl, knight, plate armor, ..." OUTDIR [--count 2] [--seed 3]
  python3 tools/gen/lineart.py clean IN.png OUT.png        # 灰色の陰影を除き、黒い線と白い地だけにする
  python3 tools/gen/lineart.py ends IN.png                 # 線の切れ端の数（少ないほど線が閉じている）
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PREFIX = "monochrome, greyscale, lineart, clean lineart, white background, no shading, "
NEGATIVE = "color, shading, gradient, screentone, sketch, rough, grey background"


def draw(prompt: str, outdir: str, count: int = 2, seed: int = 3) -> list[str]:
    sys.path.insert(0, str(Path(__file__).parent))
    import free_text
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    names = free_text.draw(PREFIX + prompt, NEGATIVE, out, seed=seed, count=count)
    for n in names:
        p = out / n
        clean(str(p), str(p.with_name(p.stem + "-line.png")))
    return names


def clean(src: str, out: str, width: int = 8, contrast: float = 0.10, solid: float = 0.25, dark: float = 0.45) -> dict:
    """灰色の陰影を除き、黒い線と白い地だけにする。
    明るさのしきい値で切ると、薄く細い線（目・瞳）が消え、顔の影が黒い塊になった。線は細く周りより暗く、
    影は広く暗いので、細さで見分ける: 半径 width の範囲で一番明るい所より contrast 以上暗い細い所を線にする（black top-hat）。
    地の solid 倍より暗い所はベタ（黒く塗りつぶす所）として残す。
    width が線の太さより狭いと、太い線の中が抜けて二重の線になった（半径 4 でランタンの枠と袖の外形）。
    半径を 8 にし、地の dark 倍より暗い所も線に含めて、太い線の中を埋める"""
    from skimage.morphology import black_tophat, disk
    g = np.asarray(Image.open(src).convert("L")).astype(float)
    edge = np.concatenate([g[:8].ravel(), g[-8:].ravel(), g[:, :8].ravel(), g[:, -8:].ravel()])
    paper = max(float(np.median(edge)), 1.0)
    v = g / paper
    thin = black_tophat(v, disk(width))            # 細い所の、周りとの暗さの差
    ink = np.clip((thin - contrast) / contrast, 0, 1)
    ink = np.maximum(ink, np.clip((solid + 0.05 - v) / 0.1, 0, 1))
    ink = np.maximum(ink, np.clip((dark + 0.05 - v) / 0.1, 0, 1) * (thin > contrast / 2))
    res = (255 * (1 - ink)).astype(np.uint8)
    Image.fromarray(res).save(out)
    return {"paper": round(paper, 1), "line_ratio": round(float((ink > 0.5).mean()), 4)}


def flat_fill(line: np.ndarray, reference: np.ndarray, close: int = 1, min_area: int = 30) -> tuple[np.ndarray, int]:
    """線で閉じた面ごとに、参考の絵の真ん中の色を1色ずつ塗る。
    線画を下絵に色を描かせると、白い地が勝って色がほとんど乗らなかった（強さ 0.6、0.75）。強く描かせた参考の絵は
    形が線とずれるので、そのまま重ねると色が線をはみ出す。面は線画から取り、色だけを参考から借りる。
    line は 0〜255 の線画（黒が線）、reference は同じ大きさの RGB。線の小さな切れ目は close 画素だけ太らせて閉じる。
    min_area より小さい面（線の間の隙間）は隣の色で埋める。戻り値は（塗った絵、面の数）"""
    from scipy import ndimage as nd
    ink = line < 128
    if close:
        ink = nd.binary_dilation(ink, iterations=close)
    lab, n = nd.label(~ink)
    size = np.bincount(lab.ravel(), minlength=n + 1)
    keep = np.nonzero(size >= min_area)[0]
    keep = keep[keep > 0]
    table = np.zeros((n + 1, 3), np.uint8)
    for c in range(3):
        table[keep, c] = np.asarray(nd.median(reference[..., c], lab, keep)).round().astype(np.uint8)
    filled = np.isin(lab, keep)
    out = table[lab]
    # 線の下と小さな面は、いちばん近い塗った面の色にする（線を重ねたとき縁に白い隙間を残さない）
    idx = nd.distance_transform_edt(~filled, return_distances=False, return_indices=True)
    out = out[idx[0], idx[1]]
    lines = (line.astype(float) / 255)[..., None]
    return (out.astype(float) * lines).astype(np.uint8), int(n)


def middle_color(pixels: np.ndarray) -> np.ndarray:
    """画素の中で、明るさが真ん中の画素の色。赤・緑・青を別々に真ん中を取ると、白と橙が混ざった所で
    どちらでもない灰色になった（技師の作業着）。実際にある色から選ぶ"""
    lum = pixels.astype(float) @ np.array([0.299, 0.587, 0.114])
    return pixels[np.argsort(lum)[len(lum) // 2]]


def color_by_parts(line: np.ndarray, line_parts: np.ndarray, reference: np.ndarray, ref_parts: np.ndarray,
                   close: int = 1, min_area: int = 30, window: float = 0.06) -> np.ndarray:
    """線で閉じた面ごとに、参考の絵の「同じ部位の、同じあたり」の色を塗る。
    参考を線画から描かせると白い地に引っ張られて色が薄く、位置で色を拾うと形のずれで顔に髪の色が乗った。
    参考は線画と別に色付きで描かせ（形は違ってよい）、部位分け（顔・髪・上着・ズボンなど）で対応を取る。
    面の部位は面の中で一番多い部位。部位の外接枠の中での面の位置（0〜1）を、参考の同じ部位の枠に写し、
    その周り（枠の window 倍）にある同じ部位の色の真ん中を取る。周りに無ければ部位全体の真ん中。人物の外は白"""
    from scipy import ndimage as nd
    ink = line < 128
    if close:
        ink = nd.binary_dilation(ink, iterations=close)
    lab, n = nd.label(~ink)
    # 線が閉じていない所（騎士の顔と髪のあいだ）では、顔と髪が1つの面につながり、多い方の髪の色で顔を塗った。
    # 線で閉じた面を、さらに部位の境目でも分ける
    # ただし服の部位どうしの境目は布の上で細かく揺れ、マントがまだらに割れたので、分けるのは髪・顔・肌と、それ以外の境目だけ
    kind = np.zeros(256, np.int64)
    kind[[2]] = 1                     # 髪
    kind[[11]] = 2                    # 顔
    kind[[12, 13, 14, 15]] = 3        # 脚・腕の肌
    k8 = kind[line_parts]
    # 小さな切れ端（線の面の 15% 未満か 400 画素未満）は分けず、面の多い方にまとめる（襟巻きの上の顔・腕の切れ端が肌色の点になった）
    base = lab.astype(np.int64) * 8
    piece = base + k8
    _, pinv, pcnt = np.unique(piece, return_inverse=True, return_counts=True)
    psize = pcnt[pinv].reshape(lab.shape)
    lsize = np.bincount(lab.ravel())[lab]
    major = np.zeros(lab.max() + 1, np.int64)
    for kk in range(4):
        cnt = np.bincount(lab[k8 == kk].ravel(), minlength=lab.max() + 1)
        better = cnt > np.bincount(lab[k8 == major[lab]].ravel(), minlength=lab.max() + 1) if kk else None
        major = np.where(better, kk, major) if kk else major
    small = (psize < np.maximum(400, 0.15 * lsize))
    k8 = np.where(small, major[lab], k8)
    key = base + k8
    key[lab == 0] = 0
    _, inv = np.unique(key, return_inverse=True)
    lab = inv.reshape(lab.shape)
    n = int(lab.max())
    size = np.bincount(lab.ravel(), minlength=n + 1)
    H, W = line.shape
    yy, xx = np.mgrid[0:H, 0:W]
    out = np.full((H, W, 3), 255, np.uint8)
    # 同じ物でも、線画と参考で別の部位に分けられることがある（技師の作業着が線画では「ズボン」、参考では「ワンピース」。
    # 参考では右の靴しか取れない）。同じ部位が参考に無いときは、仲間の部位（服どうし、左右どうし）から色を取る
    groups = [(4, 5, 6, 7), (9, 10), (12, 13), (14, 15)]
    boxes, whole, refmask = {}, {}, {}
    for k in np.unique(line_parts):
        if k == 0:
            continue
        rm = ref_parts == k
        # 参考に数画素だけある部位も無いと数える（技師の参考に「ズボン」が 204 画素だけあり、その灰色で作業着を塗った）
        if rm.sum() <= 500:
            g = next((g for g in groups if k in g), (k,))
            # 仲間のうち、線画で使われていない部位を優先する（線画の「ズボン」と参考の「ワンピース」を組にする）。
            # 仲間をまとめて使うと、白いシャツと橙の作業着が混ざった
            # 線画に数画素だけある部位は使われていないと数える（技師の線画にワンピースが数画素あり、組が作れなかった）
            spare = [j for j in g if (ref_parts == j).sum() > 500 and (line_parts == j).sum() <= 500]
            if spare:
                rm = ref_parts == max(spare, key=lambda j: (ref_parts == j).sum())
            else:
                rm = np.isin(ref_parts, g)
        if not rm.any():
            continue
        ys, xs = np.nonzero(line_parts == k)
        ry, rx = np.nonzero(rm)
        boxes[k] = ((ys.min(), ys.max(), xs.min(), xs.max()), (ry.min(), ry.max(), rx.min(), rx.max()))
        whole[k] = middle_color(reference[rm])
        refmask[k] = rm
    objs = nd.find_objects(lab)
    painted = np.zeros(n + 1, bool)
    for r in range(1, n + 1):
        if size[r] < min_area or objs[r - 1] is None:
            continue
        sl = objs[r - 1]
        m = lab[sl] == r
        parts_here = line_parts[sl][m]
        k = int(np.bincount(parts_here).argmax())
        if k == 0:
            painted[r] = True            # 人物の外は白で塗り終えたものとする（隣の色で埋めると背景まで色が付いた）
            continue
        if k not in boxes:
            continue
        (y0, y1, x0, x1), (Y0, Y1, X0, X1) = boxes[k]
        cy, cx = yy[sl][m].mean(), xx[sl][m].mean()
        ty = Y0 + (cy - y0) / max(y1 - y0, 1) * (Y1 - Y0)
        tx = X0 + (cx - x0) / max(x1 - x0, 1) * (X1 - X0)
        ry, rx = max(int((Y1 - Y0) * window), 3), max(int((X1 - X0) * window), 3)
        a0, a1, b0, b1 = int(max(ty - ry, 0)), int(min(ty + ry + 1, H)), int(max(tx - rx, 0)), int(min(tx + rx + 1, W))
        pick = refmask[k][a0:a1, b0:b1]
        col = middle_color(reference[a0:a1, b0:b1][pick]) if pick.sum() >= 5 else whole[k]
        out[sl][m] = col
        painted[r] = True
    # 色を取る先が無い面（参考では脚がスカートとタイツで隠れ、「脚」が無い）は塗らずに残し、隣の面の色で埋める。
    # 白のまま塗り終えたと数えると、スカートの中に白い斑点が残った
    filled = (lab > 0) & (size[lab] >= min_area) & painted[lab]
    idx = nd.distance_transform_edt(~filled, return_distances=False, return_indices=True)
    out = out[idx[0], idx[1]]
    return (out.astype(float) * (line.astype(float) / 255)[..., None]).astype(np.uint8)


def ends(src: str) -> dict:
    """線の切れ端（骨組みにしたときに隣が1つしか無い点）の数。閉じた線画ほど少ない"""
    from skimage.morphology import skeletonize
    ink = np.asarray(Image.open(src).convert("L")) < 128
    sk = skeletonize(ink)
    n = sum(np.roll(np.roll(sk, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - sk
    tips = int((sk & (n == 1)).sum())
    return {"ends": tips, "length": int(sk.sum()), "ends_per_1000": round(tips / max(sk.sum(), 1) * 1000, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("prompt"); d.add_argument("out"); d.add_argument("--count", type=int, default=2); d.add_argument("--seed", type=int, default=3)
    c = sub.add_parser("clean")
    c.add_argument("src"); c.add_argument("out")
    e = sub.add_parser("ends")
    e.add_argument("src")
    a = ap.parse_args()
    r = {"draw": lambda: draw(a.prompt, a.out, a.count, a.seed), "clean": lambda: clean(a.src, a.out),
         "ends": lambda: ends(a.src)}[a.cmd]()
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
