"""前の版が出力の置き場に書いた、赤ペンの直しだけの絵（直した所のほかは透明）を見つける。

0.5.19 までの版は、赤ペンの直しの結果を出力の置き場に書き、履歴とライブラリーに足していた。
レイヤーを消してもその絵が残り、履歴・ライブラリーから押すと透明な絵が出て、ゴミに見えた。
今の版は直しをレイヤーにだけ置くので、残った絵はアプリがごみ箱へ移す（消すのは利用者がごみ箱で選んだときだけ）。
"""
from __future__ import annotations

from pathlib import Path


def is_redpen_result(path: str | Path) -> bool:
    """赤ペンの直しだけの絵か（PNG に埋めた mode が「直す」）"""
    from chatdraw.finishers import embedded
    try:
        return embedded(path).get("mode") == "直す"
    except Exception:   # noqa: BLE001  読めない絵は直しの絵とみなさない（利用者の絵を動かさない）
        return False


def old_redpen_files(roots) -> list[Path]:
    """出力の置き場から、赤ペンの直しだけの絵を探す。ごみ箱（.trash）とアプリの置き場（. で始まるディレクトリ）の中は見ない"""
    found: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.png")):
            rel = p.relative_to(root).parts
            if any(part.startswith(".") for part in rel[:-1]) or p.name.endswith(".parts.png") or p in found:
                continue
            if is_redpen_result(p):
                found.append(p)
    return found
