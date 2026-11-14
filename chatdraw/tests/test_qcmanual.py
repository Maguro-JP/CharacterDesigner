"""手で呼ぶ検品を、窓から押す経路で通す（偽の模型と偽の検品）。
検品は崩れた所を赤ペンで囲んで指示を書くだけで直さない。指示の空の囲みで直しを押すと、その中を検品して 1 回だけ直す"""
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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw import qcmanual  # noqa: E402
from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg, wait_idle  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def hand_flaw(box=(40, 40, 90, 90)):
    return {"readable": True, "bad": ["手 1: 指が 6 本"], "feet": [], "faces": [], "face": {"readable": True},
            "hands": [{"box": list(box), "bad": ["指が 6 本"], "seen": True}]}


CLEAN = {"readable": True, "bad": [], "hands": [{"box": [1, 1, 5, 5], "bad": [], "seen": True}], "feet": [], "faces": [],
         "face": {"readable": True}}


class QcManualTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        src = self.d / "a.png"
        figure().save(src)   # 人が描いた絵として開く（AI の描いた履歴は無い）
        self.w.resize(1200, 800)
        self.w.show()
        self.w.canvas.replace_with_image(str(src))
        QTest.qWait(50)
        self.said = []
        self.w.notify = lambda title, kind="", body="", **k: self.said.append(f"{title} {body}")
        self.old = qcmanual.inspect
        self.seen = []

    def tearDown(self):
        qcmanual.inspect = self.old
        self.w.closing_checked = True
        self.w.close()
        self.tmp.cleanup()

    def fake(self, res):
        def run(img):
            self.seen.append(img.size)
            return res
        qcmanual.inspect = run

    def settle(self):
        wait_idle(self.qapp, self.w, 60)
        wait_bg(self.qapp, self.w)

    def redraws(self):
        return [x for x in self.painter.calls if x[0] == "redraw"]

    def test_menu_marks_flaws_without_fixing(self):
        self.fake(hand_flaw())
        acts = [a for a in self.w.menuBar().actions() if a.text() == "編集"][0].menu().actions()
        [a for a in acts if a.text() == "検品する"][0].trigger()
        self.settle()
        pen = self.w.canvas.redpen
        self.assertEqual(len(pen.marks), 1, self.said)
        self.assertIn("指が 6 本", pen.texts[0])
        self.assertEqual(self.redraws(), [])          # 検品は直さない
        self.assertEqual(self.w.mode.currentIndex(), 2)   # そのまま「囲んだ所を直す」を押せる
        self.assertTrue(any("1 か所" in t for t in self.said), self.said)
        mask = pen.masks()[0]
        from chatdraw.app import gray_to_pil
        x0, y0, x1, y1 = gray_to_pil(mask).getbbox()
        self.assertTrue(x0 <= 40 and y0 <= 40 and x1 >= 90 and y1 >= 90)   # 枠を囲む

    def test_right_click_menu_has_inspect(self):
        self.fake(CLEAN)
        m = self.w.build_canvas_menu()
        [a for a in m.actions() if a.text() == "検品する"][0].trigger()
        self.settle()
        self.assertEqual(self.w.canvas.redpen.marks, [])
        self.assertTrue(any("崩れは見つかりませんでした" in t for t in self.said), self.said)

    def test_cannot_check_is_said(self):
        self.fake({"readable": False, "bad": [], "hands": [], "reason": "検品の部品がありません"})
        self.w.inspect_now()
        self.settle()
        self.assertTrue(any("検品できなかった" in t and "部品" in t for t in self.said), self.said)

    def test_blank_canvas_says_one_line(self):
        self.fake(hand_flaw())
        self.w.canvas.new_canvas(200, 200)
        self.w.inspect_now()
        self.settle()
        self.assertEqual(self.seen, [])
        self.assertTrue(any("絵がありません" in t for t in self.said), self.said)

    def mark(self):
        c = self.w.canvas
        self.w.tool_actions["redpen"].trigger()
        vp = c.viewport()
        start = c.mapFromScene(c.sceneRect().center()) + QPoint(-30, -30)
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
        for i in range(1, 16):
            QTest.mouseMove(vp, start + QPoint(4 * i, 4 * i))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 60))
        QTest.qWait(20)

    def test_empty_note_inspects_inside_and_fixes_once(self):
        self.fake(hand_flaw((2, 2, 20, 20)))
        self.mark()
        n = len(self.w.canvas.layers)
        pen = self.w.canvas.redpen
        notes, put = [], pen.set_text
        pen.set_text = lambda i, t: (notes.append(t), put(i, t))
        QTest.mouseClick(self.w.button, Qt.LeftButton)
        self.settle()
        self.settle()
        self.assertEqual(len(self.seen), 1)
        self.assertLess(self.seen[0][0], self.w.canvas.size_px()[0])   # 囲みの中だけを検品する
        self.assertTrue(any("指が 6 本" in t for t in notes), notes)   # 見つけた崩れを指示にする
        self.assertEqual(len(self.redraws()), 1, self.said)             # 1 回だけ直す
        self.assertEqual(len(self.w.canvas.layers), n + 1)
        self.assertEqual(len(self.seen), 1)                              # 直したあとに検品し直さない

    def test_empty_note_without_flaws_does_nothing(self):
        self.fake(CLEAN)
        self.mark()
        n = len(self.w.canvas.layers)
        QTest.mouseClick(self.w.button, Qt.LeftButton)
        self.settle()
        self.assertEqual(self.redraws(), [])
        self.assertEqual(len(self.w.canvas.layers), n)
        self.assertTrue(any("見つからなかった" in t for t in self.said), self.said)


if __name__ == "__main__":
    unittest.main()
