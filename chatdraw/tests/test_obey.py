"""頼んだ通りに動くかの試験。描けないときに止めずに段を下げて描き続けること、頼みの言葉が先頭に来て足した言葉で薄まらないこと、
チャットの一言で描く・直す・加工する・設定を変える・戻すができ、決めたことを 1 行で返すことを、アプリの画面から流して確かめる"""
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from chatdraw import chatintent, engine, variety  # noqa: E402
from chatdraw.engine import Studio  # noqa: E402


class KeepDrawingTest(unittest.TestCase):
    """「描けませんでした」で終えない"""

    def _studio(self):
        return Studio(painter=mock.Mock(model="a", stop=False, avoid=""), out=Path("."))

    def test_tries_every_model_before_giving_up(self):
        st = self._studio()
        models = [mock.Mock(repo=f"m{i}", name=f"m{i}", steps=20, guidance=5.0) for i in range(3)]
        calls = []

        def draw(text, seed, on_status=None, **kw):
            calls.append(getattr(st.painter, "model", ""))
            if len(calls) < 6:   # そのまま・7 割・5 割・模型 1・模型 2 で落ち、模型 3 で描ける
                raise MemoryError("足りない")
            return "p", Path("x.png")

        def fallback(kw, exclude=()):
            left = [m for m in models if m.repo not in exclude]
            return left[0] if left else None

        class P:
            def __init__(self, repo, steps, guidance=None):
                self.model, self.stop, self.avoid = repo, False, ""

        with mock.patch.object(st, "draw", side_effect=draw), mock.patch.object(st, "_fallback_model", side_effect=fallback), \
                mock.patch.object(engine, "Painter", P), mock.patch.object(engine, "release_memory"):
            self.assertEqual(st.draw_anyway("女の子", 1, size=(832, 1216))[0], "p")
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls[-1], "m2")

    def test_memory_failures_keep_going_with_new_seeds(self):
        st = self._studio()
        n = []

        def draw(text, seed, on_status=None, **kw):
            n.append(seed)
            if len(n) < 8:
                raise MemoryError("足りない")
            return "p", Path("x.png")
        with mock.patch.object(st, "draw", side_effect=draw), mock.patch.object(st, "_fallback_model", return_value=None), \
                mock.patch.object(engine, "release_memory"), mock.patch("time.sleep"):
            self.assertEqual(st.draw_anyway("女の子", 1, size=(832, 1216))[0], "p")
        self.assertEqual(len(n), 8)   # 前は 3 回で「描けませんでした」だった

    def test_user_stop_still_stops(self):
        st = self._studio()
        with mock.patch.object(st, "draw", side_effect=engine.Stopped("止めました")):
            with self.assertRaises(engine.Stopped):
                st.draw_anyway("女の子", 1)


class AskedWordsFirstTest(unittest.TestCase):
    def test_quality_words_go_after_the_request(self):
        head, tail = engine.lead_quality("masterpiece, best quality, absurdres, ", "very aesthetic")
        self.assertEqual(head, "")
        self.assertTrue(tail.startswith("masterpiece"))
        self.assertEqual(engine.lead_quality("score_9, score_8_up, ", "")[0], "score_9, score_8_up, ")   # 頭に無いと効かない札

    def test_long_request_gets_fewer_added_words(self):
        short = variety.vary("1girl, solo", 3, text="女の子")
        long_ = "1girl, solo, red hat, blue dress, holding umbrella, cat ears, green eyes, braid"
        added_long = len(variety.vary(long_, 3, text="x").split(",")) - len(long_.split(","))
        added_short = len(short.split(",")) - 2
        self.assertLessEqual(variety.room_for(long_), 1)   # 足すのは場所だけ（test_quality2）
        self.assertGreaterEqual(added_short, added_long)


class ParseTest(unittest.TestCase):
    def test_settings_and_finishers(self):
        self.assertEqual(chatintent.parse("4枚ずつ描くようにして").arg, 4)
        self.assertEqual(chatintent.parse("大きさを1024にして").arg, "正方形")
        self.assertEqual(chatintent.parse("横長にして").arg, "横")
        self.assertEqual(chatintent.parse("水彩風にして").arg, "style_watercolor")
        self.assertEqual(chatintent.parse("水彩風にして", has_image=False).kind, "style")
        self.assertEqual(chatintent.parse("綺麗にして").arg, "retouch")
        for t in ("猫を2枚描いて", "猫耳の少女を描いて", "髪を赤く直して"):
            self.assertIsNone(chatintent.parse(t), t)


class ChatWindowTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        self.app = QApplication.instance() or QApplication([])
        self.tmp = TemporaryDirectory()
        self.w = Window(Studio(FakeWords(), FakePainter(), Path(self.tmp.name)))
        self.said = []
        orig = self.w.chat.add

        def add(who, text, *a, **k):
            if who == "ai":
                self.said.append(text)
            return orig(who, text, *a, **k)
        self.w.chat.add = add

    def tearDown(self):
        from chatdraw.tests.test_chatdraw import sweep_windows
        sweep_windows()
        self.tmp.cleanup()

    def settle(self, until, n=20000):
        for _ in range(n):
            self.app.processEvents()
            if until():
                return True
            if self.w.thread:
                self.w.thread.wait(10)
            else:
                time.sleep(0.005)
        return False

    def idle(self):
        return self.w._plan_idle() and not getattr(self.w, "_plan_queue", [])

    def draw_one(self):
        self.w.ai_panel.set_count(1)   # 前の試験が枚数を 4 に変えて残すと、まとめて描く確かめの窓で止まった
        n = len(self.w.images)
        self.w.chat_send("猫耳の少女を描いて")
        self.assertTrue(self.settle(lambda: len(self.w.images) > n and self.idle()))

    def test_settings_from_chat(self):
        w = self.w
        w.chat_send("4枚ずつ描くようにして")
        self.assertEqual(w.ai_panel.count(), 4)
        self.assertIn("4 枚ずつ", self.said[-1])
        w.chat_send("横長にして")
        self.assertTrue(w.size_pick.currentText().startswith("横"))
        self.assertIn("1216×832", self.said[-1])
        w.chat_send("水彩風にして")   # 絵の無いうちは、これから描く画風
        self.assertEqual(w.ai_panel.style, "水彩")
        w.chat_send("1枚ずつ描くようにして")   # 次の試験に枚数を持ち越さない
        self.assertEqual(w.ai_panel.count(), 1)

    def test_draw_then_process_then_back(self):
        w = self.w
        self.draw_one()
        layers = len(w.canvas.layers)
        with mock.patch.object(w, "finish_chain", wraps=w.finish_chain) as chain:
            w.chat_send("綺麗にして")
            ok = self.settle(self.idle, n=20000)
            self.assertTrue(ok, (self.said[-3:], w.thread, getattr(w, "bg_pending", 0), w.asking))
            self.assertEqual(chain.call_args[0][0], ["retouch"])
        self.assertIn("線と塗りを整えます", self.said[-1] if "整え" in self.said[-1] else " ".join(self.said))
        key = w._canvas_key()
        w.chat_send("前の絵に戻して")
        self.assertIn("元に戻しました", self.said)
        self.assertTrue(len(w.canvas.layers) <= layers + 1)
        del key

    def test_fix_without_region_asks(self):
        w = self.w
        self.draw_one()
        n = len(w.images)
        # 偽の描き手の絵は一色なので、絵があるかの判定は本物の絵と同じ答え（ある）にする
        with mock.patch("chatdraw.confirm.ask", return_value="redpen") as ask, mock.patch.object(w, "_has_picture", return_value=True):
            w.chat_send("髪を赤く直して")
            self.settle(self.idle, n=400)
        self.assertEqual(ask.call_args[0][1], "fix_no_region")
        self.assertEqual(len(w.images), n)   # 聞いた答えが「囲む」なら、新しく描かない
        self.assertIn("赤ペンにしました。直す所を囲んで、もう一度送ってください", self.said)

    def test_fix_inside_selection(self):
        w = self.w
        self.draw_one()
        n = len(w.canvas.layers)
        w.canvas.select_all()
        with mock.patch("chatdraw.confirm.ask") as ask:
            w.chat_send("髪を赤く直して")
            # 直した結果は画像のファイルにせず、直した所だけのレイヤーにだけ置く（履歴の絵は増えない）
            self.assertTrue(self.settle(lambda: len(w.canvas.layers) > n and self.idle()))
        ask.assert_not_called()   # 囲んであれば聞かずに直す


if __name__ == "__main__":
    unittest.main()
