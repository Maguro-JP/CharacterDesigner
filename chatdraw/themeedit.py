"""テーマを自分で作る窓。元にするテーマを選び、色・模様・演出を替えると、その場で画面に当たる。
名前を付けて保存すると「表示」の「テーマ」に並ぶ。保存しないで閉じると元のテーマに戻す。
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QPushButton, QVBoxLayout)

from chatdraw import backdrop, themes


class ThemeEditor(QDialog):
    def __init__(self, w):
        super().__init__(w)
        self.w = w
        self.setWindowTitle("テーマを作る")
        self.before = themes.current["name"]
        self.t = themes.base(self.before)
        lay = QVBoxLayout(self)
        head = QLabel("テーマを作る")
        head.setObjectName("dialogTitle")
        lay.addWidget(head)
        form = QFormLayout()
        self.base_pick = QComboBox()
        self.base_pick.addItems(themes.all_names())
        self.base_pick.setCurrentText(self.before)
        self.base_pick.currentTextChanged.connect(self.from_base)
        form.addRow("元にするテーマ", self.base_pick)
        self.swatches: dict[str, QPushButton] = {}
        for key, label in themes.EDITABLE.items():
            b = QPushButton()
            b.setFixedHeight(26)
            b.clicked.connect(lambda _=False, k=key: self.pick(k))
            self.swatches[key] = b
            form.addRow(label, b)
        self.pattern = QComboBox()
        for key, label in backdrop.PATTERNS.items():
            self.pattern.addItem(label, key)
        self.pattern.currentIndexChanged.connect(lambda _i: self.set("pattern", self.pattern.currentData()))
        form.addRow("絵の周りの模様", self.pattern)
        self.moving = QCheckBox("模様を動かし、描くボタンを光らせる")
        self.moving.toggled.connect(lambda on: self.set("motion", "1" if on else "0"))
        form.addRow("演出", self.moving)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("名前を付けて保存")
        buttons.button(QDialogButtonBox.Cancel).setText("やめる")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(buttons)
        lay.addLayout(row)
        self.show_values()

    def show_values(self):
        for key, b in self.swatches.items():
            c = self.t.get(key, "#000000")
            text = "#000000" if QColor(c).lightness() > 140 else "#ffffff"
            b.setText(c)
            b.setStyleSheet(f"background:{c}; color:{text}; border:1px solid #888; border-radius:6px;")
        self.pattern.blockSignals(True)
        self.pattern.setCurrentIndex(max(0, self.pattern.findData(self.t.get("pattern", "none"))))
        self.pattern.blockSignals(False)
        self.moving.blockSignals(True)
        self.moving.setChecked(self.t.get("motion", "1") == "1")
        self.moving.blockSignals(False)

    def preview(self):
        self.w.preview_theme(self.t)

    def from_base(self, name: str):
        self.t = themes.base(name)
        self.show_values()
        self.preview()

    def set(self, key: str, value: str):
        self.t[key] = value
        self.show_values()
        self.preview()

    def pick(self, key: str):
        c = QColorDialog.getColor(QColor(self.t.get(key, "#000000")), self, themes.EDITABLE[key])
        if c.isValid():
            self.set(key, c.name())

    def save(self, name: str | None = None):
        if not name:
            name, ok = QInputDialog.getText(self, "テーマの名前", "名前", text=f"{self.base_pick.currentText()}（自分）")
            if not ok or not name.strip():
                return
        name = name.strip()
        themes.save_custom(self.w.layout_store, name, self.t)
        self.w.set_theme(name)
        self.accept()

    def reject(self):
        self.w.set_theme(self.before)   # 保存しないで閉じたら、元のテーマに戻す
        super().reject()
