"""キャラクターデザインを、本体の窓に拡張として付ける（atelier/extensions.py）。

本体はこのパッケージを読まない。ここが本体の公開している口に、キャラクターデザインのメニュー・ファイルのメニューの項目・
ライブラリーのタブ・モード・描く仕組みへの人物の渡し方・表情差分の渡し方を足す。
本体とは別のパッケージにしてあり、entry points の `atelier.extensions` の組で本体に見つけてもらう。本体の側にキャラクターデザインの名前を残さないため。
"""
from __future__ import annotations

import types

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QListWidgetItem, QMenu

from atelier.app import modes
from character_designer.window_part import CharaWindowPart
from atelier.ui.tour import Step

MENU = "キャラクターデザイン"
MODE = "designer"
MODE_SPEC = dict(
    name="キャラクターデザイナー", sub="設定、三面図、表情差分、キャラクターシート、追加資料",
    tip="人物の設定を書き、三面図・表情差分・追加資料を描いて、キャラクターシートと .chara にまとめます",
    menus=(MENU,), hide_panels=("brushes",),
    presets=("標準", "キャラデザ", "アイコン", "ラフを清書"))
# ファイルのメニューに足す項目: 名前、窓のメソッドの名前、ツールチップ
FILE_ITEMS = (
    ("キャラクターを新しく作る…", "charafile_new", "名前・見た目・服・性格などの設定を書いて、新しいキャラクターを作ります"),
    ("キャラクターを開く…", "charafile_open", "キャラクターファイル（.chara）を開きます。開いた人物の設定・目・色・参考画像・LoRA で描きます"),
    ("キャラクターを保存", "charafile_save", "開いている人物を、設定資料と絵ごとキャラクターファイルに保存します"),
    ("キャラクターを書き出す…", "charafile_export", "開いている人物を、置き場を選んでキャラクターファイルに書き出します。人に渡すときに使います"),
)


def _mode_tour(w) -> list[Step]:
    bar = lambda: w.menuBar()
    return [
        Step(lambda: None, "キャラクターデザイナーのモード", "人物の設定から、三面図・表情差分・キャラクターシートを作るモードです。"),
        Step(bar, MENU, "「キャラクターデザイン」のメニューの「キャラデザを作る…」で、設定を書くと残りを順に描きます。\n"
             "「追加資料」から四面図・ポーズ差分・髪型差分などを 1 つずつ足せます。"),
        Step(bar, "一括生成とシート", "「一括生成…」で複数の人物の三面図と表情差分をまとめて描けます。\n"
             "「キャラクターシートを作る」で 1 枚に並べ、PSD と PNG で保存します。"),
    ]


class CharaExtension:
    name = "chara"

    def attach(self, window) -> None:
        # 窓のメソッドとして呼ばれていた名前（w.chara_design、w.charafile_open など）をそのまま使えるよう、窓の物に結び付ける
        for name, fn in vars(CharaWindowPart).items():
            if callable(fn) and not name.startswith("__"):
                setattr(window, name, types.MethodType(fn, window))
        self._add_menu(window)
        self._add_file_items(window)
        self._add_library_tab(window)
        window.studio_hooks.append(lambda studio: self._give_character(window, studio))
        window.expression_sources.append(lambda: self._expressions(window))
        modes.register(MODE, dict(MODE_SPEC, tour=_mode_tour), after="illustrator")
        window.add_mode(MODE)

    def unload(self) -> None:
        modes.unregister(MODE)

    @staticmethod
    def _add_menu(window) -> None:
        window.chara_menu = QMenu(MENU, window)   # 窓を親にして作り、参照を持つ（文字だけで足すと中身ごと消えた）
        window.menuBar().insertMenu(window.logo_menu.menuAction(), window.chara_menu)
        window.chara_menu.aboutToShow.connect(lambda: window._fill_chara_menu())
        window._fill_chara_menu()

    @staticmethod
    def _add_file_items(window) -> None:
        """1 人分の設定・絵・シート・参考画像・LoRA の選び方を 1 つに持つ .chara の項目を、保存と書き出しの間に足す"""
        menu, anchor = window.file_menu, window.file_extension_anchor
        menu.insertSeparator(anchor)
        for label, method, tip in FILE_ITEMS:
            # 押したときに窓から引く（結び付けたメソッドを入れ替えても、入れ替えたほうを呼ぶ）
            act = QAction(label, window, triggered=lambda _=False, m=method: getattr(window, m)())
            act.setToolTip(tip)
            menu.insertAction(anchor, act)

    @staticmethod
    def _add_library_tab(window) -> None:
        """ライブラリーの置き場の .chara を並べるタブ。ダブルクリックで開き、その人物で描く"""
        from atelier.panels.library_panel import _grid
        panel = window.library_panel
        grid = _grid()
        grid.setToolTip("キャラクターファイル。ダブルクリックで開くと、その人物の設定・目・色・参考画像・LoRA で描きます")
        grid.itemDoubleClicked.connect(lambda it: window.charafile_open(it.data(Qt.UserRole + 1)))
        panel.tabs.insertTab(2, grid, "キャラクター")   # 作品・資料の次、好みの前
        panel.characters = grid
        panel.refresh_characters = lambda: _fill_characters(grid)
        panel.refresh_hooks.append(panel.refresh_characters)
        panel.refresh_characters()

    @staticmethod
    def _give_character(window, studio) -> None:
        """モデルを替えて描く仕組みを作り直しても、開いている人物で描き続ける"""
        from character_designer import chara_file as charafile
        if getattr(window, "chara_file", None):
            studio.character = charafile.for_studio(window.chara_file)

    @staticmethod
    def _expressions(window) -> tuple[str, list]:
        """使う人物の表情差分の絵（ロゴ・スタンプの「表情差分をまとめてスタンプにする」が使う）"""
        from character_designer import chara_design as charadesign
        ident = getattr(window, "chara_id", "")
        return ident, (charadesign.expression_files(ident) if ident else [])


def _fill_characters(grid) -> None:
    """キャラクターのタブを並べ直す。小さな絵は .chara の中の thumb.png（無ければ名前だけ）"""
    import json
    import zipfile
    from character_designer import chara_file as charafile
    grid.clear()
    for path in charafile.files_in_library():
        try:
            with zipfile.ZipFile(path) as z:
                man = json.loads(z.read("manifest.json").decode("utf-8"))
                raw = z.read("thumb.png") if "thumb.png" in z.namelist() else b""
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue
        item = QListWidgetItem(str(man.get("name", path.stem))[:10])
        pm = QPixmap()
        if raw and pm.loadFromData(raw):
            item.setIcon(QIcon(pm.scaled(176, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        item.setData(Qt.UserRole + 1, str(path))
        item.setToolTip(f"{man.get('name', '')}\n{man.get('profile', {}).get('look', '')}\n更新 {man.get('updated', '')}")
        grid.addItem(item)


EXTENSION = CharaExtension()
