"""数の欄・選ぶ欄・つまみが、欄をスクロールしようとしたホイールを横取りしないようにする。

欄の上でホイールを回すと、カーソルの下の種や強さの数が勝手に変わった。
押して選んだ（キーボードの焦点がある）ときだけホイールで変え、それ以外はスクロールに回す。
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
                               QScrollBar)


def _guarded(obj) -> bool:
    return isinstance(obj, (QAbstractSpinBox, QComboBox, QAbstractSlider)) and not isinstance(obj, QScrollBar)


class WheelGuard(QObject):
    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Polish and _guarded(obj):
            obj.setFocusPolicy(Qt.StrongFocus)   # ホイールで焦点を取らせない
        elif t == QEvent.Wheel and _guarded(obj) and not obj.hasFocus():
            p = obj.parentWidget()
            while p is not None and not isinstance(p, QAbstractScrollArea):
                p = p.parentWidget()
            if p is not None:
                QApplication.sendEvent(p.verticalScrollBar(), e)   # 囲む欄をスクロールする
            return True
        return False


def install(app: QApplication | None = None) -> WheelGuard:
    """アプリ全体に 1 回だけ付ける。既に作った欄にも当てる"""
    app = app or QApplication.instance()
    guard = getattr(app, "_wheel_guard", None)
    if guard is None:
        guard = WheelGuard(app)
        app.installEventFilter(guard)
        app._wheel_guard = guard
        for w in app.allWidgets():
            if _guarded(w):
                w.setFocusPolicy(Qt.StrongFocus)
    return guard
