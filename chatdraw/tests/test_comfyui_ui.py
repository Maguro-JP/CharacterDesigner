"""工程ごとの秒の帯、並べて比べる窓、操作を探す窓（Ctrl+K）を、本物と同じ経路（キー、メニュー、描く頼み）で流す"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_idle  # noqa: E402
from chatdraw.tests.test_editing import app  # noqa: E402


class ComfyLikeUiTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        self.w.show()
        self.qapp.processEvents()

    def tearDown(self):
        self.w.dirty = False
        for d in (getattr(self.w, "cmd_palette", None), getattr(self.w, "compare", None)):
            d and d.close()
        self.w.close()
        self.tmp.cleanup()

    def draw(self, text):
        self.w.entry.setText(text)
        self.w.send()
        wait_idle(self.qapp, self.w)

    def test_stage_times_and_compare(self):
        self.draw("赤いマフラーの女の子")
        self.draw("青い帽子の男の子")
        a = self.w.activity
        line = a.timeline.text()
        self.assertTrue(a.stage_times, line)                 # 工程ごとの秒が残る
        self.assertIn("秒", line)
        self.assertNotIn("止まりました", line)
        self.assertGreaterEqual(self.w.history.count(), 2)
        # メニューの「表示 › 描いた絵を並べて比べる」を押す
        acts = {t: x for t, x in __import__("chatdraw.palette", fromlist=["x"]).menu_actions(self.w.menuBar())}
        acts["表示 › 描いた絵を並べて比べる"].trigger()
        self.qapp.processEvents()
        self.assertEqual(len(self.w.compare.cells), 2)
        self.w.compare.cells[1].mousePressEvent(None)        # 押すとその絵を出して閉じる
        self.qapp.processEvents()
        self.assertFalse(self.w.compare.isVisible())

    def test_stop_marks_stage(self):
        a = self.w.activity
        a.begin("テスト", "描く")
        a.status("絵の模型を読んでいます")
        a.status("描いています（1/4）")
        a.status("検品しています（1/2）")
        a.end("止めました")
        self.assertEqual(a.stopped_at, "検品")
        self.assertIn("検品", a.timeline.text())
        self.assertIn("ここで止まりました", a.timeline.text())

    def test_palette_by_key(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.keyClick(self.w, Qt.Key_K, Qt.ControlModifier)   # キーで開く
        self.qapp.processEvents()
        pal = getattr(self.w, "cmd_palette", None)
        self.assertIsNotNone(pal)
        self.assertTrue(pal.isVisible())
        self.assertGreater(pal.list.count(), 20)            # メニューの操作が並ぶ
        pal.box.setText("全体を表示")              # 打つ（日本語は keyClicks で打てないので文字を入れる）
        self.assertGreaterEqual(pal.list.count(), 1)
        self.assertIn("全体", pal.list.currentItem().text())
        hit = []
        pal.list.currentItem().data(Qt.UserRole).triggered.connect(lambda *_: hit.append(1))
        QTest.keyClick(pal.box, Qt.Key_Return)              # Enter で呼ぶ
        self.qapp.processEvents()
        self.assertEqual(hit, [1])
        self.assertFalse(pal.isVisible())
        pal2 = self.w.open_palette()
        pal2.box.setText("zzzzありえない")
        self.assertEqual(pal2.list.count(), 0)
        self.assertTrue(pal2.empty.isVisibleTo(pal2))       # 0 件のとき次にすることを出す


if __name__ == "__main__":
    unittest.main()
