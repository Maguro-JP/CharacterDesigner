"""役目ごとの模型（お気に入り）を選ぶ窓。役目 1 つに 1 行、手元にある模型から選ぶ（取っていない物は出さない）。
選ばない役目は「おまかせ」のまま（おすすめの順で選ぶ）。保存は chatdraw/favmodels.py"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from chatdraw import favmodels

AUTO_LABEL = "おまかせ"


class RoleModelsDialog(QDialog):
    def __init__(self, have, parent=None):
        super().__init__(parent)
        self.setWindowTitle("役目ごとの模型")
        lay = QVBoxLayout(self)
        note = QLabel("役目ごとに使う模型を選びます。選んだ役目は、描くたびにその模型を使います")
        note.setWordWrap(True)
        lay.addWidget(note)
        form = QFormLayout()
        lay.addLayout(form)
        data = favmodels.load()
        self.boxes: dict[str, QComboBox] = {}
        for role, (label, tip) in favmodels.ROLES.items():
            box = QComboBox()
            box.setToolTip(tip + "。「おまかせ」は頼みに合う物を選びます")
            box.addItem(AUTO_LABEL, "")
            for m in have:
                box.addItem(m.name, m.repo)
            now = data.get(role, "")
            if now and box.findData(now) < 0:   # 手元から消した模型も、選んであったことは見せる（黙って外さない）
                box.addItem(f"{now}（手元に無い）", now)
            box.setCurrentIndex(max(0, box.findData(now)))
            name = QLabel(label)
            name.setToolTip(tip)
            form.addRow(name, box)
            self.boxes[role] = box
        if not have:
            empty = QLabel("手元に絵の模型がありません。AI のメニューの「模型の管理…」から取ってください")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("やめる")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {role: box.currentData() or "" for role, box in self.boxes.items()}

    def store(self):
        favmodels.save(self.values())
