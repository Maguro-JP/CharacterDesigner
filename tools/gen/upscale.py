"""描いた絵を高い解像度に引き上げる（AI の拡大）。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/upscale.py in.png out.png [--long 4096]

使う重みは Real-ESRGAN のアニメ絵用（RealESRGAN_x4plus_anime_6B、BSD-3-Clause、18MB）。
線と塗りの境目を保ったまま4倍に拡大する。網の形（RRDBNet）はここに書き、重みだけを読む
（読み込み用の部品 spandrel は torchvision まで要り、この用途には重いため）。
重みは `sh tools/gen/setup.sh` が .cache/gen/upscale に取る。

画像生成の模型（SDXL）は約100万画素で描くのが得意で、それより大きく直接描かせると崩れる。
そのため「得意な大きさで描く → hires で 1.5 倍に描き直して細部を足す → ここで4倍に拡大する」の順で高解像度にする。
"""
from __future__ import annotations

import cdhome
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEIGHTS = cdhome.HOME / "gen" / "upscale" / "RealESRGAN_x4plus_anime_6B.pth"
URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
# 写真（写実の絵）用。アニメ用は塗りを平らにする学習なので、写真に掛けると肌のきめと髪の毛筋が溶けて油絵のようになる
WEIGHTS_PHOTO = cdhome.HOME / "gen" / "upscale" / "RealESRGAN_x4plus.pth"
URL_PHOTO = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"

_NET = {}


def _net(kind: str = "anime"):
    if kind in _NET:
        return _NET[kind]
    import torch
    from torch import nn
    import torch.nn.functional as F

    class RDB(nn.Module):
        def __init__(self, nf=64, gc=32):
            super().__init__()
            self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
            self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
            self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
            self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
            self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            return self.conv5(torch.cat((x, x1, x2, x3, x4), 1)) * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, nf=64):
            super().__init__()
            self.rdb1, self.rdb2, self.rdb3 = RDB(nf), RDB(nf), RDB(nf)

        def forward(self, x):
            return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x

    class RRDBNet(nn.Module):
        def __init__(self, nb=6, nf=64):
            super().__init__()
            self.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
            self.body = nn.Sequential(*[RRDB(nf) for _ in range(nb)])
            self.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, True)

        def forward(self, x):
            feat = self.conv_first(x)
            feat = feat + self.conv_body(self.body(feat))
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            return self.conv_last(self.lrelu(self.conv_hr(feat)))

    weights, nb = (WEIGHTS_PHOTO, 23) if kind == "photo" else (WEIGHTS, 6)
    if not weights.exists():
        raise FileNotFoundError(f"拡大の重みが無い。`sh tools/gen/setup.sh` で取る（{weights}）")
    state = torch.load(weights, map_location="cpu", weights_only=True)
    state = state.get("params_ema", state.get("params", state))
    net = RRDBNet(nb=nb)
    net.load_state_dict(state, strict=True)
    import device
    device.module(net, torch)
    _NET[kind] = net.eval()
    return _NET[kind]


def x4(img, tile: int = 256, pad: int = 16, kind: str = "anime"):
    """PIL の絵を4倍にする。CPU のメモリーに収めるため、端を重ねたタイルに分けて回す"""
    import numpy as np
    import torch
    from PIL import Image
    net = _net(kind)
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = a.shape
    t = torch.from_numpy(a).permute(2, 0, 1)[None]
    out = torch.zeros((1, 3, h * 4, w * 4))
    with torch.inference_mode():
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                y0, x0 = max(0, y - pad), max(0, x - pad)
                y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
                dev = next(net.parameters()).device
                r = net(t[:, :, y0:y1, x0:x1].to(dev)).float().cpu()
                ty, tx = (y - y0) * 4, (x - x0) * 4
                hh, ww = min(tile, h - y) * 4, min(tile, w - x) * 4
                out[:, :, y * 4:y * 4 + hh, x * 4:x * 4 + ww] = r[:, :, ty:ty + hh, tx:tx + ww]
    b = (out[0].clamp(0, 1).permute(1, 2, 0).numpy() * 255.0).round().astype(np.uint8)
    return Image.fromarray(b)


def upscale(src, out, long: int = 4096, kind: str = "anime"):
    """src を長い辺が long 画素になるまで拡大して out に置く。返すのは出来た大きさ"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    while max(im.size) < long:
        im = x4(im, kind=kind)
    if max(im.size) != long:
        s = long / max(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im.save(out)
    return im.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--long", type=int, default=4096, help="長い辺の画素数（既定 4096）")
    ap.add_argument("--kind", choices=["anime", "photo"], default="anime", help="photo は写実の絵・写真用の重み")
    a = ap.parse_args()
    print(upscale(a.src, a.out, a.long, a.kind))


if __name__ == "__main__":
    main()
