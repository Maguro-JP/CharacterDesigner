"""描く経路の質を下げていた所と、模型の構成の取り違えの試験。

- SDXL は学んだ大きさ（約 100 万画素）で描く。小さく頼むと描く仕組みが学んだ大きさに戻して描いてから縮めるので、
  縮めて広げ直す段（hires）は描いた細部を捨てるだけだった。仕上がりの大きさで 1 回描くことを見る
- 2 段で描くときは、構図の模型を同じ処理で読まない（2 段は別の処理で模型を読む）
- 「構図と仕上げを分けて描く」をお気に入りで選んだときは、構図と仕上げのお気に入りで描く
- 模型の管理の窓で編成を作って切り替え、使うを押すと、お気に入りの編成で描く設定になる（offscreen の窓で押す）
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image  # noqa: E402

from chatdraw import favmodels, omakase  # noqa: E402
from chatdraw.tests.test_omakase import OK, FakePainter, FakeStudio, checker, model  # noqa: E402


class SizeTest(unittest.TestCase):
    def test_sdxl_does_not_draw_small(self):
        m = model("s/sdxl", family="sdxl")
        small, full = omakase.small_size((832, 1216), m)
        self.assertFalse(omakase.draws_small(small, full, m))

    def test_sd15_still_draws_small(self):
        m = model("s/sd15", family="sd15")
        small, full = omakase.small_size((832, 1216), m)
        self.assertTrue(omakase.draws_small(small, full, m))


class HiresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_sdxl_paints_once_at_full_size(self):
        log = []
        m = model("c/compose", "anime illustration", family="sdxl")
        st = FakeStudio(Path(self.tmp.name))
        omakase.draw(st, "騎士の女の子", 1, lambda s: None, have=[m], painter_for=lambda x: FakePainter(x.repo, log),
                     check=checker([OK]), size=(832, 1216))
        self.assertEqual(log[0], ("paint", "c/compose", (832, 1216)))
        self.assertNotIn("hires", [e[0] for e in log])
        self.assertEqual(st.saved[0].size, (832, 1216))

    def test_two_stage_does_not_load_compose_model_in_process(self):
        flux = model("a/flux", "anime illustration, strong prompt adherence", family="flux2", score=90)
        sdxl = model("s/sdxl", "anime")
        loaded = []
        st = FakeStudio(Path(self.tmp.name))
        st._two_stage_models = lambda *a, **k: (flux, sdxl)
        with mock.patch.object(omakase, "_compose_two", lambda studio, text, seed, two, size, say: (Image.new("RGB", size), "tags")), \
                mock.patch("random.Random.random", lambda self: 0.0):
            omakase.draw(st, "騎士の女の子", 1, lambda s: None, have=[flux, sdxl],
                         painter_for=lambda x: (loaded.append(x.repo), FakePainter(x.repo, []))[1],
                         check=checker([OK]), size=(128, 192))
        self.assertNotIn("a/flux", loaded)


class TwoWayFavoritesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_two_way_uses_favorite_compose_and_finish(self):
        from chatdraw import twostage
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter as P, FakeWords
        top = model("t/top", family="flux2", score=95)
        mine = model("m/mine", family="flux2", score=10)
        fin = model("f/fin", family="sdxl", score=10)
        other = model("o/other", family="sdxl", score=90)
        favmodels.set_role("compose", mine.repo)
        favmodels.set_role("finish", fin.repo)
        st = Studio(FakeWords(), P(), Path(self.tmp.name))
        st.way, st.use_favorites, st.image_auto = "two", True, False
        with mock.patch("chatdraw.choose.installed_images", lambda: [top, mine, fin, other]), \
                mock.patch.object(twostage, "parts_ready", lambda: True):
            two = st._two_stage_models(None, None)
        self.assertEqual((two[0].repo, two[1].repo), ("m/mine", "f/fin"))


class ManagerSetsWindowTest(unittest.TestCase):
    """模型の管理の窓で、編成を作る・切り替える・使うを押す"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_make_switch_and_use_set(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 が無い")
        from chatdraw import manager
        app = QApplication.instance() or QApplication([])
        a = model("a/a", family="sdxl")
        b = model("b/b", family="sdxl")

        class Settings(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)

            def set(self, k, v):
                self[k] = v
        settings = Settings(image_model="x")
        favmodels.save_set("立ち絵", {"compose": a.repo}, use=True)
        favmodels.save_set("背景", {"compose": b.repo, "background": b.repo}, use=False)
        win = manager.ModelManager.__new__(manager.ModelManager)
        from PySide6.QtWidgets import QDialog, QLabel
        QDialog.__init__(win)
        win.settings, win.status = settings, QLabel()
        win._changed = lambda: None
        box = win._sets_row()
        self.assertEqual(win.set_pick.currentText(), "立ち絵")
        win.set_pick.setCurrentText("背景")   # 切り替え
        self.assertEqual(favmodels.active(), "背景")
        self.assertEqual(favmodels.load(), {"compose": b.repo, "background": b.repo})
        win.set_use.click()
        self.assertEqual(settings["image_model"], favmodels.FAV)
        box.deleteLater()
        app.processEvents()


class BodyRoleTest(unittest.TestCase):
    """手・足・体は「身体」の 1 つの役目。手だけ選んで、足が別の模型で直されることがない"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_every_fix_kind_has_a_listed_role(self):
        for kind, role in favmodels.KIND_ROLE.items():
            self.assertIn(role, favmodels.ROLES, kind)
        self.assertEqual(favmodels.KIND_ROLE["hand"], favmodels.KIND_ROLE["foot"])

    def test_old_hand_favorite_reads_as_body(self):
        from chatdraw.paths import write_json
        write_json(favmodels.roles_file(), {"active": "標準", "sets": {"標準": {"hand": "h/h"}}})
        self.assertEqual(favmodels.load(), {"body": "h/h"})

    def test_body_favorite_fixes_hands_and_feet(self):
        mine = model("m/mine", family="sdxl", score=1)
        other = model("o/other", "good hands and anatomy", family="sdxl", score=99)
        favmodels.set_role("body", mine.repo)
        p = omakase.plan("騎士", [mine, other])
        favmodels.apply(p, [mine, other])
        for kind in ("hand", "foot"):
            if kind in p.fix:
                self.assertEqual(p.fix[kind][0][0].repo, "m/mine", kind)


class SetsMenuTest(unittest.TestCase):
    """編成のメニューは模型の選択と別。編成した物は模型の選択に 1 つずつ出て、押すとその編成で描く"""

    def test_sets_listed_in_model_choice_and_menu_is_separate(self):
        from chatdraw.tests.test_aitabs import window
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            w = window(d)
            favmodels.save_set("立ち絵", {"compose": "a/a"}, use=False)
            favmodels.save_set("背景", {"background": "b/b"}, use=False)
            w._fill_ai_menu()
            acts = {a.text(): a for a in w.ai_menu.actions()}
            self.assertIn("編成: 立ち絵", acts)
            self.assertIn("編成: 背景", acts)
            self.assertNotIn("お気に入り（役目ごと）", acts)
            sub = acts["模型の編成"].menu()
            self.assertEqual([a.text() for a in sub.actions()],
                             ["編成を作る…", "今の編成を直す…", "今の編成の名前を変える…", "今の編成を消す…"])
            with mock.patch.object(type(w), "_studio_from_settings", lambda self: self.studio):
                acts["編成: 背景"].trigger()
            self.assertEqual(favmodels.active(), "背景")
            self.assertEqual(w.settings.get("image_model"), favmodels.FAV)
            self.assertEqual(w.model_label.text(), "編成: 背景")
            checked = [a.text() for a in w.ai_menu.actions() if a.isCheckable() and a.isChecked()]
            self.assertEqual(checked, ["編成: 背景"])
            w.close()


if __name__ == "__main__":
    unittest.main()
