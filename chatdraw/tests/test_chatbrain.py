"""チャットの相談相手（流しながら答える・今の絵を知って答える・頼まれた操作をする）と、押して話す音声入力の試験。
アプリの窓を offscreen で作り、言葉の模型と声は偽の物で、送る・押す・離すを本物と同じ経路で流す"""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.tests.test_chatdraw import FakeWords  # noqa: E402
from chatdraw.tests.test_shortcuts import Base  # noqa: E402


class StreamWords(FakeWords):
    """少しずつ答える言葉の模型。渡された会話を覚え、決めた答えを数文字ずつ返す"""

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def stream(self, messages, max_tokens=300):
        self.seen.append(messages)
        reply = self.replies.pop(0) if self.replies else "はい。"
        for i in range(0, len(reply), 4):
            time.sleep(0.02)
            yield reply[i:i + 4]


class Flow(Base):
    def pump(self, until, sec=15):
        end = time.time() + sec
        while time.time() < end:
            self.qa.processEvents()
            if until():
                return
            time.sleep(0.02)
        self.fail("待っていた物が来ませんでした")

    def texts(self):
        return [b.text for b in self.w.chat.bubbles()]


class ConverseTest(Flow):
    def test_streams_knows_canvas_and_remembers(self):
        words = self.w.studio.words = StreamWords(["顔のまわりに光を足すと明るく見えます。", "前に話した光を、髪の縁にも足しましょう。"])
        pieces = []
        orig = self.w._chat_piece
        self.w._chat_piece = lambda t: (pieces.append(t), orig(t))
        self.w._chat_stream = None
        self.w.chat_send("この絵をもっと明るくするには？")
        self.pump(lambda: not self.w.asking)
        self.assertGreater(len(pieces), 2)                       # 流しながら出した
        self.assertTrue(pieces[-1].startswith("顔のまわり"))
        system = words.seen[0][0]["content"]
        self.assertIn("レイヤー", system)                          # 今の絵とレイヤーを見せた
        self.assertIn("赤ペンの印", system)
        self.assertEqual(self.texts()[-1], "顔のまわりに光を足すと明るく見えます。")
        self.w.chat_send("それを続けて")
        self.pump(lambda: not self.w.asking)
        talk = " ".join(m["content"] for m in words.seen[1][1:])
        self.assertIn("この絵をもっと明るくするには", talk)          # 前の会話を覚えている
        self.assertIn("顔のまわりに光", talk)
        self.assertEqual(len(self.w.chat.bubbles()), 4)          # 途中の吹き出しは残さない

    def test_progress_goes_to_progress_panel_not_chat(self):
        before = len(self.w.chat.bubbles())
        self.w.say("工程 1「下絵」12 秒: 崩れは見つかりませんでした")
        self.assertEqual(len(self.w.chat.bubbles()), before)
        self.assertIn("工程 1", self.w.activity.detail.text())
        self.assertIn("工程 1", self.w.statusBar().currentMessage())

    def test_no_model_tells_how_to_get_one(self):
        from chatdraw import assistant

        class NoWords(FakeWords):
            def ready(self):
                return False
        self.w.studio.words = NoWords()
        self.w.chat_send("今日は何を描こうかな")
        self.pump(lambda: not self.w.asking)
        b = self.w.chat.bubbles()[-1]
        self.assertEqual(b.text, assistant.NO_MODEL)
        btn = b.buttons.itemAt(0).widget()
        self.assertEqual(btn.text(), "言葉の模型を取る")
        self.assertIn("模型の管理", btn.toolTip())


class ActionTest(Flow):
    def test_finisher_action_shows_line_then_runs(self):
        from chatdraw import finishers
        label = next(iter(finishers.REGISTRY.values())).label
        self.w.studio.words = StreamWords([f"柔らかくします。\n操作: 加工 {label}"])
        ran = []
        with mock.patch.object(self.w, "finish_with", lambda n, background=False: ran.append(n)):
            self.w.chat_send("もう少し柔らかい感じにできる？")
            self.pump(lambda: any(t.startswith("する: ") for t in self.texts()))
            self.assertIn(f"「{label}」を掛けます", self.texts()[-1])   # する前に 1 行で見せる
            self.assertEqual(ran, [])
            self.pump(lambda: ran)
        self.assertEqual(finishers.REGISTRY[ran[0]].label, label)

    def test_draw_action_keeps_word_field_and_cancel_stops(self):
        self.w.entry.setText("赤いマフラーの少女")
        self.w.studio.words = StreamWords(["描いてみます。\n操作: 描く 青い服の少女", "はい。\n操作: 描く 猫"])
        sent = []
        with mock.patch.object(self.w, "send", lambda once=None: sent.append(once)):
            self.w.chat_send("青い服にした絵も見たい")
            self.pump(lambda: sent)
            self.assertEqual(sent, ["青い服の少女"])
            self.assertEqual(self.w.entry.text(), "赤いマフラーの少女")   # 描くワードは変えない
            self.w.chat_send("猫も見たい")
            self.pump(lambda: self.texts()[-1].startswith("する: "))
            b = self.w.chat.bubbles()[-1]
            b.buttons.itemAt(0).widget().click()                        # やめる
            t = time.time() + 2.2
            while time.time() < t:
                self.qa.processEvents()
                time.sleep(0.02)
        self.assertEqual(sent, ["青い服の少女"])
        self.assertIn("やめました", b.text)

    def test_word_change_only_when_asked(self):
        self.w.entry.setText("少女")
        self.w.studio.words = StreamWords(["猫にしました。\n操作: 描くワード 猫", "変えます。\n操作: 描くワード 黒猫"])
        self.w.chat_send("猫の方がいいかな")
        self.pump(lambda: not self.w.asking)
        t = time.time() + 2
        while time.time() < t:
            self.qa.processEvents()
            time.sleep(0.02)
        self.assertEqual(self.w.entry.text(), "少女")                    # 頼まれていないので変えない
        self.w.chat_send("描くワードを黒猫に変えて")
        self.pump(lambda: self.w.entry.text() == "黒猫")

    def test_redpen_without_marks_switches_tool(self):
        msg = self.w.run_chat_action(("赤ペンで直す", ""))
        self.assertIn("赤ペンの印がありません", msg)
        self.assertEqual(self.w.canvas.tool, "redpen")


class PeekListener:
    """押して話す偽のマイク。途中の音を peek で返し、途中は短い言葉、仕上げは全文を返す"""

    def __init__(self):
        self.language = "ja"

    def start(self):
        pass

    def peek(self):
        return b"part"

    def stop(self):
        return b"all"

    def transcribe(self, audio, partial=False):
        time.sleep(0.03)
        return "髪を" if audio == b"part" else "髪を長くするには"


class VoiceTest(Flow):
    def test_hold_to_talk_shows_live_text_and_sends(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from chatdraw import voice
        mic = self.w.chat.mic_button
        mic.kind, mic.listener = "whisper", PeekListener()
        got = []
        with mock.patch.object(voice, "LIVE_MS", 100), mock.patch.object(self.w, "chat_send", got.append):
            mic.ticker.setInterval(100)
            QTest.mousePress(mic, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
            self.assertTrue(mic.recording)
            self.pump(lambda: self.w.chat.live.isVisible() if self.w.chat.isVisible() else bool(self.w.chat.live.text()))
            self.assertIn("髪を", self.w.chat.live.text())                 # 話している間の文字
            self.assertIn("日本語", mic.message)                           # 見分けた言語
            t = time.time() + voice.HOLD_SEC + 0.1
            while time.time() < t:
                self.qa.processEvents()
                time.sleep(0.02)
            QTest.mouseRelease(mic, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
            self.pump(lambda: got)
        self.assertEqual(got, ["髪を長くするには"])                        # 離すと送る
        self.assertFalse(mic.recording)
        self.assertEqual(self.w.chat.live.text(), "")

    def test_noise_is_not_transcribed(self):
        import numpy as np
        from chatdraw import voice
        quiet = (np.random.default_rng(0).standard_normal(voice.RATE * 2) * 0.002).astype("float32")
        self.assertLess(voice.speech_seconds(quiet), voice.MIN_SPEECH_SEC)
        loud = (np.sin(np.arange(voice.RATE) / 8.0) * 0.2).astype("float32")
        self.assertGreater(voice.speech_seconds(loud), 0.9)
        with mock.patch.object(voice, "whisper_model", side_effect=AssertionError("雑音で模型を回した")):
            self.assertEqual(voice.WhisperListener().transcribe(quiet), "")
        self.assertTrue(voice.hallucinated("ご視聴ありがとうございました。"))
        self.assertFalse(voice.hallucinated("ご視聴ありがとうございましたと書いた看板を持つ少女"))

    def test_model_loads_once(self):
        from chatdraw import voice
        made = []

        class FakeModel:
            def __init__(self, name, **kw):
                made.append(name)
        fake = mock.MagicMock(WhisperModel=FakeModel)
        with mock.patch.dict(sys.modules, {"faster_whisper": fake}), mock.patch.object(voice, "_model", None):
            a, b = voice.whisper_model(), voice.whisper_model()
        self.assertIs(a, b)
        self.assertEqual(made, ["small"])


class ShotTest(Flow):
    def test_window_shot(self):
        """窓の写しを撮る（目で見えるか・幅が潰れていないかを確かめるため）。CD_SHOT に置き場を渡したときだけ残す"""
        out = os.environ.get("CD_SHOT")
        self.w.chat.resize(380, 620)
        self.w.studio.words = StreamWords(["光を足すと明るく見えます。顔のまわりから試しましょう。\n操作: 描く 光の差す少女"])
        with mock.patch.object(self.w, "send", lambda once=None: None):
            self.w.chat_send("もっと明るい絵にしたい")
            self.pump(lambda: any(t.startswith("する: ") for t in self.texts()))
        self.w.chat.show_live("髪を長く")
        self.qa.processEvents()
        self.assertGreater(self.w.chat.input.width(), 120)
        for b in self.w.chat.bubbles():
            self.assertLessEqual(b.width(), self.w.chat.scroll.viewport().width())
        if out:
            self.w.grab().save(str(Path(out) / "window.png"))
            self.w.chat.grab().save(str(Path(out) / "chat.png"))


if __name__ == "__main__":
    unittest.main()
