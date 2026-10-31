"""アプリが使うディレクトリを 1 か所にまとめ、エクスプローラーで開く。

置き場があちこちにあると、利用者は描いた絵や模型をどこに置いたか探すことになる。
メニュー「ファイル」の「ディレクトリを開く」と、道を見せる所の「開く」ボタンは、どれもここを通す。
まだ無いディレクトリは作ってから開く（開けずに何も起きないのを避ける）。
"""
from __future__ import annotations

from pathlib import Path


def folders(settings) -> list[tuple[str, Path, str]]:
    """（メニューの名前、道、説明）の並び。道は開くたびに決める（設定で保存先を変えたらすぐ合うように）"""
    from chatdraw import paths
    from chatdraw.project import autosave_path
    out = Path(settings.get("output_dir"))
    return [
        ("描いた絵", out, "描いた絵・線画・ドット絵・タイムラプスを保存する所（設定の「保存」で変えられます）"),
        ("自動保存の作業ファイル", autosave_path().parent, "閉じたときや落ちたときに残す作業ファイル"),
        ("模型の置き場", paths.LLM_HOME, "絵と言葉の模型を置く所。ほかの自作アプリと共有します"),
        ("手で置く模型", paths.LLM_HOME / "manual", ".safetensors か、model_index.json のあるディレクトリを置くと一覧に出ます"),
        ("資料", paths.HOME / "library", "参考に集めた絵"),
        ("設定と記録", paths.HOME, "設定、記録（chatdraw.log、setup.log）。困ったときに中を見たり渡したりします"),
    ]


def open_folder(path: Path | str) -> Path:
    """ディレクトリを作ってから OS のファイルの画面で開く"""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
    return p


def fill_menu(menu, settings, parent=None):
    """「ディレクトリを開く」の下に、置き場を 1 つずつ並べる"""
    from PySide6.QtGui import QAction
    menu.clear()
    for name, path, tip in folders(settings):
        act = QAction(name, parent or menu, triggered=lambda _=False, p=path: open_folder(p))
        act.setToolTip(f"{tip}\n{path}")
        act.setStatusTip(str(path))
        menu.addAction(act)
    menu.setToolTipsVisible(True)
