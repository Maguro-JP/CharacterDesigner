"""加工（綺麗にする・仕上げ・拡大・透過・背景を消す・エフェクト）の結果が、本物の経路で押したときに今の絵の一番上の
新しいレイヤーに入り、履歴の「描いた絵」にも入り、別の絵を選んでも履歴から戻せるか。
前は「別ファイル」の設定で新しいウィンドウになり、拡大はキャンバスを結果 1 枚に置き換え、加工した絵は履歴に入らず、
履歴やライブラリーで別の絵を選ぶと消えて、フォルダーを開かないと戻せなかった"""
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
from PySide6.QtCore import Qt  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def size(path):
    with Image.open(path) as im:
        return im.size


class KeepResultTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = Window(Studio(FakeWords(), FakePainter(), self.d))
        self.old_place = self.w.settings.store.value("result_place")
        # 利用者が「別ファイル」にしていても、加工の結果は今の絵のレイヤーに入ることを見る
        self.w.settings.set("result_place", "別ファイル")
        self.w.settings.set("output_dir", str(self.d / "out"))
        self.src = self.d / "a.png"
        figure().save(self.src)
        self.w.edit_image(str(self.src))
        self.spawn = mock.patch("PySide6.QtCore.QProcess.startDetached", return_value=True)
        self.started = self.spawn.start()

    def tearDown(self):
        self.spawn.stop()
        if self.old_place is None:
            self.w.settings.store.remove("result_place")
        else:
            self.w.settings.set("result_place", self.old_place)
        self.wait(lambda: self.w.thread is None and not self.w.bg_pending)
        self.w.dirty = False
        self.w.close()
        self.tmp.cleanup()

    def wait(self, cond, sec=60):
        end = time.time() + sec
        while time.time() < end:
            self.qapp.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return cond()

    def names(self):
        return [l.name for l in self.w.canvas.layers]

    def history(self):
        return [self.w.history.item(i).data(Qt.UserRole) for i in range(self.w.history.count())]

    def assertPlaced(self, name, before):
        """一番上の新しいレイヤーに入って選ばれ、下のレイヤーは消えていない。新しいウィンドウは開いていない"""
        c = self.w.canvas
        self.assertEqual(c.layers[-1].name, name, self.names())
        self.assertEqual(c.current, len(c.layers) - 1)
        self.assertEqual(self.names()[:-1], before)
        self.assertFalse(self.started.called, "加工の結果で新しいウィンドウを開いた")

    def press(self, fn, done):
        fn()
        self.assertTrue(self.wait(done), self.names())

    def test_finish_in_background_goes_to_layer_and_history(self):
        before, hist = self.names(), self.w.history.count()
        self.press(lambda: self.w.finish_with("clean", background=True), lambda: len(self.w.canvas.layers) > len(before))
        self.assertPlaced("綺麗にした絵", before)
        self.assertEqual(self.w.history.count(), hist + 1)
        got = self.history()[0]
        self.assertTrue(Path(got).is_file(), got)
        self.assertEqual(size(got), size(self.src))

    def test_enlarge_keeps_layers(self):
        from chatdraw import finishers
        f = finishers.Finisher("test_x2", "試験の拡大", "", "", "", lambda: True, lambda: "",
                               lambda im: im.resize((im.width * 2, im.height * 2)))
        with mock.patch.dict(finishers.REGISTRY, {"test_x2": f}):
            before = self.names()
            w0, h0 = self.w.canvas.size_px()
            self.press(lambda: self.w.finish_with("test_x2", background=True), lambda: len(self.w.canvas.layers) > len(before))
        self.assertPlaced("綺麗にした絵（拡大）", before)
        self.assertEqual(self.w.canvas.size_px(), (w0 * 2, h0 * 2))
        self.assertTrue(all((l.image.width(), l.image.height()) == (w0 * 2, h0 * 2) for l in self.w.canvas.layers))
        self.w.canvas.undo()   # 元に戻すで前の大きさとレイヤーに戻る
        self.assertEqual(self.names(), before)
        self.assertEqual(self.w.canvas.size_px(), (w0, h0))

    def test_effect_layer_and_full_picture_in_history(self):
        from chatdraw import finishers
        if not finishers.REGISTRY["air_haze"].ready():
            self.skipTest(finishers.REGISTRY["air_haze"].why_not())
        before = self.names()
        self.press(lambda: self.w.finish_with("air_haze", background=True), lambda: len(self.w.canvas.layers) > len(before))
        self.assertPlaced("エフェクト: 霞と遠近", before)
        self.assertEqual(size(self.history()[0]), size(self.src))
        self.assertNotIn("-layer", self.history()[0])   # 履歴には掛けた後の絵全体

    def test_remove_background_and_transparent_are_layers(self):
        for fn, name in ((self.w.remove_background, "背景を消した絵"), (self.w.make_transparent, "透過")):
            before, hist = self.names(), self.w.history.count()
            self.press(fn, lambda: len(self.w.canvas.layers) > len(before))
            self.assertPlaced(name, before)
            self.assertEqual(self.w.history.count(), hist + 1)

    def test_picking_other_picture_keeps_result_in_history(self):
        before = self.names()
        self.press(lambda: self.w.finish_with("clean", background=True), lambda: len(self.w.canvas.layers) > len(before))
        work_names = self.names()
        other = self.d / "b.png"
        Image.new("RGB", (40, 60), (200, 20, 20)).save(other)
        self.w.show_history_image(str(other))   # 履歴で別の絵を選ぶ
        self.assertEqual(self.w.canvas.size_px(), (40, 60))
        kept = self.history()[0]
        self.assertTrue(kept.endswith(".cdproj"), kept)
        self.assertTrue(self.wait(lambda: Path(kept).is_file()))
        self.assertTrue(any(p.endswith("-clean.png") for p in self.history()))   # 加工した絵そのものも履歴にある
        # 残した作業を履歴から選ぶと、加工したレイヤーごと戻る
        self.w.show_history_image(kept)
        self.assertTrue(self.wait(lambda: self.names() == work_names), self.names())
        self.assertEqual(self.w.canvas.layers[-1].name, "綺麗にした絵")

    def test_library_open_keeps_work_and_undo(self):
        before = self.names()
        self.press(lambda: self.w.finish_with("clean", background=True), lambda: len(self.w.canvas.layers) > len(before))
        work_names = self.names()
        other = self.d / "c.png"
        Image.new("RGB", (40, 60), (20, 20, 200)).save(other)
        hist = self.w.history.count()
        self.w.open_path(str(other))   # ライブラリーのダブルクリックと同じ入口
        self.assertEqual(self.w.history.count(), hist + 1)
        self.w.canvas.undo()   # 元に戻すでも戻せる
        self.assertEqual(self.names(), work_names)

    def test_no_duplicate_when_nothing_changed(self):
        self.w.canvas.place_result(str(self.src), "重ねた絵")
        hist = self.w.history.count()
        other = self.d / "b.png"
        Image.new("RGB", (40, 60), (200, 20, 20)).save(other)
        self.w.keep_work()
        self.w.keep_work()
        self.assertEqual(self.w.history.count(), hist + 1)
        self.w.show_history_image(str(other))   # 絵 1 枚と空のレイヤーだけなら残さない
        self.w.show_history_image(str(self.src))
        self.assertEqual(self.w.history.count(), hist + 1)


if __name__ == "__main__":
    unittest.main()
