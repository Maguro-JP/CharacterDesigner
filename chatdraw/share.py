"""履歴の絵を SNS に送る。

設定の「SNS 連携」で選んだ先だけを使え、オフなら右クリックの項目を止める。
アプリが勝手に投稿することはしない。絵をコピーし、その SNS の投稿の画面（公式の共有の URL）を開くので、
利用者が貼り付けて（Ctrl+V）自分で投稿する。鍵や合言葉をアプリに預ける必要がない。
"""
from __future__ import annotations

from urllib.parse import quote

# 名前と、投稿の画面を開く公式の共有の URL（text に頼みの言葉を入れる）
SERVICES = {
    "X（Twitter）": "https://x.com/intent/post?text={text}",
    "Bluesky": "https://bsky.app/intent/compose?text={text}",
    "Misskey": "https://misskey.io/share?text={text}",
}


def enabled(settings, name: str) -> bool:
    return settings.get("sns") == name


def compose_url(name: str, text: str) -> str:
    return SERVICES[name].format(text=quote(f"{text} #CharacterDesigner".strip()))


def post(window, name: str, path: str, text: str = ""):
    """絵をコピーして、投稿の画面を開く。貼り付けて投稿するのは利用者"""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if not enabled(window.settings, name):
        window.notify("SNS 連携はオフです", "info", "設定の「SNS 連携」で送る先を選ぶと使えます")
        return
    window.copy_image(path)
    QDesktopServices.openUrl(QUrl(compose_url(name, text)))
    window.notify(f"{name} の投稿の画面を開きました", "ok", "絵はコピーしてあります。投稿の欄に貼り付けて（Ctrl+V）投稿してください")
