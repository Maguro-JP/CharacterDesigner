"""起動したときに選ぶモード（イラストレーター・キャラクターデザイナー・ロゴ・エンブレム・スタンプ）。

全部の機能を 1 つの画面に並べると、メニューが 13 本になり、どこに何があるか分からなかった。
モードごとに、その仕事に要るメニュー・欄・AI のプリセットだけを出す。モードを替えても、作業中の絵とレイヤーはそのまま
（隠すのはメニューと欄だけで、キャンバスには触らない）。
選んだモードは覚え、「次から聞かない」を付けたら次からは窓を出さずにそのモードで開く。表示のメニューからいつでも替えられる。
"""
from __future__ import annotations

from chatdraw.tour import Step

# どのモードでも出すメニュー
COMMON_MENUS = ("ファイル", "編集", "表示", "AI", "設定", "選択範囲", "レイヤー", "ウィンドウ", "配置", "ヘルプ")

# 鍵: 名前、ひとこと、出すメニュー（COMMON_MENUS の外の物）、隠す欄、出す AI のプリセット
MODES = {
    "illustrator": dict(
        name="イラストレーター", sub="場面の絵、背景、加工",
        tip="場面の 1 枚や背景を描き、綺麗にする・拡大・画風などの加工をかけます",
        menus=("加工",), hide_panels=(),
        presets=("標準", "イラスト", "背景美術", "ラフを清書", "ラフから自由に", "モノクロ")),
    "designer": dict(
        name="キャラクターデザイナー", sub="設定、三面図、表情差分、キャラクターシート、追加資料",
        tip="人物の設定を書き、三面図・表情差分・追加資料を描いて、キャラクターシートと .chara にまとめます",
        menus=("キャラクターデザイン",), hide_panels=("brushes",),
        presets=("標準", "キャラデザ", "アイコン", "ラフを清書")),
    "logo": dict(
        name="ロゴ・エンブレム・スタンプ", sub="透過、単色、線の太さ、正方形、LINE スタンプの大きさ",
        tip="ロゴ・エンブレムのマークやスタンプを描き、背景を抜いて決まった大きさで書き出します",
        menus=("ロゴ・スタンプ",), hide_panels=("brushes", "talk"),
        presets=("標準", "ロゴ", "スタンプ")),
}
DEFAULT = "illustrator"
ALL_MENUS = COMMON_MENUS + tuple(m for v in MODES.values() for m in v["menus"])


def stored(store) -> tuple[str, bool]:
    """覚えたモードと、「次から聞かない」か"""
    key = str(store.value("mode/current", "") or "")
    ask = int(store.value("mode/ask", 1) or 0)
    return (key if key in MODES else ""), not ask


def remember(store, key: str, dont_ask: bool | None = None):
    store.setValue("mode/current", key)
    if dont_ask is not None:
        store.setValue("mode/ask", 0 if dont_ask else 1)


def visible_menus(key: str) -> tuple[str, ...]:
    return COMMON_MENUS + MODES[key]["menus"]


def apply(w, key: str):
    """モードに合わせてメニュー・欄・プリセットを出し分ける。キャンバスとレイヤーには触らない"""
    if key not in MODES:
        key = DEFAULT
    m = MODES[key]
    w.app_mode = key
    show = set(visible_menus(key))
    for a in w.menuBar().actions():
        if a.menu() is not None and a.text().replace("&", "") in ALL_MENUS:
            a.setVisible(a.text().replace("&", "") in show)
    hidden = set(m["hide_panels"])
    before = getattr(w, "_mode_hidden", set())
    for k, (dock, _area) in getattr(w, "panels", {}).items():
        if k in hidden:
            dock.hide()
        elif k in before:
            dock.show()   # 前のモードで隠した欄だけを戻す（利用者が自分で閉じた欄は開かない）
    w._mode_hidden = hidden
    panel = getattr(w, "ai_panel", None)
    if panel is not None and hasattr(panel, "fill_presets"):
        panel.mode_presets = m["presets"]
        panel.fill_presets()
    for k, act in getattr(w, "mode_actions", {}).items():
        act.setChecked(k == key)
    w.setWindowTitle(f"CharacterDesigner — {m['name']}")


def tour(w, key: str) -> list[Step]:
    """モードごとの短いツアー（3 枚）"""
    bar = lambda: w.menuBar()
    chat = lambda: w.panels["chat"][0]
    steps = {
        "illustrator": [
            Step(lambda: None, "イラストレーターのモード", "場面の絵や背景を描き、加工をかけるためのモードです。"),
            Step(chat, "描く", "AI の欄に描きたい場面を書いて「描く」を押します。プリセットで横長のイラスト・背景美術を選べます。"),
            Step(bar, "加工", "描いた絵は「加工」のメニューで綺麗にする・拡大・画風を替える、ができます。\nモードは「表示」の「モード」で替えられます。"),
        ],
        "designer": [
            Step(lambda: None, "キャラクターデザイナーのモード", "人物の設定から、三面図・表情差分・キャラクターシートを作るモードです。"),
            Step(bar, "キャラクターデザイン", "「キャラクターデザイン」のメニューの「キャラデザを作る…」で、設定を書くと残りを順に描きます。\n"
                 "「追加資料」から四面図・ポーズ差分・髪型差分などを 1 つずつ足せます。"),
            Step(bar, "一括生成とシート", "「一括生成…」で複数の人物の三面図と表情差分をまとめて描けます。\n"
                 "「キャラクターシートを作る」で 1 枚に並べ、PSD と PNG で保存します。"),
        ],
        "logo": [
            Step(lambda: None, "ロゴ・エンブレム・スタンプのモード", "マークやスタンプを描いて、決まった形で書き出すモードです。"),
            Step(chat, "描く", "プリセットの「ロゴ」「スタンプ」を選び、描きたい物を書いて「描く」を押します。"),
            Step(bar, "書き出し", "「ロゴ・スタンプ」の「書き出しの形を選ぶ…」で、透過・単色・線の太さ・正方形・LINE スタンプの大きさを選んで書き出します。"),
        ],
    }
    return steps[key if key in steps else DEFAULT]


def show_tour(w, key: str, force: bool = False) -> bool:
    """そのモードのツアーを、初めてのときだけ出す（force で何度でも）"""
    from chatdraw.tour import Tour
    done = f"mode/tour_{key}"
    if not force and int(w.layout_store.value(done, 0) or 0):
        return False
    w.layout_store.setValue(done, 1)
    w.mode_tour = Tour(w, tour(w, key))
    w.mode_tour.start()
    return True


class ModeDialog:
    """起動したときにモードを選ぶ窓。大きなボタン 3 つと「次から聞かない」"""

    def __init__(self, parent, current: str = ""):
        from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QVBoxLayout
        self.d = QDialog(parent)
        self.d.setWindowTitle("モードを選ぶ")
        lay = QVBoxLayout(self.d)
        lay.addWidget(QLabel("何を作りますか。あとから「表示」の「モード」で替えられます。"))
        self.choice = ""
        self.buttons = {}
        for key, m in MODES.items():
            b = QPushButton(f"{m['name']}\n{m['sub']}")
            b.setToolTip(m["tip"])
            b.setMinimumHeight(64)
            b.clicked.connect(lambda _=False, k=key: self.pick(k))
            if key == current:
                b.setDefault(True)
            lay.addWidget(b)
            self.buttons[key] = b
        self.dont_ask = QCheckBox("次から聞かない")
        self.dont_ask.setToolTip("次の起動から、この窓を出さずに選んだモードで開きます")
        lay.addWidget(self.dont_ask)

    def pick(self, key: str):
        self.choice = key
        self.d.accept()

    def exec(self) -> str:
        self.d.exec()
        return self.choice
