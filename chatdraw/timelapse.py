"""タイムラプス。人が線を引くたび・AI が 1 工程描くたびに小さな写しを残し、GIF に書き出す。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

MAX_SIDE = 720       # 1 枚の写しの長い辺（メモリを食いすぎない大きさ）
MAX_FRAMES = 3000    # これを超えたら 1 枚おきに間引く（長く描いてもメモリが増え続けない）


class Recorder:
    def __init__(self):
        self.frames: list[Image.Image] = []
        self.enabled = True

    def add(self, img: Image.Image):
        if not self.enabled:
            return
        im = img.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        if self.frames and self.frames[-1].tobytes() == im.tobytes():
            return   # 何も変わっていない写しは足さない
        self.frames.append(im)
        if len(self.frames) > MAX_FRAMES:
            self.frames = self.frames[::2]

    def clear(self):
        self.frames.clear()

    def export(self, path: str | Path, seconds: float = 15.0) -> int:
        """全体が seconds 秒ほどになる GIF に書き出す。書いた枚数を返す"""
        if not self.frames:
            return 0
        frames = self.frames
        step = max(1, len(frames) // 600)   # 600 枚を超える分は間引く
        frames = frames[::step]
        if frames[-1] is not self.frames[-1]:
            frames.append(self.frames[-1])
        size = frames[-1].size
        frames = [f if f.size == size else f.resize(size) for f in frames]
        per = max(20, int(seconds * 1000 / len(frames)))
        durations = [per] * (len(frames) - 1) + [2000]   # 最後の完成した絵で 2 秒止める
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
        return len(frames)
