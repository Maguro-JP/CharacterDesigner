"""絵ごとの作業（レイヤー・赤ペン）が、別の絵へ移って戻っても、窓を閉じて開き直しても元のとおりに戻るか。
赤ペンの直しの結果が、画像のファイル・履歴・ライブラリーに出ないか（レイヤーにだけ置く）。
直しは本物と同じ経路（Window.send の直す形 → 裏の糸の Job → Studio.fix → on_one）で、小さな偽の模型で流す"""
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

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def pixels(layer) -> str:
    """画素の指紋（形式の違いは見ない。並べて比べると差の表示に時間がかかるので、指紋で比べる）"""
    import hashlib
    from PySide6.QtGui import QImage
    img = layer.image.convertToFormat(QImage.Format_ARGB32)
    return hashlib.sha1(bytes(img.constBits())).hexdigest()


class LayerKeepTest(unittest.TestCase):
    def setUp(self):
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.out = self.d / "out"
        self.home = mock.patch("chatdraw.paths.HOME", self.d / "home")
        self.home.start()
        # 偽の模型の直しは毎回違う崩れの文を返し、直しきるまで回る形（上限なし）が終わらない。崩れの検査だけを外す
        self.quiet = [mock.patch("chatdraw.engine.flaws", lambda *a, **k: []),
                      mock.patch("chatdraw.seamfix.settle", lambda before, result, mask, say=None: (result, []))]
        for q in self.quiet:
            q.start()
        self.a, self.b = self.out / "a.png", self.out / "b.png"
        self.out.mkdir()
        figure().save(self.a)
        Image.new("RGB", (96, 128), (30, 60, 200)).save(self.b)
        self.w = self.window()

    def window(self):
        from chatdraw.app import Window
        from chatdraw.library import Library
        w = Window(Studio(FakeWords(), FakePainter(), self.out))
        self.old_place = w.settings.store.value("result_place")
        w.settings.set("result_place", "上のレイヤー")
        w.library = Library(self.d / "lib")
        return w

    def tearDown(self):
        self.close(self.w)
        self.home.stop()
        for q in self.quiet:
            q.stop()
        self.tmp.cleanup()

    def close(self, w):
        if self.old_place is None:
            w.settings.store.remove("result_place")
        else:
            w.settings.set("result_place", self.old_place)
        w.dirty = False
        w.close()

    def wait(self, w, sec=120):
        end = time.time() + sec
        while (w.thread is not None or getattr(w, "bg_pending", 0)) and time.time() < end:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.qapp.processEvents()

    def redpen_fix(self, w):
        """赤ペンで囲んで指示を書き、「描く」で直す（アプリの経路そのまま）"""
        c = w.canvas
        c.set_tool("redpen")
        pen = c.redpen
        pen.begin(QPointF(20, 20))
        for x, y in ((60, 20), (60, 60), (20, 60), (20, 21)):
            pen.add(QPointF(x, y))
        pen.end()
        pen.set_text(1, "目を大きく")
        w.mode.setCurrentIndex(2)
        w.entry.setText("目を大きく")
        with mock.patch.object(w, "_keep_original", lambda text: text):
            w.send()
        t0 = time.time()
        self.wait(w)
        print(f"直しの時間 {time.time() - t0:.1f} 秒")
        self.assertIsNone(w.thread, "直しが終わらない")

    def build_a(self, w):
        w.show_history_image(str(self.a))
        c = w.canvas
        while len(c.layers) < 3:
            c.add_layer()
        for i, (name, op) in enumerate((("下塗り", 0.9), ("絵 A", 0.7), ("上の線", 0.5))):
            c.layers[i].name, c.layers[i].opacity = name, op
        c.layers[2].image.fill(0x80FF0000)
        c.rebuild()
        self.redpen_fix(w)
        # 直したあとに、次の直しの印を 1 つ残しておく（印と指示が戻るかを見る）
        pen = c.redpen
        pen.begin(QPointF(5, 5))
        for x, y in ((30, 5), (30, 30), (5, 30), (5, 6)):
            pen.add(QPointF(x, y))
        pen.end()
        pen.set_text(len(pen.marks), "髪を整える")

    def state(self, c):
        return ([(l.name, round(l.opacity, 3), l.visible, l.redpen) for l in c.layers], [pixels(l) for l in c.layers],
                [[(round(p.x()), round(p.y())) for p in pts] for pts in c.redpen.marks], list(c.redpen.texts))

    def assertNoRedpenFiles(self, w):
        from chatdraw.workkeep import is_redpen_result, is_work_file
        files = [p for p in self.out.rglob("*.png") if not is_work_file(p)]
        self.assertEqual([p for p in files if is_redpen_result(p)], [], "赤ペンの結果が出力の置き場にある")
        self.assertEqual(sorted(p.name for p in files), ["a.png", "b.png"])
        hist = [w.history.item(i).data(0x0100) for i in range(w.history.count())]
        self.assertEqual([h for h in hist if h and Path(h).name not in ("a.png", "b.png")], [])
        self.assertEqual([i for i in w.library.items if Path(i["path"]).name not in ("a.png", "b.png")], [])
        self.assertEqual(list(Path(os.environ.get("TMPDIR", "/tmp")).glob("cd-redpen-*.png")), [])

    def test_switch_and_reopen_keep_layers(self):
        w = self.w
        self.build_a(w)
        c = w.canvas
        self.assertTrue(any(l.redpen for l in c.layers), [l.name for l in c.layers])
        before = self.state(c)
        print("A の作業:", before[0], "印", len(before[2]), before[3])
        w.show_history_image(str(self.b))
        self.assertEqual(len(c.layers), 2)
        self.assertEqual(c.redpen.marks, [])
        w.show_history_image(str(self.a))
        after = self.state(c)
        self.assertEqual(after, before)
        self.assertNoRedpenFiles(w)
        # 閉じて開き直す
        self.close(w)
        self.w = w = self.window()
        w.show_history_image(str(self.a))
        again = self.state(w.canvas)
        self.assertEqual(again[0], before[0])
        self.assertEqual(again[1], before[1])
        self.assertEqual(again[2:], before[2:])
        self.assertNoRedpenFiles(w)
        print("開き直したあと:", again[0], "印", len(again[2]), again[3])

    def test_unused_redpen_layers_are_dropped(self):
        w = self.w
        w.show_history_image(str(self.a))
        self.redpen_fix(w)
        c = w.canvas
        fixed = [i for i, l in enumerate(c.layers) if l.redpen]
        self.assertEqual(len(fixed), 1)
        c.set_visible(fixed[0], False)   # 使わないので隠した
        n = len(c.layers)
        w.show_history_image(str(self.b))
        w.show_history_image(str(self.a))
        self.assertEqual(len(c.layers), n - 1)
        self.assertFalse(any(l.redpen for l in c.layers))
        # 元に戻した直しも、やり直すで戻らない（捨てた）
        self.redpen_fix(w)
        c.tool = "pen"
        c.undo()
        self.assertFalse(any(l.redpen for l in c.layers))
        w.show_history_image(str(self.b))
        w.show_history_image(str(self.a))
        self.assertFalse(c.redo_stack)
        self.assertNoRedpenFiles(w)

    def test_kept_redpen_layer_survives(self):
        w = self.w
        w.show_history_image(str(self.a))
        self.redpen_fix(w)
        w.show_history_image(str(self.b))
        w.show_history_image(str(self.a))
        self.assertEqual(sum(l.redpen for l in w.canvas.layers), 1)

    def test_old_library_redpen_items_hidden(self):
        from chatdraw.finishers import KEY
        from chatdraw.library import Library
        from PIL import PngImagePlugin
        old = self.out / "old-fix.png"
        info = PngImagePlugin.PngInfo()
        info.add_itxt(KEY, '{"mode": "直す"}')
        Image.new("RGBA", (8, 8)).save(old, pnginfo=info)
        lib = Library(self.d / "lib2")
        lib.items = [{"id": "x", "kind": "work", "path": str(old)}, {"id": "y", "kind": "work", "path": str(self.a)}]
        lib.save()
        lib = Library(self.d / "lib2")
        self.assertEqual([i["id"] for i in lib.items], ["y"])
        self.assertEqual(lib.add_work(str(old)), {})
        self.assertTrue(old.exists())   # 利用者のファイルには触らない


if __name__ == "__main__":
    unittest.main()
