"""線画を最初に描く（人の描き手と同じ順番: 線画 → 色）。

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
    """線で閉じた面ごとに、参考の絵の真ん中の色を1色ずつ塗る（人の描き手の下塗りと同じ単位）。
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
