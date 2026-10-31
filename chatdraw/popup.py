"""進みのポップアップ。AI が描いている間、絵の欄の右下に下からせり上がって出る。

上に進みの欄を常に置くと、絵を見る場所が狭くなった。描いている間だけ右下に小さく出し、
描き終わっても結果が読めるよう、利用者が × で閉じるまで残す（自分で消えると状態が分からなかった）。
中身は進みの欄（activity）の知らせ（changed）をそのまま映す。進みの欄は「ウィンドウ」メニューから今まで通り出せる。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout

WIDTH, MARGIN = 340, 16


class ProgressPopup(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.setObjectName("progressPopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 10)
        head = QHBoxLayout()
        self.title = QLabel("AI")
        self.title.setObjectName("sectionHead")
        head.addWidget(self.title, 1)
        close = QToolButton()
        close.setText("×")
        close.setToolTip("閉じる（描いている間はまた出ます）")
        close.setAutoRaise(True)
        close.clicked.connect(self.close_popup)
        head.addWidget(close)
        lay.addLayout(head)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        lay.addWidget(self.text)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)
        self.setFixedWidth(WIDTH)
        self.hide()
        # 工程の数が分からない間は、帯を自分で動かす（見た目の設定（QSS）を当てると Qt の動く帯は止まって見えた）
        self.pulse = QTimer(self)
        self.pulse.setInterval(60)
        self.pulse.timeout.connect(lambda: self.bar.setValue((self.bar.value() + 4) % 100))
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self.place)   # 出てくる途中に絵の欄の大きさが変わったときも、止まった所で付け直す
        window.activity.changed.connect(self.update_state)
        if window.centralWidget() is not None:   # 欄を動かして絵の欄の大きさが変わったら付け直す
            window.centralWidget().installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Resize, QEvent.Move):
            self.place()
        return False

    def target(self) -> QPoint:
        """絵の欄（真ん中）の右下。ウィンドウの右下に置くと、チャットの「止める」や右の欄の上に重なった"""
        self.adjustSize()
        c = self.w.centralWidget()
        g = c.geometry() if c is not None and c.isVisible() else self.w.rect()
        self.setFixedWidth(max(120, min(WIDTH, g.width() - 2 * MARGIN)))   # 絵の欄が狭いときは縮める
        self.adjustSize()
        # 絵の欄が低い・狭いときも欄の外（上のツールバーやチャット）にはみ出さないよう、左上の端で止める
        x = max(g.left(), g.right() - self.width() - MARGIN)
        y = max(g.top(), g.bottom() - self.height() - MARGIN)
        return QPoint(x, y)

    def pop(self):
        """下からせり上がって出る。もう出ているときは場所を合わせて一番上に出し直す。
        出ているときに場所だけ合わせていたので、あとから付け直した欄（浮かせて戻した欄、作り直した AI の欄）や
        案内の幕の下に隠れたままになり、「出なくなった」ように見えた。毎回いちばん上に出す"""
        end = self.target()
        if self.isVisible() and not self.isHidden():
            if self.anim.state() != QPropertyAnimation.Running:
                self.move(end)
            self.raise_()
            return
        self.move(end.x(), self.w.height())
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(QPoint(end.x(), self.w.height()))
        self.anim.setEndValue(end)
        self.anim.start()

    def close_popup(self):
        """× で閉じる。閉じるのはこの 1 回分だけで、次に描く・取るときはまた出る"""
        self.anim.stop()
        self.pulse.stop()
        self.hide()

    def tell(self, title: str, text: str, pct: int = -2):
        """描く・取る以外の知らせ（描けなかった理由、模型を取る進み）を同じ場所に出す。
        描く前に止まったとき（AI が使えない、模型が無い）と、模型を取っている間に何も出なかった"""
        self.text.setText(text)
        self.title.setText(title)
        if pct >= 0:
            self.pulse.stop()
            self.bar.setValue(pct)
        elif pct == -1:
            self.pulse.start()
        else:
            self.pulse.stop()
            self.bar.setValue(100)
        self.pop()

    def place(self):
        """ウィンドウの大きさが変わったら、右下に付け直す"""
        if self.isVisible() and self.anim.state() != QPropertyAnimation.Running:
            self.move(self.target())

    def update_state(self, text: str, pct: int):
        self.text.setText(text)
        if pct == -2:   # 終わった。結果を出したまま残す
            self.title.setText("終わりました")
            self.pulse.stop()
            self.bar.setValue(100)
        elif pct < 0:
            self.title.setText("AI が描いています")
            self.pulse.start()
        else:
            self.pulse.stop()
            self.title.setText(f"AI が描いています　{pct}%")
            self.bar.setValue(pct)
        self.pop()
