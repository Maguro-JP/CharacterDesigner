"""チャットの頼みの枚数・複数枚の途中の失敗・デバッグモード・頼んでいない性的な絵の打ち消し。
絵の模型は偽物に替え、アプリの窓の本物の経路（chat_send → 段取り → Job → engine.prompt_args）を流す"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, sweep_windows  # noqa: E402

# 頼みの文 → (枚数, 描く言葉)。枚数の言葉だけを取り、残りは書いたまま
CASES = [
    ("10回描いて", 10, ""), ("赤い服の子を3枚描いて", 3, "赤い服の子"), ("猫を10回描いて", 10, "猫"), ("5体描いて", 5, ""),
    ("りんごを2個描いて", 2, "りんご"), ("10回を描いて", 10, ""), ("三枚描いて青い空", 3, "青い空"),
    ("3枚、赤い服の子を描いて", 3, "赤い服の子"), ("猫耳の少女を4枚描いてください", 4, "猫耳の少女"), ("騎士を２枚描いて", 2, "騎士"),
    ("夕暮れの街を5回描いて", 5, "夕暮れの街"), ("青い髪の女の子 笑顔 を3枚描いて", 3, "青い髪の女の子 笑顔"),
    ("3体の竜が戦う絵を描いて", 1, "3体の竜が戦う絵"), ("2個のりんごを持つ少女を描いて", 1, "2個のりんごを持つ少女"),
    ("魔法使いを5枚ほど描いて", 5, "魔法使い"), ("海辺の少女を十枚描いて", 10, "海辺の少女"), ("制服の女の子を描いて", 1, "制服の女の子"),
    ("赤いマフラーの女の子を2回描いて", 2, "赤いマフラーの女の子"), ("鎧の騎士 全身を3枚描いて", 3, "鎧の騎士 全身"),
    ("犬と猫を6枚描いて良いのを残して", 6, "犬と猫"), ("ドラゴンを7体描いて", 7, "ドラゴン"), ("黒猫を3匹描いて", 3, "黒猫"),
    ("桜の木の下の少女を3枚描いてね", 3, "桜の木の下の少女"), ("宇宙飛行士を4回描いて", 4, "宇宙飛行士"),
]


class CountWordsTest(unittest.TestCase):
    def test_count_is_taken_out_without_leftovers(self):
        from chatdraw import chatplan
        for text, n, body in CASES:
            p = chatplan.parse(text)
            self.assertEqual((p.repeat, p.body), (n, body), text)
            self.assertNotIn("を描いて", p.body, text)
            self.assertNotRegex(p.body, r"\d+\s*(回|枚)", text)


class SafetyWordsTest(unittest.TestCase):
    def test_refused_only_child_and_sexual(self):
        from chatdraw.engine import refused
        for ok in ("1girl, young girl, school uniform, no underwear visible", "1girl, child, essex", "girl, kidney bean",
                   "少女を描いて、エロくしないで", "少女の下着姿ではなく制服", "children, playground"):
            self.assertFalse(refused(ok), ok)
        for ng in ("child, nude", "少女 裸", "little girl, lingerie", "loli"):
            self.assertTrue(refused(ng), ng)

    def test_safe_tag_and_nsfw_negative(self):
        from chatdraw.engine import SAFE_NEGATIVE
        from chatdraw.tests.test_perfamily import args_for
        _info, args = args_for("cagliostrolab/animagine-xl-4.0", "1girl, red scarf")
        self.assertIn("nsfw", args["negative_prompt"])
        self.assertIn("safe", [t.strip() for t in args["prompt"].split(",")])
        _info, args = args_for("cagliostrolab/animagine-xl-4.0", "1girl, nude")
        self.assertNotIn(SAFE_NEGATIVE, args["negative_prompt"])   # 頼んだ言葉は打ち消さない

    def test_debug_lift_words(self):
        from chatdraw import debuglog
        from chatdraw.tests.test_perfamily import args_for
        debuglog.configure(True, ["words"])
        try:
            _info, args = args_for("cagliostrolab/animagine-xl-4.0", "1girl, red scarf")
        finally:
            debuglog.configure(False)
        self.assertEqual(args["prompt"], "1girl, red scarf")
        self.assertNotIn("nsfw", args.get("negative_prompt", ""))

    def test_unsafe_read_is_redraw_reason(self):
        from chatdraw.requestcheck import unsafe
        self.assertTrue(unsafe("1girl, red scarf", {"explicit": 0.9}))
        self.assertFalse(unsafe("1girl, nude", {"explicit": 0.9}))


class FlakyPainter(FakePainter):
    """2 回目の描く呼び出しだけ落ちる描き手"""
    fail_on = {2}

    def paint(self, prompt, seed, on_step=None, **kw):
        self.n = getattr(self, "n", 0) + 1
        if self.n in self.fail_on:
            raise RuntimeError("試験で落とした 2 枚目")
        return super().paint(prompt, seed, on_step, **kw)


def run_until(app, w, cond, limit=120.0):
    end = time.time() + limit
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        w.thread and w.thread.wait(10)
        time.sleep(0.01)
    return False


class WindowPathTest(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.d = TemporaryDirectory()
        import chatdraw.paths as paths
        self._home, paths.HOME = paths.HOME, Path(self.d.name)   # 記録のファイルを試験の置き場に書く

    def tearDown(self):
        from chatdraw import debuglog
        debuglog.configure(False)
        sweep_windows()
        import chatdraw.paths as paths
        paths.HOME = self._home
        self.d.cleanup()

    def window(self, painter):
        from chatdraw.app import Window
        w = Window(Studio(FakeWords(), painter, Path(self.d.name)))
        w.studio.way = "one"
        if isinstance(painter, FlakyPainter):
            w.studio.draw_anyway = None   # 段を下げる描き直しは別の試験で見る。ここは段を下げても落ちた 1 枚の扱いを見る
        return w

    def test_chat_ten_times(self):
        w = self.window(FakePainter())
        w.entry.setText("黒猫")   # 描く言葉の無い「10回描いて」は、今の描く内容を 10 枚描く
        w.chat_send("10回描いて")
        self.assertTrue(run_until(self.app, w, lambda: len(w.images) == 10 and w.thread is None))
        self.assertEqual(w.ai_panel.count(), 10)
        self.assertEqual(w.last_text, "黒猫")

    def test_one_failure_keeps_the_rest(self):
        painter = FlakyPainter()
        w = self.window(painter)
        w.entry.setText("雪の城の前の騎士")
        w.chat_send("雪の城の前の騎士を3枚描いて")
        self.assertTrue(run_until(self.app, w, lambda: len(w.images) == 3 and w.thread is None))
        said = w.chat.toPlainText() if hasattr(w.chat, "toPlainText") else ""
        self.assertEqual(len(w.images), 3, said)
        self.assertEqual(w.job.drawn, 3)
        self.assertTrue(w.job.reasons)

    def test_debug_mode_shows_full_exception(self):
        from chatdraw import debuglog
        w = self.window(FlakyPainter())
        w.settings.set("debug", 1)
        w.settings.set("debug_checker", 1)
        w.apply_debug_mode()
        self.assertTrue(debuglog.on() and debuglog.lifted("checker"))
        self.assertFalse(w._debug_dock().isHidden())
        w.chat_send("騎士を3枚描いて")
        self.assertTrue(run_until(self.app, w, lambda: len(w.images) == 3 and w.thread is None))
        text = w.debug_view.toPlainText()
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("試験で落とした 2 枚目", text)
        self.assertIn("空きメモリ", text)
        from chatdraw import sent   # 模型に渡した言葉（本物の描き手が呼ぶ所）も記録に流れる
        sent.record("描く", "1girl, knight, safe", "nsfw, nude")
        self.assertTrue(run_until(self.app, w, lambda: "[言葉] 描く: 1girl, knight, safe" in w.debug_view.toPlainText(), 10))
        self.assertTrue(debuglog.file().exists())
        self.assertIn("Traceback", w.debug_box.detailedText())
        w.settings.set("debug", 0)
        w.settings.set("debug_checker", 0)   # 利用者の設定に残さない
        w.apply_debug_mode()
        self.assertFalse(debuglog.on())

    def test_negative_has_nsfw_in_app(self):
        from chatdraw import sent
        sent.clear()
        w = self.window(FakePainter())
        w.chat_send("猫を描いて")
        self.assertTrue(run_until(self.app, w, lambda: len(w.images) == 1 and w.thread is None))
        # 偽物の描き手は prompt_args を通らないので、本物と同じ関数で打ち消しを作って確かめる
        from chatdraw.engine import negative_for, SAFE_NEGATIVE
        self.assertTrue(SAFE_NEGATIVE.startswith("nsfw"))
        self.assertNotIn("nsfw", negative_for(type("I", (), {"negative": ""})(), "", bare=True))


class PruneTest(unittest.TestCase):
    def test_old_logs_are_removed(self):
        from chatdraw import debuglog
        with TemporaryDirectory() as d:
            import chatdraw.paths as paths
            old = paths.HOME
            paths.HOME = Path(d)
            try:
                f = debuglog.folder()
                f.mkdir(parents=True)
                (f / "chatdraw-20200101.log").write_text("x")
                os.utime(f / "chatdraw-20200101.log", (0, 0))
                (f / "chatdraw-new.log").write_text("x")
                self.assertEqual(debuglog.prune(), 1)
                self.assertTrue((f / "chatdraw-new.log").exists())
            finally:
                paths.HOME = old


if __name__ == "__main__":
    unittest.main()
