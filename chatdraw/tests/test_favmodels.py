"""模型のお気に入り（役目ごとの模型、chatdraw/favmodels.py）と、速い流れ・精度の流れの分かれ方の試験。

偽の模型で描き、役目ごとに選んだ模型がその役目で使われること、模型を 1 つ選んだときにほかの模型で上書きされないこと、
どちらの流れでも頼みに書かれていない言葉を模型に足さないことを見る。窓から押して保存し、お気に入りで描くことも見る。
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
from chatdraw.tests.test_omakase import BAD_HAND, COMPOSE, FACES, HANDS, OK, FakeStudio, checker, model  # noqa: E402

PLAIN = model("p/plain", "anime illustration")
TEXT = "剣を持った騎士の女の子"


class LogPainter:
    """描いた模型と、渡された言葉を残す偽の模型"""

    def __init__(self, repo, log):
        self.model, self.log, self.avoid, self.stop, self.upscale = repo, log, "", False, 1.5

    def paint(self, prompt, seed, size=None, **kw):
        self.log.append(("paint", self.model, prompt))
        return Image.new("RGB", size or (64, 64), (200, 200, 200))

    def redraw(self, prompt, seed, image, mask, strength=0.5, **kw):
        kind = "hires" if mask.getextrema() == (255, 255) else "redraw"
        self.log.append((kind, self.model, prompt))
        return Image.new("RGB", image.size, (10, 10, 10))


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def draw(self, have, results, **kw):
        log = []
        st = FakeStudio(Path(self.tmp.name))
        said = []
        omakase.draw(st, TEXT, 1, said.append, have=have, painter_for=lambda m: LogPainter(m.repo, log),
                     check=checker(results), size=(128, 192), **kw)
        return log, st, said

    def test_saved_roles_round_trip(self):
        favmodels.set_role("compose", HANDS.repo)
        favmodels.set_role("hand", FACES.repo)
        self.assertEqual(favmodels.load(), {"compose": HANDS.repo, "hand": FACES.repo})
        favmodels.set_role("hand", "")
        self.assertEqual(favmodels.load(), {"compose": HANDS.repo})
        with self.assertRaises(KeyError):
            favmodels.set_role("nope", "x")

    def test_each_role_uses_the_chosen_model(self):
        # おまかせなら構図は COMPOSE、手の直しは HANDS が選ばれる。お気に入りで、構図を PLAIN、手を FACES にする
        favmodels.set_role("compose", PLAIN.repo)
        favmodels.set_role("hand", FACES.repo)
        log, st, said = self.draw([COMPOSE, HANDS, FACES, PLAIN], [BAD_HAND, OK], mode=favmodels.FAV)
        self.assertEqual([(k, m) for k, m, _p in log if k != "hires"], [("paint", "p/plain"), ("redraw", "f/faces")])
        self.assertEqual(st.saved[1]["way"], "favorites")
        self.assertTrue(any("お気に入りを使う役目: 構図、手" in s for s in said))

    def test_background_role_composes_background_requests(self):
        favmodels.set_role("background", PLAIN.repo)
        log, _st, _ = self.draw([COMPOSE, HANDS, PLAIN], [OK], mode=favmodels.FAV)
        # 背景の無い頼みでは、背景のお気に入りで構図を描かない
        self.assertFalse(omakase.split(TEXT)["background"])
        self.assertEqual(log[0][:2], ("paint", "c/compose"))

    def test_missing_or_blocked_favorite_falls_back(self):
        favmodels.set_role("compose", "gone/model")
        log, _st, _ = self.draw([COMPOSE, HANDS], [OK], mode=favmodels.FAV)
        self.assertEqual(log[0][:2], ("paint", "c/compose"))

    def test_single_model_is_never_replaced(self):
        log, st, _ = self.draw([COMPOSE, HANDS, FACES], [BAD_HAND, OK], mode="single", single=FACES)
        self.assertEqual({m for _k, m, _p in log}, {"f/faces"})
        self.assertEqual(st.saved[1]["way"], "precise")

    def test_no_unasked_words_in_paint_prompt(self):
        favmodels.set_role("compose", PLAIN.repo)
        log, _st, _ = self.draw([COMPOSE, PLAIN], [OK], mode=favmodels.FAV)
        paints = [p for k, _m, p in log if k == "paint"]
        self.assertEqual(paints, ["tags: " + TEXT])   # 偽の言葉の模型の訳だけで、背景・構図・質の言葉を足さない

    def test_precise_or_fast(self):
        self.assertTrue(favmodels.precise("auto", "女の子"))
        self.assertTrue(favmodels.precise(favmodels.FAV, "女の子"))
        self.assertFalse(favmodels.precise("single", "女の子"))
        self.assertFalse(favmodels.precise("single", "女の子", "標準"))
        self.assertTrue(favmodels.precise("single", "女の子", "厚塗り"))
        self.assertTrue(favmodels.precise("single", "赤い髪、青い目、白い服、剣、夕方の街"))

    def test_omakase_two_stage_follows_planned_composer(self):
        # 2 段の構図は、段取りで選んだ構図の模型を使う（前は点の一番高い構図の模型に固定された）
        flux_a = model("a/flux", "anime illustration, strong prompt adherence", family="flux2", score=90)
        flux_b = model("b/flux", "anime illustration, strong prompt adherence, good hands", family="flux2", score=60)
        sdxl = model("s/sdxl", "anime")
        used = []
        st = FakeStudio(Path(self.tmp.name))
        st._two_stage_models = lambda *a, **k: (flux_a, sdxl)
        with mock.patch.object(omakase, "_compose_two", lambda studio, text, seed, two, size, say:
                               (used.append(two[0].repo), (Image.new("RGB", size), "tags"))[1]), \
                mock.patch.object(omakase, "explore", lambda ranked, seed: [r for r in ranked if r[0] is flux_b]
                                  + [r for r in ranked if r[0] is not flux_b]), \
                mock.patch("random.Random.random", lambda self: 0.0):
            omakase.draw(st, TEXT, 1, lambda m: None, have=[flux_a, flux_b, sdxl], painter_for=lambda m: LogPainter(m.repo, []),
                         check=checker([OK]), size=(128, 192))
        self.assertEqual(used, ["b/flux"])


class EngineFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def studio(self):
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        return Studio(FakeWords(), FakePainter(), Path(self.tmp.name))

    def test_single_short_request_is_one_fast_draw_without_two_stage(self):
        st = self.studio()
        st._two_stage_models = mock.Mock(side_effect=AssertionError("2 段に替えない"))
        with mock.patch("chatdraw.omakase.draw", side_effect=AssertionError("精度の流れに入らない")):
            st.draw("女の子", 3)
        self.assertEqual(len([c for c in st.painter.calls if c[0] != "redraw"]), 1)
        self.assertEqual(st.painter.calls[0][0], st.words.to_prompt("女の子"))   # 言葉の模型の訳のまま。言葉を足さない

    def test_detailed_or_preset_goes_precise_with_the_same_model(self):
        st = self.studio()
        with mock.patch("chatdraw.omakase.draw", return_value=("p", Path("x.png"))) as od:
            st.draw("赤い髪、青い目、白い服、剣、夕方の街", 3)
            self.assertEqual(od.call_args.kwargs["mode"], "single")
            st.draw("女の子", 3, meta={"preset": "厚塗り"})
            self.assertEqual(od.call_count, 2)

    def test_favorites_and_auto_go_precise(self):
        st = self.studio()
        st.use_favorites = True
        with mock.patch("chatdraw.omakase.draw", return_value=("p", Path("x.png"))) as od:
            st.draw("女の子", 3)
            self.assertEqual(od.call_args.kwargs["mode"], favmodels.FAV)
            st.use_favorites, st.image_auto = False, True
            st.draw("女の子", 3)
            self.assertEqual(od.call_args.kwargs["mode"], "auto")


class WindowTest(unittest.TestCase):
    """窓から役目ごとの模型を選んで保存し、絵の模型がお気に入りに替わることを見る"""

    def test_pick_roles_from_window(self):
        from chatdraw.tests.test_aitabs import app, window
        from chatdraw import favpanel
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            w = window(d)
            before = w.settings.get("image_model")
            self.addCleanup(lambda: w.settings.set("image_model", before))
            w.have_image_models = lambda: [COMPOSE, HANDS, FACES]
            shown = {}

            def fake_exec(dlg):
                dlg.boxes["compose"].setCurrentIndex(dlg.boxes["compose"].findData(HANDS.repo))
                dlg.boxes["face"].setCurrentIndex(dlg.boxes["face"].findData(FACES.repo))
                dlg.resize(420, dlg.sizeHint().height())
                shown["grab"] = dlg.grab()
                return True

            with mock.patch.object(favpanel.RoleModelsDialog, "exec", fake_exec), \
                    mock.patch.object(type(w), "_studio_from_settings", lambda self: self.studio):
                w.open_role_models()
            self.assertEqual(favmodels.load(), {"compose": HANDS.repo, "face": FACES.repo})
            self.assertEqual(w.settings.get("image_model"), favmodels.FAV)
            w._show_model()
            self.assertEqual(w.model_label.text(), "お気に入り（役目ごと）")
            self.assertIn("構図: h/hands", w.model_label.toolTip())
            out = os.environ.get("CD_SNAP_DIR")
            if out:   # 目で見るための写し
                shown["grab"].save(str(Path(out) / "roles-dialog.png"))
                w.resize(1400, 900)
                w.show()
                app().processEvents()
                w.ai_panel.grab().save(str(Path(out) / "aipanel-favorites.png"))
            w.close()


class ManagerSetsAndFilterTest(unittest.TestCase):
    """模型の管理の窓: 役目ごとの編成を作る・名前・直す・消す・切り替える。絞り込みに合わない物は取得済みでも ★ でも出さない"""

    def setUp(self):
        from chatdraw.tests.test_aitabs import app
        app()
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def manager(self, have=()):
        from PySide6.QtCore import QSettings
        from chatdraw import manager
        from chatdraw.settings import Settings
        st = Settings(QSettings(str(Path(self.tmp.name) / "s.ini"), QSettings.IniFormat))
        items = [manager.Item("image", m.name, Path(self.tmp.name) / m.name, 1.0, m.repo) for m in have]
        self.p = mock.patch.object(manager, "installed", lambda: list(items))
        self.p.start()
        self.addCleanup(self.p.stop)
        return manager.ModelManager(st), st

    def texts(self, dlg):
        from PySide6.QtWidgets import QLabel
        out = []   # 今の並びの部品だけを見る（作り直す前の部品は deleteLater で後から消える）
        for i in range(dlg.list.count()):
            w = dlg.list.itemAt(i).widget()
            if w is not None:
                out += [w.text()] if isinstance(w, QLabel) else [x.text() for x in w.findChildren(QLabel)]
        return out

    def test_filter_hides_installed_and_favorite_that_do_not_match(self):
        from chatdraw import ratings
        from chatdraw.models import catalog_images, style
        cat = catalog_images()
        real = [m for m in cat if style(m) == "real"]
        anime = [m for m in cat if style(m) == "anime"]
        self.assertTrue(real and anime)
        fav_real, have_real = real[0], real[-1]
        ratings.set_favorite(fav_real.repo, True)
        dlg, _st = self.manager(have=[have_real])
        dlg.filter.setCurrentText("アニメ・イラスト")
        from chatdraw.tests.test_aitabs import app
        app().processEvents()
        shown = " ".join(self.texts(dlg))
        self.assertNotIn(fav_real.name, shown)    # ★ でも、絞り込みに合わなければ出さない
        self.assertNotIn(have_real.name, shown)   # 取得済みでも出さない
        self.assertIn(anime[0].name, shown)
        dlg.filter.setCurrentText("取得済み")
        app().processEvents()
        self.assertIn(have_real.name, " ".join(self.texts(dlg)))
        out = os.environ.get("CD_SNAP_DIR")
        if out:
            dlg.filter.setCurrentText("アニメ・イラスト")
            dlg.resize(560, 700)
            dlg.show()
            app().processEvents()
            dlg.grab().save(str(Path(out) / "manager-filter-anime.png"))
        dlg.close()

    def test_make_rename_edit_switch_delete_sets(self):
        from chatdraw import favpanel
        from chatdraw.tests.test_aitabs import app
        dlg, st = self.manager()
        dlg._have_models = lambda: [COMPOSE, HANDS, FACES]
        picks = {}

        def fake_exec(d):
            for role, repo in picks.items():
                d.boxes[role].setCurrentIndex(d.boxes[role].findData(repo))
            return True
        with mock.patch.object(favpanel.RoleModelsDialog, "exec", fake_exec):
            picks.update(compose=HANDS.repo, face=FACES.repo)
            dlg.new_set("アニメの立ち絵")
            self.assertEqual(favmodels.active(), "アニメの立ち絵")
            self.assertEqual(favmodels.load(), {"compose": HANDS.repo, "face": FACES.repo})
            picks.clear()
            picks.update(compose=COMPOSE.repo, background=FACES.repo)
            dlg.new_set("背景つき")
            self.assertEqual(favmodels.sets(), [favmodels.DEFAULT_SET, "アニメの立ち絵", "背景つき"])
            # 窓の切り替えの欄で切り替える
            dlg.set_pick.setCurrentText("アニメの立ち絵")
            app().processEvents()
            self.assertEqual(favmodels.active(), "アニメの立ち絵")
            self.assertEqual(favmodels.load()["compose"], HANDS.repo)
            picks.clear()
            picks.update(hand=HANDS.repo)
            dlg.edit_set()
            self.assertEqual(favmodels.load(), {"compose": HANDS.repo, "face": FACES.repo, "hand": HANDS.repo})
        dlg.rename_set("立ち絵")
        self.assertIn("立ち絵", favmodels.sets())
        self.assertEqual(favmodels.active(), "立ち絵")
        dlg.set_use.click()
        self.assertEqual(st.get("image_model"), favmodels.FAV)
        self.assertIn("構図: h/hands", dlg.set_summary.text())
        out = os.environ.get("CD_SNAP_DIR")
        if out:
            dlg.resize(560, 700)
            dlg.show()
            app().processEvents()
            dlg.grab().save(str(Path(out) / "manager-sets.png"))
        dlg.delete_set(confirm=False)
        self.assertNotIn("立ち絵", favmodels.sets())
        dlg.close()

    def test_old_flat_file_reads_as_default_set(self):
        from chatdraw.paths import write_json
        write_json(favmodels.roles_file(), {"compose": "a/b"})
        self.assertEqual(favmodels.sets(), [favmodels.DEFAULT_SET])
        self.assertEqual(favmodels.load(), {"compose": "a/b"})


if __name__ == "__main__":
    unittest.main()
