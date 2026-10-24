"""欄の配置。おすすめの配置といくつかの決まった配置、寄せ（左・右・真ん中）、等分（3・5）、
自分の配置の保存と読み出し、ファイルへの書き出しと読み込み。

欄の境目は、どの配置でもドラッグで広げ縮めできる（QMainWindow の境目）。
配置の中身は Qt の saveState（欄と帯の位置・大きさ・出し入れ）とウィンドウの大きさで、ファイルには JSON で書く。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt

L, R, T, B = Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea, Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea
VERSION = 1


def _reset(w):
    """欄をいったん全部くっつけ直す（別ウィンドウや畳んだ物も戻す）"""
    for d, _ in w.panels.values():
        d.setFloating(False)
        title = d.titleBarWidget()
        if getattr(title, "collapsed", False):
            title.toggle()
    # 左右の欄を上下の端まで伸ばし、上と下の欄は真ん中だけにする（真ん中の上に進み、下にチャット）
    w.setCorner(Qt.TopLeftCorner, L)
    w.setCorner(Qt.BottomLeftCorner, L)
    w.setCorner(Qt.TopRightCorner, R)
    w.setCorner(Qt.BottomRightCorner, R)


def _column(w, area, keys: list[str], sizes: list[int] | None = None):
    """keys の欄を area に縦に積む。sizes は高さの比"""
    docks = [w.panels[k][0] for k in keys]
    for i, d in enumerate(docks):
        if i == 0:
            w.addDockWidget(area, d)
        else:
            w.splitDockWidget(docks[i - 1], d, Qt.Vertical)
        d.show()
    if sizes and len(docks) > 1:
        h = max(w.height(), 600)
        total = sum(sizes)
        w.resizeDocks(docks, [int(h * s / total) for s in sizes], Qt.Vertical)
    return docks


def _tabs(w, keys: list[str]):
    """keys の欄を 1 か所にタブで重ねる。最初の欄を前に出す"""
    docks = [w.panels[k][0] for k in keys]
    for d in docks[1:]:
        w.tabifyDockWidget(docks[0], d)
        d.show()
    docks[0].raise_()


def _hide(w, keys):
    for k in keys:
        w.panels[k][0].hide()


def _widths(w, left: list, right: list, side: int):
    if left:
        w.resizeDocks([w.panels[left[0]][0]], [side], Qt.Horizontal)
    if right:
        w.resizeDocks([w.panels[right[0]][0]], [side], Qt.Horizontal)


def recommended(w):
    """おすすめ。左に手で描く道具（色・ブラシ・レイヤー）、右の上に表示（全体・参考画像）、右の中に AI の設定、
    右の下に履歴、真ん中の上に進み、真ん中の下にチャット"""
    _reset(w)
    _column(w, L, ["color", "brushes"], [4, 6])
    _tabs(w, ["brushes", "layers"])
    w.panels["layers"][0].raise_()
    _column(w, R, ["view", "chat", "history"], [3, 3, 4])
    w.addDockWidget(T, w.panels["progress"][0])
    w.addDockWidget(B, w.panels["talk"][0])
    for k in ("progress", "talk"):
        w.panels[k][0].show()
    side = min(330, max(250, int(max(w.width(), 1200) * 0.19)))
    _widths(w, ["color"], ["view"], side)
    w.resizeDocks([w.panels["progress"][0], w.panels["talk"][0]], [70, 190], Qt.Vertical)


def simple(w):
    """シンプル。左に色、右に AI とレイヤー、下にチャットだけ"""
    _reset(w)
    _column(w, L, ["color"])
    _column(w, R, ["chat", "layers"], [4, 6])
    w.addDockWidget(B, w.panels["talk"][0])
    w.panels["talk"][0].show()
    _hide(w, ["brushes", "history", "view", "progress"])
    _widths(w, ["color"], ["chat"], 280)
    w.resizeDocks([w.panels["talk"][0]], [170], Qt.Vertical)


def ai_focus(w):
    """AI 中心。チャットを大きく、右に AI・進み・履歴。手で描く道具は隠す"""
    _reset(w)
    _column(w, R, ["chat", "progress", "history"], [3, 2, 5])
    _column(w, L, ["view"])
    w.addDockWidget(B, w.panels["talk"][0])
    w.panels["talk"][0].show()
    _hide(w, ["color", "brushes", "layers"])
    _widths(w, ["view"], ["chat"], 300)
    w.resizeDocks([w.panels["talk"][0]], [300], Qt.Vertical)


def drawing_focus(w):
    """作画中心。左に色・ブラシ・レイヤー、右に表示だけ。AI の欄は隠す"""
    _reset(w)
    _column(w, L, ["color", "brushes", "layers"], [4, 3, 3])
    _column(w, R, ["view"])
    _hide(w, ["chat", "history", "progress", "talk"])
    _widths(w, ["color"], ["view"], 280)


PRESETS = {"おすすめ": recommended, "シンプル": simple, "AI 中心": ai_focus, "作画中心": drawing_focus}


def visible(w) -> list[str]:
    return [k for k, (d, _) in w.panels.items() if d.isVisible() and not d.isFloating()]


def align(w, where: str):
    """見えている欄を寄せる。left・right は片側に縦に積み、center は左右に半分ずつ分けて絵を真ん中に置く"""
    keys = visible(w) or list(w.panels)
    _reset(w)
    if where in ("left", "right"):
        _column(w, L if where == "left" else R, keys)
        _widths(w, keys if where == "left" else [], keys if where == "right" else [], 320)
    else:
        half = (len(keys) + 1) // 2
        _column(w, L, keys[:half])
        _column(w, R, keys[half:])
        _widths(w, keys[:half], keys[half:], 300)


def split(w, n: int):
    """ウィンドウの幅を n 等分する。3 なら 左の欄・絵・右の欄 を 1:1:1、5 なら 1:3:1。欄は縦にも等分する"""
    keys = visible(w) or list(w.panels)
    _reset(w)
    half = (len(keys) + 1) // 2
    left = _column(w, L, keys[:half], [1] * half)
    right = _column(w, R, keys[half:], [1] * (len(keys) - half))
    width = max(w.width(), 900) // n
    if left:
        w.resizeDocks([left[0]], [width], Qt.Horizontal)
    if right:
        w.resizeDocks([right[0]], [width], Qt.Horizontal)


# ---- 自分の配置: 保存・読み出し・書き出し・読み込み ----
def snapshot(w) -> dict:
    return {"version": VERSION, "app": "CharacterDesigner",
            "state": base64.b64encode(bytes(w.saveState())).decode(),
            "geometry": base64.b64encode(bytes(w.saveGeometry())).decode()}


def restore(w, data: dict) -> bool:
    if data.get("app") != "CharacterDesigner" or "state" not in data:
        return False
    _reset(w)
    ok = w.restoreState(QByteArray(base64.b64decode(data["state"])))
    if data.get("geometry"):
        w.restoreGeometry(QByteArray(base64.b64decode(data["geometry"])))
    return bool(ok)


def saved_names(store) -> list[str]:
    store.beginGroup("layouts")
    names = sorted(store.childKeys())
    store.endGroup()
    return names


def save(w, store, name: str):
    store.setValue(f"layouts/{name}", json.dumps(snapshot(w)))


def load(w, store, name: str) -> bool:
    raw = store.value(f"layouts/{name}")
    return bool(raw) and restore(w, json.loads(raw))


def remove(store, name: str):
    store.remove(f"layouts/{name}")


def export(w, path: str, name: str = ""):
    data = snapshot(w)
    data["name"] = name or Path(path).stem
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def import_(w, path: str) -> str | None:
    """読み込んで当てる。当てられたら配置の名前を返す"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("name") or Path(path).stem if restore(w, data) else None
