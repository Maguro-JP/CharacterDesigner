"""テーマの演出。絵の周りの模様を動かす、AI で描くボタンをゆっくり光らせる、テーマを替えるときに溶け込ませる。

演出はテーマの motion が "1" のときだけ動く。描いている最中の手の動きを邪魔しないよう、模様は 1 秒に 20 回まで、
紙の外だけを描き直す。動きを切る設定（motion.MOTION = False、試験）でも、止まった模様は描く。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QTimer, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel

from chatdraw import backdrop, motion

FPS = 20


class Look:
    def __init__(self, w):
        self.w = w
        self.t: dict = {}
        self.start = time.monotonic()
        self.timer = QTimer(w)
        self.timer.setInterval(1000 // FPS)
        self.timer.timeout.connect(self.tick)
        self.glow = QGraphicsDropShadowEffect(w.button)
        self.glow.setOffset(0, 0)
        w.button.setGraphicsEffect(self.glow)
        self.pulse = QVariantAnimation(w)
        self.pulse.setStartValue(6.0)
        self.pulse.setEndValue(26.0)
        self.pulse.setDuration(1400)
        self.pulse.setEasingCurve(QEasingCurve.InOutSine)
        self.pulse.setLoopCount(-1)
        self.pulse.valueChanged.connect(lambda v: self.glow.setBlurRadius(v))
        c = w.canvas
        c.backdrop = self.paint
        for bar in (c.horizontalScrollBar(), c.verticalScrollBar()):
            bar.valueChanged.connect(lambda _v: c.viewport().update())   # 模様は画面に貼り付くので、動かしたら全体を描き直す

    def phase(self) -> float:
        return time.monotonic() - self.start if self.moving() else 0.0

    def moving(self) -> bool:
        return motion.MOTION and self.t.get("motion", "1") == "1" and self.t.get("pattern", "none") != "none"

    def paint(self, painter, rect):
        if self.t:
            backdrop.paint(painter, rect, self.t, self.phase())

    def tick(self):
        if self.w.isVisible() and not self.w.isMinimized():
            self.w.canvas.update_margins()

    def apply(self, t: dict):
        self.t = t
        self.glow.setColor(QColor(t["a1"]))
        if self.moving():
            self.timer.start(1000 // backdrop.FPS.get(t.get("pattern"), FPS))
        else:
            self.timer.stop()
        if motion.MOTION and t.get("motion", "1") == "1":
            self.pulse.start()
        else:
            self.pulse.stop()
            self.glow.setBlurRadius(14)
        self.w.canvas.viewport().update()


def crossfade(w, change):
    """今の画面を写した板を上に置いてから change() で替え、板を消していく。替わる瞬間のちらつきを見せない"""
    if not motion.MOTION or not w.isVisible():
        change()
        return
    shot = QLabel(w)
    shot.setPixmap(w.grab())
    shot.setGeometry(w.rect())
    shot.show()
    shot.raise_()
    change()
    motion.fade_out(shot, ms=motion.NORMAL + 120, then=shot.deleteLater)
