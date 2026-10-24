"""絵を大きくする（AI の拡大）。線と塗りの境目を保ったまま 4 倍にし、要る大きさに縮める。

重みは Real-ESRGAN のアニメ絵用（RealESRGAN_x4plus_anime_6B、BSD-3-Clause、18MB）。初めて使うときに 1 回だけ取る。
網の形（RRDBNet）はここに書き、重みだけを読む（読み込み用の部品は torchvision まで要り、この用途には重い）。
画像生成の模型は約 100 万画素で描くのが得意で、それより大きく直接描かせると崩れるので、大きくするのはここで行う。
"""
from __future__ import annotations

from chatdraw.paths import LLM_HOME, SHARED
import os

UPSCALE = LLM_HOME / "upscale" if SHARED else LLM_HOME / "gen" / "upscale"
WEIGHTS = UPSCALE / "RealESRGAN_x4plus_anime_6B.pth"
URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
_NET = []


def ready() -> bool:
    return WEIGHTS.exists()


def fetch():
    """重み（18MB）を取る。途中で切れても壊れた重みを残さないよう、別名で取ってから名前を替える"""
    import urllib.request
    UPSCALE.mkdir(parents=True, exist_ok=True)
    part = WEIGHTS.with_suffix(".part")
    urllib.request.urlretrieve(URL, part)
    part.replace(WEIGHTS)


def _net():
    if _NET:
        return _NET[0]
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

    if not ready():
        fetch()
    state = torch.load(WEIGHTS, map_location="cpu", weights_only=True)
    state = state.get("params_ema", state.get("params", state))
    model = RRDBNet(nb=6)
    model.load_state_dict(state, strict=True)
    if torch.cuda.is_available():
        model = model.half().cuda()
    _NET.append(model.eval())
    return _NET[0]


def x4(img, tile: int = 256, pad: int = 16, on_step=None):
    """PIL の絵を 4 倍にする。メモリーに収めるため、端を重ねたタイルに分けて回す"""
    import numpy as np
    import torch
    from PIL import Image
    net = _net()
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = a.shape
    t = torch.from_numpy(a).permute(2, 0, 1)[None]
    out = torch.zeros((1, 3, h * 4, w * 4))
    tiles = [(y, x) for y in range(0, h, tile) for x in range(0, w, tile)]
    dev = next(net.parameters()).device
    dtype = next(net.parameters()).dtype
    with torch.inference_mode():
        for i, (y, x) in enumerate(tiles, 1):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
            r = net(t[:, :, y0:y1, x0:x1].to(dev, dtype)).float().cpu()
            ty, tx = (y - y0) * 4, (x - x0) * 4
            hh, ww = min(tile, h - y) * 4, min(tile, w - x) * 4
            out[:, :, y * 4:y * 4 + hh, x * 4:x * 4 + ww] = r[:, :, ty:ty + hh, tx:tx + ww]
            if on_step:
                on_step(i, len(tiles))
    b = (out[0].clamp(0, 1).permute(1, 2, 0).numpy() * 255.0).round().astype(np.uint8)
    return Image.fromarray(b)


def upscale(img, scale: int = 2, on_step=None):
    """img を scale 倍（2 か 4）にする。透明な所は、透明度だけを普通の拡大で合わせる"""
    from PIL import Image
    big = x4(img, on_step=on_step)
    size = (img.width * scale, img.height * scale)
    if big.size != size:
        big = big.resize(size, Image.LANCZOS)
    if img.mode == "RGBA":
        big.putalpha(img.getchannel("A").resize(size, Image.LANCZOS))
    return big
