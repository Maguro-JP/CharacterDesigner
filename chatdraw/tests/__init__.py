"""chatdraw の試験。

試験が開くウィンドウは、閉じるときに欄の配置・テーマ・済んだツアーを QSettings（~/.config/CharacterDesigner）に書く。
利用者の設定と同じ場所に書いていたため、前の試験（前の回の一式も）で出した進みの欄が次のウィンドウで開いたままになり、
進みのポップアップが「欄に出ているので二重に出さない」で出ず、順番によって試験が落ちた。
試験の間は設定の置き場を一時の場所に替え、利用者の設定にも触らない"""
import atexit
import os
import shutil
import tempfile

_CONFIG = tempfile.mkdtemp(prefix="chatdraw-test-config-")
os.environ["XDG_CONFIG_HOME"] = _CONFIG
atexit.register(shutil.rmtree, _CONFIG, True)



# 始めた QThread を弱い参照で覚えておく。強く持つと、終わりの片付けの順が変わって Segmentation fault になった
import weakref  # noqa: E402

from PySide6.QtCore import QThread  # noqa: E402

_STARTED: list = []
_start = QThread.start


def _remember_start(self, *a):
    _STARTED.append(weakref.ref(self))
    return _start(self, *a)


QThread.start = _remember_start


def _finish():
    """一式の終わりに、動いている QThread を待ち、ウィンドウを Qt が生きているうちに消す。
    描く糸が動いたまま Python が終わると「QThread: Destroyed while thread is still running」で abort（134）し、
    ウィンドウを残したまま終わると、終わりの gc で Segmentation fault（139）になった。試験が全部通っても一式が落ちていた"""
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for r in _STARTED:
        t = r()
        try:
            if t is not None and t.isRunning():
                t.quit()
                t.wait(30000)
        except RuntimeError:
            pass   # C++ 側はもう消えている
    _STARTED.clear()
    app = QApplication.instance()
    if app is not None:
        for w in app.topLevelWidgets():
            w.hide()
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()


atexit.register(_finish)   # 後に登録した物が先に走る（設定の一時の場所を消すより前）
