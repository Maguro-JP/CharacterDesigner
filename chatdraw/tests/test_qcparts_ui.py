"""初回の取得で検品の部品も取り、取れなかった物を画面に 1 行で出し、AI のメニューから取り直せるか（取得は偽にする）"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))


class FetchTest(unittest.TestCase):
    def test_fetch_keeps_going_and_names_failures(self):
        from chatdraw import qcparts
        tried = []

        def fake(p):
            tried.append(p.key)
            if p.key == "parts":
                raise OSError("網が切れた")
        with mock.patch.object(qcparts, "ready", return_value=False):
            failed = qcparts.fetch(fetcher=fake)
        self.assertEqual(tried, [p.key for p in qcparts.PARTS])        # 1 つ落ちても残りは取る
        self.assertEqual(failed, ["部位分け"])
        line = qcparts.failed_line(failed)
        self.assertNotIn("\n", line)
        self.assertIn("部位分け", line)
        self.assertIn("検品の部品を取り直す", line)

    def test_ready_parts_are_not_fetched(self):
        from chatdraw import qcparts
        with mock.patch.object(qcparts, "ready", return_value=True):
            self.assertEqual(qcparts.fetch(fetcher=lambda p: self.fail("取った")), [])


class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def spin(self):
        for _ in range(5):
            self.app.processEvents()

    def test_first_run_fetches_qc_parts_and_shows_one_line(self):
        from chatdraw import qcparts, setup
        with mock.patch.object(setup, "ensure_shared"), mock.patch.object(setup, "engine_ready", return_value=True), \
                mock.patch.object(setup.Fetcher, "_image") as image, mock.patch.object(qcparts, "fetch", return_value=["手", "足"]) as qc:
            dlg = setup.SetupDialog(None, None, first=True)
            dlg.show()
            dlg.pages.setCurrentIndex(1)
            dlg.fetcher.run(setup.IMAGES[0], None)
            self.spin()
            image.assert_called_once()
            qc.assert_called_once()
            self.assertEqual(dlg.pages.currentIndex(), 2)                  # 取れなくても先へ進む（描くのは止めない）
            self.assertTrue(dlg.qc_note.isVisible())
            self.assertIn("手、足", dlg.qc_note.text())
            self.assertNotIn("\n", dlg.qc_note.text())
            dlg.close()

    def test_all_fetched_shows_nothing(self):
        from chatdraw import qcparts, setup
        with mock.patch.object(setup, "ensure_shared"), mock.patch.object(setup, "engine_ready", return_value=True), \
                mock.patch.object(setup.Fetcher, "_image"), mock.patch.object(qcparts, "fetch", return_value=[]):
            dlg = setup.SetupDialog(None, None, first=True)
            dlg.show()
            dlg.fetcher.run(setup.IMAGES[0], None)
            self.spin()
            self.assertFalse(dlg.qc_note.isVisible())
            dlg.close()

    def test_ai_menu_refetches(self):
        from chatdraw import engine, qcparts, setup
        from chatdraw.app import Window
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        with TemporaryDirectory() as d:
            w = Window(engine.Studio(FakeWords(), FakePainter(), Path(d)))
            acts = {a.text(): a for a in w.ai_menu.actions()}
            self.assertIn("検品の部品を取り直す", acts)
            self.assertTrue(acts["検品の部品を取り直す"].toolTip())
            said = []
            with mock.patch.object(setup, "ensure_shared"), mock.patch.object(setup, "engine_ready", return_value=True), \
                    mock.patch.object(qcparts, "fetch", return_value=["部位分け"]), \
                    mock.patch.object(w, "notify", side_effect=lambda text, kind="info", *a, **k: said.append((text, kind))), \
                    mock.patch("threading.Thread", side_effect=lambda target, args, daemon: mock.Mock(start=lambda: target(*args))):
                acts["検品の部品を取り直す"].trigger()
                self.spin()
            self.assertTrue(said)
            self.assertIn("部位分け", said[-1][0])
            self.assertEqual(said[-1][1], "error")
            w.close()


if __name__ == "__main__":
    unittest.main()
