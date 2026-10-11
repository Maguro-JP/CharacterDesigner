"""人の描き方の順番（ラフ → 線画 → 線の強弱 → 下塗り → 影 → 仕上げ）で絵を作る。docs/knowledge/drawing-process.md

  python3 tools/gen/handdraw.py run <元の絵> <出力フォルダ> [--guide <色を借りる絵>]

元の絵（ラフや模型の絵）から線を抜いて閉じ、強弱を付け、閉じた領域ごとに平らな色を置き、影を足して線を重ねる。
各段の絵を 1-lines.png … 5-final.png として残す（どの段で崩れたかを見るため）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))


def _grow(mask: np.ndarray, r: int) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype("uint8") * 255).filter(ImageFilter.MaxFilter(2 * r + 1))) > 127


def _shrink(mask: np.ndarray, r: int) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype("uint8") * 255).filter(ImageFilter.MinFilter(2 * r + 1))) > 127


def lines(src: str, gap: int = 2) -> np.ndarray:
    """線を抜いて閉じる。XDoG の線を gap 画素ぶん太らせてから細らせ（閉じる処理）、小さな切れ目を繋ぐ。
    線が閉じていないと、下塗りで隣の領域へ色が漏れる"""
    import imgproc
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        imgproc.lineart(src, f"{d}/l.png")
        line = np.asarray(Image.open(f"{d}/l.png")) < 128
    return _shrink(_grow(line, gap), max(gap - 1, 0)) | line


def person_mask(src: str) -> np.ndarray:
    import imgproc
    im = Image.open(src).convert("RGB")
    return imgproc._person_alpha(src, im)


def weight(line: np.ndarray, person: np.ndarray, light=(-1.0, -1.0)) -> np.ndarray:
    """線の強弱。外側の輪郭は太く（3画素）、内側の細部は細く（1画素）、影の側（光と反対）の輪郭はさらに太く（4画素）。
    人の描き手が「形の前後と重さ」を線で伝えるやり方を、外形からの距離と光の向きで近づける"""
    H, W = line.shape
    edge = person & ~_shrink(person, 3)            # 人物の外形の帯
    outer = line & _grow(edge, 2)
    inner = line & ~outer
    out = np.zeros_like(line)
    # 内側の線は細らせる（太いまま重ねると細部が黒く潰れた）。2画素以上の太さの所だけ1画素削る
    core = _shrink(inner, 1)                               # 3画素以上の太さの所の芯
    out |= core | (inner & ~_grow(core, 1))                 # 太い線は芯だけ、細い線はそのまま
    out |= _grow(outer, 1)                         # 外側は太く
    # 影の側: 外形の帯のうち、人物の重心から見て光と反対の向きにある所
    ys, xs = np.nonzero(person)
    if len(ys):
        cy, cx = ys.mean(), xs.mean()
        yy, xx = np.mgrid[0:H, 0:W]
        lx, ly = light
        dark_side = ((xx - cx) * -lx + (yy - cy) * -ly) > 0
        out |= _grow(outer & dark_side, 2)
    return out


def flats(line: np.ndarray, person: np.ndarray, guide: Image.Image, min_area: int = 30) -> np.ndarray:
    """閉じた領域ごとに平らな色を1つ置く（バケツ塗り）。色は guide の、その領域の中央値。
    人物の外は白。線の上は後で線を重ねるので、隣の色で埋める"""
    from collections import deque
    H, W = line.shape
    g = np.asarray(guide.convert("RGB").resize((W, H))).astype(int)
    out = np.full((H, W, 3), 255, dtype=np.uint8)
    seen = line.copy() | ~person
    labels = np.full((H, W), -1, dtype=np.int32)
    n = 0
    for y0 in range(H):
        for x0 in range(W):
            if seen[y0, x0]:
                continue
            comp, q = [], deque([(y0, x0)])
            seen[y0, x0] = True
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
            ys, xs = np.array(comp).T
            if len(comp) >= min_area:
                out[ys, xs] = np.median(g[ys, xs], axis=0).astype(np.uint8)
                labels[ys, xs] = n
                n += 1
            else:
                out[ys, xs] = g[ys, xs]   # 小さな隙間は元の色（ベタの点が浮かないように）
    # 線の下・小さな領域・人物の中の未塗りは、隣の大きな領域の色で埋める（細い領域が白く抜けた）。
    # 塗った所から外へ1画素ずつ色を広げる（最も近い塗った色で埋めるのと同じ）
    holes = person & (labels < 0)
    have = labels >= 0
    for _ in range(40):
        if not (holes & ~have).any():
            break
        grown = have.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(np.roll(have, dy, 0), dx, 1)
            col = np.roll(np.roll(out, dy, 0), dx, 1)
            take = holes & ~grown & src
            out[take] = col[take]
            grown |= take
        have = grown
    return out, n


def grisaille(value: np.ndarray, flat: np.ndarray, person: np.ndarray) -> np.ndarray:
    """グリザイユ: 灰色だけで明暗を描き込み、その上に色を重ねる（docs/knowledge/painting-workflow.md）。
    1. 明暗（value、0〜255 の灰色）を人物の中で 5〜95% に引き伸ばす（灰色の段で明暗を決め切る）
    2. 下塗りの色をオーバーレイで乗せる（明暗は灰色から、色相は下塗りから来る）
    3. もう一度、下塗りの色を 35% だけ普通に重ねて灰色っぽさを消す
    4. 明暗の上位 3% に加算で光を置く
    セル塗りは影を面で1段置くが、グリザイユは明暗が連続して残るので、立体の量感が出る"""
    v = value.astype(float)
    if person.any():
        lo, hi = np.percentile(v[person], 5), np.percentile(v[person], 95)
        v = ((v - lo) / max(hi - lo, 1) * 255).clip(0, 255)
    a, b = v[..., None] / 255, flat.astype(float) / 255
    over = np.where(a < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b)) * 255
    col = over * 0.65 + flat.astype(float) * 0.35
    if person.any():
        top = person & (v >= np.percentile(v[person], 97))
        glow = np.asarray(Image.fromarray(top.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(2))).astype(float)[..., None] / 255
        col = col + glow * 60
    out = np.where(person[..., None], col, flat.astype(float))
    return out.clip(0, 255).astype(np.uint8)


def regions_from_color(img: np.ndarray, person: np.ndarray, scale: float = 400, min_size: int = 300) -> np.ndarray:
    """下塗りの面を、元の絵の色の境目から取る。部位分けは鎧もスカートも1つの「ワンピース」にし、胸当てと肩当ての形が消えた。
    人の描き手は下描きで決めた形ごとに色を置く。明るさの違い（影と光）では分けず、色味の違いで分けたいので、
    Lab の明るさを 1/3 に弱めてから境目を探す（felzenszwalb。乱数を使わない）。人物の外は 0"""
    from skimage.color import rgb2lab
    from skimage.segmentation import felzenszwalb
    lab = rgb2lab(img)
    lab[..., 0] /= 3
    seg = felzenszwalb(lab, scale=scale, sigma=1.0, min_size=min_size) + 1
    return np.where(person, seg, 0)


def cel_from_original(img: np.ndarray, regions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """面ごとに、元の絵の明るさが面の中ほどより暗い所を影、それ以外を地の色にする（2段のアニメ塗り）。
    光の当たり方は元の絵が決めたまま残る。明るさの幅が小さい面（平らな面）には影を置かない。
    戻り値は（塗った絵, 影の所）"""
    out = img.copy()
    shadow = np.zeros(regions.shape, bool)
    lum = img.astype(float) @ np.array([0.299, 0.587, 0.114])
    for r in np.unique(regions):
        if r == 0:
            continue
        m = regions == r
        v = lum[m]
        mid = np.median(v)
        dark = m & (lum < mid)
        if np.percentile(v, 90) - np.percentile(v, 10) < 18 or dark.sum() < 20:
            out[m] = np.median(img[m], 0)
            continue
        out[m & ~dark] = np.median(img[m & ~dark], 0)
        out[dark] = np.median(img[dark], 0)
        shadow |= dark
    return out, shadow


def keep_folds(shaded: np.ndarray, original: np.ndarray, zone: np.ndarray, sigma: float = 6.0) -> np.ndarray:
    """元の絵に描かれたしわを、しわの場所（folds.zone）の中だけ仕上げに戻す。
    下塗りで面を平らにすると、元の絵のしわ（細かい明暗）が消える。人の描き手は、布が引かれ・寄る所のしわを描き、
    それ以外は省く（docs/knowledge/folds-and-lines.md）。元の明るさから大きな明暗（sigma でぼかしたもの）を引いた
    細かい明暗だけを、範囲の中で仕上げの明るさに足す。色相は仕上げのまま。範囲の縁はぼかして段を付けない"""
    from scipy.ndimage import gaussian_filter
    lum = original.astype(float) @ np.array([0.299, 0.587, 0.114])
    detail = lum - gaussian_filter(lum, sigma)
    soft = gaussian_filter(zone.astype(float), sigma)
    return (shaded.astype(float) + (detail * soft)[..., None]).clip(0, 255).astype(np.uint8)


def run(src: str, outdir: str, guide: str | None = None, style: str = "cel2", line_style: str = "default",
        brush: str | None = None, shadow_cut: float = 0.93, shadow_depth: float = 1.0,
        line_ink: float = 1.0, paint: str = "cel") -> dict:
    """paint は塗りの手順（cel: 影を面で1段置く、grisaille: 灰色の明暗に色を重ねる）。
    line_style は線の作風（casts/brushes.json の styles。chibi はデフォルメで太い線）。brush で筆を指定できる"""
    import imgproc
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    person = person_mask(src)
    # 人物の外の線（ラフの効果線・背景の当たり線）は清書に入れない。外形の線を残すため、人物を少し太らせた範囲で切る
    line = lines(src) & _grow(person, 4)
    Image.fromarray(np.where(line, 0, 255).astype("uint8")).save(out / "1-lines.png")
    strong = weight(line, person)
    Image.fromarray(np.where(strong, 0, 255).astype("uint8")).save(out / "2-weight.png")
    # 下塗りの境: 線だけでは閉じない所がある（機械技師の絵で体じゅうが1つの領域に繋がり、茶色1色になった）。
    # 人の描き手が部位ごとにレイヤーを分けるのと同じく、部位分けの境も塗り分けの境にする
    walls = line.copy()
    try:
        import edit
        lab = np.asarray(edit.parts(src).resize(line.shape[::-1], Image.NEAREST)).astype(int)
        border = np.zeros_like(line)
        border[:-1] |= lab[:-1] != lab[1:]
        border[:, :-1] |= lab[:, :-1] != lab[:, 1:]
        walls |= border & person
    except Exception:
        pass
    flat, regions = flats(walls, person, Image.open(guide or src))
    Image.fromarray(flat).save(out / "3-flats.png")
    # 影: 立体の計算（imgproc.shade）で暗くなった所だけを「影の面」として取り、下塗りの色ごとに1段暗い影色を平らに置く。
    # 計算の明暗をそのまま掛けると、下塗りとほぼ同じに見えた（段が無い）。人の影は面で置く
    imgproc.shade(str(out / "3-flats.png"), str(out / "4-calc.png"), style=style)
    calc = np.asarray(Image.open(out / "4-calc.png").convert("L")).astype(float)
    base = np.asarray(Image.fromarray(flat).convert("L")).astype(float)
    shadow = person & (calc < base * shadow_cut)
    shadow = _shrink(_grow(shadow, 2), 2)            # 細かい斑を面にまとめる
    shaded = flat.astype(float).copy()
    tint = 1 - (1 - np.array([0.62, 0.60, 0.80])) * shadow_depth   # 影は寒色寄りに落とす（黒を混ぜると濁る）
    # 影の境目だけ馴染ませる: 影の面の縁を細くぼかして掛ける（アニメ塗りは境目を残すので 1.5 画素だけ）
    soft = np.asarray(Image.fromarray(shadow.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(1.5))).astype(float)[..., None] / 255
    shaded = shaded * (1 - soft) + shaded * tint * soft
    if paint == "cel":
        # 上の下塗りと影は、部位分けの粗い面と、絵とは別の明暗の計算から作るので、元の絵の形と光を捨てていた
        # （騎士で胸当てと肩当てが1つの灰色になり、大きな明暗の差 26.1）。元の絵の色の境目で面を取り、
        # 面の中で元の絵が暗い所を影にすると、形と光が残る（騎士 11.4、魔女 5.3 と 7.4。docs/knowledge/painting-workflow.md）
        base_img = np.asarray(Image.open(guide or src).convert("RGB").resize(shadow.shape[::-1]))
        reg = regions_from_color(base_img, person)
        cel, shadow = cel_from_original(base_img, reg)
        flat = np.where(person[..., None], cel, 255).astype(np.uint8)
        regions = int(len(np.unique(reg)) - 1)
        Image.fromarray(flat).save(out / "3-flats.png")
        shaded = flat.astype(float)
    if paint == "grisaille":
        g0v = np.asarray(Image.open(src).convert("L").resize(shadow.shape[::-1])).astype(float)
        Image.fromarray(g0v.astype(np.uint8)).save(out / "4-value.png")
        shaded = grisaille(g0v, flat, person).astype(float)
    Image.fromarray(shaded.clip(0, 255).astype(np.uint8)).save(out / "4-shade.png")
    # 色を重ねる（オーバーレイ）: 光源の側（左上）を暖かく、反対側を冷たく。人の描き手が最後に掛ける色味の層
    Hh, Ww = shadow.shape
    yy, xx = np.mgrid[0:Hh, 0:Ww]
    # 光源の向きは元の絵から決める: 人物の中で明るい所の重心から暗い所の重心へ向かう向きの反対が光の来る側
    g0 = np.asarray(Image.open(src).convert("L").resize((Ww, Hh))).astype(float)
    pv = g0[person]
    py, px = yy[person], xx[person]
    hi, lo = pv >= np.percentile(pv, 75), pv <= np.percentile(pv, 25)
    ly, lx = py[hi].mean() - py[lo].mean(), px[hi].mean() - px[lo].mean()
    n = max((ly ** 2 + lx ** 2) ** 0.5, 1e-6)
    ly, lx = ly / n, lx / n
    side = (lx * (xx - px.mean()) / Ww + ly * (yy - py.mean()) / Hh) * 2   # 光の側ほど大きい
    warm = np.array([1.0, 0.55, 0.25]) * 255
    cool = np.array([0.25, 0.4, 1.0]) * 255
    tone = np.where(side[..., None] > 0, warm, cool)
    k = (np.abs(side)[..., None] * 0.18 * person[..., None])
    def overlay(a, b):
        a, b = a / 255, b / 255
        return np.where(a < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b)) * 255
    shaded = shaded * (1 - k) + overlay(shaded, tone) * k
    # ハイライト（加算）: 影でない所のうち、光源の側の外形の縁に細い光
    rim = person & ~_shrink(person, 3) & (side > 0.05) & ~shadow
    hl = np.asarray(Image.fromarray(rim.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(1))).astype(float)[..., None] / 255
    shaded = shaded + hl * 70
    shaded = shaded.clip(0, 255).astype(np.uint8)
    Image.fromarray(shaded).save(out / "4-light.png")
    # しわ: 布が引かれ・寄る場所（曲げた肘・膝、脇、腰からの裾）を関節から決め、そこでだけ元の絵のしわを戻す。
    # 関節が取れない絵（デフォルメでマントに隠れた体など）では戻さない（デフォルメはしわを減らす）
    try:
        import edit
        import folds
        import joints
        lab_f = np.asarray(edit.parts(src).resize(shaded.shape[1::-1], Image.NEAREST))
        orig_f = np.asarray(Image.open(src).convert("RGB").resize(shaded.shape[1::-1]))
        pts = joints.find(src)
        found = folds.sites(pts, lab_f, orig_f)
        if found:
            z = folds.zone(found, pts, np.isin(lab_f, folds.CLOTH) & ~folds.metal_mask(orig_f, np.isin(lab_f, folds.CLOTH)))
            shaded = keep_folds(shaded, orig_f, z)
            Image.fromarray((z * 255).astype("uint8")).save(out / "4-fold-zone.png")
    except Exception as e:
        print(f"しわの場所が決められない: {e}", file=sys.stderr)
    Image.fromarray(shaded).save(out / "4-folds.png")
    # 線: 墨で重ねる。暗い面の上では墨が沈んで見えないので、下の色を明るくした色の線にする（色トレスの考え方）
    lum = np.asarray(Image.fromarray(shaded).convert("L")).astype(float)
    # 線は筆跡としてブラシで引き直す（brushes.py）。外形の筆跡は太く。暗い面の上は下の色を明るくした線（色トレス）
    import brushes
    st = brushes.table()["styles"].get(line_style, brushes.table()["styles"]["default"])
    paths = brushes.strokes(strong)
    edge = _grow(person & ~_shrink(person, 3), 3)
    weights = [1.5 if np.mean([edge[y, x] for y, x in p]) > 0.5 else 1.0 for p in paths]
    layer = np.asarray(brushes.render(line.shape[::-1], paths, brush or st["brush"], st["line_scale"], weights)).astype(float)
    a = layer[..., 3:] / 255
    # 筆跡にならなかった短い線（目・口・まつ毛など顔の細い線）は、元の線を細いまま残す（ブラシで引き直すと抜け落ちた）
    left = strong & (a[..., 0] < 0.2)
    a = np.maximum(a, (left * 0.85)[..., None])
    ink = np.where((lum < 70)[..., None], (shaded.astype(float) * 1.9 + 50).clip(0, 255), np.array([40, 30, 40], dtype=float))
    # 線の濃さ: 1 なら墨、小さいほど下の面の色の濃い色に寄せる（色トレス）。調整の往復で、明暗が細切れなら線を面に馴染ませる
    ink = ink * line_ink + shaded.astype(float) * 0.55 * (1 - line_ink)
    shaded = (shaded.astype(float) * (1 - a) + ink * a).clip(0, 255).astype(np.uint8)
    # 目は人の描き手も最後に別に描く（講座でも「目の線画は後の工程で描く」）。顔の部位の中の目の周りだけ、元の絵の描き込みを戻す
    try:
        import edit
        lab = np.asarray(edit.parts(src).resize(shaded.shape[1::-1], Image.NEAREST))
        face = _shrink(lab == 11, 4)
        if face.any():
            ys, xs = np.nonzero(face)
            top, bot = ys.min(), ys.max()
            eyes = face & (np.arange(face.shape[0])[:, None] > top + (bot - top) * 0.30) & \
                (np.arange(face.shape[0])[:, None] < top + (bot - top) * 0.62)
            soft = np.asarray(Image.fromarray(eyes.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(3))).astype(float)[..., None] / 255
            orig = np.asarray(Image.open(src).convert("RGB")).astype(float)
            shaded = (shaded.astype(float) * (1 - soft) + orig * soft).clip(0, 255).astype(np.uint8)
    except Exception:
        pass   # 部位分けが使えないときは戻さない（線だけで描いた目のまま）
    Image.fromarray(shaded).save(out / "5-final.png")
    return {"regions": regions, "line_ratio": round(float(line.mean()), 4), "weighted_ratio": round(float(strong.mean()), 4)}


def adjust(src: str, outdir: str, tries: int = 3, **kw) -> dict:
    """調整の往復: 仕上げを縮めて明暗の塊（notan）を測り、細切れなら影の面を広く深くしてやり直す。人の描き手が
    縮めて全体を見ては影を足し直すのと同じ。上限 tries 回。一番まとまった回を outdir に残す"""
    import imgproc
    import shutil
    import tempfile
    best = None
    cut, depth, ink = kw.pop("shadow_cut", 0.93), kw.pop("shadow_depth", 1.0), kw.pop("line_ink", 1.0)
    history = []
    for k in range(tries):
        tmp = tempfile.mkdtemp()
        r = run(src, tmp, shadow_cut=cut, shadow_depth=depth, line_ink=ink, **kw)
        m = imgproc.notan(f"{tmp}/5-final.png", f"{tmp}/notan.png")
        history.append({"try": k, "line_ink": round(ink, 2), "fragment_ratio": m["fragment_ratio"]})
        if best is None or m["fragment_ratio"] < best[0]:
            if best:
                shutil.rmtree(best[1], ignore_errors=True)
            best = (m["fragment_ratio"], tmp, r)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
        if m["fragment_ratio"] <= 0.08:
            break
        # 段ごとに測ると、細切れを一番増やすのは線だった（騎士: ざらつきまで 0.087、線を重ねて 0.131）。
        # 影の広さと深さはほとんど効かなかったので、線を面の色に馴染ませる（色トレスに寄せる）
        ink = ink * 0.6
    shutil.copytree(best[1], outdir, dirs_exist_ok=True)
    shutil.rmtree(best[1], ignore_errors=True)
    return {**best[2], "history": history}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("src"); r.add_argument("out"); r.add_argument("--guide", default=None); r.add_argument("--style", default="cel2")
    r.add_argument("--line-style", default="default"); r.add_argument("--brush", default=None)
    r.add_argument("--paint", default="cel", choices=["cel", "grisaille"])
    r.add_argument("--adjust", type=int, default=0, help="調整の往復の上限回数（0 なら1回だけ描く）")
    a = ap.parse_args()
    print(json.dumps(adjust(a.src, a.out, a.adjust, guide=a.guide, style=a.style, line_style=a.line_style, brush=a.brush, paint=a.paint)
                     if a.adjust else run(a.src, a.out, a.guide, a.style, a.line_style, a.brush, paint=a.paint), ensure_ascii=False))
