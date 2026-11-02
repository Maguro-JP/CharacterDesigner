"""赤ペンの印が印ごとにレイヤーの欄の行になり、指示がその行のコメントになるか。
前は印が「赤ペン」の 1 行にまとまり、指示は絵の上の赤い札でいつも出ていて、絵が見えず邪魔だった。
印はキャンバスをマウスで囲み、指示は絵の上の欄に打って Enter、と利用者と同じ経路で書く"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp, mktemp

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.layerpanel import mark_of  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_idle  # noqa: E402


class RedPenLayersTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.app = QApplication.instance() or QApplication([])
        self.dir = Path(mkdtemp())
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.dir))
        self.w.layout_store = QSettings(mktemp(suffix=".ini"), QSettings.IniFormat)
        self.w.layout_store.setValue("feature_tours", 0)
        self.w.resize(1200, 900)
        self.w.show()
        self.w.canvas.new_canvas(200, 160)
        self.w.tool_actions["redpen"].trigger()
        self.app.processEvents()

    def tearDown(self):
        self.w.dirty = False
        self.w.close()

    def view(self, x, y) -> QPoint:
        return self.w.canvas.mapFromScene(QPointF(x, y))

    def circle(self, x, y, note):
        """キャンバスの上をマウスで四角く囲み、出てきた欄に指示を打って Enter"""
        vp = self.w.canvas.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, self.view(x, y))
        for dx, dy in ((10, 0), (20, 0), (30, 0), (30, 15), (30, 30), (15, 30), (0, 30), (0, 15), (0, 3)):
            QTest.mouseMove(vp, self.view(x + dx, y + dy))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, self.view(x, y + 2))
        self.app.processEvents()
        self.assertFalse(self.w.note_edit.isHidden())               # 囲むとすぐ指示の欄が出る
        self.w.note_edit.clear()
        self.w.note_edit.insert(note)   # 日本語は入力メソッドから入るので、打った後の文を欄に入れる（QTest のキーは ASCII だけ）
        QTest.keyClick(self.w.note_edit, Qt.Key_Return)
        self.app.processEvents()

    def rows(self):
        lst = self.w.layer_panel.list
        return [lst.item(r) for r in range(lst.count()) if mark_of(lst.item(r).data(Qt.UserRole))]

    def label_pixels(self, n) -> int:
        """番号 n の丸の右（札が出る所）にある、赤い画素の数。札が出ていなければ 0"""
        pen = self.w.canvas.redpen
        img = QImage(200, 160, QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        pen.paint(p, None)
        p.end()
        c = pen.marks[n - 1][0]
        count = 0
        for x in range(int(c.x()) + 2, min(200, int(c.x()) + 60)):
            for y in range(max(0, int(c.y()) - 26), int(c.y()) - 2):
                col = img.pixelColor(x, y)
                count += col.alpha() > 100 and col.red() > 200 and col.green() < 120
        return count

    def test_one_row_per_mark_note_as_comment(self):
        pen = self.w.canvas.redpen
        self.circle(30, 60, "手を直して")
        self.circle(120, 60, "帽子を青に")
        rows = self.rows()
        self.assertEqual(len(rows), 2)                                # 印を 2 つ書くと行が 2 つ
        self.assertTrue(rows[0].text().startswith("赤ペン 1"))
        self.assertTrue(rows[1].text().startswith("赤ペン 2"))
        self.assertIn("手を直して", rows[0].toolTip())               # 指示は行のツールチップに出る
        self.assertIn("帽子を青に", rows[1].toolTip())
        self.assertIn("帽子を青に", rows[1].text())                  # 名前の横にも短く出る
        self.assertEqual(pen.shown_notes(), [])                       # 絵の上の札はいつもは出さない
        self.assertEqual(self.label_pixels(1), 0)
        self.assertEqual(self.label_pixels(2), 0)

        self.w.layer_panel.list.setCurrentItem(self.rows()[1])       # 行を選ぶと、その印だけ札が出る
        self.assertEqual(pen.shown_notes(), [2])
        self.assertGreater(self.label_pixels(2), 20)
        self.assertEqual(self.label_pixels(1), 0)

        pen.set_active(0)                                             # カーソルを番号の丸に合わせたときも出る
        c = pen.marks[0][0]
        QTest.mouseMove(self.w.canvas.viewport(), self.view(c.x() - 13 / self.w.canvas.zoom(), c.y() - 13 / self.w.canvas.zoom()))
        self.app.processEvents()
        self.assertEqual(pen.shown_notes(), [1])
        QTest.mouseMove(self.w.canvas.viewport(), self.view(190, 150))
        self.app.processEvents()
        self.assertEqual(pen.shown_notes(), [])

        self.w.layer_panel.list.setCurrentItem(self.rows()[0])       # 1 つ消すと行が 1 つ
        self.w.layer_panel._delete()
        self.app.processEvents()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].text().startswith("赤ペン 1"))
        self.assertIn("帽子を青に", rows[0].toolTip())               # 残った印が 1 番に繰り上がる
        self.w.canvas.undo()                                          # 元に戻すで、消した印が同じ番号に戻る
        self.app.processEvents()
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertIn("手を直して", rows[0].toolTip())
        self.assertIn("帽子を青に", rows[1].toolTip())
        self.w.canvas.redo()                                          # やり直すで、また消える
        self.app.processEvents()
        self.assertEqual([r.text() for r in self.rows()], ["赤ペン 1　帽子を青に"])

    def test_hide_and_reorder_rows(self):
        pen = self.w.canvas.redpen
        self.circle(30, 60, "目を大きく")
        self.circle(120, 60, "指を5本に")
        self.rows()[0].setCheckState(Qt.Unchecked)                   # チェックを外すと隠す
        self.app.processEvents()
        self.assertEqual(pen.hidden, [True, False])
        self.assertEqual(self.rows()[0].checkState(), Qt.Unchecked)
        self.w.layer_panel.list.setCurrentItem(self.rows()[1])       # ▲で 2 番を 1 番にする
        self.w.layer_panel.buttons["up_b"].click()
        self.app.processEvents()
        self.assertEqual(pen.texts, ["指を5本に", "目を大きく"])
        self.assertEqual(pen.hidden, [False, True])
        self.assertIn("指を5本に", self.rows()[0].toolTip())

    def test_fix_uses_every_mark_and_note(self):
        self.circle(30, 60, "手を直して")
        self.circle(120, 60, "帽子を青に")
        self.rows()[0].setCheckState(Qt.Unchecked)                   # 隠した印も直すときは使う
        self.app.processEvents()
        notes = [n for _, n in self.w.fix_regions("")]
        self.assertEqual(notes, ["手を直して", "帽子を青に"])
        self.w.mode.setCurrentIndex(2)
        self.w.entry.clear()
        self.w.send()
        wait_idle(self.app, self.w)
        self.assertEqual(len([c for c in self.painter.calls if c[0] == "redraw"]), 2)   # 印ごとに 1 回ずつ直す
        self.assertEqual(self.rows(), [])                             # 直したら印の行は消える


if __name__ == "__main__":
    unittest.main()
