"""絵ごとの作業の情報（レイヤー、赤ペンの印と指示、選んだレイヤー、表示の倍率と回転、元に戻すの記録）を残して戻す。

履歴やライブラリーから別の絵へ移ると、キャンバスは新しい絵に置き換わる。前は置き換えた時点でレイヤーと赤ペンの印が消え、
同じ絵へ戻っても絵 1 枚だけに戻っていた。ここでは絵の置き場ごとに作業を残す。
- レイヤーの画素・名前・不透明度・表示は ORA（この下の write_ora。Krita などでも開ける）に書く
- ORA に入らない物（ロック、赤ペンの直しの印、赤ペンの印と指示、選んだレイヤー、表示）は隣の .work.json に書く
- 元に戻すの記録はファイルに書かず、アプリを開いている間だけ覚える（画素の写しが大きく、ディスクを食うため）
どちらも別名に書いてから置き換えるので、書いている途中で落ちても前の作業は壊れない。
置き場は絵の隣。書けない場所（読み取りだけのフォルダー）の絵は、利用者のデータの置き場（paths.HOME / work）に書く。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

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


from chatdraw.redpenclean import is_redpen_result, old_redpen_files  # noqa: E402,F401  前の版からの呼び名


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
            "shapes": [_path_rows(pen.shape_of(n)) for n in range(1, len(pen.marks) + 1)],
            "selection": [sel.x(), sel.y(), sel.width(), sel.height()] if sel is not None else None,
            "view": {"zoom": canvas.zoom(), "angle": getattr(canvas, "angle", 0.0), "flipped": bool(getattr(canvas, "flipped", False)),
                     "fit": bool(getattr(canvas, "auto_fit", True))},
        },
        "merged": canvas.flatten().copy(),
    }


def write(state: dict, key: str) -> Path:
    """capture の中身を書く（裏の糸で呼べる）。隣に書けなければ利用者のデータの置き場に書く。書いた ORA の場所を返す"""
    from types import SimpleNamespace
    snap = {"size": tuple(state["info"]["size"]), "merged": state["merged"],
            "layers": [SimpleNamespace(name=l.name, visible=l.visible, opacity=l.opacity, image=l.image) for l in state["layers"]]}
    last = None
    for ora, info in places(key):
        try:
            ora.parent.mkdir(parents=True, exist_ok=True)
            write_ora(snap, ora)
            part = info.with_name(info.name + ".part")
            part.write_text(json.dumps({**state["info"], "image": str(key)}, ensure_ascii=False, indent=1), encoding="utf-8")
            part.replace(info)
            return ora
        except OSError as e:
            last = e
    raise last or OSError("作業を書けませんでした")


def read(key: str) -> dict | None:
    """書いた作業を読む（裏の糸で呼べる）。無い・壊れていれば None"""
    from chatdraw.canvas import Layer
    for ora, info in places(key):
        if not (ora.is_file() and info.is_file()):
            continue
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
            _meta, parts = read_ora(ora)
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
    shapes = info.get("shapes", [])
    for i, (pts, note) in enumerate(zip(info.get("marks", []), info.get("notes", []))):
        pen.marks.append([QPointF(x, y) for x, y in pts])
        pen.texts.append(note)
        pen.hidden.append(bool(hidden[i]) if i < len(hidden) else False)
        pen.shapes.append(_rows_path(shapes[i]) if i < len(shapes) else None)
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


def _path_rows(path):
    """形の印を JSON に書ける形（角の並びの並び）にする。手で描いた印（None）は None"""
    if path is None:
        return None
    return [[[round(p.x(), 2), round(p.y(), 2)] for p in poly] for poly in path.toSubpathPolygons()]


def _rows_path(rows):
    if not rows:
        return None
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainterPath, QPolygonF
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)   # 穴（自動選択で選んだ物の中の抜け）を穴のまま戻す
    for poly in rows:
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
        path.closeSubpath()
    return path


# ---- ORA（OpenRaster。Krita などでも開ける）。作業を絵ごとに残すためだけに使う ----
def _place(img: QImage, w: int, h: int, x: int, y: int) -> QImage:
    """レイヤーの絵を、キャンバスの大きさの透明な絵の (x, y) に置く（位置を保つ）"""
    from PySide6.QtGui import QPainter
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(0)
    if not img.isNull() and img.width() and img.height():
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(x, y, img)
        p.end()
    return out


def write_ora(snap: dict, path: str | Path):
    """OpenRaster の決まりで書く: 先頭に縮めない mimetype、stack.xml（上のレイヤーから）、レイヤーごとの PNG、
    重ねた 1 枚（mergedimage.png）と小さな見本。途中で落ちても前のファイルを壊さないよう別名に書いてから替える"""
    from xml.sax.saxutils import quoteattr
    from PySide6.QtCore import Qt
    w, h = snap["size"]
    path = Path(path)
    part = path.with_name(path.name + ".part")
    rows = []
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        for i, layer in enumerate(snap["layers"]):
            src = f"data/{i:03d}.png"
            z.writestr(src, _png_bytes(layer.image))
            rows.append(f'  <layer name={quoteattr(layer.name)} src="{src}" x="0" y="0" '
                        f'opacity="{layer.opacity:.4f}" visibility="{"visible" if layer.visible else "hidden"}"/>')
        z.writestr("stack.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<image version="0.0.5" w="{w}" h="{h}">\n <stack>\n'
                   + "\n".join(reversed(rows)) + "\n </stack>\n</image>\n")
        z.writestr("mergedimage.png", _png_bytes(snap["merged"]))
        z.writestr("Thumbnails/thumbnail.png", _png_bytes(snap["merged"].scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
    part.replace(path)


def read_ora(path: str | Path) -> tuple[dict, list]:
    """ORA を読んで read と同じ形で返す。入れ子の stack は中のレイヤーを順に並べ、隠した stack の中は隠す"""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("stack.xml"))
        w, h = int(root.get("w")), int(root.get("h"))
        top_first = []

        def walk(node, shown, alpha):
            for child in node:
                vis = shown and child.get("visibility", "visible") != "hidden"
                op = alpha * float(child.get("opacity", 1.0))
                if child.tag == "stack":
                    walk(child, vis, op)
                elif child.tag == "layer" and child.get("src"):
                    img = _qimage_from(z.read(child.get("src")))
                    x, y = int(float(child.get("x", 0))), int(float(child.get("y", 0)))
                    top_first.append((child.get("name", ""), _place(img, w, h, x, y), vis, op))
        stack = root.find("stack")
        walk(stack if stack is not None else root, True, 1.0)
    if not top_first:
        raise ValueError("レイヤーの無い ORA です")
    layers = list(reversed(top_first))
    return {"app": "ORA", "size": [w, h], "current": len(layers) - 1}, layers



def _png_bytes(img):
    from chatdraw.project import _png
    return _png(img)


def _qimage_from(data):
    from PySide6.QtGui import QImage
    return QImage.fromData(data)
