"""写実の絵の明暗を、影の段数と境のぼかしを選んでアニメの塗りに落とす。

描く模型は影を体の形と無関係な所（脚を斜めに横切る直線、片脚だけ）に置いた（身体 回1〜7）。
写実で描かせた絵の明暗は、体の形と光源の向きに沿う。その明暗の位置はそのまま使い、塗りの見た目だけを変える。
  soft 0   : 境のはっきりした段の影（アニメ・マンガの 1影・2影）
  soft 1   : 段を作らず、なめらかに馴染ませた影（写実寄りの立体感）
色は写実の絵から肌のきめを消した平らな色にし、明るさだけを段に置き換える。線は付けない（後の描き直しに任せる）。

  python3 tools/gen/toneshade.py 写実.png OUT.png [--tones 2] [--soft 0.0]
"""
from __future__ import annotations

import argparse

import numpy as np


def shade(rgb: np.ndarray, person: np.ndarray, tones: int = 2, soft: float = 0.0) -> np.ndarray:
    """rgb は 0〜1 の (H, W, 3)、person は人物の画素（True）。人物の外はそのまま返す"""
    from scipy import ndimage
    lum = rgb.mean(-1)
    # 肌のきめ・毛穴の細かい明暗は影ではないので、ぼかしてから段を決める
    smooth = ndimage.gaussian_filter(lum, 8)
    # 平らな色: 人物の中で色を大きくぼかし、明るさで割って「光の当たり方を除いた色」にする
    w = ndimage.gaussian_filter(person.astype(float), 12) + 1e-6
    flat = np.dstack([ndimage.gaussian_filter(rgb[..., c] * person, 12) / w for c in range(3)])
    # 色の向き（色相と彩度）だけを残す。明るさで割ると彩度が上がって橙に寄ったので、明るさの比で戻す
    flat /= np.maximum(flat.mean(-1, keepdims=True), 1e-6)
    flat = 1 + (flat - 1) * 0.8
    v = smooth[person]
    lit = np.percentile(v, 90)
    rel = np.clip(smooth / max(lit, 1e-6), 0, 1)
    # 段の境は人物の明るさの分位で決める。2 段なら影 1 本（暗い 35%）、3 段なら 2影（暗い 12%）も足す
    cuts = [np.percentile(rel[person], q) for q in ((35,) if tones <= 2 else (35, 12))]
    levels = [1.0, 0.72, 0.5][: len(cuts) + 1]
    step = np.full(rel.shape, levels[0])
    area = person.sum()
    for c, lv in zip(cuts, levels[1:]):
        m = (rel < c) & person
        # 小さな斑（血管・きめの名残）は影の形ではないので塗らない。人物の 0.3% より小さい塊を落とす
        m = ndimage.binary_opening(m, iterations=2)
        lab, n = ndimage.label(m)
        if n:
            sizes = ndimage.sum(m, lab, range(1, n + 1))
            m = np.isin(lab, 1 + np.nonzero(sizes >= 0.003 * area)[0])
        step = np.where(m, lv, step)
    # soft: 段と元のなめらかな明るさを混ぜる。境だけを少しぼかし、0 でも 1 画素のギザギザを残さない
    step = ndimage.gaussian_filter(step, 1.0)
    tone = (1 - soft) * step + soft * (0.5 + 0.5 * rel)
    out = rgb.copy()
    out[person] = np.clip(flat[person] * tone[person, None] * lit, 0, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--tones", type=int, default=2)
    ap.add_argument("--soft", type=float, default=0.0)
    a = ap.parse_args()
    from PIL import Image
    import edit
    rgb = np.asarray(Image.open(a.src).convert("RGB"), dtype=np.float32) / 255.0
    person = np.asarray(edit.parts(a.src)) != 0
    Image.fromarray((shade(rgb, person, a.tones, a.soft) * 255).astype(np.uint8)).save(a.out)


if __name__ == "__main__":
    main()
