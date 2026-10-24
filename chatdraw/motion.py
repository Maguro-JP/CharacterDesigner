"""画面の動き。出す・隠す・畳む・知らせを、短い動きで見せて、何が起きたかを目で追えるようにする。

動きは 160〜220 ミリ秒に抑える（長いと作業の邪魔になる）。動きを切る設定（MOTION = False）でも同じ結果になる。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QParallelAnimationGroup
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

MOTION = True
FAST, NORMAL = 160, 220


def _keep(widget: QWidget, anim):
    """動きが終わるまで消されないように持っておく"""
    widget._motion = anim
    anim.start()
    return anim


def fade_in(widget: QWidget, ms: int = NORMAL):
    """透明から見えるまで。終わったら効果を外す（外さないと、中の部品の描画が遅くなる）"""
    if not MOTION:
        widget.show()
        return None
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    eff.setOpacity(0.0)
    widget.show()
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    return _keep(widget, a)


def fade_out(widget: QWidget, ms: int = FAST, then=None):
    if not MOTION:
        widget.hide()
        if then:
            then()
        return None
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(ms)
    a.setStartValue(1.0)
    a.setEndValue(0.0)
    a.setEasingCurve(QEasingCurve.InCubic)

    def done():
        widget.hide()
        widget.setGraphicsEffect(None)
        if then:
            then()
    a.finished.connect(done)
    return _keep(widget, a)


def slide_in(widget: QWidget, end: QPoint, dx: int = 0, dy: int = 24, ms: int = NORMAL):
    """end の位置へ、少しずれた所から滑り込ませ、同時に見えるようにする"""
    if not MOTION:
        widget.move(end)
        widget.show()
        return None
    widget.move(end + QPoint(dx, dy))
    group = QParallelAnimationGroup(widget)
    move = QPropertyAnimation(widget, b"pos", widget)
    move.setDuration(ms)
    move.setStartValue(end + QPoint(dx, dy))
    move.setEndValue(end)
    move.setEasingCurve(QEasingCurve.OutCubic)
    group.addAnimation(move)
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    eff.setOpacity(0.0)
    fade = QPropertyAnimation(eff, b"opacity", widget)
    fade.setDuration(ms)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    group.addAnimation(fade)
    group.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget.show()
    return _keep(widget, group)


def resize_height(widget: QWidget, start: int, end: int, ms: int = FAST, then=None):
    """高さの上限を start から end へ動かす（欄やリボンを畳む・広げる）"""
    if not MOTION:
        widget.setMaximumHeight(end)
        if then:
            then()
        return None
    a = QPropertyAnimation(widget, b"maximumHeight", widget)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.InOutCubic)
    if then:
        a.finished.connect(then)
    return _keep(widget, a)
