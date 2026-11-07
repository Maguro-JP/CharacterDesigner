"""右クリックの加工の出し入れ、言葉で指示、指示の登録、音声入力、チャットの操作の試験。
どれもアプリの窓を作り、メニューの項目・ボタンを押して（trigger / click）最後まで流す。絵の模型は偽の模型、声は偽の聞き手で流す"""
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

from chatdraw.engine import has_japanese  # noqa: E402
from chatdraw.tests.test_shortcuts import Base  # noqa: E402


class FakeListener:
    """マイクの代わり。start で聞き始め、stop で音を返し、transcribe で決めた言葉を返す"""

    def __init__(self, words="青い服の少女"):
        self.words, self.started, self.audio = words, 0, None

    def start(self):
        self.started += 1

    def stop(self):
        self.audio = b"fake-audio"
        return self.audio

    def transcribe(self, audio):
        assert audio == b"fake-audio"
        time.sleep(0.05)   # 裏の糸で文字にする間も画面が動くことを見る
        return self.words


class Flow(Base):
    def pump(self, until, sec=30):
        end = time.time() + sec
        while time.time() < end:
            self.qa.processEvents()
            if until():
                return
            time.sleep(0.02)
        self.fail("待っていた物が来ませんでした")

    def menu_action(self, text, menu=None):
        if menu is None:
            menu = self._menu = self.w.build_canvas_menu()
            self._keep = []
        acts = menu.actions()
        self._keep.append(acts)
        for a in acts:
            if a.text() == text:
                return a
            if a.menu() is not None:
                got = self.menu_action(text, a.menu())
                if got is not None:
                    return got
        return None


class HiddenTest(Flow):
    def test_default_shows_only_common_and_picker_keeps_choice(self):
        from PySide6.QtCore import QSettings, Qt
        from chatdraw import shortcuts
        st = shortcuts.Store(QSettings(self.ini + ".fresh", QSettings.IniFormat))   # 利用者がまだ選んでいない形
        self.w._shortcut_store = st
        acts = self.actions()
        self.assertIn("fin:clean", acts)
        self.assertIn("app:lineart", acts)
        self.assertNotIn("fin:mat_gem", acts)                   # よく使う物でない加工は初めは隠す
        self.assertNotIn("質感", [a.text() for a in self._menu.actions()])   # 中身の無いまとまりも出さない
        self.menu_action("加工を選ぶ…").trigger()
        dlg = self.w._pick_dialog
        for i in range(dlg.list.count()):
            it = dlg.list.item(i)
            if it.data(Qt.UserRole) == "fin:mat_gem":
                it.setCheckState(Qt.Checked)
            if it.data(Qt.UserRole) == "app:lineart":
                it.setCheckState(Qt.Unchecked)
        dlg.save()
        acts = self.actions()
        self.assertIn("fin:mat_gem", acts)
        self.assertNotIn("app:lineart", acts)
        # 開き直しても残る（設定の鍵に書いてある）
        again = shortcuts.Store(QSettings(self.ini + ".fresh", QSettings.IniFormat))
        self.assertIn("app:lineart", again.hidden())
        self.assertNotIn("fin:mat_gem", again.hidden())
        st.set_favorite("app:lineart", True)                     # ★ を付けた物は隠していても出す
        self.assertIn("app:lineart", self.actions())
        self.press("fin:mat_gem")                               # 出した物は押して最後まで動く


class TextInstructionTest(Flow):
    def open_dialog(self):
        self.menu_action("言葉で指示…").trigger()
        return self.w._text_dialog

    def test_fix_whole_picture_japanese_goes_through_words_and_lands_on_top(self):
        n = len(self.w.canvas.layers)
        dlg = self.open_dialog()
        self.assertEqual(dlg.where.text(), "直す所: 絵全体")
        dlg.edit.setText("目を大きく")
        dlg.run.click()
        self.wait()
        redraws = [c for c in self.painter.calls if c[0] == "redraw"]
        self.assertTrue(redraws)
        self.assertFalse(has_japanese(redraws[-1][1]), redraws[-1][1])   # 日本語をそのまま絵の模型に渡さない
        c = self.w.canvas
        self.assertGreater(len(c.layers), n)
        self.assertEqual(c.current, len(c.layers) - 1)              # 結果は一番上の新しいレイヤーで、選んだ状態

    def test_region_and_effect_and_draw(self):
        from PySide6.QtCore import QRect
        self.w.canvas.set_selection(QRect(10, 10, 40, 40))
        dlg = self.open_dialog()
        self.assertEqual(dlg.where.text(), "直す所: 囲んだ所")
        self.w.canvas.set_selection(None)
        dlg.edit.setText("線画にして")
        n = len(self.w.canvas.layers)
        dlg.run.click()
        self.pump(lambda: not getattr(self.w, "_plan_queue", []))
        self.wait()
        self.assertGreater(len(self.w.canvas.layers), n)
        dlg = self.open_dialog()
        dlg.edit.setText("猫耳の少女を描いて")
        before = len(self.painter.calls)
        dlg.run.click()
        self.wait()
        new = [c for c in self.painter.calls[before:] if c[0] != "redraw"]
        self.assertTrue(new)
        self.assertFalse(has_japanese(new[-1][0]))

    def test_register_from_dialog_then_one_click_edit_move_remove(self):
        dlg = self.open_dialog()
        dlg.edit.setText("背景を夕焼けに")
        with mock.patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("夕焼け", True)):
            dlg.save.click()
        sid = dlg.saved
        top = [a for a in self.w.build_canvas_menu().actions() if a.objectName() == sid]
        self.assertEqual(len(top), 1)                               # 小さなメニューに入れず、1 回で押せる所にある
        calls = len(self.painter.calls)
        top[0].trigger()
        self.wait()
        self.assertTrue(any(c[0] == "redraw" for c in self.painter.calls[calls:]))
        b = self.w.shortcut_store().add("目", "目を大きく")
        man = self.w.open_shortcuts()
        man.select(sid)
        man.edit_text("背景を青空に")
        self.assertEqual(next(p["text"] for p in self.w.shortcut_store().prompts() if p["id"] == sid), "背景を青空に")
        man.select(b)
        man.up.click()
        self.assertEqual([p["id"] for p in self.w.shortcut_store().prompts()], [b, sid])
        man.down.click()
        self.assertEqual([p["id"] for p in self.w.shortcut_store().prompts()], [sid, b])
        man.select(b)
        man.rem.click()
        self.assertEqual([p["id"] for p in self.w.shortcut_store().prompts()], [sid])
        for x in (man.edit, man.up, man.down, man.rem):
            self.assertTrue(x.toolTip())


class VoiceTest(Flow):
    def test_every_field_has_mic_and_text_arrives(self):
        dlg = self.w.open_text_instruction()
        for field, mic in ((self.w.entry, self.w.mic_button), (self.w.chat.input, self.w.chat.mic_button),
                           (dlg.edit, dlg.mic)):
            with self.subTest(field=type(field).__name__):
                self.assertTrue(mic.toolTip())
                fake = FakeListener()
                mic.kind, mic.listener = "whisper", fake
                field.setText("")
                mic.click()                                         # 押して話す
                self.assertTrue(mic.recording)
                self.assertEqual(fake.started, 1)
                mic.click()                                         # もう一度押すと文字にする
                self.pump(lambda: not mic.busy)
                self.assertEqual(field.text(), "青い服の少女")
                self.assertEqual(mic.text(), "🎤")
        dlg.reject()

    def test_appends_to_what_is_written(self):
        mic = self.w.mic_button
        mic.kind, mic.listener = "whisper", FakeListener("全身")
        self.w.entry.setText("赤いマフラーの女の子")
        mic.click()
        mic.click()
        self.pump(lambda: not mic.busy)
        self.assertEqual(self.w.entry.text(), "赤いマフラーの女の子 全身")

    def test_missing_tells_what_to_install(self):
        from chatdraw import voice
        with mock.patch.object(voice, "_has", return_value=False), mock.patch.object(voice.sys, "platform", "linux"):
            self.assertIsNone(voice.backend())
            b = voice.mic_button(self.w.entry, parent=self.w)
            self.assertIn("faster-whisper", b.toolTip())
            self.assertIn("sounddevice", b.toolTip())
            b.click()
            self.assertIn("pip install", b.message)

    def test_whisper_model_goes_to_shared_place(self):
        from chatdraw import paths, voice
        seen = {}

        class FakeModel:
            def __init__(self, name, **kw):
                seen.update(name=name, **kw)

        fake = mock.MagicMock(WhisperModel=FakeModel)
        with mock.patch.dict(sys.modules, {"faster_whisper": fake}), mock.patch.object(voice, "_model", None):
            voice.whisper_model()
        self.assertEqual(seen["name"], "small")
        self.assertEqual(seen["download_root"], str(paths.HUB))

    def test_failure_frees_button(self):
        mic = self.w.mic_button
        bad = FakeListener()
        bad.transcribe = lambda a: (_ for _ in ()).throw(RuntimeError("壊れた"))
        mic.kind, mic.listener = "whisper", bad
        mic.click()
        mic.click()
        self.pump(lambda: not mic.busy)
        self.assertIn("できませんでした", mic.message)
        self.assertEqual(mic.text(), "🎤")


class ChatTest(Flow):
    def bubbles(self):
        return self.w.chat.bubbles()

    def test_ambiguous_effect_offers_buttons_then_result_thumbnail_opens(self):
        self.w.chat_send("何か加工して")
        b = self.bubbles()[-1]
        labels = [b.buttons.itemAt(i).widget().text() for i in range(b.buttons.count())]
        self.assertIn("線画", labels)
        n = len(self.w.canvas.layers)
        next(b.buttons.itemAt(i).widget() for i in range(b.buttons.count())
             if b.buttons.itemAt(i).widget().text() == "線画").click()
        self.pump(lambda: self.bubbles()[-1].image is not None)
        self.assertGreater(len(self.w.canvas.layers), n)
        last = self.bubbles()[-1]
        self.assertTrue(Path(last.image).is_file())
        self.assertLessEqual(max(last.thumb.iconSize().width(), last.thumb.iconSize().height()), 160)
        last.thumb.click()
        viewer = self.w.chat._viewer
        self.assertTrue(viewer.isVisible())
        viewer.accept()

    def test_registered_instruction_by_name_and_choice(self):
        st = self.w.shortcut_store()
        a = st.add("夕焼け", "背景を夕焼けに")
        st.add("目", "目を大きく")
        self.w.chat_send("登録した指示を使って")
        b = self.bubbles()[-1]
        self.assertEqual(b.buttons.count(), 2)
        calls = len(self.painter.calls)
        self.w.chat_send("「夕焼け」を使って")
        self.wait()
        self.assertTrue(any(c[0] == "redraw" for c in self.painter.calls[calls:]))
        self.assertEqual(st.uses().get(a), 1)
        self.pump(lambda: self.bubbles()[-1].image is not None)

    def test_style_layers_save(self):
        self.w.chat_send("画風を変えて")
        b = self.bubbles()[-1]
        self.assertGreater(b.buttons.count(), 1)
        name = b.buttons.itemAt(1).widget().text()
        b.buttons.itemAt(1).widget().click()
        self.pump(lambda: not getattr(self.w, "asking", False))
        self.assertEqual(self.w.ai_panel.style, name)
        self.w.chat_send("レイヤーを足して")
        self.pump(lambda: not getattr(self.w, "asking", False))
        c = self.w.canvas
        self.w.chat_send("レイヤーを隠して")
        self.pump(lambda: not getattr(self.w, "asking", False))
        self.assertFalse(c.layers[c.current].visible)
        self.w.chat_send("レイヤーを出して")
        self.pump(lambda: not getattr(self.w, "asking", False))
        self.assertTrue(c.layers[c.current].visible)
        self.w.chat_send("線画にしてから書き出して")
        self.pump(lambda: not getattr(self.w, "_plan_queue", []))
        self.wait()
        out = Path(self.w.settings.get("output_dir"))
        self.assertTrue(list(out.glob("*.png")))

    def test_thumbnail_survives_restart(self):
        from chatdraw.chatpanel import ChatPanel
        self.w.chat.set_store(Path(self.tmp.name) / "chat.json")
        self.w.chat_send("線画にして")
        self.pump(lambda: self.bubbles()[-1].image is not None)
        again = ChatPanel(Path(self.tmp.name) / "chat.json")
        self.assertTrue(any(b.image for b in again.bubbles()))


if __name__ == "__main__":
    unittest.main()
