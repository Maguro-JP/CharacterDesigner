"""ディテール追加・AI の絵のタイムラプス・利用者の統計を、窓から押して最後まで動かす試験。

- ディテール追加: 前は細部のある所の明るさを薄く足すだけで、検品の混ぜ直しでさらに薄まり、見て分かる変化が無かった
- タイムラプス: AI が 1 回で描くと記録が 1 枚になり、GIF も動画も作れなかった
- 統計: 判定と使った模型・画風を集計し、並べ方だけに使う（描く言葉には足さない）
"""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from chatdraw.tests.test_uifix import app, spin  # noqa: E402
from chatdraw.tests.test_works import menu_action, window  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "library" / "daily" / "2026-10-13" / "05-yukionna.png"


def sample(side=192) -> Image.Image:
    im = Image.open(SAMPLE).convert("RGB")
    im.thumbnail((side, side))
    return im


def fineness(im) -> float:
    from scipy.ndimage import gaussian_filter
    L = np.asarray(im.convert("RGB"), np.float32) @ np.float32([0.299, 0.587, 0.114])
    return float(np.abs(L - gaussian_filter(L, 1.0)).mean())


class DetailTest(unittest.TestCase):
    def test_detail_really_adds_detail(self):
        """前の作り（変わった画素 4.6%、細かさ +5%）より、はっきり細部が増える。形と色相は保つ"""
        from chatdraw import finishers
        src = sample()
        with mock.patch("chatdraw.facefeat.keep", lambda s, o, m=None: (o, dict(measured=False))):
            out = finishers.run("detail", src)
        a, b = np.asarray(src, np.int32), np.asarray(out, np.int32)
        changed = (np.abs(a - b).max(2) > 0).mean()
        self.assertGreater(changed, 0.05)
        self.assertGreater(fineness(out), fineness(src) * 1.1)
        q = finishers.scores(src, out)
        self.assertLess(q["color"], 14.0)         # 色相は変えない（明るさだけを足す）

    def test_detail_from_window_puts_top_layer(self):
        with TemporaryDirectory() as d:
            w = window(d)
            p = Path(d) / "s.png"
            sample().save(p)
            w.canvas.place_result(str(p), "元の絵")
            spin()
            n = len(w.canvas.layers)
            with mock.patch("chatdraw.facefeat.keep", lambda s, o, m=None: (o, dict(measured=False))):
                path = w.finish_with("detail")
            spin()
            self.assertIsNotNone(path)
            self.assertEqual(len(w.canvas.layers), n + 1)
            self.assertIn("ディテール", w.canvas.layers[-1].name if hasattr(w.canvas.layers[-1], "name") else "ディテール")
            w.hide()
            w.deleteLater()


class TimelapseTest(unittest.TestCase):
    def test_reconstruct_line_flat_finish(self):
        from chatdraw import timelapse
        im = sample()
        frames = timelapse.reconstruct(im)
        self.assertEqual(len(frames), timelapse.RECON_LINE + timelapse.RECON_FLAT + timelapse.RECON_FINISH)
        self.assertEqual(frames[-1].tobytes(), im.tobytes())
        first = np.asarray(frames[timelapse.RECON_LINE - 1].convert("L"))
        self.assertGreater((first > 200).mean(), 0.5)   # 線画の段は白地が多い

    def test_one_shot_job_gets_reconstructed(self):
        from chatdraw import timelapse
        rec = timelapse.Recorder()
        rec.begin_job()
        self.assertEqual(rec.end_job(sample()), "reconstruct")
        self.assertGreater(len(rec.frames), 10)
        rec2 = timelapse.Recorder()
        rec2.begin_job()
        for k in range(3):
            rec2.add(Image.new("RGB", (32, 32), (k * 60, 0, 0)))   # 拡散の途中の絵
        self.assertEqual(rec2.end_job(sample()), "preview")
        self.assertEqual(len(rec2.frames), 4)

    def test_export_from_file_menu_gif_and_video(self):
        from chatdraw import timelapse
        with TemporaryDirectory() as d:
            w = window(d)
            w.recorder.enabled = True
            w.recorder.clear()
            w.recorder.begin_job()
            w.recorder.end_job(sample())
            gif, mp4 = Path(d) / "t.gif", Path(d) / "t.mp4"
            with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", lambda *a, **k: (str(gif), "")):
                menu_action(w, "ファイル", "書き出す", "タイムラプスを GIF に…").trigger()
            self.assertGreater(Image.open(gif).n_frames, 10)
            with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", lambda *a, **k: (str(mp4), "")):
                menu_action(w, "ファイル", "書き出す", "タイムラプスを動画（MP4）に…").trigger()
            if timelapse.video_available():
                self.assertGreater(mp4.stat().st_size, 1000)
            else:
                self.assertGreater(Image.open(mp4.with_suffix(".webp")).n_frames, 10)
            with mock.patch.object(timelapse, "video_backend", return_value="webp"):
                n, out = w.recorder.export_video(mp4)
            self.assertEqual(out.suffix, ".webp")
            w.hide()
            w.deleteLater()

    def test_ai_draw_from_window_records_timelapse(self):
        from chatdraw.tests.test_chatdraw import FakePainter

        class Real(FakePainter):   # 一色の絵では逆算の段がどれも同じになるので、本物の絵を返す
            def paint(self, *a, **k):
                out = super().paint(*a, **k)
                return sample(max(out.size)).resize(out.size) if hasattr(out, "size") else out
        with TemporaryDirectory() as d:
            w = window(d, Real())
            w.recorder.enabled = True
            w.recorder.clear()
            w.entry.setText("雪の城の前の騎士")
            w.send()
            for _ in range(400):
                app().processEvents()
                if w.thread is None and w.images:
                    break
                import time
                time.sleep(0.02)
            self.assertTrue(w.images, "描き終えていない")
            self.assertGreater(len(w.recorder.frames), 5)   # 1 回で描いても過程が残る
            w.hide()
            w.deleteLater()


class UserStatsTest(unittest.TestCase):
    def _log(self, d, rows):
        f = Path(d) / "draw_log.jsonl"
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return f

    def test_collect_and_order(self):
        from chatdraw import userstats
        rows = [dict(tags=["girl"], model="b/x", verdict="good", size=[832, 1216]) for _ in range(4)]
        rows += [dict(tags=["cat"], model="a/y", verdict="bad") for _ in range(3)]
        with TemporaryDirectory() as d, mock.patch("chatdraw.wordlearn.log_file", lambda: Path(d) / "draw_log.jsonl"):
            self._log(d, rows)
            userstats.refresh()
            st = userstats.collect()
            self.assertEqual((st["count"], st["good"], st["bad"], st["retries"]), (7, 4, 3, 5))
            self.assertGreater(userstats.model_pref("b/x"), userstats.model_pref("a/y"))
            self.assertIn("832×1216", userstats.summary())
            self.assertTrue(userstats.clear())
            self.assertEqual(userstats.collect()["count"], 0)
            userstats.refresh()

    def test_never_adds_words(self):
        """統計は描く言葉に何も足さない（wordlearn.adjust は並べ替えるだけ）"""
        from chatdraw import wordlearn
        rows = [dict(tags=["girl", "red scarf"], model="m", flaws=1, missing=["red scarf"], passed=False, verdict="good")] * 10
        with TemporaryDirectory() as d, mock.patch("chatdraw.wordlearn.log_file", lambda: Path(d) / "draw_log.jsonl"):
            self._log(d, rows)
            out, _, _ = wordlearn.adjust("cat", "m")
            self.assertEqual(out, "cat")

    def test_help_menu_shows_and_clears(self):
        from PySide6.QtWidgets import QMessageBox
        from chatdraw import userstats
        with TemporaryDirectory() as d, mock.patch("chatdraw.wordlearn.log_file", lambda: Path(d) / "draw_log.jsonl"):
            self._log(d, [dict(tags=["girl"], model="m", verdict="good")] * 3)
            userstats.refresh()
            w = window(d)
            menu_action(w, "ヘルプ", "あなたの統計…").trigger()
            spin()
            dlg = w._stats_dialog
            self.assertIn("3 枚", dlg.text.text())
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                dlg.wipe.click()
            self.assertIn("まだ記録がありません", dlg.text.text())
            dlg.close()
            w.hide()
            w.deleteLater()


if __name__ == "__main__":
    unittest.main()
