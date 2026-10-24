"""設定。値は利用者ごとに残し（QSettings）、設定ウィンドウで変える。設定を足すときは FIELDS に 1 行足す。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from chatdraw.engine import HOME, IMAGE_MODEL

# (キー, 見出し, 欄の名前, 種類, 既定値, 補足)。種類で入力の部品が決まる
FIELDS = [
    ("image_model", "絵の模型", "模型", "image_model", IMAGE_MODEL, "絵を描く模型。手元に取ってある物から選ぶか、Hugging Face の名前を書く"),
    ("words_model", "言葉の模型", "模型", "words_model", str(HOME / "llm" / "model.gguf"), "日本語の頼みを描く言葉に直す模型（.gguf）"),
    ("steps", "描く工程の数", "描き方", "int:4:80", 24, "多いほど細かく描けて、時間がかかる"),
    ("guidance", "頼みの効き", "描き方", "float:1:15", 5.0, "大きいほど頼みの言葉に寄せる"),
    ("rough_follow", "ラフに沿う強さ", "描き方", "float:0.3:1", 1.0, "大きいほどラフの線の形に沿う。小さいほど AI が形を変える"),
    ("output_dir", "描いた絵の保存先", "保存", "dir", str(Path.home() / "Pictures" / "CharacterDesigner"), ""),
]


def local_models() -> list[str]:
    """手元に取ってある、絵を描ける模型（model_index.json がある物）"""
    hub = HOME / "gen" / "hf" / "hub"
    out = []
    for d in sorted(hub.glob("models--*")):
        if any(s.joinpath("model_index.json").exists() for s in d.glob("snapshots/*")):
            out.append(d.name[len("models--"):].replace("--", "/"))
    return out


class Settings:
    def __init__(self, store: QSettings | None = None):
        self.store = store or QSettings("CharacterDesigner", "chatdraw-settings")

    def get(self, key: str):
        field = next(f for f in FIELDS if f[0] == key)
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
        if kind == "image_model":
            w = QComboBox()
            w.setEditable(True)
            w.addItems(local_models())
            w.setCurrentText(value)
            return w
        if kind == "words_model":
            w = QComboBox()
            w.setEditable(True)
            w.addItems([str(p) for p in sorted((HOME / "llm").glob("*.gguf"))])
            w.setCurrentText(value)
            return w
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
        if kind == "dir":
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value))
            pick = QPushButton("選ぶ…")
            pick.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "保存先", edit.text())) and edit.setText(d))
            row.addWidget(edit)
            row.addWidget(pick)
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
