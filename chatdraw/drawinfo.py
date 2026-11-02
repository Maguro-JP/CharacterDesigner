"""描いた絵の設定（模型・頼み・禁止ワード・種・大きさ・描いた日時）を、絵に埋めた記録から読んで見せる。

履歴とライブラリーの右クリックの「描いた設定を見る…」から開く。ツールチップに全部を詰めると長くなり絵の上を覆ったので、
ツールチップは短いまま、設定は小さな窓に文字で出してコピーできるようにした。
"""
from __future__ import annotations

import re
from pathlib import Path

MISSING = "記録なし"
LABELS = ("模型", "頼み（模型に渡した言葉）", "禁止ワード", "種", "大きさ", "描いた日時")


def _model_name(repo: str) -> str:
    """模型の札の名前。一覧に無い模型は、記録の名前をそのまま出す"""
    try:
        from chatdraw.models import image_model
        name = getattr(image_model(repo), "name", "") or repo
    except Exception:
        name = repo
    return str(name)


def _size(path: Path, meta: dict) -> str:
    """絵の実際の大きさ。絵が読めなければ、描くときに選んだ大きさの記録"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        return f"{w} × {h}"
    except (OSError, ValueError):
        pass
    size = meta.get("size")
    if isinstance(size, (list, tuple)) and len(size) == 2:
        return f"{size[0]} × {size[1]}"
    return MISSING


def _drawn(path: Path, meta: dict) -> str:
    """描いた日時。記録に無ければ、保存した名前（20261102-153012-種.png）から読む。ファイルの更新日時は使わない
    （ライブラリーへ保存するときに記録を埋め直すと変わり、描いた日時ではなくなる）"""
    if meta.get("drawn"):
        return str(meta["drawn"])
    m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", path.name)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{s}"
    return MISSING


def rows(path: str | Path) -> list[tuple[str, str]]:
    """見せる行（名前, 中身）。PNG に埋めた記録を先に、無ければ前の版の .json を読む。無い項目は「記録なし」"""
    from chatdraw import finishers
    path = Path(path)
    meta = finishers.sidecar(path)
    model = ""
    if meta.get("compose_model") and meta.get("model"):   # 2 段で描いた絵は、構図と仕上げの 2 つの模型
        model = f"構図: {_model_name(meta['compose_model'])} / 仕上げ: {_model_name(meta['model'])}"
    elif meta.get("model"):
        model = _model_name(meta["model"])
    prompt = meta.get("prompt") or meta.get("text") or ""
    negative = meta.get("negative")
    if negative is None:
        negative = MISSING
    elif not negative:
        negative = "なし"
    seed = meta.get("seed")
    return [
        ("模型", model or MISSING),
        ("頼み（模型に渡した言葉）", str(prompt) or MISSING),
        ("禁止ワード", str(negative)),
        ("種", MISSING if seed is None or seed == "" else str(seed)),
        ("大きさ", _size(path, meta)),
        ("描いた日時", _drawn(path, meta)),
    ]


def as_text(path: str | Path) -> str:
    return "\n".join(f"{k}: {v}" for k, v in rows(path))


def dialog(parent, path: str | Path):
    """設定を出す小さな窓。中身は選んでコピーでき、「コピー」で全部をクリップボードに入れる"""
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout
    text = as_text(path)
    d = QDialog(parent)
    d.setWindowTitle("描いた設定 — " + Path(path).name)
    lay = QVBoxLayout(d)
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setObjectName("drawinfo")
    fm = QFontMetrics(box.font())
    box.setMinimumSize(min(560, fm.horizontalAdvance("あ") * 34), fm.lineSpacing() * 10)
    lay.addWidget(box)
    row = QHBoxLayout()
    copy = QPushButton("コピー")
    copy.setToolTip("設定を全部コピーします")
    copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
    close = QPushButton("閉じる")
    close.clicked.connect(d.accept)
    row.addStretch(1)
    row.addWidget(copy)
    row.addWidget(close)
    lay.addLayout(row)
    return d


def show(parent, path: str | Path):
    d = dialog(parent, path)
    d.show()   # 窓を開いたままでも絵や履歴を触れるよう、待たせない
    return d
