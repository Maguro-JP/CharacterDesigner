"""模型の非表示・ブロック・停止。気に入らない模型を一覧・推奨・おまかせ・AI のメニュー・取得から外せ、描いている処理を止めて模型をメモリから降ろせるか"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))


def _env(d):
    from chatdraw import manager
    return [mock.patch.dict(os.environ, {"CD_HOME": d}), mock.patch.object(manager, "HUB", Path(d) / "hub"),
            mock.patch.object(manager, "GGUF", Path(d) / "g"), mock.patch.object(manager, "OWN_LLM", Path(d) / "none")]


class BlockTest(unittest.TestCase):
    def test_block_includes_hide_and_unblock_keeps_old_hide(self):
        from chatdraw import ratings
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            self.assertFalse(ratings.is_blocked("a/a"))
            ratings.set_blocked("a/a", True)
            self.assertTrue(ratings.is_blocked("a/a"))
            self.assertTrue(ratings.is_hidden("a/a"))           # ブロックは非表示を含む
            ratings.set_blocked("a/a", False)
            self.assertFalse(ratings.is_hidden("a/a"))
            ratings.set_hidden("b/b", True)
            ratings.set_blocked("b/b", True)
            ratings.set_blocked("b/b", False)
            self.assertTrue(ratings.is_hidden("b/b"))           # 解除しても、前の非表示は残る

    def test_blocked_never_chosen_offered_or_listed(self):
        from chatdraw import choose, models, ratings
        a = models.ImageModel("a/a", "A", "", "anime", 1, 20, 5, score=90)
        b = models.ImageModel("b/b", "B", "", "anime", 1, 20, 5, score=10)
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            ratings.set_blocked("a/a", True)
            self.assertEqual(choose.choose_image("女の子", "", have=[a, b])[0], b)
            self.assertIsNone(choose.choose_image("女の子", "", have=[a])[0])   # 非表示と違い、ほかに無くても選ばない
            self.assertNotIn(a, models.pick([a, b], "すべて", have={"a/a"}))
            self.assertIn(a, models.pick([a, b], models.HIDDEN))               # 解除するために、隠した物の絞り込みには出す
            top = models.offered_images()[0]
            ratings.set_blocked(top.repo, True)
            self.assertNotIn(top, models.offered_images())

    def test_blocked_is_not_fetched(self):
        from chatdraw import ratings, setup
        from chatdraw.models import ImageModel
        m = ImageModel("a/a", "A", "", "", 1, 20, 5)
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}), \
                mock.patch.object(setup, "ensure_shared"), mock.patch.object(setup, "engine_ready", return_value=True), \
                mock.patch.object(setup.Fetcher, "_image") as got:
            ratings.set_blocked("a/a", True)
            f = setup.Fetcher()
            out = []
            f.finished.connect(out.append)
            f.run(m, None)
            got.assert_not_called()
            self.assertIn("ブロック", out[0])


class MenuTest(unittest.TestCase):
    def test_more_and_right_click_have_hide_block_stop_with_tooltips(self):
        from contextlib import ExitStack
        from PySide6.QtCore import QSettings, Qt
        from PySide6.QtWidgets import QApplication
        from chatdraw import manager, models, ratings
        from chatdraw.settings import Settings
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d, ExitStack() as st:
            for p in _env(d):
                st.enter_context(p)
            s = Settings(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
            m = models.IMAGES[0]
            s.set("image_model", m.repo)
            dlg = manager.ModelManager(s)
            menu = dlg._more(m, ("取る", None))
            names = [a.text() for a in menu.actions() if a.text()]
            for want in ("非表示にする", "ブロックする", "描いている処理を止める", "メモリから降ろす"):
                self.assertIn(want, names)
            self.assertTrue(all(a.toolTip() and a.toolTip() != a.text() for a in menu.actions() if a.text()))
            cards = [dlg.list.itemAt(i).widget() for i in range(dlg.list.count()) if hasattr(dlg.list.itemAt(i).widget(), "more")]
            self.assertTrue(cards)
            self.assertEqual(cards[0].contextMenuPolicy(), Qt.CustomContextMenu)   # 右クリックでも同じ物
            dlg.set_blocked(m, True)
            self.assertTrue(ratings.is_blocked(m.repo))
            self.assertNotEqual(s.get("image_model"), m.repo)                      # 使っていた物はおまかせに戻す
            names = [a.text() for a in dlg._more(m, ("取る", None)).actions()]
            self.assertIn("ブロックを解除", names)
            dlg.fetch(m)
            self.assertIn("ブロック", dlg.status.text())
            dlg.set_blocked(m, False)
            self.assertFalse(ratings.is_blocked(m.repo))


class StopTest(unittest.TestCase):
    def test_unload_frees_pipes(self):
        from chatdraw.engine import Painter
        p = Painter("a/a")
        p._pipe, p._sketch = object(), object()
        self.assertTrue(p.loaded())
        p.unload()
        self.assertFalse(p.loaded())

    def test_stopped_result_is_discarded(self):
        """止めたあとに返ってきた絵（直しの途中で抜けた物）は置かない"""
        from chatdraw.app import Job
        from chatdraw.engine import Painter

        class Studio:
            painter = Painter("a/a")

            def fix(self, *a, **k):
                self.painter.stop = True
                return ["x"], "half.png"

            def draw(self, *a, **k):
                self.painter.stop = True
                return "x", "half.png"
        for regions in (None, [(None, "x")]):
            job = Job(Studio(), "x", [1], regions=regions)
            got, failed = [], []
            job.one.connect(lambda *a: got.append(a))
            job.failed.connect(failed.append)
            job.run()
            self.assertEqual(got, [])
            self.assertIn("止め", failed[0])


if __name__ == "__main__":
    unittest.main()
