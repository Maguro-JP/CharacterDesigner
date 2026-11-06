"""描いている途中に落ちないための試験。

メモリ不足（CUDA の out of memory、MemoryError）を偽の模型で起こし、アプリが生きたまま少ないメモリの設定で 1 回だけ描き直すか、
描き直しても足りなければ日本語の理由で「描けませんでした」に返るかを、本物と同じ経路（頼みを書いて「描く」→ 裏の糸 → Studio.draw）で見る。
ほかに、読む前のメモリの見積もり、途中の絵の間引き、描く前の自動保存と使わない模型の片付け、描いている途中に閉じたときを見る。
"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw import engine  # noqa: E402
from chatdraw.engine import Painter, Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402


class OOMPainter(Painter):
    """本物の Painter の paint（memory_retry を通る）を使い、中の _paint だけを偽にする。fails 回だけメモリ不足で落ちる"""

    def __init__(self, fails: int = 1, error=RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")):
        super().__init__("fake")
        self.fails, self.error, self.calls, self.unloads = fails, error, 0, 0

    def ready(self):
        return True

    def unload(self):
        self.unloads += 1
        super().unload()

    def _paint(self, prompt, seed, on_step=None, *a, **kw):
        from PIL import Image
        self.calls += 1
        if self.calls <= self.fails:
            raise self.error
        if on_step:
            on_step(1, 1)
        return Image.new("RGB", (64, 96), "white")

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        return image.copy()


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait_done(a, w, limit: float = 30.0):
    end = time.time() + limit
    while w.thread is not None and time.time() < end:
        a.processEvents()
        w.thread and w.thread.wait(10)
    a.processEvents()


class MemoryRetryTest(unittest.TestCase):
    def test_oom_once_retries_with_low_memory(self):
        p = OOMPainter(fails=1)
        notes = []
        p.on_note = notes.append
        img = p.paint("knight", 1)
        self.assertEqual(img.size, (64, 96))
        self.assertEqual(p.calls, 2, "1 回だけ描き直していない")
        self.assertTrue(p.low_memory)
        self.assertEqual(p.unloads, 1, "描き直す前に模型を降ろしていない")
        self.assertIn(engine.LOW_MEMORY_NOTE, notes)

    def test_oom_twice_gives_japanese_reason(self):
        p = OOMPainter(fails=5, error=MemoryError())
        with self.assertRaises(MemoryError) as got:
            p.paint("knight", 1)
        self.assertEqual(p.calls, 2, "2 回より多く描いた")
        self.assertIn("メモリが足りず", engine.explain(got.exception))

    def test_other_errors_are_not_retried(self):
        p = OOMPainter(fails=1, error=ValueError("bad"))
        with self.assertRaises(ValueError):
            p.paint("knight", 1)
        self.assertEqual(p.calls, 1)
        self.assertFalse(p.low_memory)

    def test_is_oom(self):
        self.assertTrue(engine.is_oom(RuntimeError("CUDA out of memory")))
        self.assertTrue(engine.is_oom(RuntimeError("[enforce fail at alloc_cpu.cpp] DefaultCPUAllocator: not enough memory")))
        self.assertTrue(engine.is_oom(MemoryError()))
        self.assertFalse(engine.is_oom(RuntimeError("shape mismatch")))

    def test_guard_switches_before_loading(self):
        p = Painter("fake")
        notes = []
        p.on_note = notes.append
        with mock.patch.object(engine, "free_ram_gb", return_value=1.0):
            p.memory_guard()
        self.assertTrue(p.low_memory)
        self.assertTrue(notes and "空いているメモリ" in notes[0], notes)
        q = Painter("fake")
        with mock.patch.object(engine, "free_ram_gb", return_value=999.0):
            q.memory_guard()
        self.assertFalse(q.low_memory)

    def test_free_ram_is_measured(self):
        self.assertGreater(engine.free_ram_gb(), 0)

    def test_low_memory_size(self):
        w, h = engine.low_memory_size((832, 1216))
        self.assertTrue(w % 64 == 0 and h % 64 == 0)
        self.assertLess(w * h, 832 * 1216 * 0.6)


class AppSurvivesTest(unittest.TestCase):
    def run_draw(self, painter):
        from chatdraw.app import Window
        a = app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        w = Window(Studio(FakeWords(), painter, Path(d.name)))
        w.settings.set("output_dir", str(Path(d.name) / "out"))
        w.told = []
        real = w.notify
        w.notify = lambda *x, **k: (w.told.append(x), real(*x, **k))[1]
        w.entry.setText("雪の城の前の騎士")
        w.send()
        wait_done(a, w)
        return a, w

    def test_oom_in_worker_retries_and_places(self):
        a, w = self.run_draw(OOMPainter(fails=1))
        self.assertIsNone(w.thread)
        self.assertEqual(len(w.images), 1, "描き直した絵が置かれていない")
        self.assertEqual(w.studio.painter.calls, 2)
        self.assertTrue(w.button.isEnabled())
        w.dirty = False
        w.close()

    def test_oom_twice_fails_gracefully(self):
        a, w = self.run_draw(OOMPainter(fails=9, error=RuntimeError("CUDA out of memory")))
        self.assertIsNone(w.thread)
        self.assertEqual(len(w.images), 0)
        self.assertTrue(w.button.isEnabled(), "落ちたあとに次の操作ができない")
        failed = [x for x in w.told if x and x[0] == "描けませんでした"]
        self.assertTrue(failed, w.told)
        self.assertIn("メモリが足りず", " ".join(map(str, failed[0])))
        w.dirty = False
        w.close()

    def test_before_draw_autosaves_and_unloads_other_model(self):
        from chatdraw.app import Window
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.settings.set("output_dir", str(Path(d) / "out"))
            other = mock.MagicMock()
            other.model = "other"
            other.loaded.return_value = True
            w._fix_cache = Studio(FakeWords(), other, Path(d))
            with mock.patch.object(w, "autosave") as save:
                w.entry.setText("騎士")
                w.send()
                self.assertTrue(save.called, "描く前に自動保存していない")
            wait_done(a, w)
            other.unload.assert_called_once()
            w.dirty = False
            w.close()

    def test_preview_is_throttled(self):
        from chatdraw.app import Job
        job = Job(Studio(FakeWords(), FakePainter(), Path(".")), "x", 1)
        got = []
        job.preview.connect(got.append)
        for _ in range(20):
            job._preview("img")
        self.assertEqual(len(got), 1)
        job._last_preview -= Job.PREVIEW_GAP
        job._preview("img")
        self.assertEqual(len(got), 2)

    def test_close_while_drawing_waits_for_thread(self):
        """描いている途中に閉じても、動いている QThread を消さない（消すと Qt がアプリごと落とす）"""
        from chatdraw.app import Window
        from chatdraw.tests.test_stop import SlowPainter
        a = app()
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), SlowPainter("step"), Path(d)))
            w.settings.set("output_dir", str(Path(d) / "out"))
            w.show()
            w.entry.setText("騎士")
            w.send()
            end = time.time() + 1.0
            while time.time() < end:
                a.processEvents()
                time.sleep(0.01)
            worker = w.thread
            self.assertIsNotNone(worker)
            w.dirty = False
            w.close()
            end = time.time() + 10
            while worker.isRunning() and time.time() < end:
                a.processEvents()
                worker.wait(10)
            a.processEvents()
            self.assertFalse(worker.isRunning(), "閉じたあとも裏の糸が動いている")
            self.assertFalse(w.isVisible())


if __name__ == "__main__":
    unittest.main()
