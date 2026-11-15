"""文字を打っている欄のキーを、ショートカットに取られないようにする。

1 文字のショートカット（B、E、T など）、Space の手のひら、Delete、Ctrl+Z が欄より先に効き、
頼みや指示を打っている途中で文字が消えたり道具が替わったりした。
焦点が文字の欄にあるときは、文字を打つキーと文字を直すキーを欄に先に渡す。
Shift+Esc（非常停止）と、Ctrl+Enter など欄が使わない組み合わせはそのまま効かせる。
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit

# Ctrl と組み合わせても欄の中の直しに使うキー（元に戻す・切り取り・貼り付け・全部選ぶ・語ごとの移動）
_CTRL_EDIT = {Qt.Key_Z, Qt.Key_Y, Qt.Key_X, Qt.Key_C, Qt.Key_V, Qt.Key_A,
              Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End}


def is_text_input(w) -> bool:
    if isinstance(w, QLineEdit):
        return not w.isReadOnly()
    if isinstance(w, (QTextEdit, QPlainTextEdit)):
        return not w.isReadOnly()
    if isinstance(w, QAbstractSpinBox):
        return not w.isReadOnly()
    return False


def keep_for_text(key, mods) -> bool:
    """このキーを文字の欄に渡すか"""
    if key == Qt.Key_Escape:
        return False   # Esc と Shift+Esc（非常停止）は欄の外でも効かせる
    if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Return, Qt.Key_Enter) and mods & ~Qt.ShiftModifier & ~Qt.KeypadModifier:
        return False   # Ctrl+Enter（描く）などは効かせる
    m = mods & ~Qt.ShiftModifier & ~Qt.KeypadModifier
    if not m:
        return True    # 文字、Space、Delete、Backspace、矢印、F キー以外は欄で使う
    if m == Qt.ControlModifier and key in _CTRL_EDIT:
        return True
    return False


class TypeGuard(QObject):
    # マウスの戻る・進むボタン。作画ソフトと同じく、元に戻す・やり直すに当てる。窓が on_mouse_back / on_mouse_forward を持てば呼ぶ
    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonPress and e.button() in (Qt.BackButton, Qt.ForwardButton):
            win = obj.window() if hasattr(obj, "window") else None
            fn = getattr(win, "on_mouse_back" if e.button() == Qt.BackButton else "on_mouse_forward", None)
            if fn is not None:
                fn()
                return True
        if e.type() == QEvent.ShortcutOverride and is_text_input(obj):
            k = e.key()
            if Qt.Key_F1 <= k <= Qt.Key_F35:
                return False   # F キーは欄では使わないので、ショートカットに回す
            if keep_for_text(k, e.modifiers()):
                e.accept()     # 受けると、帯やメニューのショートカットより先に欄にキーが来る
                return True
        return False


def install(app: QApplication | None = None) -> TypeGuard:
    """アプリ全体に 1 回だけ付ける"""
    app = app or QApplication.instance()
    guard = getattr(app, "_type_guard", None)
    if guard is None:
        guard = TypeGuard(app)
        app.installEventFilter(guard)
        app._type_guard = guard
    return guard
