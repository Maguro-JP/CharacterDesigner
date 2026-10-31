"""スクリーントーンの見本帳。漫画の加工（manga.py）が、影や地の濃さに応じて貼る。

トーンはどれも「濃さ 0〜1 の地図」を受け取り、「墨 0/1 の地図」を返す。
濃さを地図で渡すので、1 枚の中で影の段ごとに別のトーンを貼り分けられる（使い分けの例は manga.py）。
線数（点や線の間隔）は絵の大きさに比例させ、縮小しても網目がつぶれないようにする。

  python3 tools/gen/tones.py 出力.png   全部のトーンを濃さの帯で並べた見本を書く
"""
from __future__ import annotations

import sys

import numpy as np

SEED = 11


def _grid(h: int, w: int):
    return np.mgrid[0:h, 0:w].astype(np.float32)


def _period(h: int, w: int, per: float) -> float:
    """短い辺に per 本並ぶ間隔（画素）。絵の大きさが変わっても網目の見え方をそろえる。
    3 画素より細かくすると点が形にならず、ただの灰色になった"""
    return max(3.0, min(h, w) / per)


def _rot(yy, xx, deg):
    t = np.deg2rad(deg)
    return xx * np.cos(t) + yy * np.sin(t), -xx * np.sin(t) + yy * np.cos(t)


def _dot(v, h, w, per, deg=45.0, white=False):
    """網点。濃い所ほど点が大きい。点の面積が濃さと等しくなるよう半径を決める（濃さどおりの灰色に見える）"""
    p = _period(h, w, per)
    yy, xx = _grid(h, w)
    u, t = _rot(yy, xx, deg)
    du = (u / p) % 1 - 0.5
    dt = (t / p) % 1 - 0.5
    d = np.hypot(du, dt)
    if white:
        # 白抜き網点: 黒地に白い点。濃さの裏を点にする
        return (d > np.sqrt(np.clip(1 - v, 0, 1) / np.pi)).astype(np.float32)
    # 濃さ 0.78 を超えると点がつながる。円の面積 pi r^2 = v から r を出し、つながった後は四隅を埋める
    r = np.sqrt(np.clip(v, 0, 1) / np.pi)
    return ((d < r) | (v > 0.95)).astype(np.float32)


def _lines(v, h, w, per, deg):
    """線トーン。濃さに応じて線の太さを変える"""
    p = _period(h, w, per)
    yy, xx = _grid(h, w)
    _, t = _rot(yy, xx, deg)
    return (((t / p) % 1) < np.clip(v, 0, 1)).astype(np.float32)


def dot_fine(v, h, w):
    """細かい網点（短い辺に 170 列）。肌の影、遠くの物"""
    return _dot(v, h, w, 170)


def dot_mid(v, h, w):
    """中くらいの網点（115 列）。服や物の影。いちばん使う"""
    return _dot(v, h, w, 115)


def dot_coarse(v, h, w):
    """粗い網点（70 列）。網点そのものを見せる演出、ポップな地"""
    return _dot(v, h, w, 70)


def dot_white(v, h, w):
    """白抜き網点。ベタの上に乗せる夜空・暗い服の柄"""
    return _dot(v, h, w, 115, white=True)


def line_h(v, h, w):
    """横の線トーン。空、平らな壁"""
    return _lines(v, h, w, 130, 0)


def line_v(v, h, w):
    """縦の線トーン。縦の影、雨の地"""
    return _lines(v, h, w, 130, 90)


def line_diag(v, h, w):
    """斜めの線トーン。斜めの影、動きのある地"""
    return _lines(v, h, w, 130, 45)


def cross(v, h, w):
    """カケアミ（交差した線）。濃さで 1 方向→2 方向→4 方向と重ねる。劇画の影"""
    a = _lines(np.minimum(v * 1.6, 0.45), h, w, 140, 45)
    b = _lines(np.minimum(np.clip(v - 0.3, 0, 1) * 1.6, 0.45), h, w, 140, -45)
    c = _lines(np.minimum(np.clip(v - 0.6, 0, 1) * 1.6, 0.45), h, w, 140, 0)
    return np.maximum(np.maximum(a, b), c)


def sand(v, h, w):
    """砂目（細かいざらつきの点）。地面、壁、古い紙"""
    rng = np.random.default_rng(SEED)
    return (rng.random((h, w)) < np.clip(v, 0, 1)).astype(np.float32)


def gradation(v, h, w):
    """グラデーション網点。渡した濃さに、上から下へ薄くなる傾きを掛ける。空、少女漫画の背景"""
    ramp = np.linspace(1.0, 0.0, h, dtype=np.float32)[:, None]
    return _dot(np.clip(v, 0, 1) * ramp, h, w, 95)


def concentric(v, h, w):
    """同心円トーン。驚き・衝撃の背景"""
    p = _period(h, w, 45)
    yy, xx = _grid(h, w)
    r = np.hypot(yy - h / 2, xx - w / 2)
    return (((r / p) % 1) < np.clip(v, 0, 1)).astype(np.float32)


def noise(v, h, w):
    """ノイズ（ぼかした砂目を 2 値にした斑）。煙、霧、汚れ"""
    rng = np.random.default_rng(SEED)
    from stylize import _blur
    n = _blur(rng.random((h, w)).astype(np.float32), max(1.0, min(h, w) / 400))
    n = (n - n.min()) / (n.max() - n.min() + 1e-6)
    return (n < np.clip(v, 0, 1)).astype(np.float32)


TONES = {
    "dot_fine": dot_fine, "dot_mid": dot_mid, "dot_coarse": dot_coarse, "dot_white": dot_white,
    "line_h": line_h, "line_v": line_v, "line_diag": line_diag, "cross": cross,
    "sand": sand, "gradation": gradation, "concentric": concentric, "noise": noise,
}


def render(name: str, v, h: int, w: int) -> np.ndarray:
    """トーン name を濃さ v（数か h×w の地図）で貼った墨の地図"""
    v = np.broadcast_to(np.asarray(v, dtype=np.float32), (h, w))
    return TONES[name](v, h, w)


def sheet(path: str, cell: int = 160):
    """見本帳。行がトーン、横に濃さ 0→1 の帯"""
    from PIL import Image, ImageDraw
    n = len(TONES)
    h, w = cell * n, cell * 4
    out = np.ones((h, w), np.float32)
    ramp = np.tile(np.linspace(0, 1, w, dtype=np.float32), (cell, 1))
    for i, name in enumerate(TONES):
        out[i * cell:(i + 1) * cell] = 1 - render(name, ramp, cell, w)
    im = Image.fromarray((out * 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(im)
    for i, name in enumerate(TONES):
        d.rectangle([0, i * cell, 90, i * cell + 14], fill="white")
        d.text((2, i * cell + 1), name, fill="red")
    im.save(path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sheet(sys.argv[1])
