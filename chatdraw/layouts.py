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
    w.__dict__.pop("_fit_cols", None)
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


def need(w, key: str) -> int:
    """欄の中身が流す棒（スクロールバー）を出さずに収まる高さ（見出しを含む）"""
    d = w.panels[key][0]
    body = d.widget()
    inner = body.widget() if hasattr(body, "widget") and body.widget() is not None else body
    title = d.titleBarWidget()
    head = title.sizeHint().height() if title is not None else 24
    if w.tabifiedDockWidgets(d):   # タブで重ねた欄は、タブの見出しの分も要る
        head += d.fontMetrics().height() + 14
    return inner.minimumSizeHint().height() + head + 12


def _group(w, d) -> list:
    """d と、d にタブで重ねた欄"""
    return [d] + [t for t in w.tabifiedDockWidgets(d) if not t.isHidden()]


def _front(w, d):
    """タブで重ねた欄のうち、前に出ている欄（裏の欄の高さは前の配置のままで当てにならない）"""
    return next((t for t in _group(w, d) if t.isVisible() and not t.visibleRegion().isEmpty()), d)


def fit_heights(w, keys: list[str], final: bool = False):
    """縦に積んだ欄の高さを、中身が収まる高さから先に配る。余りは最後の欄（一覧など伸びて役に立つ欄）に回す。
    比（5:5 など）で配ると、中身の多い欄（色）だけが足りず、欄の中に流す棒が出た。
    並べた直後（final でない）は欄の高さが前の配置のままなので、並べ終わったあと（settle）に final で配り直す"""
    if len(keys) < 2:
        return
    cols = w.__dict__.setdefault("_fit_cols", [])
    if not final and keys not in cols:
        cols.append(list(keys))
    docks = [_front(w, w.panels[k][0]) for k in keys]
    keys_of = {id(d): k for k, (d, _) in w.panels.items()}
    want = [max(need(w, keys_of[id(t)]) for t in _group(w, d)) for d in docks]
    room = sum(d.height() for d in docks)
    if sum(want) > room:
        if final:
            # 全部は収まらない。比で削ると、どの欄にも流す棒が出た。収まらない欄はタブにまとめて、1 つずつ広く見せる
            for d in docks[1:]:
                if d not in w.tabifiedDockWidgets(docks[0]):
                    w.tabifyDockWidget(docks[0], d)
            docks[0].raise_()
        return
    want[-1] += room - sum(want)
    w.resizeDocks(docks, want, Qt.Vertical)


def settle(w):
    """並べ終わったあとと、ウィンドウの大きさが変わったあとに、中身が収まらない欄のある列だけ高さを配り直す。
    ウィンドウを広げると Qt は増えた高さを今の比で配り、色の欄のように中身の多い欄が足りないまま残った。
    収まっている列は動かさない（利用者が境目をドラッグして決めた高さを崩さない）"""
    for keys in list(w.__dict__.get("_fit_cols", [])):
        docks = [w.panels[k][0] for k in keys]
        if not all(not d.isHidden() and not d.isFloating() for d in docks):
            continue
        fronts = [_front(w, d) for d in docks]
        if any(f.height() < need(w, k) - 4 for f, k in zip(fronts, keys) if f is w.panels[k][0]):
            fit_heights(w, keys, final=True)
    # 左右の欄の幅も、中身より狭くなった欄だけ広げる
    for k, (d, _) in w.panels.items():
        if d.isHidden() or d.isFloating() or d.visibleRegion().isEmpty() or w.dockWidgetArea(d) not in (L, R):
            continue
        if d.width() < need_width(w, k) - 4:
            w.resizeDocks([d], [need_width(w, k)], Qt.Horizontal)


def fit_talk(w, wish: int):
    """下のチャットの高さ。望む高さと、書く欄と吹き出し 1 つが収まる高さの大きい方"""
    w.resizeDocks([w.panels["talk"][0]], [max(wish, need(w, "talk"))], Qt.Vertical)


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


def need_width(w, key: str) -> int:
    """欄の中身が横に流す棒を出さずに収まる幅（縦の流す棒と枠の分を含む）"""
    body = w.panels[key][0].widget()
    inner = body.widget() if hasattr(body, "widget") and body.widget() is not None else body
    return inner.minimumSizeHint().width() + 60


def _widths(w, left: list, right: list, side: int):
    """左右の欄の幅。決めた幅より中身が広い欄があれば、その幅まで広げる（表示の欄が 300 で横に流す棒を出した）"""
    for keys in (left, right):
        if keys:
            width = max([side] + [need_width(w, k) for k in keys if not w.panels[k][0].isHidden()])
            w.resizeDocks([w.panels[keys[0]][0]], [width], Qt.Horizontal)


# よく使う道具。おすすめの配置では、これだけを道具の帯に出す（ほかはクリエイター向けの配置か、AI に頼めば使える）
ESSENTIAL_TOOLS = ("pen", "eraser", "fill", "eyedropper", "select", "move", "hand", "redpen")


def bars(w, ribbon: bool, tools: tuple | None, options: bool = True, bottom: bool = False, panelbar: bool = True):
    """帯の出し入れと、道具の帯に出す道具（None なら全部）"""
    w.ribbon_bar.setVisible(ribbon)
    w.options.setVisible(options)
    w.bottom_bar.setVisible(bottom)
    w.panel_bar.setVisible(panelbar)
    w.tools.setVisible(tools is None or bool(tools))
    for key, act in w.tool_actions.items():
        act.setVisible(tools is None or key in tools)
    for act in w.tools.actions():
        if act.isSeparator():
            act.setVisible(tools is None)   # 道具を絞ったときは区切りの線だけが並ばないようにする


def _first_tool(w, key: str):
    """配置ごとの初めの道具。デザインツールの配置（クリエイター向け）はペン、ほかは手（絵を動かして見る）"""
    if hasattr(w, "select_tool"):
        w.select_tool(key)


def _progress_idle(w):
    """進みは右下のポップアップに出すので、上の進みの欄は初めは隠す（絵を見る場所を広く取る）"""
    w.panels["progress"][0].hide()


def recommended(w):
    """おすすめ（初めの配置）。絵を広く見せるため、リボンと下の帯は出さず、道具はよく使うものだけにする。
    左に色とレイヤー、右の上に表示、右の中に AI の設定、右の下に履歴、真ん中の上に進み、真ん中の下にチャット"""
    _reset(w)
    bars(w, ribbon=False, tools=ESSENTIAL_TOOLS)
    _column(w, L, ["color", "layers"], [5, 5])
    _hide(w, ["brushes"])
    _column(w, R, ["chat", "history"], [5, 5])
    _tabs(w, ["history", "view", "library"])
    w.panels["history"][0].raise_()
    w.addDockWidget(T, w.panels["progress"][0])
    w.addDockWidget(B, w.panels["talk"][0])
    w.panels["talk"][0].show()
    side = min(320, max(260, int(max(w.width(), 1200) * 0.19)))
    _widths(w, ["color", "layers"], ["chat", "history", "view", "library"], side)
    # チャットは会話を読み返せる高さにする（200 のままだと 1080 の高さでも吹き出しが 2 つしか見えなかった。低い画面では絵の場所を残す）
    fit_talk(w, 200 if w.height() < 900 else int(w.height() * 0.3))
    fit_heights(w, ["color", "layers"])
    _progress_idle(w)
    _first_tool(w, "hand")


def creator(w):
    """クリエイター向け。リボンと全部の道具、左に色・ブラシ・レイヤー、右に表示と履歴、下に小さくチャット"""
    _reset(w)
    bars(w, ribbon=True, tools=None, bottom=True)
    _column(w, L, ["color", "layers"], [5, 5])
    _tabs(w, ["color", "brushes"])   # 3 つ縦に積むと、ノートの画面（高さ 720）に収まらなかった
    _column(w, R, ["view", "history"], [5, 5])
    _tabs(w, ["history", "chat", "library"])
    w.panels["history"][0].raise_()
    w.addDockWidget(T, w.panels["progress"][0])
    w.addDockWidget(B, w.panels["talk"][0])
    w.panels["talk"][0].show()
    _widths(w, ["color", "brushes", "layers"], ["view", "history", "chat", "library"], 300)
    fit_talk(w, 130)
    fit_heights(w, ["color", "layers"])
    fit_heights(w, ["view", "history"])
    _progress_idle(w)
    _first_tool(w, "pen")


def ai_focus(w):
    """AI 特化。手で描く道具は出さず、左に AI プリセットと作風、右に全体と履歴、下にチャットを大きく。上に進み"""
    _reset(w)
    bars(w, ribbon=False, tools=("redpen", "select", "hand"), options=False)   # 手で描く道具は出さず、AI に直す所を示す道具だけ
    _column(w, L, ["chat"])
    _column(w, R, ["view", "history"], [3, 7])
    _tabs(w, ["history", "library"])
    w.addDockWidget(T, w.panels["progress"][0])
    w.addDockWidget(B, w.panels["talk"][0])
    w.panels["talk"][0].show()
    _hide(w, ["color", "brushes", "layers"])
    _widths(w, ["chat"], ["view", "history", "library"], 320)
    fit_talk(w, 260)
    fit_heights(w, ["view", "history"])
    _progress_idle(w)
    _first_tool(w, "hand")


def simple(w):
    """シンプル。よく使う道具と色、下にチャットだけ。ほかの欄は欄の帯から開く"""
    _reset(w)
    bars(w, ribbon=False, tools=ESSENTIAL_TOOLS)
    _column(w, L, ["color"])
    w.addDockWidget(B, w.panels["talk"][0])
    w.panels["talk"][0].show()
    _hide(w, ["brushes", "layers", "history", "view", "chat", "progress", "library"])
    _widths(w, ["color"], [], 260)
    fit_talk(w, 160)
    _first_tool(w, "hand")


def canvas_only(w):
    """絵だけ。帯も欄も隠して、絵をいちばん広く見せる（Tab でも同じ）"""
    _reset(w)
    bars(w, ribbon=False, tools=(), options=False, panelbar=False)
    _hide(w, list(w.panels))


def drawing_focus(w):
    """作画中心。全部の道具と、左に色・ブラシ・レイヤー、右に表示。AI の欄は隠す"""
    _reset(w)
    bars(w, ribbon=False, tools=None)
    _column(w, L, ["color", "layers"], [5, 5])
    _tabs(w, ["color", "brushes"])   # 3 つ縦に積むと、ノートの画面（高さ 720）に収まらなかった
    _column(w, R, ["view"])
    _hide(w, ["chat", "history", "progress", "talk", "library"])
    _widths(w, ["color", "brushes", "layers"], ["view"], 280)
    fit_heights(w, ["color", "layers"])


PRESETS = {"おすすめ": recommended, "クリエイター向け": creator, "AI 特化": ai_focus, "作画中心": drawing_focus,
           "シンプル": simple, "絵だけ": canvas_only}


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
    # 別の大きさの画面で保存した配置だと、別ウィンドウの欄が画面の外に出て見えなくなった
    for d, _ in w.panels.values():
        if d.isFloating() and hasattr(w, "keep_on_screen"):
            w.keep_on_screen(d)
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
