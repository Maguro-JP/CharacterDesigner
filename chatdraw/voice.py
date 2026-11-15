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
HOLD_SEC = 0.45   # これより長く押していたら「押して話す・離して送る」、短く押したら「押すたびに始める・止める」
LIVE_MS = 1500    # 話している間、これだけごとに途中の文字を出す
MIN_SPEECH_SEC = 0.4   # 声の大きさが閾を超えた長さがこれより短い音は、雑音として文字にしない
NOISE_RMS = 0.012      # 声とみなす音の大きさ（float32 の RMS）。キーボードや机を叩く音・空調の音を拾わない
NO_SPEECH = 0.6        # whisper が「声ではない」と見た確からしさがこれを超える区切りは捨てる
# 無音や雑音から whisper が作りがちな文（動画の締めの決まり文句）。これだけの答えは聞き取れなかったとして扱う
HALLUCINATED = ("ご視聴ありがとうございました", "ご清聴ありがとうございました", "チャンネル登録", "thank you for watching",
                "thanks for watching")
LANGS = {"ja": "日本語", "en": "英語", "zh": "中国語", "ko": "韓国語", "fr": "フランス語", "de": "ドイツ語", "es": "スペイン語"}
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
        return ("声で入力します。押したまま話して離すと文字にして入れます（チャットはそのまま送ります）。"
                "短く押すと聞き始め、もう一度押すと止めます。話している間は途中の文字が出ます。言語は自動で見分けます"
                "（手元の模型で読み、外へ送りません）")
    if kind == "windows":
        return "声で入力します（Windows の音声入力 Win+H を開きます）。手元の模型で読むには " + INSTALL + " を入れてください"
    return missing()


_model = None
_model_lock = threading.Lock()
_run_lock = threading.Lock()   # 1 つの模型を途中の文字と仕上げの文字で同時に回さない


def whisper_model():
    """模型はアプリの中で 1 回だけ読む（読むのに数秒かかる）。どの欄のマイクも同じ模型を使う。置き場は共有の huggingface"""
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            from chatdraw import paths
            paths.ensure_shared()
            _model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=str(paths.HUB))
        return _model


def preload():
    """初めて押したときに待たないよう、裏で模型を読んでおく（読み終えていれば何もしない）"""
    if _model is None and whisper_ready():
        threading.Thread(target=lambda: _safe(whisper_model), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception:   # noqa: BLE001  先読みが落ちても、押したときに理由を出す
        pass


def speech_seconds(audio, rate: int = RATE, frame: int = 480) -> float:
    """音の中で、声の大きさ（NOISE_RMS）を超えた長さ（秒）。雑音だけの録音を文字にしないために使う"""
    import numpy as np
    a = np.asarray(audio, dtype="float32").reshape(-1)
    n = a.size // frame
    if n == 0:
        return 0.0
    rms = np.sqrt((a[:n * frame].reshape(n, frame) ** 2).mean(axis=1))
    return float((rms > NOISE_RMS).sum() * frame / rate)


def hallucinated(text: str) -> bool:
    t = (text or "").strip().strip("。.!！ ").lower()
    return not t or any(h in t for h in HALLUCINATED) and len(t) <= 24


class WhisperListener:
    """マイクの音を集め、止めたら faster-whisper で文字にする。言語は whisper に見分けさせ、見分けた言語を残す"""

    def __init__(self):
        self.chunks, self.stream = [], None
        self.language: str | None = None   # 見分けた言語（"ja" など）。途中の文字で決まったら仕上げにも使う

    def start(self):
        import sounddevice as sd
        self.chunks = []
        self.language = None
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                     callback=lambda data, _n, _t, _s: self.chunks.append(data.copy()))
        self.stream.start()
        preload()

    def peek(self):
        """録っている途中の音（止めずに）"""
        import numpy as np
        chunks = list(self.chunks)
        return np.concatenate(chunks).reshape(-1) if chunks else np.zeros(0, "float32")

    def stop(self):
        import numpy as np
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        return np.concatenate(self.chunks).reshape(-1) if self.chunks else np.zeros(0, "float32")

    def transcribe(self, audio, partial: bool = False) -> str:
        if getattr(audio, "size", 0) < RATE // 4:   # 0.25 秒より短い音は、押し間違いとして文字にしない
            return ""
        if speech_seconds(audio) < MIN_SPEECH_SEC:   # 声の大きさに届かない音（雑音）は模型に回さない
            return ""
        with _run_lock:
            segments, info = whisper_model().transcribe(
                audio, beam_size=1 if partial else 3, vad_filter=True, language=self.language,
                condition_on_previous_text=False)
            segs = [s for s in segments if getattr(s, "no_speech_prob", 0.0) <= NO_SPEECH]
        if self.language is None and getattr(info, "language_probability", 0) >= 0.5:
            self.language = info.language
        text = "".join(s.text for s in segs).strip()
        return "" if hallucinated(text) else text


def insert(target, text: str):
    """欄の今の言葉の後ろに足す（書きかけの言葉を消さない）"""
    text = (text or "").strip()
    if not text:
        return
    cur = target.text() if hasattr(target, "text") else ""
    target.setText(f"{cur.rstrip()} {text}".strip() if cur.strip() else text)
    target.setFocus()


def mic_button(target, listener=None, kind: str | None = "auto", parent=None, on_final=None, on_live=None):
    """欄 target に声の言葉を入れるマイクのボタンを作る。listener と kind は試験で差し替える。
    on_final(text) は押したまま話して離したときに呼ぶ（チャットはそのまま送る）。on_live(text) は話している間の途中の文字"""
    import time
    from PySide6.QtCore import Qt, QTimer, Signal
    from PySide6.QtWidgets import QPushButton

    class MicButton(QPushButton):
        heard = Signal(str)
        failed = Signal(str)
        live = Signal(str)

        def __init__(self):
            super().__init__("🎤", parent)
            self.setFixedWidth(40)
            self.target = target
            self.kind = backend() if kind == "auto" else kind
            self.listener = listener
            self.recording = False
            self.busy = False
            self.message = ""
            self.live_text = ""
            self.on_final, self.on_live = on_final, on_live
            self.send_after = False   # 押したまま話して離したときは、文字にしたら送る
            self._pressed_at = None
            self._skip_click = False
            self._live_busy = False
            self.setToolTip(tooltip(self.kind))
            self.clicked.connect(self._clicked)
            self.heard.connect(self._heard)
            self.failed.connect(self._failed)
            self.live.connect(self._live)
            self.limit = QTimer(self)
            self.limit.setSingleShot(True)
            self.limit.timeout.connect(lambda: self.recording and self.press())
            self.ticker = QTimer(self)
            self.ticker.setInterval(LIVE_MS)
            self.ticker.timeout.connect(self._live_tick)

        # 押して話す・離して送る。短く押したときは、押すたびに始める・止める
        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton and not self.busy and not self.recording and self.kind == "whisper":
                self._pressed_at = time.time()
                self.press()
                self._skip_click = True
            super().mousePressEvent(e)

        def mouseReleaseEvent(self, e):
            held = self._pressed_at is not None and time.time() - self._pressed_at >= HOLD_SEC
            self._pressed_at = None
            if held and self.recording:
                self.send_after = self.on_final is not None
                self.press()
            super().mouseReleaseEvent(e)

        def _clicked(self):
            if self._skip_click:   # 押したときに聞き始めた（離したときの click で止めない）
                self._skip_click = False
                return
            self.press()

        def enterEvent(self, e):
            if self.kind == "whisper":
                preload()   # カーソルを合わせた時点で模型を読み始め、押してから待たない
            super().enterEvent(e)

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
                self.live_text = ""
                self.setText("■")
                self.setToolTip("聞いています。離すか、もう一度押すと文字にして入れます")
                self.limit.start(MAX_SEC * 1000)
                if hasattr(self.listener, "peek"):
                    self.ticker.start()
                self._tell("聞いています。話し終えたら離すか、もう一度押してください")
                return
            self.recording = False
            self.limit.stop()
            self.ticker.stop()
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

        def _live_tick(self):
            """話している間の途中の文字。前の途中がまだ終わっていなければ飛ばす（模型を待ち行列にしない）"""
            if not self.recording or self._live_busy:
                return
            self._live_busy = True
            audio = self.listener.peek()

            def work():
                try:
                    got = self.listener.transcribe(audio, partial=True)
                except TypeError:
                    got = self.listener.transcribe(audio)
                except Exception:   # noqa: BLE001  途中の文字は出せなくても、仕上げで文字にする
                    got = ""
                finally:
                    self._live_busy = False
                if got:
                    self.live.emit(got)
            threading.Thread(target=work, daemon=True).start()

        def _live(self, text: str):
            if not self.recording:
                return   # 止めたあとに届いた途中の文字は出さない
            self.live_text = text
            if self.on_live is not None:
                self.on_live(text)
            lang = LANGS.get(getattr(self.listener, "language", None) or "", "")
            self._tell(("聞いています（" + lang + "）: " if lang else "聞いています: ") + text)

        def _reset(self):
            self.busy = False
            self.setText("🎤")
            self.setToolTip(tooltip(self.kind))
            if self.on_live is not None:
                self.on_live("")

        def _heard(self, text: str):
            send, self.send_after = self.send_after, False
            self._reset()
            if text.strip():
                insert(self.target, text)
                self._tell(f"入れました: {text.strip()}")
                if send and self.on_final is not None:
                    self.on_final(text.strip())
            else:
                self._tell("声が聞き取れませんでした（雑音だけの音は文字にしません）。もう一度押して話してください")

        def _failed(self, why: str):
            self.send_after = False
            self._reset()
            self._tell(why)

        def _tell(self, text: str):
            self.message = text
            w = self.window()
            bar = getattr(w, "statusBar", None)
            if callable(bar):
                bar().showMessage(text, 6000)

    return MicButton()
