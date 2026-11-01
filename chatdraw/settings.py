"""設定。値は利用者ごとに残し（QSettings）、設定ウィンドウで変える。設定を足すときは FIELDS に 1 行足す。

模型（絵の模型・言葉の模型・模型の置き場）は設定ウィンドウに出さない。模型の管理（chatdraw/manager.py）の 1 か所で選ぶ。
設定と管理の 2 か所に入口があると、片方で選んだ物がもう片方に古いまま残って食い違ったため。値は同じ QSettings に置く（MODEL_FIELDS）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from chatdraw.engine import IMAGE_MODEL

# (キー, 見出し, 欄の名前, 種類, 既定値, 補足)。種類で入力の部品が決まる
MODEL_FIELDS = [
    ("image_model", "絵の模型", "模型", "image_model", IMAGE_MODEL, ""),
    ("words_model", "言葉の模型", "模型", "words_model", "", ""),   # "" は未選択、NO_WORDS は「使わない」
    ("model_dir", "模型の置き場", "模型", "model_dir", "", ""),
]
FIELDS = [
    ("draw_way", "描き方", "描き方", "choice:おまかせ,1つの模型で描く,構図と仕上げを分けて描く", "おまかせ",
     "構図と仕上げを分けて描く: 文で頼める模型（FLUX.2 klein など）が構図を描き、その骨組みと奥行きに沿って SDXL のアニメの模型が"
     "白紙から描き直す。手足や姿勢が崩れにくいが、1 枚に数倍の時間がかかる。おまかせは、要る模型と部品がそろっていれば分けて描く"),
    ("steps", "描く工程の数", "描き方", "int:4:80", 24, "多いほど細かく描けて、時間がかかる"),
    ("guidance", "頼みの効き", "描き方", "float:1:15", 5.0, "大きいほど頼みの言葉に寄せる"),
    ("rough_follow", "ラフに沿う強さ", "描き方", "float:0.3:1", 1.0, "大きいほどラフの線の形に沿う。小さいほど AI が形を変える"),
    ("output_dir", "描いた絵の保存先", "保存", "dir", str(Path.home() / "Pictures" / "CharacterDesigner"), ""),
    ("notify", "知らせ", "操作", "choice:デスクトップにも出す,画面の中だけ", "デスクトップにも出す",
     "ほかのウィンドウを見ている間に描き終わったら、デスクトップの通知とタスクバーの点滅で知らせる"),
    ("first_tool", "起動したときの道具", "操作", "choice:手,ペン", "手", "起動したときに持つ道具。手は絵を動かして見る。右ボタンのドラッグでは、どの道具でも絵を動かせる"),
    ("cursor_hide", "カーソルを隠す", "操作", "choice:止まったら隠す,いつも出す", "止まったら隠す",
     "絵の上でマウスを止めて 1.5 秒たつとカーソルを隠す。動かすとすぐ出る"),
    ("timelapse", "タイムラプス", "操作", "choice:記録する,記録しない", "記録する", "線を引くたび、AI が描く工程ごとに写しを撮り、描いた過程を残す"),
    ("sns", "SNS 連携", "操作", "choice:オフ,X（Twitter）,Bluesky,Misskey", "オフ",
     "オンにすると、履歴の右クリックから絵をコピーして投稿の画面を開ける。投稿するのは利用者で、アプリが勝手に送ることはない"),
    ("result_place", "AI の結果の置き場", "操作", "choice:上のレイヤー,別ファイル", "上のレイヤー",
     "AI が描いた・直した・加工した結果を置く所。上のレイヤーは一番上の新しいレイヤーに置いて選ぶ。別ファイルは新しい作業ファイルとして別のウィンドウで開く"),
    ("cursor", "カーソル", "操作", "choice:十字と筆の輪,点と筆の輪,筆の輪だけ,矢印", "十字と筆の輪", "絵の上で描くときのカーソルの形"),
]


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
        self.accept()
