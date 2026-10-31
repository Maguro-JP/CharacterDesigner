import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.engine import Studio  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402


def window(d):
    from PySide6.QtWidgets import QApplication
    from chatdraw.app import Window
    QApplication.instance() or QApplication([])
    return Window(Studio(FakeWords(), FakePainter(), Path(d)))


class PresetResetTest(unittest.TestCase):
    def test_default_preset_restores_after_other_preset(self):
        from chatdraw.aipanel import DEFAULT_PRESET
        with TemporaryDirectory() as d:
            w = window(d)
            p = w.ai_panel
            self.assertEqual(p.preset, DEFAULT_PRESET)
            start = p.current()
            self.assertTrue(p.apply_name("イラスト"))
            p.seed_lock.setChecked(True)
            self.assertNotEqual(p.current(), start)
            self.assertTrue(p.apply_name(DEFAULT_PRESET))
            self.assertEqual(p.current(), start)
            self.assertFalse(p.seed_lock.isChecked())
            checked = [b.text() for b in p.preset_group.buttons() if b.isChecked()]
            self.assertEqual(checked, [DEFAULT_PRESET])


class WheelGuardTest(unittest.TestCase):
    def test_wheel_does_not_change_unfocused_spinbox(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication, QScrollArea, QSpinBox, QVBoxLayout, QWidget
        from chatdraw import wheelguard
        app = QApplication.instance() or QApplication([])
        wheelguard.install(app)
        area = QScrollArea()
        inner = QWidget()
        lay = QVBoxLayout(inner)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(50)
        lay.addWidget(spin)
        lay.addSpacing(2000)
        area.setWidget(inner)
        area.resize(200, 200)
        area.show()
        app.processEvents()
        self.assertEqual(spin.focusPolicy(), Qt.StrongFocus)
        spin.clearFocus()   # 表示した直後は最初の欄に焦点が来る。押していない状態にそろえる
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(spin, ev)
        self.assertEqual(spin.value(), 50)
        self.assertGreater(area.verticalScrollBar().value(), 0)   # 欄のほうがスクロールする
        spin.setFocus()
        app.processEvents()
        if spin.hasFocus():   # 押して選んだあとはホイールで変えられる
            QApplication.sendEvent(spin, ev)
            self.assertNotEqual(spin.value(), 50)
        area.close()


class NavigatorRectTest(unittest.TestCase):
    def test_view_rect_follows_and_drags(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        with TemporaryDirectory() as d:
            w = window(d)
            app = QApplication.instance()
            w.resize(1400, 900)
            w.show()
            w.canvas.set_zoom(2.0)
            nav = w.navigator
            nav.resize(240, 240)
            nav.redraw() if nav.isVisible() else nav.setPixmap(
                __import__("PySide6.QtGui", fromlist=["QPixmap"]).QPixmap.fromImage(
                    w.canvas.flatten().scaled(232, 232, Qt.KeepAspectRatio)))
            app.processEvents()
            r = nav.view_rect()
            self.assertIsNotNone(r)
            self.assertLess(r.width(), nav.pixmap().width())   # 拡大していると一部だけが見える
            before = w.canvas.horizontalScrollBar().value(), w.canvas.verticalScrollBar().value()
            c = r.center()
            for t, p, b in ((QEvent.MouseButtonPress, c, Qt.LeftButton), (QEvent.MouseMove, c + QPointF(0, 60), Qt.LeftButton),
                            (QEvent.MouseButtonRelease, c + QPointF(0, 60), Qt.NoButton)):
                QApplication.sendEvent(nav, QMouseEvent(t, p, p, Qt.LeftButton, b, Qt.NoModifier))
            after = w.canvas.horizontalScrollBar().value(), w.canvas.verticalScrollBar().value()
            self.assertGreater(after[1], before[1])
            self.assertAlmostEqual(nav.view_rect().center().y(), c.y() + 60, delta=3)
            w.close()


class SlowWords(FakeWords):
    """答えに時間のかかる言葉の模型。チャットが画面の糸を止めないかを見る"""
    def __init__(self, reply="髪を長くします。\n描く内容: 長い髪の少女 赤いマフラー"):
        self.reply, self.asked = reply, []

    def ask(self, system, text, max_tokens=64, one_line=True):
        import time
        self.asked.append((system, text))
        time.sleep(0.4)
        return self.reply


class AvoidPainter(FakePainter):
    avoid = ""

    def paint(self, prompt, seed, on_step=None, **kw):
        self.seen_avoid = self.avoid   # 描いた時点の禁止ワード
        return super().paint(prompt, seed, on_step=on_step, **kw)


def wait(app, cond, sec=10.0):
    import time
    end = time.time() + sec
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.01)
    return cond()


class ChatTest(unittest.TestCase):
    def test_chat_answers_in_background_and_offers_prompt(self):
        import time
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            words = SlowWords()
            w = Window(Studio(words, FakePainter(), Path(d)))
            w.entry.setText("赤いマフラーの少女")
            t0 = time.time()
            w.chat_send("髪を長くして")
            self.assertLess(time.time() - t0, 0.2)               # 模型の答えを待たずに戻る（画面が固まらない）
            self.assertEqual([b.who for b in w.chat.bubbles()], ["user"])
            self.assertTrue(wait(app, lambda: len(w.chat.bubbles()) == 2))
            bubble = w.chat.bubbles()[-1]
            self.assertEqual(bubble.who, "ai")
            self.assertIn("髪を長く", bubble.text)
            self.assertNotIn("描く内容:", bubble.text)
            self.assertIn("赤いマフラーの少女", words.asked[0][0])   # 今の描く内容を模型に見せる
            apply_ = [bubble.buttons.itemAt(i).widget() for i in range(bubble.buttons.count())]
            self.assertEqual([b.text() for b in apply_], ["AI の欄に入れる", "入れて描く"])
            apply_[0].click()
            self.assertEqual(w.entry.text(), "長い髪の少女 赤いマフラー")
            self.assertEqual(len(w.studio.painter.calls), 0)       # 入れるだけでは描かない
            w.chat_send("ありがとう")                               # 2 回目は前の会話も渡す
            self.assertTrue(wait(app, lambda: len(words.asked) == 2 and len(w.chat.bubbles()) == 4))
            self.assertIn("髪を長くして", words.asked[1][1])
            w.chat.clear()
            self.assertEqual(w.chat.bubbles(), [])
            self.assertEqual(w.chat.turns, [])
            w.close()

    def test_chat_runs_commands_and_works_without_model(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.assistant import NO_MODEL

        class NoWords(FakeWords):
            def ready(self):
                return False
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            w = Window(Studio(NoWords(), FakePainter(), Path(d)))
            w.chat_send("消しゴムにして")
            self.assertTrue(wait(app, lambda: len(w.chat.bubbles()) == 2))
            self.assertEqual(w.canvas.tool, "eraser")
            w.chat_send("今日は何を描こうかな")
            self.assertTrue(wait(app, lambda: len(w.chat.bubbles()) == 4))
            self.assertEqual(w.chat.bubbles()[-1].text, NO_MODEL)
            w.close()

    def test_enter_sends_shift_enter_breaks_line(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        with TemporaryDirectory() as d:
            w = window(d)
            got = []
            w.chat.sent.connect(got.append)
            w.chat.input.setText("一行目")
            w.chat.input.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier, "\r"))
            self.assertIn("\n", w.chat.input.text())
            self.assertEqual(got, [])
            w.chat.input.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))
            self.assertEqual(len(got), 1)
            self.assertEqual(w.chat.input.text(), "")
            w.close()


class AiTabTest(unittest.TestCase):
    def test_negative_field_reaches_painter(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.engine import negative_for
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d:
            painter = AvoidPainter()
            w = Window(Studio(FakeWords(), painter, Path(d)))
            w.ai_panel.negative.setText("帽子、text")
            self.assertEqual(w.ai_panel.avoid_words(), ["hat", "text"])
            w.entry.setText("雪の城の前の騎士")
            w.ai_panel.update_preview()
            self.assertIn("描かない物: hat, text", w.ai_panel.preview.text())
            w.send()
            self.assertTrue(wait(app, lambda: w.images and not w.thread))
            self.assertIn("hat", painter.seen_avoid)
            self.assertIn("text", painter.seen_avoid)
            self.assertIn("hat", negative_for(None, painter.seen_avoid))   # 模型の決まった禁止ワードに足して渡る
            w.close()

    def test_sections_collapse_and_remember(self):
        with TemporaryDirectory() as d:
            w = window(d)
            secs = w.ai_panel.sections
            self.assertEqual(list(secs), ["描く内容", "作風とプリセット", "模型", "詳しい設定", "加工"])
            self.assertTrue(secs["描く内容"].is_open())
            self.assertFalse(secs["詳しい設定"].is_open())                 # 詳しい所は初めは畳む
            self.assertTrue(secs["詳しい設定"].box.isHidden())
            self.assertTrue(secs["描く内容"].isAncestorOf(w.entry))
            self.assertTrue(secs["描く内容"].isAncestorOf(w.button))
            self.assertTrue(secs["詳しい設定"].isAncestorOf(w.ai_panel.seed))
            self.assertTrue(secs["詳しい設定"].isAncestorOf(w.strength))
            self.assertTrue(secs["模型"].isAncestorOf(w.model_label))
            secs["詳しい設定"].head.click()
            self.assertTrue(secs["詳しい設定"].is_open())
            self.assertEqual(int(w.layout_store.value("ai_sections/詳しい設定")), 1)
            secs["詳しい設定"].head.click()
            w.close()


if __name__ == "__main__":
    unittest.main()
