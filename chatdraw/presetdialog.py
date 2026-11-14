"""自分の AI プリセットを作る・直す窓。

前は今の描き方・大きさ・画風・強さをそのまま残すだけで、名前のあとから中身を直せず、描くワードや禁止ワードも入れられなかった。
ここでは 1 つのプリセットに、描き方・大きさ・画風・ラフに沿う強さ・枚数・種・絵の模型・描くワード・禁止ワードを持たせる。
描くワードと禁止ワードは利用者が書いた言葉で、当てたときに AI の欄の書く欄にそのまま入れる（隠れた言葉は足さない）。
空の欄は「当てても変えない」の意味。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit, QSlider,
                               QSpinBox)
from PySide6.QtCore import Qt

KEEP = "変えない"
MODES = ("新規", "ラフから", "直す")   # app の描き方の欄（Window.mode）と同じ並び（番号で持つ）


def model_choices() -> list[tuple[str, str]]:
    """(見せる名前, 設定の値)。変えない・おまかせ・手元にある絵の模型"""
    out = [(KEEP, ""), ("おまかせ", "auto")]
    try:
        from chatdraw.models import all_images
        from chatdraw.setup import AUTO, has_image
        out[1] = ("おまかせ", AUTO)
        out += [(m.name, m.repo) for m in all_images() if has_image(m)]
    except Exception:   # noqa: BLE001  模型の一覧が読めなくてもプリセットは作れる
        pass
    return out


class PresetDialog(QDialog):
    def __init__(self, panel, name: str = "", data: dict | None = None, favorites=()):
        from chatdraw.aipanel import SIZES, STYLE_TAGS
        super().__init__(panel)
        data = dict(data or {})
        self.setWindowTitle("AI プリセットを編集" if name else "AI プリセットを作る")
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("例: 白地の立ち絵")
        self.name.setToolTip("AI の欄の「作風」に出る名前")
        form.addRow("名前", self.name)
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.setCurrentIndex(int(data.get("mode", 0)) if 0 <= int(data.get("mode", 0)) < len(MODES) else 0)
        form.addRow("描き方", self.mode)
        self.size = QComboBox()
        self.size.addItems(list(SIZES))
        self.size.setCurrentText(data.get("size", "縦"))
        form.addRow("大きさ", self.size)
        self.style = QComboBox()
        self.style.addItems(list(STYLE_TAGS))
        self.style.setCurrentText(data.get("style", "おまかせ"))
        form.addRow("画風", self.style)
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(30, 100)
        self.strength.setValue(int(data.get("strength", 100)))
        self.strength.setToolTip("ラフに沿う強さ。大きいほど線どおりに描きます")
        form.addRow("ラフに沿う強さ", self.strength)
        self.count = QSpinBox()
        self.count.setRange(0, 20)
        self.count.setSpecialValueText(KEEP)
        self.count.setSuffix(" 枚")
        self.count.setValue(int(data.get("count", 0)))
        self.count.setToolTip("一度に描く枚数。「変えない」なら今の枚数のまま")
        form.addRow("枚数", self.count)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setSpecialValueText("毎回変える")
        self.seed.setValue(int(data.get("seed", 0)))
        self.seed.setToolTip("種を決めると、同じ頼みで同じ絵になります。0 は毎回変える")
        form.addRow("種", self.seed)
        self.model = QComboBox()
        for label, key in model_choices():
            self.model.addItem(label, key)
        i = self.model.findData(data.get("model", ""))
        self.model.setCurrentIndex(max(0, i))
        self.model.setToolTip("当てたときに替える絵の模型。「変えない」なら今の模型のまま")
        form.addRow("絵の模型", self.model)
        self.fav = QComboBox()
        self.fav.addItem("登録した描くワードから入れる…", "")
        for f in favorites:
            self.fav.addItem(f, f)
        self.fav.setToolTip("描くワードに登録した言葉を、下の欄に入れます")
        self.fav.activated.connect(self._use_fav)
        self.words = QPlainTextEdit(data.get("words", ""))
        self.words.setPlaceholderText("当てたときに描くワードの欄に入れる言葉（空なら変えない）")
        self.words.setFixedHeight(64)
        form.addRow("描くワード", self.fav)
        form.addRow("", self.words)
        self.negative = QLineEdit(data.get("negative", ""))
        self.negative.setPlaceholderText("当てたときに禁止ワードの欄に入れる言葉（空なら変えない）")
        form.addRow("禁止ワード", self.negative)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("保存")
        bb.button(QDialogButtonBox.Cancel).setText("やめる")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _use_fav(self, i: int):
        text = self.fav.itemData(i)
        if text:
            self.words.setPlainText(text)
        self.fav.setCurrentIndex(0)

    def _ok(self):
        if self.name.text().strip():
            self.accept()
        else:
            self.name.setFocus()
            self.name.setPlaceholderText("名前を書いてください")

    def result_data(self) -> tuple[str, dict]:
        d = dict(mode=self.mode.currentIndex(), size=self.size.currentText(), style=self.style.currentText(),
                 strength=self.strength.value())
        if self.count.value():
            d["count"] = self.count.value()
        if self.seed.value():
            d["seed"] = self.seed.value()
        if self.model.currentData():
            d["model"] = self.model.currentData()
        if self.words.toPlainText().strip():
            d["words"] = self.words.toPlainText().strip()
        if self.negative.text().strip():
            d["negative"] = self.negative.text().strip()
        return self.name.text().strip(), d
