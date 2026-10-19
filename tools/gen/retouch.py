"""写真の補正の技術を、イラストの仕上げに使う（バリ取り・フリンジ除去・色かぶり補正など）。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/retouch.py auto in.png out.png [--preset illust|photo]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/retouch.py <工程> in.png out.png       # 1 つだけ掛ける
  PYTHONPATH=.cache/gen/lib python3 tools/gen/retouch.py measure in.png               # 数字だけ

工程（写真の現像で掛ける順）と、それぞれが良くしたかを測る数字:

| 工程 | 写真での意味 | イラストでの使い道 | 数字（小さいほど良い） |
|---|---|---|---|
| heal | ごみ・センサーの汚れ消し | 線から離れた黒い粒（AI の描き残し）を消す | specks（小さな暗い粒の数） |
| denoise | ノイズ除去（縁を残す） | 塗りのざらつき・JPEG の濁り | noise（平らな所の揺れ） |
| white_balance | 色かぶり補正 | 全体が黄色・青に寄った絵を戻す | cast（灰色の所の色の偏り） |
| levels | 露出・レベル補正 | 眠い（白が白でない・黒が黒でない）絵を締める | flat（明るさの幅の不足） |
| dehaze | かすみ除去 | 白っぽく霞んだ絵（hires の後に出やすい） | haze（最も暗い色の明るさ） |
| local_contrast | 部分の明暗差を上げる | 眠い陰影を立てる（強く掛けない） | flat |
| defringe | 色収差・フリンジ除去 | 線の縁の紫・緑のにじみ（拡大で出る） | fringe（縁の紫・緑の割合） |
| deburr | 輪郭のバリ取り | 人物の輪郭から細く飛び出した毛羽・欠け | burrs（輪郭の小さな出っ張りと欠けの数） |
| dejag | ジャギー消し（アンチエイリアス） | 線の縁の階段 | jaggy（線の縁の折れの多さ） |
| sharpen | アンシャープマスク | 拡大でぼけた線を締める（明るさだけ） | blur（縁の急さの不足） |

どの工程も、掛けたあとで自分の数字が良くなり、絵の形（縮めた明るさ）が変わりすぎていないときだけ採る。
採らなかった工程と理由は結果に残す。良くなったと言えない補正を、掛けたことにしない。
顔（部位分けの 11）は線が細かく崩れやすいので、heal・dejag・deburr は触らない。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))

DRIFT = 0.02        # 工程ごとに許す形の変わり方（縮めた明るさの相関を 1 から引いたもの）
FACE = 11


# ---- 数字 ----

def _lum(a: np.ndarray) -> np.ndarray:
    return (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114) / 255.0


def _chroma(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """YCbCr の色の 2 軸（-128〜128）"""
    cb = -0.168736 * a[..., 0] - 0.331264 * a[..., 1] + 0.5 * a[..., 2]
    cr = 0.5 * a[..., 0] - 0.418688 * a[..., 1] - 0.081312 * a[..., 2]
    return cb, cr


def _grad(L: np.ndarray) -> np.ndarray:
    from scipy.ndimage import sobel
    return np.hypot(sobel(L, 0), sobel(L, 1))


def cast(a: np.ndarray) -> float:
    """灰色に近い所（色の薄い所）の色の偏りの大きさ。白・灰・黒が色付いていると大きい"""
    cb, cr = _chroma(a)
    sat = np.hypot(cb, cr)
    near = sat < np.quantile(sat, 0.25)
    if near.sum() < 100:
        return 0.0
    return float(np.hypot(cb[near].mean(), cr[near].mean()))


def flat(a: np.ndarray) -> float:
    """明るさの幅の不足（1 - 1%〜99% の幅）。白が白でなく黒が黒でない眠い絵で大きい"""
    L = _lum(a)
    lo, hi = np.quantile(L, [0.01, 0.99])
    return float(1 - (hi - lo))


def haze(a: np.ndarray, size: int = 15) -> float:
    """暗いチャンネル（局所の最も暗い色）の中央値。霞んだ絵ほど黒が浮いて大きい"""
    from scipy.ndimage import minimum_filter
    dark = minimum_filter(a.min(2), size=size) / 255.0
    return float(np.median(dark))


def noise(a: np.ndarray) -> float:
    """平らな所（縁の無い所）の明るさの揺れ（0〜255 の標準偏差）"""
    from scipy.ndimage import uniform_filter
    L = _lum(a) * 255
    g = _grad(L / 255)
    flat_ = g < np.quantile(g, 0.5)
    resid = L - uniform_filter(L, 5)
    return float(resid[flat_].std()) if flat_.any() else 0.0


def fringe(a: np.ndarray) -> float:
    """強い縁の上で、紫・緑に色付いた画素の割合（千分率）。拡大や圧縮で線の縁に出るにじみ"""
    L = _lum(a)
    edge = _grad(L) > 0.25
    if edge.sum() < 50:
        return 0.0
    cb, cr = _chroma(a)
    purple = (cb > 18) & (cr > 8)
    green = (cb < -12) & (cr < -12)
    return float(((purple | green) & edge).sum() / edge.sum() * 1000)


def _figure(a: np.ndarray, far: float = 40.0) -> np.ndarray:
    """背景（四隅の色）から離れた所を人物の形とする"""
    corners = np.stack([a[2, 2], a[2, -3], a[-3, 2], a[-3, -3]])
    bg = np.median(corners, 0)
    return np.abs(a - bg).sum(2) > far


def burrs(a: np.ndarray, r: int | None = None) -> int:
    """輪郭の小さな出っ張り（細く飛び出した毛羽）と欠け（細い切れ込み）の数"""
    from scipy.ndimage import binary_closing, binary_opening, label
    m = _figure(a)
    r = r or max(2, round(min(a.shape[:2]) / 400))
    k = np.ones((2 * r + 1, 2 * r + 1), bool)
    spur = m & ~binary_opening(m, k)
    notch = binary_closing(m, k) & ~m
    return int(label(spur)[1] + label(notch)[1])


def _line(a: np.ndarray) -> np.ndarray:
    import cleanup
    return cleanup.line_mask(a)


def jaggy(a: np.ndarray) -> float:
    """線の縁の折れの多さ: 線の縁の画素のうち、縦横の向きが急に入れ替わる所の割合（千分率）"""
    m = _line(a)
    if m.sum() < 100:
        return 0.0
    edge = m & ~np.pad(m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:], 1)
    # 縁の画素で、左右と上下の両方に縁が続く（L 字の角）を折れと数える
    h = edge[:, 1:] & edge[:, :-1]
    v = edge[1:] & edge[:-1]
    corner = np.zeros_like(edge)
    corner[1:, 1:] = h[1:, :] & v[:, 1:]
    return float(corner.sum() / max(1, edge.sum()) * 1000)


def specks(a: np.ndarray) -> int:
    import cleanup
    return cleanup.measure("", a, np.zeros(a.shape[:2], np.uint8))["specks"]


def blur(a: np.ndarray) -> float:
    """縁の急さの不足（1 / 上位 1% の縁の強さ）。ぼけた線ほど大きい"""
    g = _grad(_lum(a))
    return float(1 / max(1e-6, np.quantile(g, 0.99)))


METRIC = {"heal": specks, "denoise": noise, "white_balance": cast, "levels": flat, "dehaze": haze,
          "local_contrast": flat, "defringe": fringe, "deburr": burrs, "dejag": jaggy, "sharpen": blur}


def measure(a: np.ndarray) -> dict:
    fns = {"specks": specks, "noise": noise, "cast": cast, "flat": flat, "haze": haze, "fringe": fringe,
           "burrs": burrs, "jaggy": jaggy, "blur": blur}
    return {k: round(float(f(a)), 4) for k, f in fns.items()}


# ---- 工程 ----

def heal(a: np.ndarray, protect: np.ndarray | None = None) -> np.ndarray:
    """線から離れた小さな暗い粒を、周りの塗りの中央値で埋める（スポット修復）"""
    import cleanup
    from scipy.ndimage import label, median_filter
    m = cleanup.line_mask(a)
    lab, _ = label(m, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    sizes[0] = cleanup.SPECK
    dirt = sizes[lab] < cleanup.SPECK
    # 線の近くの小さな塊は、毛先や線のかすれの切れ端なので消さない（消すと髪の束が点線になった）。離れた粒だけを消す
    from scipy.ndimage import distance_transform_edt
    far = distance_transform_edt(~(m & ~dirt)) > ISOLATED
    dirt &= far
    if protect is not None:
        dirt &= ~protect
    fill = np.stack([median_filter(a[..., c], size=9) for c in range(3)], -1)
    out = a.copy()
    out[dirt] = fill[dirt]
    return out


def _guided(I: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """ガイド付きフィルター（He ほか 2010）。I の縁を保ったまま p をならす"""
    from scipy.ndimage import uniform_filter
    s = 2 * r + 1
    mI, mp = uniform_filter(I, s), uniform_filter(p, s)
    cov = uniform_filter(I * p, s) - mI * mp
    var = uniform_filter(I * I, s) - mI * mI
    A = cov / (var + eps)
    b = mp - A * mI
    return uniform_filter(A, s) * I + uniform_filter(b, s)


def denoise(a: np.ndarray, r: int = 3, eps: float = 2e-3) -> np.ndarray:
    """縁を残してざらつきを消す（明るさをガイドにしたガイド付きフィルター）"""
    L = _lum(a)
    return np.stack([_guided(L, a[..., c] / 255, r, eps) * 255 for c in range(3)], -1)


def white_balance(a: np.ndarray, strength: float = 0.8) -> np.ndarray:
    """色の薄い所が灰色になるよう、3 色の掛け率を合わせる（グレーワールドを無彩色の所だけで行う）"""
    cb, cr = _chroma(a)
    sat = np.hypot(cb, cr)
    near = sat < np.quantile(sat, 0.25)
    if near.sum() < 100:
        return a
    mean = a[near].mean(0)
    gain = mean.mean() / np.maximum(mean, 1)
    gain = 1 + (gain - 1) * strength
    return a * gain


def levels(a: np.ndarray, lo: float = 0.005, hi: float = 0.995) -> np.ndarray:
    """明るさの下端と上端を黒と白へ伸ばす。色相を保つため 3 色に同じ変換を掛ける"""
    L = _lum(a) * 255
    l0, l1 = np.quantile(L, [lo, hi])
    if l1 - l0 < 10:
        return a
    return (a - l0) * (255 / (l1 - l0))


def dehaze(a: np.ndarray, size: int = 15, omega: float = 0.8, t0: float = 0.4) -> np.ndarray:
    """暗いチャンネルの事前知識（He ほか 2009）で霞を引く。大気の色は暗いチャンネルの明るい所から取る"""
    from scipy.ndimage import minimum_filter
    x = a / 255
    dark = minimum_filter(x.min(2), size=size)
    top = dark >= np.quantile(dark, 0.999)
    A = x[top].mean(0)
    t = 1 - omega * minimum_filter((x / np.maximum(A, 1e-3)).min(2), size=size)
    t = _guided(_lum(a), t, 20, 1e-3)
    t = np.clip(t, t0, 1)[..., None]
    return ((x - A) / t + A) * 255


def local_contrast(a: np.ndarray, amount: float = 0.3, clip: float = 0.01) -> np.ndarray:
    """局所の明暗差を上げる（CLAHE を明るさだけに掛け、amount で元と混ぜる）"""
    from skimage import exposure
    L = np.clip(_lum(a), 0, 1)
    L2 = exposure.equalize_adapthist(L, clip_limit=clip)
    gain = (L * (1 - amount) + L2 * amount) / np.maximum(L, 1e-3)
    return a * np.clip(gain, 0.5, 2.0)[..., None]


def defringe(a: np.ndarray, reach: int = 2) -> np.ndarray:
    """強い縁の周りの紫・緑の色付きを、近くの色付いていない所の色へ寄せる（色収差の除去）"""
    from scipy.ndimage import binary_dilation, median_filter
    L = _lum(a)
    edge = binary_dilation(_grad(L) > 0.25, iterations=reach)
    cb, cr = _chroma(a)
    bad = edge & (((cb > 18) & (cr > 8)) | ((cb < -12) & (cr < -12)))
    if not bad.any():
        return a
    # 色だけを差し替え、明るさは残す
    cb_m, cr_m = median_filter(np.where(bad, 0, cb), 7), median_filter(np.where(bad, 0, cr), 7)
    Y = L * 255
    cb2, cr2 = np.where(bad, cb_m, cb), np.where(bad, cr_m, cr)
    r = Y + 1.402 * cr2
    g = Y - 0.344136 * cb2 - 0.714136 * cr2
    b = Y + 1.772 * cb2
    return np.stack([r, g, b], -1)


def _masked_mean(a: np.ndarray, m: np.ndarray, size: int) -> np.ndarray:
    """m の画素だけの周りの平均の色（m の外の色を混ぜない）"""
    from scipy.ndimage import uniform_filter
    w = uniform_filter(m.astype(float), size)
    return np.stack([uniform_filter(a[..., c] * m, size) for c in range(3)], -1) / np.maximum(w, 1e-6)[..., None]


def _small(mask: np.ndarray, most: int) -> np.ndarray:
    from scipy.ndimage import label
    lab, _ = label(mask, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    sizes[0] = most + 1
    return sizes[lab] <= most


def deburr(a: np.ndarray, protect: np.ndarray | None = None, r: int | None = None) -> np.ndarray:
    """輪郭のバリ取り: 細く飛び出した小さな毛羽を周りの背景の色で消し、細い小さな切れ込みを隣の人物の色で埋める。
    髪の毛先のような長い出っ張りは消さない（面積が r×r×3 を超える塊は残す）。埋める色は近くの背景・人物だけの平均
    （四隅の色や黒で埋めると、背景のある絵で四角い色の塊が出た）"""
    from scipy.ndimage import binary_closing, binary_opening
    m = _figure(a)
    r = r or max(2, round(min(a.shape[:2]) / 400))
    k = np.ones((2 * r + 1, 2 * r + 1), bool)
    most = 3 * r * r
    spur = m & ~binary_opening(m, k)
    notch = binary_closing(m, k) & ~m
    spur &= _small(spur, most)
    notch &= _small(notch, most)
    if protect is not None:
        spur &= ~protect
        notch &= ~protect
    out = a.copy()
    size = 4 * r + 3
    if spur.any():
        out[spur] = _masked_mean(a, ~m, size)[spur]
    if notch.any():
        out[notch] = _masked_mean(a, m & ~spur, size)[notch]
    return out


def dejag(a: np.ndarray, protect: np.ndarray | None = None, reach: float = 2.0) -> np.ndarray:
    """線の縁の階段をならす: 縁の画素だけ、縁の向き（明るさの勾配に直交する向き）に沿って前後の色と平均する。
    新しい線の色を置かないので、線は太りも痩せもしない（線を 2 倍でならして描き直すやり方は、線を太らせ角張らせた）"""
    from scipy.ndimage import gaussian_filter, map_coordinates, sobel
    L = gaussian_filter(_lum(a), 1.0)
    gy, gx = sobel(L, 0), sobel(L, 1)
    mag = np.hypot(gx, gy)
    band = mag > max(0.15, np.quantile(mag, 0.9))
    if protect is not None:
        band &= ~protect
    ys, xs = np.nonzero(band)
    if ys.size == 0:
        return a
    tx, ty = -gy[ys, xs] / mag[ys, xs], gx[ys, xs] / mag[ys, xs]
    out = a.copy()
    for c in range(3):
        acc, wsum = a[ys, xs, c].copy(), np.ones(ys.size)
        for k, w in ((1.0, 0.8), (-1.0, 0.8), (reach, 0.4), (-reach, 0.4)):
            acc += w * map_coordinates(a[..., c], [ys + k * ty, xs + k * tx], order=1, mode="nearest")
            wsum += w
        out[ys, xs, c] = acc / wsum
    return out


def sharpen(a: np.ndarray, sigma: float = 1.2, amount: float = 0.6) -> np.ndarray:
    """アンシャープマスクを明るさだけに掛ける（色ににじみを出さない）"""
    from scipy.ndimage import gaussian_filter
    from scipy.ndimage import binary_dilation
    L = _lum(a) * 255
    d = (L - gaussian_filter(L, sigma)) * amount
    # 強い縁の周りだけを締める。平らな所まで掛けると塗りのざらつきが黒い粒になり、線の塊が 710 → 1390 に増えた
    g = _grad(L / 255)
    near = binary_dilation(g > np.quantile(g, 0.95), iterations=2)
    w = gaussian_filter(near.astype(float), 1.0)
    return a + (d * w)[..., None]


OPS = {"heal": heal, "denoise": denoise, "white_balance": white_balance, "levels": levels, "dehaze": dehaze,
       "local_contrast": local_contrast, "defringe": defringe, "deburr": deburr, "dejag": dejag, "sharpen": sharpen}
PROTECTED = {"heal", "deburr", "dejag"}
# 写真とイラストで掛ける工程を変える。イラストは平らな塗りが持ち味なので、かすみ除去と局所の明暗差は掛けない
PRESETS = {
    # 色かぶり補正はイラストに掛けない。夕方の暖色・夜の青のような色は描き手が決めた色で、灰色へ戻すと絵が変わった
    "illust": ["heal", "defringe", "deburr", "dejag", "levels", "sharpen"],
    "photo": ["heal", "denoise", "white_balance", "levels", "dehaze", "local_contrast", "defringe", "sharpen"],
}


def drift(a: np.ndarray, b: np.ndarray, scale: int = 16) -> float:
    """形の変わり方: 縮めた明るさどうしの相関を 1 から引いたもの。明るさや色の全体の変化（レベル補正・色かぶり補正）は
    形の変化に数えない（明るさの差で測ると、レベル補正を 0.247 と数えて落とした）"""
    def small(x):
        im = Image.fromarray(np.clip(_lum(x) * 255, 0, 255).astype("uint8"))
        return np.asarray(im.resize((max(1, im.width // scale), max(1, im.height // scale)), Image.BOX), dtype=float).ravel()
    x, y = small(a), small(b)
    if x.std() < 1e-6 or y.std() < 1e-6:
        return 0.0 if np.allclose(x, y) else 1.0
    return float(1 - np.corrcoef(x, y)[0, 1])


ISOLATED = 8        # 線からこれだけ離れた粒だけを消す（画素）
LOCAL = 14.0        # 区画（32 画素）の平均の色が、全体の色の変え方で説明できずに変わってよい上限（0〜255）


def damage(a: np.ndarray, b: np.ndarray, cell: int = 32) -> float:
    """局所の壊れ: 色ごとに b ≒ k a + c を絵全体で合わせた残りを、32 画素の区画の平均で見た最大（上位 0.1%）。
    全体の明るさ・色の変え方（レベル補正）は残りに出ず、一部だけの壊れ（輪郭が四角く欠ける、黒い塊）が出る。
    縮めた明るさの相関だけでは、輪郭を壊したバリ取りを 0.0135 と数えて通した"""
    h, w = a.shape[0] // cell * cell, a.shape[1] // cell * cell
    if h == 0 or w == 0:
        return 0.0
    res = []
    for c in range(3):
        x, y = a[:h, :w, c].ravel(), b[:h, :w, c].ravel()
        k, c0 = np.polyfit(x, y, 1) if x.std() > 1e-6 else (1.0, float((y - x).mean()))
        d = (b[:h, :w, c] - (k * a[:h, :w, c] + c0)).reshape(h // cell, cell, w // cell, cell).mean((1, 3))
        res.append(np.abs(d))
    return float(np.quantile(np.max(res, 0), 0.999))


LINE_GUARD = {"denoise", "defringe", "deburr", "dejag", "sharpen"}   # 線の形を変えうる工程（明るさ全体の工程は除く）


def line_state(a: np.ndarray) -> tuple[int, int]:
    """主線の塊の数と面積。毛先が切れて点線になると塊が増え、線が太る・痩せると面積が変わる"""
    import cleanup
    from scipy.ndimage import label
    m = _line(a)
    lab, n = label(m, structure=np.ones((3, 3)))
    # 粒（cleanup.SPECK 未満）は数えない。シャープは縁の際に見えない粒を作り、塊を 671 → 976 に増やしたが、
    # 元の大きさで見て線は切れていなかった。切れた毛先は粒より大きい塊になる
    sizes = np.bincount(lab.ravel())[1:]
    big = sizes >= cleanup.SPECK
    return int(big.sum()), int(sizes[big].sum())


def line_broken(a: np.ndarray, b: np.ndarray, pieces: float = 1.05, area: float = 0.02, thickness: bool = True) -> str:
    """線を壊したか。4096 画素の絵で、バリ取りは毛先を切って塊を 671 → 1255 に、ジャギー消しは線を太らせ角張らせて
    面積を 3.3% 変えた。どちらも自分の数字（出っ張りの数・折れの多さ）は良くなっていた"""
    n0, s0 = line_state(a)
    n1, s1 = line_state(b)
    if n1 > n0 * pieces + 5:
        return f"線が切れる（塊 {n0} → {n1}）"
    # 塊が 1 割以上減ったときは、ざらつきや粒を線と取っていたのが消えただけなので、面積の減りは問わない
    if thickness and n1 > n0 * 0.9 and abs(s1 - s0) > max(area * s0, 64):   # 小さな絵では数十画素の揺れを数えない
        return f"線の太さが変わる（面積 {s0} → {s1}）"
    return ""


def apply(a: np.ndarray, name: str, protect: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """工程を 1 つ掛け、自分の数字が良くなり形が変わりすぎないときだけ採る"""
    fn, metric = OPS[name], METRIC[name]
    t = time.time()
    b = np.clip(fn(a, protect) if name in PROTECTED else fn(a), 0, 255)
    before, after = metric(a), metric(b)
    d = drift(a, b)
    dm = damage(a, b)
    better = after < before
    # シャープは線を濃くするのが目的なので、線の面積の増えは問わない（切れて塊が増えるのは問う）
    broken = line_broken(a, b, thickness=name != "sharpen") if name in LINE_GUARD and better else ""
    ok = better and d <= DRIFT and dm <= LOCAL and not broken
    why = "" if ok else ("数字が良くならない" if not better else f"形が変わりすぎる（{d:.3f}）" if d > DRIFT
                         else f"一部が壊れる（{dm:.1f}）" if dm > LOCAL else broken)
    rep = {"step": name, "before": round(float(before), 4), "after": round(float(after), 4), "drift": round(d, 4),
           "damage": round(dm, 1), "used": ok, "seconds": round(time.time() - t, 1)}
    if why:
        rep["why"] = why
    return (b if ok else a), rep


def _protect(src: str | None, shape) -> np.ndarray | None:
    if not src:
        return None
    try:
        import edit
        seg = np.asarray(edit.parts(src).resize((shape[1], shape[0]), Image.NEAREST))
        return seg == FACE
    except Exception:
        return None


def auto(src: str, out: str, preset: str = "illust") -> dict:
    a = np.asarray(Image.open(src).convert("RGB")).astype(float)
    protect = _protect(src, a.shape)
    steps = []
    for name in PRESETS[preset]:
        a, rep = apply(a, name, protect)
        steps.append(rep)
    Image.fromarray(np.clip(a, 0, 255).astype("uint8")).save(out)
    return {"preset": preset, "steps": steps}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["auto", "measure", *OPS])
    ap.add_argument("src")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--preset", choices=list(PRESETS), default="illust")
    a = ap.parse_args()
    if a.cmd == "measure":
        print(json.dumps(measure(np.asarray(Image.open(a.src).convert("RGB")).astype(float)), ensure_ascii=False))
    elif a.cmd == "auto":
        print(json.dumps(auto(a.src, a.out, a.preset), ensure_ascii=False, indent=1))
    else:
        img = np.asarray(Image.open(a.src).convert("RGB")).astype(float)
        res, rep = apply(img, a.cmd, _protect(a.src, img.shape))
        Image.fromarray(np.clip(res, 0, 255).astype("uint8")).save(a.out)
        print(json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
