"""画面の言葉の切り替え（日本語が既定、英語を選べる）。

画面の言葉はコードに日本語で書いたまま、表示の直前に表（EN）で引き換える。Qt の tr と .qm の仕組みは、翻訳のファイルを作る道具
（lupdate、lrelease）が配布物に要り、言葉を足すたびに組み直しが要るため使わない。表に無い言葉は日本語のまま出す（欠けても止まらない）。
選んだ言語は設定の「言語」に残し、次に開いたときから当てる（開いている窓の言葉を全部作り直すと、開いた欄や選んだ物が崩れるため）。
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

LANGS = ("日本語", "English")

EN = {
    # メニュー
    "ファイル": "File", "編集": "Edit", "表示": "View", "AI": "AI", "キャラクターデザイン": "Character Design",
    "ロゴ・スタンプ": "Logos & Stamps", "設定": "Settings", "選択範囲": "Selection", "レイヤー": "Layer", "ウィンドウ": "Window",
    "ヘルプ": "Help", "書き出す": "Export", "ディレクトリを開く": "Open Folder", "テーマ": "Theme", "タイムラプス": "Timelapse",
    "欄の位置": "Panel Position", "帯の位置": "Toolbar Position", "機能ごとの案内": "Feature Guides",
    "設定…": "Settings…", "キーの設定…": "Key Bindings…", "使い方ツアー": "Guided Tour", "操作方法": "How to Use",
    "手順書（入れ方・模型の置き方・困ったとき）": "Manual (install, models, troubleshooting)", "記録の置き場を開く": "Open Log Folder",
    "更新を確かめる": "Check for Updates", "お気に入りの作風…": "Favorite Styles…", "予約の一覧": "Scheduled Requests",
    "予約を全部消す": "Clear All Scheduled", "参考画像を探す…": "Find Reference Images…",
    "新規": "New", "開く…": "Open…", "保存": "Save", "名前を付けて保存…": "Save As…", "終了": "Quit",
    "元に戻す": "Undo", "やり直す": "Redo", "切り取り": "Cut", "コピー": "Copy", "貼り付け": "Paste",
    # 主な部品
    "描く": "Draw", "止める": "Stop", "送る": "Send", "指示": "Prompt", "作風": "Style", "直す・仕上げ": "Fix & Finish",
    "詳しい設定": "Advanced", "チャット": "Chat", "履歴": "History", "色": "Color", "ブラシ": "Brushes", "進み": "Progress",
    "ライブラリー": "Library", "言語": "Language", "閉じる": "Close", "消す": "Delete", "使う": "Use", "名前": "Name", "言葉": "Words",
}


def current(store: QSettings | None = None) -> str:
    store = store or QSettings("CharacterDesigner", "chatdraw-settings")
    v = str(store.value("language", LANGS[0]) or LANGS[0])
    return v if v in LANGS else LANGS[0]


def t(text: str, lang: str | None = None) -> str:
    """画面に出す言葉。英語が選ばれていて表にあれば英語、無ければそのまま"""
    lang = lang or current()
    if lang != "English":
        return text
    if text in EN:
        return EN[text]
    core = text.replace("&", "")
    return EN.get(core, text)


def translate_menus(bar, lang: str | None = None) -> int:
    """メニューの帯と、その下のメニュー・項目の見出しを引き換える。換えた数を返す（試験で見る）"""
    lang = lang or current()
    if lang == "日本語":
        return 0
    n = 0
    seen = set()

    def walk(menu):
        nonlocal n
        if id(menu) in seen:
            return
        seen.add(id(menu))
        for a in menu.actions():
            new = t(a.text(), lang)
            if new != a.text():
                a.setText(new)
                n += 1
            if a.menu() is not None:
                walk(a.menu())
    walk(bar)
    return n


def translate_widgets(root, lang: str | None = None) -> int:
    """押しボタン・欄の見出し・タブの見出しを引き換える"""
    lang = lang or current()
    if lang == "日本語":
        return 0
    from PySide6.QtWidgets import QAbstractButton, QDockWidget, QTabWidget
    n = 0
    for w in root.findChildren(QAbstractButton):
        new = t(w.text(), lang)
        if new != w.text():
            w.setText(new)
            n += 1
    for d in root.findChildren(QDockWidget):
        new = t(d.windowTitle(), lang)
        if new != d.windowTitle():
            d.setWindowTitle(new)
            n += 1
    for tabs in root.findChildren(QTabWidget):
        for i in range(tabs.count()):
            new = t(tabs.tabText(i), lang)
            if new != tabs.tabText(i):
                tabs.setTabText(i, new)
                n += 1
    return n
