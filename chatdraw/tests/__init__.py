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


def _wait_threads():
    """一式の終わりに、まだ動いている QThread を待つ。試験のウィンドウの描く糸が動いたまま Python が終わると、
    Qt が「QThread: Destroyed while thread is still running」で abort し、試験が全部通っても終了コードが 134 になった"""
    import gc
    import sys
    if "PySide6.QtCore" not in sys.modules:
        return
    from PySide6.QtCore import QThread
    for t in [o for o in gc.get_objects() if isinstance(o, QThread)]:
        try:
            if t.isRunning():
                t.quit()
                t.wait(30000)
        except RuntimeError:
            pass   # C++ 側はもう消えている


atexit.register(_wait_threads)   # 後に登録した物が先に走る（設定の一時の場所を消すより前）
