"""AI が筆を動かして描くための、筆の線と塗りの範囲（chatdraw/phases.py が使う）。

模型の下絵を一度に貼るのではなく、下絵から線の座標と塗る範囲を取り、それを筆の線として 1 本ずつ紙に置く。
人の描き方と同じく、アタリ・構図の線 → 体・顔・髪・服の線 → 清書 → 部位ごとの下塗り → 影 2 段 → 光 → 目 → 髪の艶 の順に置く。

- 線と範囲は下絵を長辺 WORK 画素に縮めた絵で取る（大きいままだと線をたどる計算が工程を重くした）。置くのは元の大きさの紙
- 部位（髪・肌・服）は色を数色にまとめ、頭の位置と肌の色から分ける。部位分けの模型を使わないので外れることがある（私の推測の作り）
- 筆はキャンバスの筆（chatdraw/brush.py）と同じ考えの丸い筆先で、線の太さと濃さを持つ。Qt を使わないので裏の糸でも置ける
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

WORK = 256          # 線と範囲を取る大きさ（長辺）
BG_DIST = 38        # 背景の色からこれより離れた所を人（描く物）とする
SKIN = (236, 204, 186)   # 肌の色の目安。頭の中でこれに一番近い色を肌にする（私の推測の値）


@dataclass
class Plan:
    """下絵から取った、筆を置く物の一式。座標は WORK の大きさで、scale を掛けると紙の大きさになる"""
    size: tuple
    scale: float
    rgb: np.ndarray          # 縮めた下絵（float、0〜255）
    lum: np.ndarray
    fg: np.ndarray           # 描く物の範囲
    head: tuple              # 頭の (中心 x, 中心 y, 半径)
    parts: dict = field(default_factory=dict)   # 部位の名前 → 範囲
    colors: dict = field(default_factory=dict)  # 部位の名前 → 下塗りの色
    edges: np.ndarray | None = None


def _cleanup(mask: np.ndarray, k: int = 1) -> np.ndarray:
    """小さな穴とごみを除く（最大・最小の濾しを 1 回ずつ）"""
    im = Image.fromarray((mask * 255).astype("uint8"))
    im = im.filter(ImageFilter.MaxFilter(2 * k + 1)).filter(ImageFilter.MinFilter(2 * k + 1))
    im = im.filter(ImageFilter.MinFilter(2 * k + 1)).filter(ImageFilter.MaxFilter(2 * k + 1))
    return np.asarray(im) > 127


def plan(ref: Image.Image) -> Plan:
    rgb_im = ref.convert("RGB")
    w, h = rgb_im.size
    scale = max(w, h) / WORK
    small = rgb_im.resize((max(8, round(w / scale)), max(8, round(h / scale))), Image.BILINEAR)
    a = np.asarray(small, dtype=float)
    lum = a @ np.array([0.299, 0.587, 0.114])
    sh, sw = lum.shape
    c = max(2, min(sh, sw) // 16)
    corners = np.concatenate([a[:c, :c].reshape(-1, 3), a[:c, -c:].reshape(-1, 3), a[-c:, :c].reshape(-1, 3), a[-c:, -c:].reshape(-1, 3)])
    bg = np.median(corners, 0)
    fg = np.linalg.norm(a - bg, axis=2) > BG_DIST
    fg = _cleanup(fg)
    if fg.mean() < 0.02:   # 背景と分けられない絵（全面が描かれている）は全部を描く物にする
        fg = np.ones_like(fg)
    ys, xs = np.nonzero(fg)
    y0, y1 = ys.min(), ys.max()
    band = fg[y0:y0 + max(2, (y1 - y0) // 7)]
    bx = np.nonzero(band.any(0))[0]
    hx = float(bx.mean()) if len(bx) else sw / 2
    hr = max(4.0, (y1 - y0) / 9)
    head = (hx, y0 + hr, hr)
    p = Plan((w, h), scale, a, lum, fg, head)
    p.edges = edges(lum, fg)
    _parts(p)
    return p


def edges(lum: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """明るさの段差（線）と、描く物の輪郭"""
    gy, gx = np.gradient(lum)
    mag = np.hypot(gx, gy)
    inside = mag[fg]
    t = max(12.0, float(np.percentile(inside, 82))) if inside.size else 255.0
    e = (mag > t) & fg
    ring = fg & ~(np.asarray(Image.fromarray((fg * 255).astype("uint8")).filter(ImageFilter.MinFilter(3))) > 127)
    return e | ring


def _parts(p: Plan):
    """色を数色にまとめ、頭の位置と肌の色から髪・肌・服に分ける"""
    im = Image.fromarray(p.rgb.astype("uint8"))
    q = im.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    lab = np.asarray(q)
    pal = np.array(q.getpalette()[:24], dtype=float).reshape(-1, 3)
    hx, hy, hr = p.head
    yy, xx = np.mgrid[:lab.shape[0], :lab.shape[1]]
    in_head = ((xx - hx) ** 2 + (yy - hy) ** 2 <= (hr * 1.4) ** 2) & p.fg
    used = [k for k in range(len(pal)) if (lab[p.fg] == k).any()]
    if not used:
        return
    head_counts = {k: int(((lab == k) & in_head).sum()) for k in used}
    near = [k for k in used if head_counts[k] > 0] or used
    skin = min(near, key=lambda k: np.linalg.norm(pal[k] - SKIN))
    top = in_head & (yy < hy)
    hair_c = {k: int(((lab == k) & top).sum()) for k in used if k != skin}
    hair = max(hair_c, key=hair_c.get) if hair_c and max(hair_c.values()) > 0 else None
    parts = {"肌": (lab == skin) & p.fg}
    if hair is not None:
        parts["髪"] = (lab == hair) & p.fg & (yy < hy + hr * 3)
    rest = p.fg.copy()
    for m in parts.values():
        rest &= ~m
    parts["服"] = rest
    p.parts = {k: v for k, v in parts.items() if v.any()}
    p.colors = {k: tuple(int(c) for c in np.median(p.rgb[v], 0)) for k, v in p.parts.items()}


def trace(mask: np.ndarray, min_len: int = 3, limit: int = 4000) -> list[list[tuple[int, int]]]:
    """線の画素をたどって筆の線（座標の並び）にする。上から順に並ぶ（人も上から描く）"""
    left = mask.copy()
    h, w = left.shape
    out = []
    pts = list(zip(*np.nonzero(left)))
    nb = ((0, 1), (1, 0), (1, 1), (1, -1), (0, -1), (-1, 0), (-1, -1), (-1, 1))
    for y, x in pts:
        if not left[y, x]:
            continue
        line = [(int(x), int(y))]
        left[y, x] = False
        cy, cx = y, x
        while True:
            for dy, dx in nb:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w and left[ny, nx]:
                    left[ny, nx] = False
                    line.append((int(nx), int(ny)))
                    cy, cx = ny, nx
                    break
            else:
                break
        if len(line) >= min_len:
            out.append(line[::2] + ([line[-1]] if len(line) % 2 == 0 else []))   # 1 画素おきに間引く（筆の線は滑らかでよい）
        if len(out) >= limit:
            break
    return out


def runs(mask: np.ndarray, band: int = 3) -> list[list[tuple[int, int]]]:
    """塗る範囲を横の筆の運びにする（band 画素ごとに、範囲の続く所を 1 本の太い線にする）"""
    out = []
    h = mask.shape[0]
    for y in range(0, h, band):
        row = mask[y:y + band].any(0)
        if not row.any():
            continue
        d = np.diff(np.concatenate([[0], row.astype(int), [0]]))
        for s, e in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            out.append([(int(s), y + band // 2), (int(e - 1), y + band // 2)])
    return out


class Paper:
    """工程ごとのレイヤー（透明な紙）に筆の線を置く。座標は Plan の大きさで受け、紙の大きさに直して置く"""

    def __init__(self, size, scale):
        self.size, self.scale = tuple(size), scale
        self.layer = Image.new("RGBA", self.size, (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)
        self.strokes = 0

    def stroke(self, pts, color, width: float, alpha: int = 255):
        s = self.scale
        xy = [((x + 0.5) * s, (y + 0.5) * s) for x, y in pts]
        wd = max(1, round(width * s))
        col = tuple(int(c) for c in color[:3]) + (int(alpha),)
        if len(xy) == 1:
            xy = xy * 2
        self.draw.line(xy, fill=col, width=wd, joint="curve")
        r = wd / 2
        for x, y in (xy[0], xy[-1]):   # 丸い筆先（線の両端を丸くする）
            self.draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        self.strokes += 1


def compose(layers: list[Image.Image], size, paper=(255, 255, 255)) -> Image.Image:
    """白い紙の上にレイヤーを順に重ねた絵"""
    out = Image.new("RGBA", tuple(size), paper + (255,))
    for lay in layers:
        out.alpha_composite(lay)
    return out.convert("RGB")


def coverage(layer: Image.Image, target: np.ndarray) -> float:
    """置くはずの範囲のうち、筆が置かれた割合（工程の検品に使う）"""
    if not target.any():
        return 1.0
    a = np.asarray(layer.split()[-1].resize((target.shape[1], target.shape[0]), Image.BILINEAR)) > 20
    return float((a & target).sum() / target.sum())


def missed(layer: Image.Image, target: np.ndarray) -> np.ndarray:
    a = np.asarray(layer.split()[-1].resize((target.shape[1], target.shape[0]), Image.BILINEAR)) > 20
    return target & ~a
