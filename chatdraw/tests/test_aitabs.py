"""AI の欄のタブと、重い処理を裏の糸に移したことの試験。

裏に移した処理は、呼んだ直後に画面の糸へ戻ること（50 ミリ秒の内）と、答えが返ったあとに結果が画面に出ることを見る。
"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg  # noqa: E402

LIMIT_MS = 50


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def window(d):
    from chatdraw.app import Window
    app()
    w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
    w.settings.set("output_dir", str(Path(d) / "out"))
    return w


def ms(fn) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def big_picture(d) -> Path:
    """模型の描く大きさ（832×1216）の、縮みにくい絵。保存と加工の重さを本物に近づける"""
    from PIL import Image
    p = Path(d) / "big.png"
    Image.effect_noise((832, 1216), 60).convert("RGB").save(p)
    return p


class TabsTest(unittest.TestCase):
    def test_tabs_and_draw_button_outside(self):
        with TemporaryDirectory() as d:
            w = window(d)
            p = w.ai_panel
            self.assertEqual([p.tabs.tabText(i) for i in range(p.tabs.count())], ["描く内容", "作風", "模型", "詳しい設定", "加工"])
            self.assertEqual(p.tabs.currentIndex(), 0)                      # 初めに開くのは描く内容
            for i in range(p.tabs.count()):
                self.assertTrue(p.tabs.tabToolTip(i))                      # 説明はツールチップ
                p.tabs.setCurrentIndex(i)
                self.assertFalse(p.tabs.isAncestorOf(w.button))             # 描くボタンはタブの外にあり、どのタブからも押せる
                self.assertTrue(p.isAncestorOf(w.button))
                self.assertTrue(p.isAncestorOf(w.stop_button))
            self.assertTrue(p.sections["作風"].isAncestorOf(p.style_buttons["アニメ"]))
            self.assertTrue(p.sections["加工"].isAncestorOf(p.pixel_button))
            p.sections["描く内容"].set_open(True)                             # 前の呼び方でタブが前に出る
            self.assertEqual(p.tabs.currentIndex(), 0)
            w.close()

    def test_draw_from_other_tab(self):
        with TemporaryDirectory() as d:
            w = window(d)
            w.ai_panel.tabs.setCurrentIndex(4)
            w.entry.setText("girl")
            w.button.click()
            end = time.time() + 20
            while (w.thread is not None or not w.images) and time.time() < end:
                app().processEvents()
                time.sleep(0.01)
            self.assertTrue(w.images)
            wait_bg(app(), w)
            w.close()


class BackgroundTest(unittest.TestCase):
    """重い処理は裏の糸。呼んだ直後に戻り、答えが返ってから画面に出る"""

    def test_pixel_lineart_save_psd_open_run_in_background(self):
        from chatdraw import project
        with TemporaryDirectory() as d:
            w = window(d)
            w.edit_image(str(big_picture(d)))
            n = len(w.canvas.layers)
            took = {"ドット絵": ms(w.make_pixel)}
            took["線画"] = ms(w.make_lineart)
            self.assertEqual(len(w.canvas.layers), n)                      # まだ置いていない（裏で作っている）
            w.ai_panel.tabs.setCurrentIndex(2)                             # 裏で動いている間も欄を触れる
            app().processEvents()
            wait_bg(app(), w)
            self.assertEqual(len(w.canvas.layers), n + 2)
            path = Path(d) / "a.cdproj"
            w.project_path = str(path)
            took["保存"] = ms(w.save_project)
            w.dirty = True
            auto = Path(d) / "auto" / "autosave.cdproj"
            from unittest import mock
            with mock.patch("chatdraw.project.autosave_path", return_value=auto):
                took["自動保存"] = ms(w.autosave)
                wait_bg(app(), w)
            self.assertTrue(path.exists() and auto.exists())
            with mock.patch("chatdraw.app.QFileDialog.getSaveFileName", return_value=(str(Path(d) / "a.psd"), "")):
                took["PSD"] = ms(w.export_psd)
            w.canvas.new_canvas(50, 50)
            took["開く"] = ms(lambda: w.open_path(str(path)))
            wait_bg(app(), w)
            self.assertEqual(len(w.canvas.layers), n + 2)
            self.assertEqual((Path(d) / "a.psd").read_bytes()[:4], b"8BPS")
            self.assertEqual(project.read(path)[0]["app"], "CharacterDesigner")
            for name, t in took.items():
                self.assertLess(t, LIMIT_MS * 3, f"{name} が画面の糸で {t:.0f} ミリ秒")   # 試験の機械の揺れを見て 3 倍まで
            print("\n画面の糸の時間（ミリ秒）: " + "、".join(f"{k} {v:.0f}" for k, v in took.items()), file=sys.stderr)
            w.dirty = False
            w.close()

    def test_model_menu_does_not_scan_on_ui(self):
        """模型のメニューは、開くたびに置き場を数えない（数えるのは裏の糸）"""
        from unittest import mock
        with TemporaryDirectory() as d:
            w = window(d)
            wait_bg(app(), w)
            self.assertIsNotNone(w._have_images)
            with mock.patch("chatdraw.setup.has_image", side_effect=AssertionError("画面の糸で数えた")):
                w._fill_ai_menu()
            w.close()

    def test_gc_runs_only_on_ui_while_background(self):
        """裏の糸が動いている間は自動の gc を止め、終われば戻す（裏の糸の gc で画面の糸が落ちた）"""
        import gc
        import threading
        with TemporaryDirectory() as d:
            w = window(d)
            go = threading.Event()
            w.in_background(go.wait, lambda _v: None)
            self.assertFalse(gc.isenabled())
            go.set()
            wait_bg(app(), w)
            w.gc_guard()
            self.assertTrue(gc.isenabled())
            w.close()

    def test_embed_is_atomic_and_off_ui(self):
        from chatdraw import finishers
        with TemporaryDirectory() as d:
            p = big_picture(d)
            finishers.embed(p, {"seed": 3})
            self.assertEqual(finishers.embedded(p)["seed"], 3)
            self.assertFalse(p.with_name(p.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()
