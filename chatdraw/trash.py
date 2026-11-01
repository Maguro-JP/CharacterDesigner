"""アプリのごみ箱。消した絵をすぐには消さず、ここへ移して戻せるようにする。

OS のごみ箱へ送ると、アプリから戻す道が無い（Windows のごみ箱を外から開いて元の場所へ戻す API は無い）。
そこで消した絵はアプリのデータの置き場の trash へ、消した 1 回ごとに 1 つのディレクトリとして移し、
元の場所とライブラリーの記録を manifest.json に残す。「戻す」で元の場所と一覧へ戻し、「空にする」で初めて本当に消す。

絵と一緒に置いた付属のファイル（頼みと設定の .json、部位分けの .parts.png など、同じ名前で始まる物）も一緒に動かす。
絵だけを動かすと、戻したときに「この設定で描き直す」が使えなくなる。
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path


def companions(path: str | Path) -> list[Path]:
    """絵と、その付属のファイル。名前が「絵の名前.」で始まる物を付属とみなす（a.png と a.json、a.parts.png）。
    a1.png は a.png の付属にしない（点の前までが同じ名前の物だけ）"""
    p = Path(path)
    if not p.parent.is_dir():
        return [p] if p.exists() else []
    found = [p] if p.exists() else []
    for q in sorted(p.parent.iterdir()):
        if q != p and q.is_file() and q.name.startswith(p.stem + "."):
            found.append(q)
    return found


class Trash:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, paths: list[str], library_items: list[dict] | None = None, label: str = "") -> str | None:
        """絵（と付属のファイル）をごみ箱へ移す。移した 1 回分の名前を返す。移す物が無ければ None"""
        files = []
        for p in paths:
            for f in companions(p):
                if f not in files:
                    files.append(f)
        if not files and not library_items:
            return None
        key = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        box = self.root / key
        box.mkdir(parents=True, exist_ok=True)
        moved = []
        for i, f in enumerate(files):
            dst = box / f"{i:03d}-{f.name}"
            shutil.move(str(f), dst)
            moved.append({"from": str(f), "stored": dst.name})
        manifest = {"when": time.strftime("%Y-%m-%d %H:%M"), "label": label or (Path(paths[0]).name if paths else ""),
                    "images": [str(p) for p in paths], "files": moved, "library": library_items or []}
        (box / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return key

    def entries(self) -> list[dict]:
        """ごみ箱の中身（新しい順）。1 件は消した 1 回分"""
        out = []
        if not self.root.is_dir():
            return out
        for box in sorted(self.root.iterdir(), reverse=True):
            try:
                m = json.loads((box / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            m["key"] = box.name
            out.append(m)
        return out

    def restore(self, key: str) -> dict | None:
        """元の場所へ戻す。元の場所に同じ名前の物が既にあれば上書きせず、名前に「-戻し」を付けて戻す。
        戻した記録（manifest。images は戻した先の場所）を返す"""
        box = self.root / key
        try:
            m = json.loads((box / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        renamed = {}
        for f in m["files"]:
            src, dst = box / f["stored"], Path(f["from"])
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                new = dst.with_name(dst.name.split(".", 1)[0] + "-戻し." + dst.name.split(".", 1)[1]) if "." in dst.name else \
                    dst.with_name(dst.name + "-戻し")
                renamed[str(dst)] = str(new)
                dst = new
            shutil.move(str(src), dst)
        m["images"] = [renamed.get(p, p) for p in m["images"]]
        for it in m.get("library", []):
            it["path"] = renamed.get(it.get("path", ""), it.get("path", ""))
        shutil.rmtree(box, ignore_errors=True)
        return m

    def purge(self, key: str | None = None):
        """本当に消す。key が無ければごみ箱を空にする"""
        if key is None:
            shutil.rmtree(self.root, ignore_errors=True)
        else:
            shutil.rmtree(self.root / key, ignore_errors=True)


def confirm(parent, title: str, text: str) -> bool:
    from PySide6.QtWidgets import QMessageBox
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes


def open_dialog(w):
    """ごみ箱の画面。消した 1 回分ずつ並べ、選んで「戻す」か「本当に消す」。「空にする」は確かめてから消す"""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
                                   QPushButton, QVBoxLayout)
    dlg = QDialog(w)
    dlg.setWindowTitle("ごみ箱")
    lay = QVBoxLayout(dlg)
    note = QLabel()
    note.setWordWrap(True)
    lay.addWidget(note)
    view = QListWidget()
    view.setViewMode(QListView.IconMode)
    view.setIconSize(QSize(88, 120))
    view.setGridSize(QSize(100, 150))
    view.setResizeMode(QListView.Adjust)
    view.setMovement(QListView.Static)
    view.setSelectionMode(QListWidget.ExtendedSelection)
    lay.addWidget(view, 1)

    def fill():
        view.clear()
        rows = w.trash.entries()
        note.setText("消した絵はここに残ります。選んで「戻す」で元の場所に戻します。" if rows else "ごみ箱は空です。")
        for m in rows:
            box = w.trash.root / m["key"]
            first = next((f for f in m["files"] if f["stored"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))), None)
            item = QListWidgetItem(m["when"][5:])
            if first:
                pm = QPixmap(str(box / first["stored"]))
                if not pm.isNull():
                    item.setIcon(QIcon(pm.scaled(176, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item.setToolTip(f"{m['when']} に消した {Path(m['images'][0]).name if m['images'] else m['label']}"
                            + (f" ほか {len(m['images']) - 1} 枚" if len(m["images"]) > 1 else ""))
            item.setData(Qt.UserRole, m["key"])
            view.addItem(item)
        empty.setEnabled(bool(rows))

    def chosen():
        return [it.data(Qt.UserRole) for it in view.selectedItems()]

    def back():
        for key in chosen():
            w.restore_trash(key)
        fill()

    def really(keys):
        if not keys:
            return
        if confirm(dlg, "本当に消す", f"{len(keys)} 件を本当に消します。戻せません。"):
            for k in keys:
                w.trash.purge(k)
            fill()

    row = QHBoxLayout()
    restore = QPushButton("戻す")
    restore.setToolTip("選んだ絵を、消す前の場所と一覧に戻します")
    restore.clicked.connect(back)
    gone = QPushButton("本当に消す…")
    gone.setToolTip("選んだ絵をごみ箱からも消します（戻せません）")
    gone.clicked.connect(lambda: really(chosen()))
    empty = QPushButton("空にする…")
    empty.setToolTip("ごみ箱の絵を全部消します（戻せません）")
    empty.clicked.connect(lambda: really([m["key"] for m in w.trash.entries()]))
    for b in (restore, gone, empty):
        row.addWidget(b)
    row.addStretch()
    close = QDialogButtonBox(QDialogButtonBox.Close)
    close.rejected.connect(dlg.reject)
    row.addWidget(close)
    lay.addLayout(row)
    view.itemDoubleClicked.connect(lambda _it: back())

    def picked():
        # 選ぶ前は押しても何も起きなかったので、選ぶまで押せない形にする（理由はツールチップ）
        on = bool(view.selectedItems())
        restore.setEnabled(on)
        gone.setEnabled(on)
        restore.setToolTip("選んだ絵を、消す前の場所と一覧に戻します" if on else "戻す絵を一覧から選ぶと押せます")
        gone.setToolTip("選んだ絵をごみ箱からも消します（戻せません）" if on else "消す絵を一覧から選ぶと押せます")
    view.itemSelectionChanged.connect(picked)
    fill()
    picked()
    dlg.resize(560, 420)
    dlg.fill = fill   # 開いたまま別の所で消したときに並べ直す
    w._trash_dialog = dlg
    dlg.open()
    return dlg
