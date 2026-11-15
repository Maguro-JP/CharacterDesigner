"""設定。値は利用者ごとに残し（QSettings）、設定ウィンドウで変える。設定を足すときは FIELDS に 1 行足す。

模型（絵の模型・言葉の模型・模型の置き場）は設定ウィンドウに出さない。模型の管理（chatdraw/manager.py）の 1 か所で選ぶ。
設定と管理の 2 か所に入口があると、片方で選んだ物がもう片方に古いまま残って食い違ったため。値は同じ QSettings に置く（MODEL_FIELDS）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from chatdraw import debuglog
from chatdraw.engine import IMAGE_MODEL

# 描き方の 2 つのモード。AI モードは今までの速い描き方（おまかせ・1 つの模型・2 段の判定は、この中の ai_way で選ぶ）。
# 精度優先は工程に分けて描く（chatdraw/phases.py）。前は 4 つが 1 つの欄に並び、どれが今までの描き方か分からなかった
AI_MODE = "AI モード（今までの描き方。速い）"
PRECISE = "精度優先（工程に分けて描く）"
_OLD_WAY = {"工程に分けて描く": PRECISE, "おまかせ": AI_MODE, "1つの模型で描く": AI_MODE, "構図と仕上げを分けて描く": AI_MODE}


def studio_way(draw_way: str, ai_way: str) -> str:
    """設定の 2 つの欄から、engine.Studio.way（phases / one / two / auto）を決める"""
    if draw_way == PRECISE:
        return "phases"
    return {"1つの模型で描く": "one", "構図と仕上げを分けて描く": "two"}.get(ai_way, "auto")


# (キー, 見出し, 欄の名前, 種類, 既定値, 補足)。種類で入力の部品が決まる
MODEL_FIELDS = [
    ("image_model", "絵の模型", "模型", "image_model", IMAGE_MODEL, ""),
    ("words_model", "言葉の模型", "模型", "words_model", "", ""),   # "" は未選択、NO_WORDS は「使わない」
    ("model_dir", "模型の置き場", "模型", "model_dir", "", ""),
]
FIELDS = [
    ("draw_way", "描き方", "描き方", f"choice:{AI_MODE},{PRECISE}", AI_MODE,
     "AI モード: 今までの描き方で、速く描く。中の描き方は下の「AI モードの描き方」で選ぶ。"
     "精度優先: 1 つの模型で、人の描き方の 12 の工程（目的・サムネイル・アタリ・体の形・顔と手と足・服と髪と持ち物・線画の清書・"
     "下塗り・光源・影 2 段・光と艶・仕上げ）に分けて描き、工程ごとに見る物を数字で測って崩れを直し、崩れが決まった工程へ戻る。"
     "時間はかかるが崩れにくい。途中の絵は隠したレイヤーに残る。描くボタンのすぐ上の「描き方」でも切り替えられる"),
    ("phase_confirm", "工程ごとに確かめる", "描き方", "bool", 0,
     "精度優先で描くとき、工程が終わるたびに止まり、その工程の絵を見せる。「進める」「この工程を描き直す」「言葉を足して描き直す」から選ぶ。"
     "切ると止まらずに最後まで描く"),
    ("ai_way", "AI モードの描き方", "描き方", "choice:おまかせ,1つの模型で描く,構図と仕上げを分けて描く", "おまかせ",
     "AI モードの中の描き方。構図と仕上げを分けて描く: 文で頼める模型（FLUX.2 klein など）が構図を描き、その骨組みと奥行きに沿って"
     " SDXL のアニメの模型が白紙から描き直す（2 段の判定）。おまかせは、要る模型と部品がそろっていれば分けて描く"),
    ("steps", "描く工程の数", "描き方", "int:4:80", 24, "多いほど細かく描けて、時間がかかる"),
    ("guidance", "頼みの効き", "描き方", "float:1:15", 5.0, "大きいほど頼みの言葉に寄せる"),
    ("rough_follow", "ラフに沿う強さ", "描き方", "float:0.3:1", 1.0, "大きいほどラフの線の形に沿う。小さいほど AI が形を変える"),
    ("mem_mode", "メモリの使い方", "描き方", "choice:自動,優先して動かす,控えめに動かす", "自動",
     "自動: 空きの 8 割を目安に、足りなければ軽い設定に落として描く。優先して動かす: 空きをほぼ使い切って描く（ほかのアプリが重くなることがある）。"
     "控えめに動かす: 空きの 6 割までにとどめ、ほかのアプリに余裕を残す。どれでも危なくなったら途中の絵を残して止まり、アプリは落とさない"),
    ("output_dir", "描いた絵の保存先", "保存", "dir", str(Path.home() / "Pictures" / "CharacterDesigner"), ""),
    ("notify", "知らせ", "操作", "choice:デスクトップにも出す,画面の中だけ", "デスクトップにも出す",
     "ほかのウィンドウを見ている間に描き終わったら、デスクトップの通知とタスクバーの点滅で知らせる"),
    ("first_tool", "起動したときの道具", "操作", "choice:手,ペン", "手", "起動したときに持つ道具。手は絵を動かして見る。右ボタンのドラッグでは、どの道具でも絵を動かせる"),
    ("cursor_hide", "カーソルを隠す", "操作", "choice:止まったら隠す,いつも出す", "止まったら隠す",
     "絵の上でマウスを止めて 1.5 秒たつとカーソルを隠す。動かすとすぐ出る"),
    ("timelapse", "タイムラプス", "操作", "choice:記録する,記録しない", "記録する", "線を引くたび、AI が描く工程ごとに写しを撮り、描いた過程を残す"),
    ("sns", "SNS 連携", "操作", "choice:オフ,X（Twitter）,Bluesky,Misskey", "オフ",
     "オンにすると、履歴の右クリックから絵をコピーして投稿の画面を開ける。投稿するのはユーザーで、アプリが勝手に送ることはない"),
    ("result_place", "AI の結果の置き場", "操作", "choice:上のレイヤー,別ファイル", "上のレイヤー",
     "AI が描いた・直した・加工した結果を置く所。上のレイヤーは一番上の新しいレイヤーに置いて選ぶ。別ファイルは新しい作業ファイルとして別のウィンドウで開く"),
    ("language", "言語", "操作", "choice:日本語,English", "日本語", "画面の言葉の言語（メニュー・ボタン・欄・ツールチップ・ダイアログ）。次に開いたときから変わる（訳の無い言葉は日本語のまま）"),
    ("cursor", "カーソル", "操作", "choice:十字と筆の輪,点と筆の輪,筆の輪だけ,矢印", "十字と筆の輪", "絵の上で描くときのカーソルの形"),
    ("debug", "デバッグモード", "デバッグ", "bool", 0,
     "下に「記録」の欄を出し、工程・模型に渡した言葉・例外の全文・空きメモリを流す。記録は HOME の logs にも残し、"
     "7 日より古い物は消す。落ちたとき・描けなかったときは理由の全文を窓で出す。子どもを性的に描く頼みを止める決まりは外せない"),
] + [(f"debug_{k}", f"外す: {label}", "デバッグ", "bool", 0, tip + "（デバッグモードがオンのときだけ効く）")
     for k, label, tip in debuglog.LIFTS]


def _open(path: str):
    if path:
        from chatdraw.folders import open_folder
        open_folder(path)


class Settings:
    def __init__(self, store: QSettings | None = None):
        self.store = store or QSettings("CharacterDesigner", "chatdraw-settings")

    def get(self, key: str):
        field = next(f for f in FIELDS + MODEL_FIELDS if f[0] == key)
        if key == "model_dir":
            from chatdraw.paths import chosen_model_dir
            return chosen_model_dir()
        value = self.store.value(key, field[4])
        if key == "draw_way":   # 前の版の 1 つの欄の値を、2 つのモードに読み替える（選んでいた描き方を変えない）
            return _OLD_WAY.get(str(value), str(value))
        if key == "ai_way" and self.store.value("ai_way", None) is None:
            old = str(self.store.value("draw_way", ""))
            if old in ("1つの模型で描く", "構図と仕上げを分けて描く"):
                return old
        kind = field[3]
        if kind.startswith("int") or kind == "bool":
            return int(value)
        if kind.startswith("float"):
            return float(value)
        return str(value)

    def set(self, key: str, value):
        self.store.setValue(key, value)


class SettingsDialog(QDialog):
    """設定ウィンドウ。タブごとに項目を並べる"""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.resize(560, 360)
        self.settings = settings
        self.inputs = {}
        tabs = QTabWidget()
        forms: dict[str, QFormLayout] = {}
        for key, label, tab, kind, _default, tip in FIELDS:
            if tab not in forms:
                page = QWidget()
                forms[tab] = QFormLayout(page)
                tabs.addTab(page, tab)
            if key == "steps":
                kind = "int:1:1000" if debuglog.lifted("steps") else kind   # デバッグモードで工程の上限を外したとき
            w = self._input(kind, settings.get(key))
            w.setToolTip(tip)
            forms[tab].addRow(label, w)
            self.inputs[key] = (kind, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("やめる")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def _input(self, kind: str, value):
        if kind.startswith("int"):
            _, lo, hi = kind.split(":")
            w = QSpinBox()
            w.setRange(int(lo), int(hi))
            w.setValue(int(value))
            return w
        if kind.startswith("float"):
            _, lo, hi = kind.split(":")
            w = QDoubleSpinBox()
            w.setRange(float(lo), float(hi))
            w.setSingleStep(0.05)
            w.setValue(float(value))
            return w
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(int(value)))
            return w
        if kind.startswith("choice:"):
            w = QComboBox()
            w.addItems(kind.split(":", 1)[1].split(","))
            w.setCurrentText(str(value))
            return w
        if kind == "dir":
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value))
            pick = QPushButton("選ぶ…")
            pick.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "保存先", edit.text())) and edit.setText(d))
            show = QPushButton("開く")
            show.setToolTip("このディレクトリをエクスプローラーで開きます。無ければ作ってから開きます")
            show.clicked.connect(lambda: _open(edit.text().strip()))
            row.addWidget(edit)
            row.addWidget(pick)
            row.addWidget(show)
            box.edit = edit
            return box
        return QLineEdit(str(value))

    def value(self, key: str):
        kind, w = self.inputs[key]
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, QCheckBox):
            return int(w.isChecked())
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            return w.value()
        if kind == "dir":
            return w.edit.text().strip()
        return w.text().strip()

    def save(self):
        for key in self.inputs:
            self.settings.set(key, self.value(key))
        apply_debug(self.settings)
        self.accept()


def apply_debug(settings: Settings) -> None:
    """設定のデバッグモードと外す制限を、裏の処理（chatdraw/debuglog.py）に渡す"""
    debuglog.configure(bool(settings.get("debug")),
                       [k for k, *_ in debuglog.LIFTS if settings.get(f"debug_{k}")])
