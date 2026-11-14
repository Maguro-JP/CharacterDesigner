"""修正依頼と、模型を使わない編集の道具（整える・揃える・消す）の入口。

赤ペンの印の右クリックと、AI の欄の「直す」の両方から同じ関数を呼ぶ。右クリックのメニューには add_to_menu の 1 か所だけで足す
（赤ペンの画面や直しの言葉の組み立てを別に直していても、合わせるときにこの 1 行だけ見ればよいように）。
"""
from __future__ import annotations

from chatdraw import fixrequests

TOOLS = {   # 道具の名前 → (メニューの名前, ツールチップ)
    "smooth": ("線を整える", "囲んだ所の線の揺れ・がたつきを滑らかにします。模型は使いません。元に戻すで戻せます"),
    "despeckle": ("ゴミの点を消す", "囲んだ所（囲みが無ければ絵全体）の小さな点を周りの色で消します。元に戻すで戻せます"),
    "erase": ("囲んだ物を消す", "囲んだ所の物を、周りの色で埋めて消します。元に戻すで戻せます"),
    "align": ("1 つ目に揃える（大きさと高さ）", "2 つ以上囲むと、2 つ目からを 1 つ目の大きさと高さに揃えます（左右の目・耳など）。元に戻すで戻せます"),
    "align_height": ("1 つ目に揃える（高さだけ）", "2 つ以上囲むと、2 つ目からの高さを 1 つ目に揃えます。大きさは変えません"),
}


def _sub(menu, title):
    """小さなメニューを、親のメニューが持つ形で足す（PySide6 の addMenu(文字) が返すメニューは、Python の参照が切れると消えた）"""
    from PySide6.QtWidgets import QMenu
    sub = QMenu(title, menu)
    sub.setToolTipsVisible(True)
    menu.addMenu(sub)
    return sub


def add_to_menu(win, menu, n: int = 0):
    """右クリックのメニューに「修正依頼」と「整える・揃える・消す」を足す。n は右クリックした印の番号（0 なら印の上ではない）"""
    fill_requests(win, _sub(menu, f"印 {n} に修正依頼" if n else "修正依頼"), n)
    fill_tools(win, _sub(menu, "整える・揃える・消す"))


def fill_requests(win, menu, n: int = 0):
    menu.setToolTipsVisible(True)
    for part, items in fixrequests.by_part().items():
        if not items:
            continue
        sub = _sub(menu, part)
        for r in items:
            act = sub.addAction(r["name"], lambda r=r: apply_request(win, r, n))
            act.setToolTip(TOOLS[r["tool"]][1] if r.get("tool") in TOOLS else "赤ペンの印の指示に書いて、囲んだ所を 1 回だけ直します")
    menu.addSeparator()
    menu.addAction("自分の指示を一覧に足す…", lambda: ask_add(win, n)).setToolTip(
        "よく使う指示を名前を付けて足します。足した指示はこの一覧の「自分の指示」に出ます")


def fill_tools(win, menu):
    menu.setToolTipsVisible(True)
    for key, (label, tip) in TOOLS.items():
        menu.addAction(label, lambda k=key: apply_tool(win, k)).setToolTip(tip)


def _targets(win, n: int) -> list[int]:
    pen = win.canvas.redpen
    shown = pen.shown()
    if n:
        return [n] if 1 <= n <= len(pen.marks) else []
    empty = [i for i in shown if not pen.texts[i - 1].strip()]
    return empty or list(shown)


def apply_request(win, req: dict, n: int = 0) -> bool:
    """修正依頼を選んだとき。指示を赤ペンの印の欄に書いて確定し、そのあとで 1 回だけ直す。直しを始めたら True"""
    if req.get("tool") in TOOLS:
        return apply_tool(win, req["tool"], n)
    c = win.canvas
    pen = c.redpen
    if not pen.marks and c.selection is None:
        win.notify("直す所を囲んでください", "info", "赤ペン（T）で直す所を囲んでから、修正依頼を選んでください")
        return False
    if pen.marks:
        for i in _targets(win, n):
            pen.set_text(i, req["name"])   # 指示の欄に書いて確定（絵の上の札とレイヤーの欄の「赤ペン n」に出る）
        if hasattr(win, "layer_panel"):
            win._refresh_layers()
        left = [i for i in pen.shown() if not pen.texts[i - 1].strip()]
        if left and not win.entry.text().strip():
            win.notify("ほかの印にも指示を書いてください", "info",
                       f"印 {', '.join(map(str, left))} に指示がありません。指示を書くか、修正依頼を選ぶと直します")
            return False
    else:
        win.entry.setText(req["name"])   # 四角の選択だけのときは、選択の指示は AI の欄の文になる
    if win.thread:
        win.statusBar().showMessage("描いている途中です。終わってから選んでください", 6000)
        return False
    win.fix_marked()   # 「描く」を直すにして押すのと同じ道を 1 回だけ通す
    return True


def ask_add(win, n: int = 0):
    """自分の指示を足す。今の印に書いた指示があれば、それを初めの文にする"""
    from PySide6.QtWidgets import QInputDialog
    pen = win.canvas.redpen
    start = pen.texts[n - 1] if n and 1 <= n <= len(pen.texts) else ""
    name, ok = QInputDialog.getText(win, "自分の指示を足す", "指示（赤ペンの印の欄に書く文。例: 袖を短く）", text=start)
    if ok and fixrequests.add_user(name):
        win.notify("修正依頼の一覧に足しました", "ok", f"「{name.strip()}」は修正依頼の「{fixrequests.USER_PART}」から選べます")
        return name.strip()
    return None


def _masks(win, n: int = 0):
    from chatdraw.app import gray_to_pil
    c = win.canvas
    pen = c.redpen
    marks = pen.masks()
    shown = [n] if n else pen.shown()
    out = [gray_to_pil(marks[i - 1]).convert("L") for i in shown if 1 <= i <= len(marks)]
    sel = c.selection_mask()
    if sel is not None and not n:
        out.append(gray_to_pil(sel).convert("L"))
    return out


def apply_tool(win, key: str, n: int = 0) -> bool:
    """模型を使わない道具を今の絵に掛け、変わった画素だけのレイヤーを一番上に置く（元に戻すで戻せる）"""
    from PIL import ImageChops
    from chatdraw import edittools, finishers
    from chatdraw.app import qimage_to_pil
    label = TOOLS[key][0]
    base = qimage_to_pil(win.canvas.flatten()).convert("RGB")
    masks = [m.resize(base.size) for m in _masks(win, n)]
    union = None
    for m in masks:
        union = m if union is None else ImageChops.lighter(union, m)
    try:
        if key == "smooth":
            out = edittools.smooth_lines(base, union)
        elif key == "despeckle":
            out = edittools.despeckle(base, union)
        elif key == "erase":
            if union is None:
                raise ValueError("消す所を赤ペンか選択で囲んでください")
            out = edittools.erase(base, union)
        else:
            out = edittools.align(base, masks, size=key == "align")
    except ValueError as e:
        win.notify(f"{label}を掛けられませんでした", "info", str(e))
        return False
    count = edittools.changed_pixels(base, out)
    if not count:
        win.notify(f"{label}: 変わる所がありませんでした", "info", "囲む所を変えるか、ほかの道具を試してください")
        return False
    path = win._finished_path(key)
    finishers.effect_layer(base, out).save(path)
    from chatdraw.canvas import preload
    preload(str(path))
    win.canvas.place_result(str(path), label)   # 一番上の新しいレイヤーに置いて選ぶ。元に戻すで戻せる
    if hasattr(win, "layer_panel"):
        win._refresh_layers()
    win.notify(f"{label}（新しいレイヤー）", "ok", f"{count} 画素を変えました。レイヤーを隠すか消すと元の絵に戻ります")
    return True
