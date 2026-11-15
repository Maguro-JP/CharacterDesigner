"""評価を付ける・消すで固まらない、落ちない、同じ模型を読み直さない、の試験。

評価（ライブラリーの好き・いまいち、★、履歴の判定、模型の点）と消す（履歴・ライブラリー・レイヤー・赤ペンの印）を、
本物の窓（offscreen）で続けて押し、1 回が 0.2 秒以内に返ることと落ちないことを見る。描いている最中にも消す。
絵の模型は、偽の diffusers の部品で読み込みの回数を数え、同じ模型で続けて描いても 1 回しか読まないことを見る。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg  # noqa: E402

LIMIT = 0.2   # 1 回の操作で画面の糸を止めてよい秒
N = 40        # 並べる絵の数（832×1216 の PNG。前は一覧を作り直すたびに全部を読み直した）


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class SlowPainter(FakePainter):
    """1 枚に 1 秒かかる絵の模型（描いている最中に消す試験のため）"""

    def paint(self, prompt, seed, on_step=None, **kw):
        end = time.time() + 1.0
        while time.time() < end:
            if on_step:
                on_step(1, 2)
            time.sleep(0.02)
        return super().paint(prompt, seed, on_step=on_step, **kw)


class RateDeleteTest(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        from chatdraw.app import Window
        app()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        self.w = Window(Studio(FakeWords(), SlowPainter(), out))
        self.w.settings.set("output_dir", str(out))
        self.paths = []
        for i in range(N):
            p = out / f"img{i}.png"
            Image.new("RGB", (832, 1216), (i * 5 % 255, 90, 60)).save(p)
            self.paths.append(str(p))
            self.w.library.add_work(str(p), {"text": "騎士", "prompt": "knight", "model": "m"})
            self.w.images.append(str(p))
            self.w.activity.add(str(p), "knight")
        self.w.library_panel.refresh()
        app().processEvents()

    def tearDown(self):
        wait_bg(app(), self.w)
        self.w.wait_io()
        self.w.dirty = False
        self.w.close()
        app().processEvents()

    def timed(self, fn, times: int = 8) -> float:
        worst = 0.0
        for i in range(times):
            t = time.perf_counter()
            fn(i)
            app().processEvents()
            worst = max(worst, time.perf_counter() - t)
        return worst

    def test_rating_does_not_freeze(self):
        from chatdraw import ownstyle, ratings
        from chatdraw.library import DISLIKE, LIKE, NONE
        panel = self.w.library_panel
        ids = [it["id"] for it in self.w.library.works()]
        worst = self.timed(lambda i: panel.rate(ids[i], (LIKE, DISLIKE, NONE)[i % 3]))
        self.assertLess(worst, LIMIT, f"好き・いまいちで {worst:.2f} 秒固まった")
        self.assertIn("好き", panel.works.item(0).text() + panel.works.item(3).text())
        worst = self.timed(lambda i: (ownstyle.set_favorite(self.paths[i], True, learn=False), panel.relabel([self.paths[i]])))
        self.assertLess(worst, LIMIT, f"★ で {worst:.2f} 秒固まった")
        worst = self.timed(lambda i: self.w.judge(self.paths[i], "good"))
        self.assertLess(worst, LIMIT, f"判定で {worst:.2f} 秒固まった")
        worst = self.timed(lambda i: ratings.set_user_rating("Lykon/dreamshaper-8", 50 + i))
        self.assertLess(worst, LIMIT, f"模型の点で {worst:.2f} 秒固まった")
        self.assertEqual(ratings.user_rating("Lykon/dreamshaper-8"), 57)
        ratings.set_user_rating("Lykon/dreamshaper-8", 0)

    def test_star_learning_runs_one_at_a_time(self):
        """★ を続けて押しても、学び直しは 1 つずつ（同じ基準のファイルを重ねて書かない）"""
        from unittest import mock
        from chatdraw import origqc, ownstyle
        running, most = [0], [0]
        lock = threading.Lock()

        def slow(path, value, reason=""):
            with lock:
                running[0] += 1
                most[0] = max(most[0], running[0])
            time.sleep(0.05)
            with lock:
                running[0] -= 1
            return {}
        with mock.patch.object(origqc, "verdict", slow):
            t0 = time.perf_counter()
            done = [ownstyle.learn_from(p, "pass") for p in self.paths[:6]]
            self.assertLess(time.perf_counter() - t0, LIMIT, "★ の学び直しを画面の糸で待った")
            end = time.time() + 10
            while any(d.is_alive() for d in done) and time.time() < end:
                app().processEvents()
                time.sleep(0.01)
        self.assertFalse(any(d.is_alive() for d in done))
        self.assertEqual(most[0], 1, "学び直しが同時に走った")

    def test_delete_in_a_row_and_while_drawing(self):
        w = self.w
        worst = self.timed(lambda i: w.delete_images([self.paths[i]], ask=False), times=6)
        self.assertLess(worst, LIMIT, f"消すで {worst:.2f} 秒固まった")
        # 同じ絵をもう一度消す（もう無い絵）・一緒に選んだ絵をまとめて消す
        worst = self.timed(lambda i: w.delete_images([self.paths[i], self.paths[10 + i]], ask=False), times=4)
        self.assertLess(worst, LIMIT, f"続けて消すで {worst:.2f} 秒固まった")
        shown = [w.library_panel.works.item(i).data(0x0100 + 1) for i in range(w.library_panel.works.count())]
        for p in self.paths[:6] + self.paths[10:14]:
            self.assertNotIn(p, shown)
            self.assertNotIn(p, w.images)
        # 描いている最中に、履歴の絵とレイヤーと赤ペンの印を消す
        w.entry.setText("雪の城の前の騎士")
        w.send()
        self.assertIsNotNone(w.thread)
        c = w.canvas
        for _ in range(3):
            c.add_layer()
        t = time.perf_counter()
        w.delete_images([self.paths[20], self.paths[21]], ask=False)
        for _ in range(6):   # 1 枚だけになっても押し続ける
            c.current = len(c.layers) + 3   # 並びの外を指していても落ちない
            c.delete_layer()
            app().processEvents()
        c.redpen.remove(5)   # 無い印
        self.assertLess(time.perf_counter() - t, LIMIT * 4)
        end = time.time() + 30
        while w.thread is not None and time.time() < end:
            app().processEvents()
            w.thread and w.thread.wait(10)
        app().processEvents()
        self.assertIsNone(w.thread, "描き終わらなかった")
        self.assertTrue(w.button.isEnabled())
        self.assertGreaterEqual(len(c.layers), 1)


class PainterReuseTest(unittest.TestCase):
    """同じ模型・同じ部品で続けて描くとき、模型を読み直さない（偽の diffusers で from_pretrained を数える）"""

    def test_same_model_is_read_once(self):
        from unittest import mock
        from PIL import Image
        from chatdraw import engine, membudget, upscale

        class Pipe:
            def __call__(self, *a, **k):
                pass
        reads = []

        def read(self):
            reads.append(self.model)
            return Pipe()
        p = engine.Painter("Laxhar/noobai-XL-Vpred-1.0")
        with mock.patch.object(engine.Painter, "_read", read), \
                mock.patch.object(engine.Painter, "_place", lambda s, pipe: setattr(s, "placed", "cpu")), \
                mock.patch.object(engine.Painter, "_paint_measured", lambda s, pipe, *a, **k: Image.new("RGB", (8, 8))), \
                mock.patch.object(membudget, "budget", lambda *a, **k: membudget.Budget(32.0, 0.0, 40.0, 0.0)):
            for i in range(3):
                p.paint("knight", i)
                # 描いた間に小さな模型（拡大・体の点）を使っても、絵の模型は降ろさない
                membudget.exclusive("upscale", upscale.unload, need_gb=upscale.NEED_GB)
                membudget.exclusive("vitpose", lambda: None, need_gb=0)
            self.assertEqual(reads, ["Laxhar/noobai-XL-Vpred-1.0"], "同じ模型を描くたびに読み直した")
            # 空きが足りないときは、今までどおり降ろしてから読む
            with mock.patch.object(membudget, "budget", lambda *a, **k: membudget.Budget(0.5, 0.0, 0.6, 0.0)):
                membudget.exclusive("upscale", upscale.unload, need_gb=upscale.NEED_GB)
            self.assertFalse(p.loaded())
            p.paint("knight", 9)
            self.assertEqual(len(reads), 2)
        p.unload()
        membudget.released("upscale")
        membudget.released("vitpose")


if __name__ == "__main__":
    unittest.main()
