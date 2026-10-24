"""ヘルプの窓。chatdraw/help/ の手順書と操作方法を、アプリの中で読む（インストールした版にも入る）。

文書は README からも辿れるよう Markdown のまま持ち、ここでは QTextBrowser で見せる。文書どうしの道（install.md など）は窓の中で開く。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

HELP = Path(__file__).with_name("help")
DOCS = {"install": ("手順書（入れ方・模型・困ったとき）", "install.md"), "manual": ("操作方法", "manual.md")}


def text(key: str) -> str:
    return (HELP / DOCS[key][1]).read_text(encoding="utf-8")


class HelpDialog(QDialog):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.resize(720, 640)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._follow)
        lay = QVBoxLayout(self)
        lay.addWidget(self.view, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("閉じる")
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self.show_doc(key)

    def show_doc(self, key: str):
        self.setWindowTitle(DOCS[key][0])
        self.view.setMarkdown(text(key))

    def _follow(self, url: QUrl):
        name = url.toString().split("#")[0]
        for key, (_title, file) in DOCS.items():
            if name.endswith(file):
                self.show_doc(key)
                return
        if url.scheme() in ("http", "https"):
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)
