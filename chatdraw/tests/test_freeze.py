"""固まる・何も起きないように見える不具合の試験。どれも、直す前の版で同じ手順を踏むと落ちることを確かめてから足した。"""
from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


def _spin(app, s: float):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()


class TourTest(unittest.TestCase):
    """案内の部品が引けないとき、幕だけが残って押した所を全部受け止め、アプリが固まったままにならないか"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from chatdraw import engine
        from chatdraw.app import Window
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = TemporaryDirectory()
        cls.w = Window(engine.Studio(FakeWords(), FakePainter(), Path(cls.tmp.name)))
        cls.w.resize(1400, 900)
        cls.w.show()
        _spin(cls.app, 0.3)

    @classmethod
    def tearDownClass(cls):
        cls.w.close()
        cls.tmp.cleanup()

    def test_missing_target_does_not_leave_veil(self):
        from chatdraw.tour import Step, Tour

        def gone():
            raise AttributeError("まだ作っていない部品")

        def boom():
            raise RuntimeError("Internal C++ object already deleted.")
        t = Tour(self.w, [Step(gone, "a", "b", before=boom), Step(lambda: self.w.canvas, "c", "d")])
        t.start()                      # 前は AttributeError で止まり、幕が残った
        _spin(self.app, 0.1)
        t.repaint()
        self.assertIsNone(t.hole())
        t.next.click()
        t.next.click()
        _spin(self.app, 0.6)
        self.assertTrue(t.done)

    def test_every_feature_tour_opens_and_closes(self):
        from chatdraw import tours
        for key in tours.catalog(self.w):
            tours.show(self.w, key, force=True)   # 赤ペンの指示（note_edit をまだ作っていない）で落ちた
            for _ in range(5):
                if self.w.tour.done:
                    break
                self.w.tour.next.click()
            self.assertTrue(self.w.tour.done, key)
        _spin(self.app, 0.6)
        from chatdraw.tour import Tour
        self.assertFalse([t for t in self.w.findChildren(Tour) if t.isVisible()])

    def test_model_manager_opens_quickly(self):
        from chatdraw.manager import ModelManager
        t0 = time.time()
        d = ModelManager(self.w.settings, self.w)
        self.assertLess(time.time() - t0, 2.0)
        d.deleteLater()


class MachineTest(unittest.TestCase):
    def test_machine_does_not_load_torch(self):
        """模型の管理を開くたびに torch を読み、その間（2.8 秒〜）窓が開かず固まって見えた"""
        code = "import sys, chatdraw.models as M; M.machine(); M.machine(); print('torch' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), "False", out.stderr[-500:])


class CheckTest(unittest.TestCase):
    def test_check_does_not_load_torch(self):
        """模型の管理を閉じたあとと描く前に、AI が使えるかを見るだけで diffusers と torch を読み、4.6 秒固まった"""
        code = ("import sys; from chatdraw.engine import check\n"
                "class P:\n model = 'x'\n def ready(self): return True\n"
                "class W:\n def ready(self): return False\n"
                "st = check(P(), W()); print('torch' in sys.modules or 'diffusers' in sys.modules, st['image'])")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                             env={**__import__("os").environ, "PYTHONPATH": str(ROOT / ".cache/gen/lib")})
        self.assertEqual(out.stdout.split()[:1], ["False"], out.stderr[-500:])


class CommandWordsTest(unittest.TestCase):
    """描く頼みに操作の言葉が入っていても、操作に取り違えない（配置が替わる、案内の幕や保存の窓が出る、で何も描かれなかった）"""

    def test_drawing_requests_are_not_commands(self):
        from chatdraw.commands import looks_like_command
        for text in ("シンプルな背景の女の子", "筆を持った少女", "使い方の分からない機械と少年", "保存食を持つ騎士",
                     "ツアーガイドの女性", "回転する少女", "新規の制服の女の子", "履歴書を持つ男性", "中止の看板の前の少年"):
            self.assertFalse(looks_like_command(text), text)

    def test_commands_still_work(self):
        from chatdraw.commands import by_words, looks_like_command
        for text in ("ペンにして", "シンプルな配置にして", "保存して", "使い方を教えて", "レイヤーを足して", "赤ペンにして",
                     "色を赤にして", "もう一度描いて", "2倍に拡大して"):
            self.assertTrue(looks_like_command(text), text)
            self.assertIsNotNone(by_words(text)[0], text)


class EnglishOnlyTest(unittest.TestCase):
    """日本語の頼みを、どの経路からでもそのまま絵の模型に渡さない"""

    def test_fallbacks_drop_japanese(self):
        from chatdraw.engine import Words, english_only, has_japanese, negative_for
        w = Words(Path(""))   # 言葉の模型が無い
        for text in ("ふにゃふにゃ", "ほにゃらら anime", "もこもこ、1girl"):
            self.assertFalse(has_japanese(w.to_prompt(text)), text)
            self.assertFalse(has_japanese(w.to_prompt(text, tags=False)), text)
        self.assertEqual(english_only("もこもこ、1girl, 帽子 hat"), "1girl, hat")
        self.assertEqual(english_only("1girl, smile"), "1girl, smile")

        class Info:
            negative = ""
        self.assertFalse(has_japanese(negative_for(Info(), "ぼやけ, blurry")))


class WordsThreadsTest(unittest.TestCase):
    def test_decode_uses_half_the_cores(self):
        """1 語ずつ出す所で全部の糸を使うと、ほかの処理と取り合って Qwen3.5 2B で 7 語に 24〜50 秒かかった（2 糸で 0.9 秒）"""
        from chatdraw.engine import decode_threads
        self.assertEqual(decode_threads(8), 4)
        self.assertEqual(decode_threads(4), 2)
        self.assertEqual(decode_threads(2), 2)
        self.assertEqual(decode_threads(1), 1)


if __name__ == "__main__":
    unittest.main()
