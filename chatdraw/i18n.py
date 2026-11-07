"""画面の言葉の切り替え（日本語が既定、英語を選べる）。

画面の言葉はコードに日本語で書いたまま、表示の直前に表（EN）で引き換える。Qt の tr と .qm の仕組みは、翻訳のファイルを作る道具
（lupdate、lrelease）が配布物に要り、言葉を足すたびに組み直しが要るため使わない。表に無い言葉は日本語のまま出す（欠けても止まらない）。
選んだ言語は設定の「言語」に残し、次に開いたときから当てる（開いている窓の言葉を全部作り直すと、開いた欄や選んだ物が崩れるため）。
メニューだけでなく、ボタン・欄・タブ・ツールチップ・ダイアログ・右クリックのメニューも、出す直前に引き換える（install）。
保存や引き当てに使う名前（タブの並び、キーの割り当て、メニューの並び）は ja で日本語に戻してから使う。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QSettings

LANGS = ("日本語", "English")

EN = {
    # メニュー
    "ファイル": "File", "編集": "Edit", "表示": "View", "AI": "AI", "キャラクターデザイン": "Character Design",
    "ロゴ・スタンプ": "Logos and Stamps", "設定": "Settings", "選択範囲": "Selection", "レイヤー": "Layer", "ウィンドウ": "Window",
    "ヘルプ": "Help", "書き出す": "Export", "ディレクトリを開く": "Open Folder", "テーマ": "Theme", "タイムラプス": "Timelapse",
    "欄の位置": "Panel Position", "帯の位置": "Toolbar Position", "機能ごとの案内": "Feature Guides",
    "設定…": "Settings…", "キーの設定…": "Key Bindings…", "使い方ツアー": "Guided Tour", "操作方法": "How to Use",
    "手順書（入れ方・模型の置き方・困ったとき）": "Manual (install, models, troubleshooting)", "記録の置き場を開く": "Open Log Folder",
    "更新を確かめる": "Check for Updates", "作風の登録…": "Favorite Styles…", "予約の一覧": "Scheduled Requests",
    "予約を全部消す": "Clear All Scheduled", "参考画像を探す…": "Find Reference Images…",
    "新規": "New", "開く…": "Open…", "保存": "Save", "名前を付けて保存…": "Save As…", "終了": "Quit",
    "元に戻す": "Undo", "やり直す": "Redo", "切り取り": "Cut", "コピー": "Copy", "貼り付け": "Paste",
    # 主な部品
    "描く": "Draw", "止める": "Stop", "送る": "Send", "指示": "Prompt", "作風": "Style", "直す・仕上げ": "Fix and Finish",
    "詳しい設定": "Advanced", "チャット": "Chat", "履歴": "History", "色": "Color", "ブラシ": "Brushes", "進み": "Progress",
    "ライブラリー": "Library", "言語": "Language", "閉じる": "Close", "消す": "Delete", "使う": "Use", "名前": "Name", "言葉": "Words",
}


# メニューの外（ボタン・欄・ツールチップ・ダイアログ）。画面で目に入る順に足す
EN.update({
    # 道具（左端の帯）
    "移動": "Move", "四角の選択": "Rectangle Select", "投げなわの選択": "Lasso Select", "多角形の選択": "Polygon Select",
    "投げなわの選択（なぞって囲む）": "Lasso Select (drag around)",
    "多角形の選択（押して角を置き、ダブルクリックか Enter で閉じる）": "Polygon Select (click corners, double-click or Enter to close)",
    "ペン": "Pen", "消しゴム": "Eraser", "ぼかし": "Blur", "スプレー": "Spray", "指先（色を伸ばす）": "Smudge",
    "塗りつぶし": "Fill", "グラデーション": "Gradient", "直線": "Line", "四角": "Rectangle", "楕円": "Ellipse", "文字": "Text",
    "スポイト": "Eyedropper", "手のひら": "Hand", "拡大（Shift か右クリックで縮小）": "Zoom (Shift or right-click to zoom out)",
    "赤ペン（AI に直す所を囲む）": "Red Pen (circle what AI should fix)", "赤ペン": "Red Pen", "道具": "Tools",
    # 共通の操作
    "新規キャンバス": "New Canvas", "ごみ箱…": "Trash…", "赤ペンの印を全部消す": "Clear All Red Pen Marks",
    "すべてを選択": "Select All", "選択を解除": "Deselect", "全体を表示": "Fit to Window", "左に回す": "Rotate Left",
    "右に回す": "Rotate Right", "回転を戻す": "Reset Rotation", "新しいレイヤー": "New Layer", "レイヤーを消す": "Delete Layer",
    "選択範囲の中を消す": "Clear Selection", "選択範囲を塗る": "Fill Selection", "選択範囲を AI で直す": "Fix Selection with AI",
    "選択を外す": "Deselect", "絵をコピー": "Copy Image", "囲んだ所を直す": "Fix Marked Area", "レイヤーを足す": "Add Layer",
    "画像をレイヤーとして読み込む…": "Import Image as Layer…", "レイヤーを PNG で保存…": "Save Layer as PNG…",
    "全部のレイヤーを PNG で書き出す…": "Export All Layers as PNG…", "新しいキャンバス": "New Canvas", "画像を開く…": "Open Image…",
    # 欄の見出し
    "カラー": "Color", "パレット": "Palette", "進み": "Progress", "全体": "Overview", "作品": "Works", "参考画像": "Reference Images",
    "好み": "Preferences", "描いた絵": "Drawn Images", "描き方": "Drawing", "操作": "Controls", "資料": "Materials",
    "緊急停止": "Emergency Stop", "■ 緊急停止": "■ Emergency Stop", "配置": "Layout", "配置…": "Layout…",
    # 色の欄
    "色相": "Hue", "彩度": "Saturation", "明度": "Value", "透明度": "Opacity", "色の出方": "Color Mode", "最近の色": "Recent Colors",
    "自分のパレット": "My Palette", "読み込み": "Load", "描く色": "Foreground Color",
    "スポイト。絵の上で押した所の色を描く色にする（I）": "Eyedropper: click on the image to pick a color (I)",
    "描く色と背景色を入れ替える（X）": "Swap foreground and background colors (X)", "黒と白に戻す（D）": "Reset to black and white (D)",
    "背景色（押すと描く色と入れ替え。X キー）": "Background color (click or X to swap)",
    "今の描く色をパレットに足す": "Add the current color to the palette", "自分のパレットをファイルに保存する": "Save my palette to a file",
    "保存したパレットのファイルを読み込む": "Load a saved palette file",
    "色相（0〜359 度）": "Hue (0–359°)", "彩度（0〜100）": "Saturation (0–100)", "明度（0〜100）": "Value (0–100)",
    "描く色の不透明さ（0 で透明、100 で透けない）。ペン・塗りつぶし・形・文字に効きます":
        "Color opacity (0 = transparent, 100 = solid). Applies to pen, fill, shapes and text",
    "今の描く色の見本（市松模様が透けて見えるほど薄い）": "Current color preview (the more checkerboard shows, the more transparent)",
    # 道具の設定の帯・ブラシ
    "太さ": "Size", "濃さ": "Opacity", "塗り": "Fill", "左右対称": "Symmetry", "筆圧→太さ": "Pressure → Size",
    "筆圧→濃さ": "Pressure → Opacity", "拡大率": "Zoom",
    # AI の欄
    "模型": "Model", "描くワード": "Prompt Words", "禁止ワード": "Negative Words", "登録": "Register", "おまかせ": "Auto",
    "作成枚数": "Count", "種を固定": "Lock Seed", "参考画像に寄せる": "Follow Reference", "ラフに沿う強さ": "Sketch Strength",
    "標準": "Default", "今の設定を保存": "Save Current Settings", "もう一度描く": "Draw Again", "指示を足す": "Add Instruction",
    "絵の模型": "Image Model", "言葉の模型": "Language Model", "模型の管理": "Model Manager", "推奨だけ表示": "Recommended Only",
    "ちびキャラに": "Make Chibi", "ドット絵に": "Make Pixel Art", "線画に": "Make Line Art", "絵を 2 倍に拡大": "Upscale 2×",
    "3D に進む": "Go to 3D", "新規": "New", "ラフから": "From Sketch", "直す": "Fix",
    # ダイアログ・案内
    "はじめに": "Getting Started", "はじめる": "Start", "次へ": "Next", "戻る": "Back", "わかった": "Got it", "あとで": "Later",
    "やめる": "Cancel", "開く": "Open", "外す": "Remove", "戻す": "Restore", "選ぶ…": "Choose…", "再生": "Play",
    "既定に戻す": "Restore Defaults", "すべて既定に戻す": "Restore All Defaults", "名前を変える": "Rename",
    "本当に消す…": "Delete Permanently…", "空にする…": "Empty…", "ごみ箱": "Trash", "タグ": "Tags", "キー:": "Key:",
    "キーの設定": "Key Bindings", "ショートカット": "Shortcut", "メニューを編集": "Edit Menus", "帯を編集": "Edit Toolbars",
    "帯を固定する": "Lock Toolbars", "テーマを作る": "Create Theme", "GIF に書き出す": "Export GIF", "動画に書き出す": "Export Video",
    "待機中": "Idle", "準備中": "Preparing", "準備しています": "Preparing", "準備ができました": "Ready", "終わりました": "Done",
    "AI が描いています": "AI is drawing", "AI が入力中": "AI is typing", "ありません": "None",
    "パレットを保存": "Save Palette", "パレットを読み込む": "Load Palette", "パレット (*.json)": "Palette (*.json)",
    "このファイルはパレットとして読めませんでした": "This file could not be read as a palette.",
    "選択範囲がありません": "No selection", "貼り付ける絵がありません": "Nothing to paste",
    "四角・投げなわ・多角形の選択で範囲を選んでから使ってください": "Select an area with the rectangle, lasso or polygon tool first.",
    "絵をコピーしてから貼り付けてください": "Copy an image first, then paste.",
    "選択範囲の中をコピーします。選択が無いときは見えている絵全体をコピーします":
        "Copy inside the selection. Without a selection, copies the whole visible image",
    "選択範囲の中をコピーして消します": "Copy inside the selection and clear it",
    "コピーした絵を一番上の新しいレイヤーに貼ります": "Paste the copied image onto a new top layer",
    "選択範囲の中を描く色で塗ります": "Fill the selection with the foreground color",
    "選択範囲の中だけを、指示の欄の言葉で AI が直します": "AI fixes only inside the selection, using the prompt words",
})


def ja(text: str) -> str:
    """英語の見出しを、元の日本語の名前に戻す（保存や引き当ては日本語の名前で行うため）。表に無ければそのまま"""
    if not _JA:
        for k, v in EN.items():
            _JA.setdefault(v, k)
    return _JA.get(text, text)


_JA: dict[str, str] = {}
_KEY = re.compile(r"^(.*?)[（(]([^（）()]*)[）)]$")   # 「元に戻す（Ctrl+Z）」の後ろのキーや補い


def current(store: QSettings | None = None) -> str:
    if store is None and _ACTIVE:
        return _ACTIVE[0]
    store = store or QSettings("CharacterDesigner", "chatdraw-settings")
    v = str(store.value("language", LANGS[0]) or LANGS[0])
    return v if v in LANGS else LANGS[0]


_ACTIVE: list[str] = []   # install で決めた言語。開いている間は設定を読み直さない（次に開いたときから変わる決まり）


def t(text: str, lang: str | None = None) -> str:
    """画面に出す言葉。英語が選ばれていて表にあれば英語、無ければそのまま。
    「元に戻す（Ctrl+Z）」のように後ろに補いの付いた言葉は、前の言葉だけを引き換えて補いを残す"""
    lang = lang or current()
    if lang != "English" or not text:
        return text
    if text in EN:
        return EN[text]
    core = text.replace("&", "")
    body = core.strip()   # 「 太さ 」のように前後に空白を置いた見出しは、空白を残して中だけ換える
    pad_l, pad_r = core[:len(core) - len(core.lstrip())], core[len(core.rstrip()):]
    if body in EN:
        return pad_l + EN[body] + pad_r
    m = _KEY.match(body)
    if m and m.group(1) in EN:
        return f"{pad_l}{EN[m.group(1)]} ({m.group(2)}){pad_r}"
    return text


def translate_menus(bar, lang: str | None = None) -> int:
    """メニューの帯と、その下のメニュー・項目の見出しとツールチップを引き換える。換えた数を返す（試験で見る）"""
    lang = lang or current()
    if lang == "日本語":
        return 0
    n = 0
    seen = set()
    # QAction.menu() は呼ばない。PySide6 6.9 では呼ぶと別の包みが作られ、窓が持っていたメニューが「消えた」扱いになった
    # （英語で開くと起動の途中で止まった）。keys.collect と同じく、見出しの操作からメニューを引く表を作る
    from PySide6.QtWidgets import QApplication, QMenu
    subs = {m.menuAction(): m for m in QApplication.allWidgets() if isinstance(m, QMenu)}

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
            tip = t(a.toolTip(), lang)
            if tip != a.toolTip():
                a.setToolTip(tip)
            if a in subs:
                walk(subs[a])
    walk(bar)
    return n


def translate_widgets(root, lang: str | None = None) -> int:
    """押しボタン・見出し・欄の見出し・タブ・ツールチップ・入力の例・窓の題・帯の操作を引き換える。換えた数を返す。
    選ぶ欄（QComboBox）の中身は設定の値として残すので換えない"""
    lang = lang or current()
    if lang == "日本語":
        return 0
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QDockWidget, QGroupBox, QLabel, QLineEdit, QMessageBox, QTabWidget, QWidget
    n = 0

    def swap(get, put):
        nonlocal n
        old = get()
        new = t(old, lang)
        if new != old:
            put(new)
            n += 1

    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        swap(w.toolTip, w.setToolTip)
        if w.isWindow():
            swap(w.windowTitle, w.setWindowTitle)
        if isinstance(w, (QAbstractButton, QLabel)):
            swap(w.text, w.setText)
        elif isinstance(w, QLineEdit):
            swap(w.placeholderText, w.setPlaceholderText)
        elif isinstance(w, QGroupBox):
            swap(w.title, w.setTitle)
        elif isinstance(w, QDockWidget):
            swap(w.windowTitle, w.setWindowTitle)
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                swap(lambda i=i: w.tabText(i), lambda s, i=i: w.setTabText(i, s))
                swap(lambda i=i: w.tabToolTip(i), lambda s, i=i: w.setTabToolTip(i, s))
        if isinstance(w, QMessageBox):
            swap(w.text, w.setText)
            swap(w.informativeText, w.setInformativeText)
    for a in root.findChildren(QAction):
        swap(a.text, a.setText)
        swap(a.toolTip, a.setToolTip)
    return n


class _Watcher(QObject):
    """後から開くダイアログ・右クリックのメニュー・欄も、出す直前に引き換える"""

    def __init__(self, lang: str):
        super().__init__()
        self.lang = lang

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show:
            from PySide6.QtWidgets import QMenu, QWidget
            if isinstance(obj, QMenu):
                translate_menus(obj, self.lang)
            elif isinstance(obj, QWidget) and obj.isWindow():
                translate_widgets(obj, self.lang)
        return False


def install(app, lang: str | None = None):
    """英語を選んでいたら、アプリ全体の窓・ダイアログ・メニューを出すたびに引き換える。日本語なら何もしない"""
    lang = lang or current()
    _ACTIVE[:] = [lang]
    if app is None:
        return None
    if lang == "日本語":
        if getattr(app, "_i18n_watcher", None) is not None:
            app.removeEventFilter(app._i18n_watcher)
            app._i18n_watcher = None
        return None
    if getattr(app, "_i18n_watcher", None) is None:
        app._i18n_watcher = _Watcher(lang)
        app.installEventFilter(app._i18n_watcher)
    app._i18n_watcher.lang = lang
    return app._i18n_watcher
