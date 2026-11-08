"""赤ペンの直しの境目を、元の絵につなぐ。

直した所の境目が元の絵とずれて見えた（色と明るさの段差、線の食い違い）。その対策を 3 つに分ける。
1. adjust_mask: 囲んだ所を、近くの線と塗りの切れ目まで少しだけ広げる。境目を平らな塗りの真ん中ではなく、
   線の際に置くと、段差が目立たなかった。広げるのは囲みから reach 画素までで、近くに線が無ければ広げない。
2. harmonize: 直した所の内側の帯だけで、色と明るさを元の絵に寄せ、元の線を帯の中へつなぐ。
   帯の外（直した所の奥）と囲みの外には触らない。囲みの外は元の画素をそのまま返す。
3. measure と settle: 境目の色の差、線のずれ、SSIM を測り、ずれていれば帯を広げて合わせ直す。
   回数の上限は置かない。帯が直した所の奥まで届いたら、それ以上は合わせようが無いので止める。

切り出して貼り戻す形はとらない（元の絵が崩れた）。どの関数も絵全体の大きさのまま扱う。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

EDGE = 22.0        # 線とみなす明るさの勾配（0〜255 の段差の半分）
COLOR_OK = 4.0     # 境目の色の差の許し（元の絵にもともとある段差を引いたあとの平均、0〜255）
SHIFT_OK = 1.0     # 線のずれの許し（画素）
SSIM_OK = 0.80     # 境目の帯の SSIM の許し
COLOR_GOOD = 1.0   # 許しに入っても、色の差がこれより大きく、帯が直した所の奥の 3 分の 1 に届くまでは帯を広げて合わせ直す


def _l(img) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _rgb(img) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32)


def _grad(g: np.ndarray) -> np.ndarray:
    gx, gy = np.zeros_like(g), np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    return np.hypot(gx, gy) / 2


def _blur(a: np.ndarray, r: float) -> np.ndarray:
    """numpy の配列を、半径 r のガウスぼかしに近い形で均す（箱のぼかしを 3 回。scipy が無くても動き、小数のまま扱える）。
    端は端の値を写して足す。a は 2 次元か 3 次元"""
    a = np.asarray(a, dtype=np.float32)
    k = max(1, int(round(r * 0.9)))   # 箱 3 回の広がりが、ガウスの r に近くなる幅
    out = a
    for axis in (0, 1):
        for _ in range(3):
            pad = [(0, 0)] * out.ndim
            pad[axis] = (k + 1, k)
            c = np.cumsum(np.pad(out, pad, mode="edge"), axis=axis, dtype=np.float64)
            hi = np.take(c, np.arange(2 * k + 1, c.shape[axis]), axis=axis)
            lo = np.take(c, np.arange(0, c.shape[axis] - 2 * k - 1), axis=axis)
            out = ((hi - lo) / (2 * k + 1)).astype(np.float32)
    return out


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return m.copy()
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * r + 1))) > 127


def _erode(m: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return m.copy()
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(2 * r + 1))) > 127


def depth(m: np.ndarray, limit: int) -> np.ndarray:
    """直す所の中の、縁からの距離（画素、limit で頭打ち）。外は 0"""
    try:
        from scipy import ndimage
        return np.minimum(ndimage.distance_transform_edt(m), limit).astype(np.float32)
    except ImportError:
        d = np.zeros(m.shape, np.float32)
        cur = m.copy()
        for _ in range(limit):
            if not cur.any():
                break
            d += cur
            cur = _erode(cur, 1)
        return d


def adjust_mask(image, mask, reach: int = 6):
    """囲んだ所を、線と塗りの切れ目まで reach 画素だけ広げた mask を返す（元の囲みは必ず含む）。

    平らな塗りの中を 1 画素ずつ外へ広げ、線（勾配が EDGE 以上）に当たった所で止める。
    線に当たらなかった所（近くに線が無い所）は広げない。境目が線の際に来る所だけを広げる。
    小さな凹み（赤ペンの線のがたつき）は閉じて埋める。"""
    m = np.asarray(mask.convert("L")) > 127
    if not m.any() or reach <= 0:
        return mask.convert("L").point(lambda v: 255 if v > 127 else 0)
    edge = _grad(_l(image)) > EDGE
    near = _dilate(m, reach)
    grown, front = m.copy(), m.copy()
    hit = np.zeros_like(m)
    for _ in range(reach):
        ring = _dilate(front, 1) & ~grown & near
        hit |= ring & edge          # 線に当たった
        front = ring & ~edge        # 平らな塗りだけを広げる
        if not front.any():
            break
        grown |= front
    # 線に当たった所の近くだけを残す（線の無い所で平らに広げると、囲みの外を必要以上に変えた）
    keep = m | (grown & _dilate(hit, reach))
    closed = _erode(_dilate(keep, 2), 2) & near   # 赤ペンの線のがたつきを閉じる
    out = keep | closed
    return Image.fromarray((out * 255).astype(np.uint8), "L")


def harmonize(before, after, mask, band: int = 6, lines: float = 1.0):
    """直した所の内側の帯（縁から band 画素）だけで、色と明るさを元の絵に寄せ、元の線を帯の中へつなぐ。

    - 色: 縁のすぐ内側で測った (元 − 直し) の差を、帯の奥へ向けて薄めながら足す（低い周波数だけ。描いた線の形は残る）
    - 線: 元の絵の帯の中にある線を、縁に近いほど強く元の画素へ戻す（外から来た線が境目で折れない）
    mask の外は before の画素をそのまま返す（1 画素も変えない）。"""
    m = np.asarray(mask.convert("L")) > 127
    b, a = _rgb(before), _rgb(after)
    if not m.any():
        return before.convert("RGB").copy()
    d = depth(m, band + 2)
    fade = np.clip(1 - (d - 1) / max(band, 1), 0, 1) * m
    fade = fade * fade * (3 - 2 * fade)                 # なめらかに薄める
    ring = (m & (d <= 2)).astype(np.float32)
    w = _blur(ring, band)
    off = _blur((b - a) * ring[..., None], band) / np.maximum(w, 1e-4)[..., None]
    out = a + off * fade[..., None]
    # 縁のすぐ内側（帯の半分）は、元の絵から直した絵へ少しずつ移す。縁の 1 画素目は元の絵とほぼ同じになり、段差が消える
    f = np.clip(1 - (d - 1) / max(2.0, band / 2), 0, 1) * m
    alpha = f * f * (3 - 2 * f)
    if lines > 0:
        gb = _grad(_l(before))
        line = np.clip((gb - EDGE * 0.6) / EDGE, 0, 1)
        alpha = np.maximum(alpha, np.clip(fade * line * lines, 0, 1))
    alpha = alpha[..., None]
    out = out * (1 - alpha) + b * alpha
    out = np.where(m[..., None], np.clip(out, 0, 255), b)
    return Image.fromarray(np.round(out).astype(np.uint8), "RGB")


def _ssim(x: np.ndarray, y: np.ndarray, where: np.ndarray) -> float:
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = _blur(x, 1.5), _blur(y, 1.5)
    sx = _blur(x * x, 1.5) - mx * mx
    sy = _blur(y * y, 1.5) - my * my
    sxy = _blur(x * y, 1.5) - mx * my
    s = ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sx + sy + c2))
    return float(s[where].mean()) if where.any() else 1.0


def measure(before, after, mask) -> dict:
    """境目のずれを数字で返す。color: 境目をまたぐ色の段差が元の絵より増えた量（0〜255 の平均）、
    shift: 元の絵で境目を横切っていた線が、直した絵でどれだけずれたか（画素の平均、4 で頭打ち）、
    ssim: 境目の帯（内と外に 4 画素）の SSIM。ok はどれも許しの中か"""
    m = np.asarray(mask.convert("L")) > 127
    if not m.any():
        return dict(color=0.0, shift=0.0, ssim=1.0, ok=True)
    b, a = _rgb(before), _rgb(after)
    inner = m & ~_erode(m, 5)
    outer = _dilate(m, 5) & ~m

    def across(img):
        """縁の内側の各画素と、すぐ外の色（外の画素だけで均した色）の差"""
        wo = _blur(outer.astype(np.float32), 3)
        out_c = _blur(img * outer[..., None], 3) / np.maximum(wo, 1e-4)[..., None]
        wi = _blur(inner.astype(np.float32), 3)
        in_c = _blur(img * inner[..., None], 3) / np.maximum(wi, 1e-4)[..., None]
        return np.abs(in_c - out_c).mean(axis=-1)
    color = float(np.clip(across(a) - across(b), 0, None)[inner].mean())
    gb, ga = _grad(_l(before)), _grad(_l(after))
    seam = _dilate(m, 4) & ~_erode(m, 4)
    lb, la = (gb > EDGE) & seam & m, ga > EDGE
    if lb.sum() >= 8:
        dist = np.full(lb.shape, 4.0, np.float32)
        for k in range(3, -1, -1):
            dist[_dilate(la, k)] = k
        shift = float(dist[lb].mean())
    else:
        shift = 0.0
    ssim = _ssim(_l(before), _l(after), seam)
    return dict(color=round(color, 2), shift=round(shift, 2), ssim=round(ssim, 3),
                ok=color <= COLOR_OK and shift <= SHIFT_OK and ssim >= SSIM_OK)


def settle(before, after, mask, say=None):
    """境目を合わせ、測り、ずれていれば帯を広げて合わせ直す。返すのは (合わせた絵, 測った数字の並び)。

    帯は 4 画素から始め、通らなければ 1.5 倍ずつ広げ、線のつなぎも強める。帯が直した所の奥（一番深い所）に届いたら、
    それ以上広げても変わらないので、一番良かった回を使う。崩れの数ではなく、色の差と線のずれと SSIM の合計で比べる。"""
    m = np.asarray(mask.convert("L")) > 127
    if not m.any():
        return after, []
    if m.mean() > 0.98:   # 絵全体を直したときは境目が無い。合わせると直した所を元の絵の色へ戻してしまう
        return after, []
    deepest = int(depth(m, 4096).max())
    tries, best = [], None
    band, lines = 4, 0.8
    while True:
        out = harmonize(before, after, mask, band=band, lines=lines)
        got = measure(before, out, mask)
        got["band"] = band
        tries.append(got)
        score = got["color"] / COLOR_OK + got["shift"] / SHIFT_OK + max(0.0, SSIM_OK - got["ssim"]) * 10
        if best is None or score < best[0]:
            best = (score, out)
        # 許しの中でも段差が残る（帯 4 画素で色の差 2.6）ので、直した所の奥の 3 分の 1 までは広げて色の差を詰める。
        # それより奥まで広げると、直した所が元の絵の色に戻っていく（頼んだ直しが薄まる）
        if band >= deepest or got["ok"] and (got["color"] <= COLOR_GOOD or band * 1.5 + 1 > deepest / 3):
            break
        if say:
            say(f"境目がずれているので、合わせ直しています（帯 {band} 画素・色の差 {got['color']}・線のずれ {got['shift']}）")
        band, lines = min(deepest, int(band * 1.5) + 1), min(1.0, lines + 0.1)
    return best[1], tries
