"""音声入力。話した言葉を文字にして、言葉の指示の欄・チャットの欄・描くワードの欄に入れる。

手元で動く物を先にする。声を文字にする模型は faster-whisper の small（約 470MB、CPU の int8 で動く）を使い、
共有の置き場（paths.HUB、Windows では C:\\LLM\\huggingface）に置いて、ほかのアプリと分け合う。
small にしたのは、日本語と英語を混ぜた頼みも 1 つの模型で読め、CPU でも数秒で返るから。Windows の音声認識（Win+H）は
OS の窓に任せる形で、話した言葉がどの欄に入るかをアプリが決められず、Windows の外では使えないので、
faster-whisper が無い Windows のときだけの代わりにする。どちらも無い環境では、ボタンのツールチップに何を入れれば使えるかを出す。
"""
from __future__ import annotations

import importlib.util
import sys
import threading

VK_LWIN, VK_H, KEYUP = 0x5B, 0x48, 0x0002
# Win を押す、H を押す、H を離す、Win を離す
SEQUENCE = ((VK_LWIN, 0), (VK_H, 0), (VK_H, KEYUP), (VK_LWIN, KEYUP))
MODEL = "small"
MODEL_MB = 470
RATE = 16000
MAX_SEC = 60   # 押したまま忘れても、1 分で止めて文字にする
INSTALL = "pip install faster-whisper sounddevice"


def available() -> bool:
    """Windows の音声入力（Win+H）が使えるか"""
    return sys.platform == "win32"


def start(user32=None) -> bool:
    """Win+H を送る。送れたら True。user32 は試験で差し替える"""
    if user32 is None:
        if not available():
            return False
        import ctypes
        user32 = ctypes.windll.user32
    for key, flag in SEQUENCE:
        user32.keybd_event(key, 0, flag, 0)
    return True


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def whisper_ready() -> bool:
    return _has("faster_whisper") and _has("sounddevice")


def backend() -> str | None:
    """使う仕組み。"whisper"（手元の模型）、"windows"（Win+H）、None（使えない）"""
    if whisper_ready():
        return "whisper"
    if available():
        return "windows"
    return None


def missing() -> str:
    """使えないときに、何を入れれば使えるかの 1 文"""
    need = [m for m, mod in (("faster-whisper", "faster_whisper"), ("sounddevice", "sounddevice")) if not _has(mod)]
    return (f"声で入力するには {' と '.join(need)} を入れてください（{INSTALL}）。"
            f"初めて使うときに声を文字にする模型 {MODEL}（約 {MODEL_MB}MB）を模型の置き場に取ります")


def tooltip(kind: str | None = None) -> str:
    kind = backend() if kind is None else kind
    if kind == "whisper":
        return "声で入力します。押して話し、もう一度押すと文字にして欄に入れます（手元の模型で読み、外へ送りません）"
    if kind == "windows":
        return "声で入力します（Windows の音声入力 Win+H を開きます）。手元の模型で読むには " + INSTALL + " を入れてください"
    return missing()


_model = None
_model_lock = threading.Lock()


def whisper_model():
    """模型は 1 回だけ読む（読むのに数秒かかる）。置き場は共有の huggingface"""
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            from chatdraw import paths
            paths.ensure_shared()
            _model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=str(paths.HUB))
        return _model


class WhisperListener:
    """マイクの音を集め、止めたら faster-whisper で文字にする"""

    def __init__(self):
        self.chunks, self.stream = [], None

    def start(self):
        import sounddevice as sd
        self.chunks = []
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                     callback=lambda data, _n, _t, _s: self.chunks.append(data.copy()))
        self.stream.start()

    def stop(self):
        import numpy as np
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        return np.concatenate(self.chunks).reshape(-1) if self.chunks else np.zeros(0, "float32")

    def transcribe(self, audio) -> str:
        if getattr(audio, "size", 0) < RATE // 4:   # 0.25 秒より短い音は、押し間違いとして文字にしない
            return ""
        segments, _info = whisper_model().transcribe(audio, beam_size=1, vad_filter=True)
        return "".join(s.text for s in segments).strip()


def insert(target, text: str):
    """欄の今の言葉の後ろに足す（書きかけの言葉を消さない）"""
    text = (text or "").strip()
    if not text:
        return
    cur = target.text() if hasattr(target, "text") else ""
    target.setText(f"{cur.rstrip()} {text}".strip() if cur.strip() else text)
    target.setFocus()


def mic_button(target, listener=None, kind: str | None = "auto", parent=None):
    """欄 target に声の言葉を入れるマイクのボタンを作る。listener と kind は試験で差し替える"""
    from PySide6.QtCore import QTimer, Signal
    from PySide6.QtWidgets import QPushButton

    class MicButton(QPushButton):
        heard = Signal(str)
        failed = Signal(str)

        def __init__(self):
            super().__init__("🎤", parent)
            self.setFixedWidth(40)
            self.target = target
            self.kind = backend() if kind == "auto" else kind
            self.listener = listener
            self.recording = False
            self.busy = False
            self.message = ""
            self.setToolTip(tooltip(self.kind))
            self.clicked.connect(self.press)
            self.heard.connect(self._heard)
            self.failed.connect(self._failed)
            self.limit = QTimer(self)
            self.limit.setSingleShot(True)
            self.limit.timeout.connect(lambda: self.recording and self.press())

        def press(self):
            if self.busy:
                return
            if self.kind is None:
                self._tell(missing())
                return
            if self.kind == "windows" and self.listener is None:
                self.target.setFocus()
                if start():
                    self._tell("話してください。言葉が欄に入ります（止めるときはもう一度 Win+H）")
                return
            if self.listener is None:
                self.listener = WhisperListener()
            if not self.recording:
                try:
                    self.listener.start()
                except Exception as e:   # noqa: BLE001  マイクが無い・使えない。理由を出して止めない
                    self._tell(f"マイクを開けませんでした: {e}")
                    return
                self.recording = True
                self.setText("■")
                self.setToolTip("聞いています。もう一度押すと文字にして欄に入れます")
                self.limit.start(MAX_SEC * 1000)
                self._tell("聞いています。話し終えたら、もう一度マイクのボタンを押してください")
                return
            self.recording = False
            self.limit.stop()
            self.busy = True
            self.setText("…")
            self.setToolTip("声を文字にしています")
            self._tell("声を文字にしています")
            try:
                audio = self.listener.stop()
            except Exception as e:   # noqa: BLE001
                self.failed.emit(f"録音を止められませんでした: {e}")
                return

            def work():
                try:
                    self.heard.emit(self.listener.transcribe(audio))
                except Exception as e:   # noqa: BLE001  裏で落ちても、ボタンを押せる形に戻す
                    self.failed.emit(f"声を文字にできませんでした: {e}")
            threading.Thread(target=work, daemon=True).start()

        def _reset(self):
            self.busy = False
            self.setText("🎤")
            self.setToolTip(tooltip(self.kind))

        def _heard(self, text: str):
            self._reset()
            if text.strip():
                insert(self.target, text)
                self._tell(f"入れました: {text.strip()}")
            else:
                self._tell("声が聞き取れませんでした。もう一度押して話してください")

        def _failed(self, why: str):
            self._reset()
            self._tell(why)

        def _tell(self, text: str):
            self.message = text
            w = self.window()
            bar = getattr(w, "statusBar", None)
            if callable(bar):
                bar().showMessage(text, 6000)

    return MicButton()
