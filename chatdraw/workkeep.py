"""絵ごとの作業の情報（レイヤー、赤ペンの印と指示、選んだレイヤー、表示の倍率と回転、元に戻すの記録）を残して戻す。

履歴やライブラリーから別の絵へ移ると、キャンバスは新しい絵に置き換わる。前は置き換えた時点でレイヤーと赤ペンの印が消え、
同じ絵へ戻っても絵 1 枚だけに戻っていた。ここでは絵の置き場ごとに作業を残す。
- レイヤーの画素・名前・不透明度・表示は ORA（project.write_ora。Krita などでも開ける）に書く
- ORA に入らない物（ロック、赤ペンの直しの印、赤ペンの印と指示、選んだレイヤー、表示）は隣の .work.json に書く
- 元に戻すの記録はファイルに書かず、アプリを開いている間だけ覚える（画素の写しが大きく、ディスクを食うため）
どちらも別名に書いてから置き換えるので、書いている途中で落ちても前の作業は壊れない。
置き場は絵の隣。書けない場所（読み取りだけのフォルダー）の絵は、利用者のデータの置き場（paths.HOME / work）に書く。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QPointF

ORA = ".layers.ora"
INFO = ".work.json"
VERSION = 1
KEEP_UNDO = 4   # 元に戻すの記録を覚えておく絵の数（古い物から忘れる。レイヤーと印はファイルに残る）


def _fallback(key: str) -> Path:
    from chatdraw.paths import HOME
    return HOME / "work" / hashlib.sha1(str(Path(key).resolve()).encode("utf-8")).hexdigest()[:16]


def places(key: str) -> list[tuple[Path, Path]]:
    """作業を書く場所の候補（隣、書けなければ利用者のデータの置き場）"""
    p = Path(key)
    near = (p.with_name(p.name + ORA), p.with_name(p.name + INFO))
    far = _fallback(key)
    return [near, (far.with_name(far.name + ORA), far.with_name(far.name + INFO))]


def is_work_file(path: str | Path) -> bool:
    name = Path(path).name
    return name.endswith(ORA) or name.endswith(INFO)


def is_redpen_result(path: str | Path) -> bool:
    """前の版が出力の置き場に書いた、赤ペンの直しだけの絵か（PNG に埋めた mode が「直す」）"""
    from chatdraw.finishers import embedded
    return embedded(path).get("mode") == "直す"


def discard_unused_redpen(canvas) -> int:
    """使っていない赤ペンの直しのレイヤー（隠したもの）を捨て、元に戻した直しの入ったやり直すの記録も捨てる。
    描いて残したレイヤーには触らない。捨てた枚数を返す"""
    keep = [l for l in canvas.layers if not (getattr(l, "redpen", False) and not l.visible)]
    dropped = len(canvas.layers) - len(keep)
    if dropped and keep:
        cur = canvas.layers[canvas.current] if 0 <= canvas.current < len(canvas.layers) else None
        canvas.layers = keep
        canvas.current = next((i for i, l in enumerate(keep) if l is cur), len(keep) - 1)
        canvas.rebuild()
    elif dropped:
        dropped = 0   # 全部が隠した直しなら、絵が無くなるので残す
    if any(e[0] == "all" and any(getattr(l, "redpen", False) for l in e[1]) for e in canvas.redo_stack) or dropped:
        canvas.redo_stack.clear()
        canvas.redo_names.clear()
    canvas.redpen.undone.clear()
    return dropped


def capture(canvas) -> dict:
    """今の作業を写す（画面の糸で呼ぶ。画素は写しなので、このあと描き続けても中身は変わらない）"""
    from chatdraw.canvas import Layer
    pen = canvas.redpen
    sel = canvas.selection
    return {
        "layers": [Layer(l.name, l.image.copy(), l.visible, l.opacity, l.locked, getattr(l, "redpen", False)) for l in canvas.layers],
        "info": {
            "version": VERSION, "app": "CharacterDesigner", "size": list(canvas.size_px()), "current": canvas.current,
            "layers": [{"name": l.name, "locked": l.locked, "redpen": getattr(l, "redpen", False)} for l in canvas.layers],
            "marks": [[[p.x(), p.y()] for p in pts] for pts in pen.marks], "notes": list(pen.texts), "hidden": list(pen.hidden),
            "selection": [sel.x(), sel.y(), sel.width(), sel.height()] if sel is not None else None,
            "view": {"zoom": canvas.zoom(), "angle": getattr(canvas, "angle", 0.0), "flipped": bool(getattr(canvas, "flipped", False)),
                     "fit": bool(getattr(canvas, "auto_fit", True))},
        },
        "merged": canvas.flatten().copy(),
    }


def write(state: dict, key: str) -> Path:
    """capture の中身を書く（裏の糸で呼べる）。隣に書けなければ利用者のデータの置き場に書く。書いた ORA の場所を返す"""
    from types import SimpleNamespace
    from chatdraw import project
    snap = {"size": tuple(state["info"]["size"]), "merged": state["merged"],
            "layers": [SimpleNamespace(name=l.name, visible=l.visible, opacity=l.opacity, image=l.image) for l in state["layers"]]}
    last = None
    for ora, info in places(key):
        try:
            ora.parent.mkdir(parents=True, exist_ok=True)
            project.write_ora(snap, ora)
            part = info.with_name(info.name + ".part")
            part.write_text(json.dumps({**state["info"], "image": str(key)}, ensure_ascii=False, indent=1), encoding="utf-8")
            part.replace(info)
            return ora
        except OSError as e:
            last = e
    raise last or OSError("作業を書けませんでした")


def read(key: str) -> dict | None:
    """書いた作業を読む（裏の糸で呼べる）。無い・壊れていれば None"""
    from chatdraw import project
    from chatdraw.canvas import Layer
    for ora, info in places(key):
        if not (ora.is_file() and info.is_file()):
            continue
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
            _meta, parts = project.read_ora(ora)
        except (OSError, ValueError, KeyError):
            continue
        rows = data.get("layers", [])
        layers = []
        for i, (name, img, visible, opacity) in enumerate(parts):
            row = rows[i] if i < len(rows) else {}
            from PySide6.QtGui import QImage
            layers.append(Layer(name, img.convertToFormat(QImage.Format_ARGB32_Premultiplied), visible, opacity,
                                bool(row.get("locked", False)), bool(row.get("redpen", False))))
        return {"layers": layers, "info": data}
    return None


def plain(state: dict) -> bool:
    """開いただけの絵か（絵 1 枚と空のレイヤーだけで、赤ペンの印も無い）。それなら作業のファイルは置かない"""
    from PySide6.QtGui import QImage
    info = state["info"]
    if info.get("marks") or len(state["layers"]) > 2 or any(l.locked or l.opacity < 1 or not l.visible for l in state["layers"]):
        return False
    filled = 0
    for l in state["layers"]:
        a = l.image.convertToFormat(QImage.Format_Alpha8)
        if bytes(a.constBits()).strip(b"\0"):
            filled += 1
    names = [l.name for l in state["layers"]]
    return filled <= 1 and "レイヤー 1" in names


def remove(key: str):
    for ora, info in places(key):
        ora.unlink(missing_ok=True)
        info.unlink(missing_ok=True)


def apply(canvas, state: dict, undo: tuple | None = None):
    """read か capture の中身をキャンバスに置く（画面の糸で呼ぶ）。undo は覚えておいた元に戻すの記録"""
    from PySide6.QtCore import QRect
    info = state["info"]
    layers = [l.copy() for l in state["layers"]]
    canvas._reset(layers, max(0, min(int(info.get("current", 0)), len(layers) - 1)))
    pen = canvas.redpen
    hidden = info.get("hidden", [])
    for i, (pts, note) in enumerate(zip(info.get("marks", []), info.get("notes", []))):
        pen.marks.append([QPointF(x, y) for x, y in pts])
        pen.texts.append(note)
        pen.hidden.append(bool(hidden[i]) if i < len(hidden) else False)
    pen.update()
    pen._changed()
    sel = info.get("selection")
    if sel:
        canvas.set_selection(QRect(*[int(v) for v in sel]))
    view = info.get("view") or {}
    if not view.get("fit", True) and view.get("zoom"):
        canvas.set_zoom(float(view["zoom"]))
    if view.get("flipped"):
        canvas.flip_view(True)
    if view.get("angle"):
        canvas.set_angle(float(view["angle"]))
    if undo is not None:
        u, un, r, rn = undo
        canvas.undo_stack[:], canvas.undo_names[:] = list(u), list(un)
        canvas.redo_stack[:], canvas.redo_names[:] = list(r), list(rn)
        canvas.history_changed.emit()


def undo_of(canvas) -> tuple:
    return (list(canvas.undo_stack), list(canvas.undo_names), list(canvas.redo_stack), list(canvas.redo_names))
