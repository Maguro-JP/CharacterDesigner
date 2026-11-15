"""時間切れ・メモリ不足の打ち切りを、止めて捨てずに一時停止にする試験（chatdraw/pausekeep.py）。

偽の模型で、工程の途中・一括生成の途中・取得の途中に打ち切りを起こし、途中が保存され、
再開で同じ工程・同じ枚・同じバイトから続くことを確かめる。窓の写しを撮って「再開」のボタンが見えるかも確かめる。
前は打ち切ると途中が消え、始めから描き直すしかなかった。
"""
import io
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw import batch, engine, fetchfile, membudget, pausekeep, phases  # noqa: E402
from chatdraw.tests.test_phases import Painter, checks  # noqa: E402

SHOTS = ROOT / ".cache" / "shots"


class KeepDir(unittest.TestCase):
    def setUp(self):
        self._d = TemporaryDirectory()
        self.d = Path(self._d.name)
        pausekeep.ROOT = self.d / "paused"

    def tearDown(self):
        pausekeep.ROOT = None
        self._d.cleanup()


class FailingPainter(Painter):
    """fail_at 回目の paint で打ち切りを起こす（1 回だけ）"""

    def __init__(self, fail_at, exc):
        super().__init__()
        self.fail_at, self.exc, self.n_paint = fail_at, exc, 0

    def paint(self, prompt, seed, on_step=None, **kw):
        self.n_paint += 1
        if self.n_paint == self.fail_at:
            raise self.exc
        return super().paint(prompt, seed, on_step=on_step, **kw)


class PhasesPauseTest(KeepDir):
    def run_with(self, exc):
        C, _ = checks(False)
        painter = FailingPainter(3, exc)
        said = []
        k = pausekeep.key("phases", "t", 5)
        with self.assertRaises(pausekeep.Paused) as cm:
            phases.draw(painter, "1girl", 5, (64, 96), self.d / "k", say=said.append, checks=C, pause_key=k, pause_job={"text": "t"})
        stopped_at = [s for s in said if s.startswith("工程 ") and ":" in s][-1]
        self.assertEqual(cm.exception.key, k)
        rec = pausekeep.info(k)
        self.assertEqual(rec["kind"], "phases")
        self.assertTrue(rec["has_state"])
        i = pausekeep.state(k)["i"]
        done_before = len(pausekeep.state(k)["history"])
        # 再開: 同じ鍵で呼び直すと、その工程から続き、前の工程は描き直さない
        said2 = []
        calls_before = painter.n_paint
        got = phases.draw(painter, "1girl", 5, (64, 96), self.d / "k2", say=said2.append, checks=C, pause_key=k)
        self.assertIn(f"一時停止した工程 {i + 1}/{len(phases.PHASES)}", said2[0])
        first = next(s for s in said2 if s.startswith("工程 "))
        self.assertTrue(first.startswith(f"工程 {i + 1}/"), (first, stopped_at))
        self.assertEqual([r["phase"] for r in got["phases"]], phases.NAMES)
        self.assertGreaterEqual(len(got["history"]), done_before + (len(phases.PHASES) - i))
        self.assertIsNone(pausekeep.info(k))   # 描き終えたら残した途中は消す
        self.assertGreater(painter.n_paint, calls_before)

    def test_memory_danger_pauses_and_resumes_same_phase(self):
        self.run_with(membudget.MemoryDanger("危ない"))

    def test_timeout_pauses_and_resumes_same_phase(self):
        self.run_with(TimeoutError("時間切れ"))

    def test_emergency_stop_is_not_kept(self):
        C, _ = checks(False)
        k = pausekeep.key("phases", "stop")
        with self.assertRaises(engine.Stopped):
            phases.draw(FailingPainter(2, engine.Stopped("止めました")), "1girl", 5, (64, 96), self.d / "k", checks=C, pause_key=k)
        self.assertIsNone(pausekeep.info(k))   # 緊急停止はそのまま止める（残さない）


class BatchPauseTest(KeepDir):
    def test_memory_error_pauses_then_resumes_at_same_image(self):
        jobs = [{"line": 1, "text": "a", "count": 3, "seed": 10, "negative": ""}]
        drawn, fail = [], [2]

        def draw(text, seed, negative):
            if seed == 11 and fail:
                fail.pop()
                raise MemoryError("足りない")
            drawn.append(seed)
            return f"/x/{seed}.png"
        k = pausekeep.key("batch", "a")
        res = batch.run(jobs, draw, pause_key=k)
        self.assertEqual(res["paused"], 1)
        self.assertEqual(drawn, [10])
        rec = pausekeep.info(k)
        self.assertEqual(rec["job"]["start"], 1)
        res2 = batch.run(rec["job"]["jobs"], draw, start=rec["job"]["start"], pause_key=k)
        self.assertEqual(drawn, [10, 11, 12])   # 一時停止した枚から続き、描いた枚は描き直さない
        self.assertIsNone(res2["paused"])
        self.assertIsNone(pausekeep.info(k))


class Resp(io.BytesIO):
    def __init__(self, data, status=200, cut=None):
        super().__init__(data)
        self.status, self.cut, self.headers = status, cut, {"Content-Length": str(len(data))}

    def read(self, n=-1):
        if self.cut is not None and self.tell() >= self.cut:
            raise ConnectionError("切れた")
        return super().read(min(n, (self.cut - self.tell()) if self.cut is not None else n))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FetchPauseTest(KeepDir):
    def test_fetch_pauses_keeps_part_and_resumes_with_range(self):
        data = bytes(range(256)) * 40
        dest = self.d / "m.bin"
        ranges = []

        def cut_opener(req, timeout=None):
            return Resp(data, cut=4000)

        with self.assertRaises(fetchfile.FetchPaused) as cm:
            fetchfile.fetch_resumable("http://x/m.bin", dest, len(data), retries=0, opener=cut_opener)
        self.assertEqual(cm.exception.got, 4000)
        self.assertEqual(dest.with_suffix(".part").stat().st_size, 4000)
        rec = pausekeep.info(cm.exception.key)
        self.assertEqual(rec["job"]["got"], 4000)

        def range_opener(req, timeout=None):
            r = req.get_header("Range")
            ranges.append(r)
            start = int(r.split("=")[1].rstrip("-"))
            return Resp(data[start:], status=206)
        fetchfile.fetch_resumable("http://x/m.bin", dest, len(data), opener=range_opener)
        self.assertEqual(ranges, ["bytes=4000-"])   # 取れた所から続ける
        self.assertEqual(dest.read_bytes(), data)
        self.assertIsNone(pausekeep.info(cm.exception.key))

    def test_not_found_is_not_paused(self):
        def nf(req, timeout=None):
            raise urllib.error.HTTPError("http://x", 404, "nf", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            fetchfile.fetch_resumable("http://x/m.bin", self.d / "m.bin", opener=nf)
        self.assertEqual(pausekeep.listing(), [])


class MemoryRetryTest(unittest.TestCase):
    def test_waits_then_pauses_instead_of_giving_up(self):
        class P:
            unloaded = 0

            def unload(self):
                P.unloaded += 1
        calls = []

        def run():
            calls.append(1)
            raise MemoryError("足りない")
        said = []
        old, engine.MEMORY_WAIT_S = engine.MEMORY_WAIT_S, 0.0
        orig = pausekeep.wait_memory
        pausekeep.wait_memory = lambda need, **k: orig(need, free=lambda: 0.0, sleep=lambda s: None, **k)
        try:
            with self.assertRaises(engine.MemoryPaused):
                engine.memory_retry(P(), run, said.append)
        finally:
            engine.MEMORY_WAIT_S = old
            pausekeep.wait_memory = orig
        self.assertTrue(pausekeep.is_pause(engine.MemoryPaused("x")))
        self.assertIn("メモリが空くのを待っています（模型を降ろしました）", said)
        self.assertGreaterEqual(P.unloaded, 3)

    def test_resumes_when_memory_frees(self):
        n = []

        def run():
            n.append(1)
            if len(n) < 4:
                raise MemoryError("足りない")
            return "描けた"
        self.assertEqual(engine.memory_retry(object(), run), "描けた")   # 空いたら続きから描く（測れない機械では待たない）


class ResumeButtonTest(KeepDir):
    def test_window_shows_resume_and_restarts_job(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        a = QApplication.instance() or QApplication([])
        k = pausekeep.key("phases", "雪の騎士")
        pausekeep.save(k, "phases", "工程 5/12「顔・手・足の下描き」で一時停止", {"text": "雪の騎士", "seeds": [3], "style": "", "size": [64, 96]})
        w = Window(Studio(FakeWords(), FakePainter(), self.d))
        w.resize(1280, 800)
        w.show()
        self.assertTrue(w.offer_paused())
        a.processEvents()
        btn = w.activity.resume_tool
        self.assertFalse(btn.isHidden())
        self.assertIn("工程 5/12", btn.toolTip())
        self.assertEqual(btn.text(), "▶ 再開")   # 説明はボタンの中ではなくツールチップ
        SHOTS.mkdir(parents=True, exist_ok=True)
        pv = w.activity.progress_view
        if not pv.isVisible():
            pv.show()
            a.processEvents()
        shot = pv.grab()
        shot.save(str(SHOTS / "pause-resume.png"))
        w.grab().save(str(SHOTS / "pause-window.png"))
        from PySide6.QtWidgets import QDockWidget
        self.assertTrue(w.findChild(QDockWidget, "progress").isVisible())   # 起動したときの「続きから」が窓に見えている
        self.assertGreater(btn.width(), 30)   # 幅が潰れていない
        self.assertTrue(btn.isVisibleTo(pv))   # 進み具合の欄の中で見えている
        w.dirty = False
        w.close()


if __name__ == "__main__":
    unittest.main()
