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
    return WEIGHTS.exists() or COMPACT.exists()


def fetch():
    """重み（18MB）を取る。途中で切れても壊れた重みを残さないよう、別名で取ってから名前を替える"""
    import urllib.request
    UPSCALE.mkdir(parents=True, exist_ok=True)
    part = WEIGHTS.with_suffix(".part")
    urllib.request.urlretrieve(URL, part)
    part.replace(WEIGHTS)


def unload():
    """拡大の模型を降ろす（描く模型を読む前に呼ばれる。模型はいつも 1 つだけ）"""
    _NET.clear()
    from chatdraw.membudget import released
    released("upscale")


def _net():
    from chatdraw.membudget import exclusive
    exclusive("upscale", unload)   # 描く・加工の模型を降ろしてから使う
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
    # channels_last にすると、CPU（4 コア）で 512×768 の 4 倍が 58.8 秒から 44.1〜46.3 秒になった。画素は前と同じ（差の最大 1）
    model = model.to(memory_format=torch.channels_last)
    _NET.append(model.eval())
    return _NET[0]


# 軽い網（SRVGGNetCompact、Real-ESRGAN の realesr-animevideov3、BSD-3-Clause、2.4MB）。出来と秒を
# chatdraw/bench_finish.py の upscale で今の網と並べて測るためのもの。既定の網は、出来が下がらず速いと分かるまで替えない
COMPACT = UPSCALE / "realesr-animevideov3.pth"
COMPACT_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth"
_COMPACT = []


def _compact():
    if _COMPACT:
        return _COMPACT[0]
    import torch
    import urllib.request
    from torch import nn
    import torch.nn.functional as F

    class SRVGG(nn.Module):
        def __init__(self, nf=64, nc=16, up=4):
            super().__init__()
            self.up = up
            body = [nn.Conv2d(3, nf, 3, 1, 1), nn.PReLU(num_parameters=nf)]
            for _ in range(nc):
                body += [nn.Conv2d(nf, nf, 3, 1, 1), nn.PReLU(num_parameters=nf)]
            body += [nn.Conv2d(nf, 3 * up * up, 3, 1, 1)]
            self.body = nn.Sequential(*body)
            self.shuffle = nn.PixelShuffle(up)

        def forward(self, x):
            return self.shuffle(self.body(x)) + F.interpolate(x, scale_factor=self.up, mode="nearest")

    if not COMPACT.exists():
        UPSCALE.mkdir(parents=True, exist_ok=True)
        part = COMPACT.with_suffix(".part")
        urllib.request.urlretrieve(COMPACT_URL, part)
        part.replace(COMPACT)
    state = torch.load(COMPACT, map_location="cpu", weights_only=True)
    state = state.get("params_ema", state.get("params", state))
    model = SRVGG()
    model.load_state_dict(state, strict=True)
    if torch.cuda.is_available():
        model = model.half().cuda()
    model = model.to(memory_format=torch.channels_last)
    _COMPACT.append(model.eval())
    return _COMPACT[0]


def first():
    """先に使う網。軽い網（animevideov3）は Actions の機械で、今の網より 10 倍速く（2 枚で 30.9 → 2.9 秒、82.6 → 7.9 秒）、
    縮め戻した絵と元の絵の SSIM（0.9725 → 0.9839、0.9881 → 0.9952）も線の重なり（0.987 → 0.991、0.907 → 0.951）も上がった。
    取れないとき（通信が無い）は今の網に戻す"""
    try:
        return _compact()
    except Exception:
        return _net()


def x4(img, tile: int | None = None, pad: int = 16, on_step=None, net=None):
    """PIL の絵を 4 倍にする。メモリーに収めるため、端を重ねたタイルに分けて回す。
    区画の大きさはメモリの予算で決める（membudget.tile_for）。出来上がりは 8 ビットの配列へ区画ごとに直に書く。
    前は 4 倍の大きさの 32 ビットの入れ物を先に取り、最後にもう 1 枚 8 ビットへ写していたので、2048 角の絵で約 1GB の山になった"""
    import numpy as np
    import torch
    from PIL import Image
    from chatdraw import membudget as mb
    net = net or _net()
    dev = next(net.parameters()).device
    dtype = next(net.parameters()).dtype
    if tile is None:
        from chatdraw.engine import free_ram_gb
        tile = mb.tile_for(free_ram_gb(), mb.free_vram_gb(), dev.type == "cuda")
    src = np.asarray(img.convert("RGB"))
    h, w, _ = src.shape
    out = np.empty((h * 4, w * 4, 3), dtype=np.uint8)
    tiles = [(y, x) for y in range(0, h, tile) for x in range(0, w, tile)]
    with torch.inference_mode():
        for i, (y, x) in enumerate(tiles, 1):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
            part = torch.from_numpy(src[y0:y1, x0:x1].astype(np.float32) / 255.0).permute(2, 0, 1)[None]
            r = net(part.to(dev, dtype)).float().cpu()
            ty, tx = (y - y0) * 4, (x - x0) * 4
            hh, ww = min(tile, h - y) * 4, min(tile, w - x) * 4
            blk = r[0, :, ty:ty + hh, tx:tx + ww].clamp(0, 1).permute(1, 2, 0).numpy()
            out[y * 4:y * 4 + hh, x * 4:x * 4 + ww] = (blk * 255.0).round().astype(np.uint8)
            del r, part, blk
            if on_step:
                on_step(i, len(tiles))
    return Image.fromarray(out)


def upscale(img, scale: int = 2, on_step=None):
    """img を scale 倍（2 か 4）にする。透明な所は、透明度だけを普通の拡大で合わせる"""
    from PIL import Image
    big = x4(img, on_step=on_step, net=first())
    size = (img.width * scale, img.height * scale)
    if big.size != size:
        big = big.resize(size, Image.LANCZOS)
    if img.mode == "RGBA":
        big.putalpha(img.getchannel("A").resize(size, Image.LANCZOS))
    return big
