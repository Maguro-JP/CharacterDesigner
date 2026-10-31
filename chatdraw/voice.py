"""音声入力。Windows に入っている音声入力（Win+H）を、書く欄に移ってから開く。

声を文字にする模型をアプリに足さずに済むよう、OS の音声入力に任せる。話した言葉は、そのとき入力を受けている
書く欄に入る。Windows 以外では使えないので、ボタンを止めてツールチップで知らせる。
"""
from __future__ import annotations

import sys

VK_LWIN, VK_H, KEYUP = 0x5B, 0x48, 0x0002
# Win を押す、H を押す、H を離す、Win を離す
SEQUENCE = ((VK_LWIN, 0), (VK_H, 0), (VK_H, KEYUP), (VK_LWIN, KEYUP))


def available() -> bool:
    return sys.platform == "win32"


def start(user32=None) -> bool:
    """Win+H を送る。送れたら True。user32 は試験で差し替える"""
    if user32 is None:
        if not available():
            return False
        import ctypes
        user32 = ctypes.windll.user32
    for key, flag in SEQUENCE:
        user32.keybd_event(key, 0, flag, 0)
    return True
