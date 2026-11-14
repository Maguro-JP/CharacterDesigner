"""0.5.18 に戻したときに消えた画面の機能（作成枚数の欄、複数枚の 1 枚の失敗、一括生成）を窓から押して確かめる"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, sweep_windows  # noqa: E402


class FlakyPainter(FakePainter):
    """2 回目の描く呼び出しだけ落ちる描き手。FAIL を含む頼みも落ちる"""
    fail_on = {2}

    def paint(self, prompt, seed, on_step=None, **kw):
        self.n = getattr(self, "n", 0) + 1
        if self.n in self.fail_on or "FAIL" in str(prompt):
            raise RuntimeError("試験で落とした 1 枚")
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


class Base(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.d = TemporaryDirectory()

    def tearDown(self):
        sweep_windows()
        self.d.cleanup()

    def window(self, painter=None, size=(1600, 1000)):
        from chatdraw.app import Window
        w = Window(Studio(FakeWords(), painter or FakePainter(), Path(self.d.name)))
        w.studio.way = "one"
        w.resize(*size)
        w.show()
        QTest.qWait(200)
        w.closing_checked = True   # 閉じるときの確かめの窓を出さない。窓は sweep_windows が閉じる
        return w


class CountFieldTest(Base):
    """作成枚数は描くボタンの左に「枚数」の名前つきの欄で出し、幅 0 に潰れず、打てる。詳しい設定には枚数を置かない"""

    def test_count_field_beside_draw_button(self):
        w = self.window()
        spin = w.ai_panel.count_spin
        self.assertTrue(spin.isVisible())
        self.assertGreaterEqual(spin.width(), 50, spin.geometry())
        self.assertEqual(w.count_label.text(), "枚数")
        self.assertTrue(w.count_label.isVisible())
        spin.setFocus(); spin.selectAll()
        QTest.keyClicks(spin, "3")
        QTest.keyClick(spin, Qt.Key_Return)
        self.assertEqual(spin.value(), 3)
        detail = w.ai_panel.sections["詳しい設定"]
        texts = [l.text() for l in detail.findChildren(QLabel)]
        self.assertFalse(any("枚数" in t for t in texts), texts)
        self.assertFalse(any(b.isVisible() for b in w.ai_panel.count_buttons[1]))

    def test_narrow_window_keeps_width(self):
        w = self.window(size=(900, 700))
        self.assertGreaterEqual(w.ai_panel.count_spin.width(), 50)

    def test_model_heading(self):
        w = self.window()
        self.assertFalse(w.model_label.text().startswith("絵の模型"), w.model_label.text())
        heads = [l.text() for l in w.findChildren(QLabel) if l.objectName() == "sectionHead"]
        self.assertIn("絵の模型", heads)


class OneFailureTest(Base):
    def test_one_failure_keeps_the_rest(self):
        w = self.window(FlakyPainter())
        w.studio.draw_anyway = None   # 段を下げる描き直しは別の試験で見る。ここは落ちた 1 枚の扱いを見る
        w.entry.setText("雪の城の前の騎士")
        w.ai_panel.set_count(3)
        w.button.click()   # 窓のボタンから押す（clicked は真偽値を渡す）
        self.assertTrue(run_until(self.app, w, lambda: w.thread is None and getattr(w.job, "drawn", None) is not None, 120))
        self.assertTrue(run_until(self.app, w, lambda: w.thread is None, 60))
        self.assertEqual(w.job.drawn, 2)
        self.assertEqual(len(w.job.reasons), 1)
        self.assertIn("2 枚目", w.job.reasons[0])
        self.assertEqual(len(w.batch), 2)


class BatchTest(Base):
    def test_parse(self):
        from chatdraw import batch
        jobs, bad = batch.parse("1girl, red scarf\n# 飛ばす\n\nknight, snow", 2, 10)
        self.assertEqual([(j["text"], j["count"], j["seed"]) for j in jobs], [("1girl, red scarf", 2, 11), ("knight, snow", 2, 14)])
        jobs, bad = batch.parse("頼み,枚数,種\n\"cat, sitting\",3,5\ndog,x,1\n,1,1", 1, 0)
        self.assertEqual([(j["text"], j["count"], j["seed"]) for j in jobs], [("cat, sitting", 3, 5)])
        self.assertEqual(len(bad), 2)

    def test_stop(self):
        from chatdraw import batch, engine

        seen = []

        def draw(text, seed, neg):
            seen.append(text)
            engine.STOP.set()
            return f"/tmp/{seed}.png"
        try:
            res = batch.run(batch.parse("a\nb\nc")[0], draw, stopped=engine.STOP.is_set)
        finally:
            engine.STOP.clear()
        self.assertEqual((len(res["done"]), res["stopped"], seen), (1, True, ["a"]))

    def test_from_file_menu_one_fails(self):
        w = self.window(FlakyPainter.__new__(FlakyPainter))
        w.studio.painter.__init__()
        w.studio.painter.fail_on = set()
        file_menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "ファイル")
        self.assertIn(w.batch_action, file_menu.actions())
        w._fill_ai_menu()
        self.assertNotIn("一括生成…", [a.text() for a in w.ai_menu.actions()])
        self.assertTrue(w.batch_action.toolTip())
        text = "1girl, red scarf\nFAIL on purpose\nknight, snow"
        with mock.patch.object(type(w), "_batch_dialog", lambda self: (text, 1, 3, None)):
            w.batch_action.trigger()
        self.assertTrue(run_until(self.app, w, lambda: getattr(w, "batch_result", None) is not None, 120))
        res = w.batch_result
        self.assertEqual(len(res["done"]), 2)
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(res["failed"][0][0], 2)
        lib = [i["path"] for i in w.library.items]
        self.assertTrue(all(p in lib for p in res["done"]))


if __name__ == "__main__":
    unittest.main()
