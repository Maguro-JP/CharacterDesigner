"""模型の管理を 1 か所にしたこと、言葉の模型の選択を覚えること、ツールチップの中身、言葉の模型への渡し方の試験"""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _settings(d):
    from PySide6.QtCore import QSettings
    from chatdraw.settings import Settings
    return Settings(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))


class SettingsHasNoModelsTest(unittest.TestCase):
    def test_settings_dialog_has_no_model_fields(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.settings import FIELDS, SettingsDialog
        QApplication.instance() or QApplication([])
        keys = {f[0] for f in FIELDS}
        self.assertFalse(keys & {"image_model", "words_model", "model_dir"})
        with TemporaryDirectory() as d:
            st = _settings(d)
            dlg = SettingsDialog(st)
            self.assertFalse(set(dlg.inputs) & {"image_model", "words_model", "model_dir"})
            self.assertEqual(st.get("words_model"), "")   # 値は残っていて読める

    def test_settings_menu_has_no_model_manager(self):
        src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("模型の管理（入れ替え・更新）", src)
        self.assertNotIn("model_dir_changed", src)


class ManagerTest(unittest.TestCase):
    def _manager(self, d):
        from PySide6.QtWidgets import QApplication
        from chatdraw import manager
        QApplication.instance() or QApplication([])
        g = Path(d) / "g"
        g.mkdir()
        (g / "mine.gguf").write_bytes(b"x" * 10)
        st = _settings(d)
        with mock.patch.object(manager, "HUB", Path(d) / "hub"), mock.patch.object(manager, "GGUF", g), \
                mock.patch.object(manager, "OWN_LLM", Path(d) / "none"):
            dlg = manager.ModelManager(st)
        return dlg, st, g

    def _cards(self, dlg):
        return [w for w in (dlg.list.itemAt(i).widget() for i in range(dlg.list.count())) if w and w.objectName() == "card"]

    def test_words_choice_lives_in_manager(self):
        from PySide6.QtWidgets import QLabel, QPushButton
        from chatdraw import manager
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            dlg, st, g = self._manager(d)
            self.assertFalse(manager.words_chosen(st))
            dlg.use_words(str(g / "mine.gguf"))
            self.assertTrue(manager.words_chosen(st))
            self.assertEqual(st.get("words_model"), str(g / "mine.gguf"))
            dlg.use_no_words()
            self.assertTrue(manager.words_chosen(st))
            self.assertEqual(st.get("words_model"), "")
            with mock.patch.object(manager, "GGUF", g), mock.patch.object(manager, "OWN_LLM", Path(d) / "none"):
                dlg.refresh()
            none = [c for c in self._cards(dlg) if c.findChildren(QLabel)[0].text() == "使わない"][0]
            self.assertEqual([b.text() for b in none.findChildren(QPushButton)], ["使用中"])
            self.assertIn("言葉の模型を使いません", none.toolTip())

    def test_model_dir_moved_to_manager(self):
        from chatdraw import paths
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            dlg, _st, _g = self._manager(d)
            with mock.patch.object(paths, "set_model_dir") as setter, mock.patch.object(paths, "chosen_model_dir", return_value=""):
                dlg.change_model_dir(str(Path(d) / "models"))
            setter.assert_called_once_with(str(Path(d) / "models"))
            self.assertIn("次の起動から", dlg.status.text())

    def test_image_rows_are_short_and_tooltip_is_clean(self):
        from PySide6.QtWidgets import QLabel
        from chatdraw import models
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            dlg, _st, _g = self._manager(d)
            rows = [c for c in self._cards(dlg) if hasattr(c, "model")]
            self.assertEqual(len(rows), len(models.IMAGES))
            for c in rows:
                m, tip = c.model, c.toolTip()
                self.assertIn(m.name, tip)
                self.assertIn("評価:", tip)
                self.assertIn(f"{m.gb:.1f}GB", tip)
                self.assertIn("商用:", tip)
                self.assertIn("まだ取っていません", tip)
                # 道・型番・内部の名前は出さない
                for bad in ("Hugging Face:", m.hub, m.file or "\0", "VRAM", m.family, m.note or "\0", "/"):
                    self.assertNotIn(bad, tip, (m.name, bad))
                meta = c.findChildren(QLabel)[1].text()
                self.assertNotIn(models.family(m.family).name, meta)   # 細目は行から減らした
                self.assertNotIn("動き方", meta)
                self.assertLessEqual(len(tip.splitlines()), 8)


class AskWordsOnceTest(unittest.TestCase):
    def _window(self, d):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from chatdraw.app import Window
        w = Window.__new__(Window)
        w.settings = _settings(d)
        w._studio_from_settings = lambda: None
        w.statusBar = mock.Mock()
        w.watch_fetch = mock.Mock()
        return w

    def test_asks_once_and_remembers_none(self):
        from chatdraw.app import Window
        from chatdraw.manager import words_chosen
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            w = self._window(d)
            asked = []
            Window.ask_words_once(w, pick=lambda items: asked.append(items) or "使わない")
            self.assertEqual(len(asked), 1)
            self.assertEqual(asked[0][-1], "使わない")
            self.assertTrue(words_chosen(w.settings))
            self.assertEqual(w.settings.get("words_model"), "")
            Window.ask_words_once(w, pick=lambda items: asked.append(items) or "使わない")   # 2 回目の起動
            self.assertEqual(len(asked), 1)

    def test_chosen_model_is_kept_and_not_upgraded(self):
        from chatdraw.app import Window
        from chatdraw.models import offered_words
        from chatdraw import setup
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}), \
                mock.patch.object(setup, "has_words", return_value=True):
            w = self._window(d)
            Window.ask_words_once(w, pick=lambda items: items[-2])   # いちばん後ろの模型
            chosen = w.settings.get("words_model")
            self.assertTrue(chosen.endswith(offered_words()[-1].file))
            w.notify = mock.Mock()
            Window.upgrade_models(w)   # 選んだ物は、点の高い物があっても替えない
            self.assertEqual(w.settings.get("words_model"), chosen)

    def test_setup_dialog_keeps_chosen_words(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.manager import choose_words
        from chatdraw.setup import SetupDialog
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            st = _settings(d)
            choose_words(st, "")
            dlg = SetupDialog(st, first=False)
            dlg.apply()
            self.assertEqual(st.get("words_model"), "")


class FakeChat:
    """偽の言葉の模型。渡された発言を残し、決めた答えを返す"""

    def __init__(self, reply):
        self.reply, self.got = reply, None

    def ready(self):
        return True

    def chat(self, messages, max_tokens=200, one_line=False):
        self.got = messages
        return self.reply


class AssistantTest(unittest.TestCase):
    def test_history_is_passed_as_roles(self):
        from chatdraw import assistant
        fake = FakeChat("赤にすると目立ちます。\n描く内容: 赤い服の少女")
        turns = [("ai", "こんにちは"), ("user", "少女を描きたい"), ("ai", "描く内容に書いてください"), ("ai", "（続き）")]
        reply, new = assistant.answer(fake, turns, "服を赤くして", "青い服の少女")
        roles = [m["role"] for m in fake.got]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[1], "user")                     # 模型の発言から始めない
        self.assertEqual(roles[-1], "user")
        self.assertEqual(fake.got[-1]["content"], "服を赤くして")
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])))   # 同じ役割は続けない
        self.assertIn("青い服の少女", fake.got[0]["content"])
        self.assertIn("ペン", fake.got[0]["content"])           # アプリでできる操作を見せる
        self.assertIn("模型の管理", fake.got[0]["content"])
        self.assertEqual((reply, new), ("赤にすると目立ちます。", "赤い服の少女"))

    def test_question_gets_no_proposal_and_labels_are_dropped(self):
        from chatdraw import assistant
        fake = FakeChat("あなた: 「設定」のメニューで保存先を変えます。\n描く内容: 少女\n利用者: ありがとう")
        reply, new = assistant.answer(fake, [], "保存先はどこで変えますか？", "少女")
        self.assertEqual(reply, "「設定」のメニューで保存先を変えます。")
        self.assertIsNone(new)

    def test_context_is_bounded(self):
        from chatdraw import assistant
        fake = FakeChat("はい")
        turns = [("user", "あ" * 400), ("ai", "い" * 400), ("user", "う" * 400), ("ai", "え" * 400)]
        assistant.answer(fake, turns, "続けて", "")
        talk = sum(len(m["content"]) for m in fake.got[1:])
        self.assertLessEqual(talk, assistant.CONTEXT_CHARS + 10)

    def test_old_ask_only_models_still_work(self):
        from chatdraw import assistant

        class Old:
            def ready(self):
                return True

            def ask(self, system, text, max_tokens=64, one_line=True):
                self.text = text
                return "描く内容: 猫"
        old = Old()
        _reply, new = assistant.answer(old, [("user", "やあ")], "猫にして", "犬")
        self.assertEqual(new, "猫")
        self.assertIn("利用者: 猫にして", old.text)

    def test_engine_chat_builds_qwen_turns(self):
        from chatdraw import engine

        class LLM:
            metadata = {"tokenizer.chat_template": "<|im_start|>"}

            def create_completion(self, prompt, stop, **kw):
                self.prompt = prompt
                return {"choices": [{"text": "はい"}], "usage": {"completion_tokens": 1}}
        llm = LLM()
        with mock.patch.object(engine, "_llm_for", return_value=llm):
            w = engine.Words(Path("x.gguf"))
            out = w.chat([{"role": "system", "content": "S"}, {"role": "user", "content": "U1"},
                          {"role": "assistant", "content": "A1"}, {"role": "user", "content": "U2"}])
        self.assertEqual(out, "はい")
        self.assertIn("<|im_start|>assistant\nA1<|im_end|>\n<|im_start|>user\nU2<|im_end|>\n<|im_start|>assistant\n", llm.prompt)


if __name__ == "__main__":
    unittest.main()
