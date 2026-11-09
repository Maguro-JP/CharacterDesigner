"""チャットの文の頼み（繰り返し・予約・書き出し・加工の並び）、登録した作風、参考画像の検索、画面の言語、プリセットの試験"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chatdraw import chatplan  # noqa: E402


def _store(d):
    return QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat)


class ParseTest(unittest.TestCase):
    def test_loop_and_keep(self):
        p = chatplan.parse("猫耳の少女を5枚描いて良いのを残して")
        self.assertEqual((p.body, p.steps, p.repeat, p.keep_best), ("猫耳の少女", ["draw"], 5, True))

    def test_repeat_capped(self):
        self.assertEqual(chatplan.parse("100回描いて").repeat, chatplan.MAX_REPEAT)

    def test_chain_in_written_order(self):
        p = chatplan.parse("この絵を2倍にしてから透過して")
        self.assertEqual(p.steps, ["upscale", "transparent"])
        self.assertEqual(p.body, "")

    def test_finisher_by_name(self):
        entries = [{"name": "face", "label": "顔を整える"}, {"name": "mat_gem", "label": "宝石"}]
        self.assertEqual(chatplan.parse("顔を整えて", entries).steps, ["finisher:face"])
        self.assertEqual(chatplan.parse("宝石を掛けて", entries).steps, ["finisher:mat_gem"])
        self.assertEqual(chatplan.parse("宝石を持つ少女を描いて", entries).steps, ["draw"])   # 名詞だけでは加工にしない
        self.assertEqual(chatplan.parse("1girl, facing viewer を描いて", entries).steps, ["draw"])

    def test_schedule(self):
        p = chatplan.parse("10分後に海辺の少女を描いて")
        self.assertEqual((p.after_min, p.body), (10, "海辺の少女"))
        self.assertEqual(chatplan.parse("1時間後に描いて").after_min, 60)
        p = chatplan.parse("毎晩 22時に 森の騎士を描いて「/tmp/x」に書き出して")
        self.assertEqual((p.daily, p.body, p.export), ((22, 0), "森の騎士", "/tmp/x"))
        self.assertEqual(chatplan.parse("毎朝描いて").daily, (8, 0))

    def test_fix_keeps_instruction(self):
        p = chatplan.parse("髪を赤く直して")
        self.assertEqual((p.steps, p.body), (["fix"], "髪を赤く"))

    def test_plain_request_is_not_special(self):
        for t in ("猫耳の少女を描いて", "ペンにして", "保存するには？", "もう一度描き直して", "ドット絵の騎士を描いて"):
            self.assertFalse(chatplan.parse(t).special, t)

    def test_next_daily(self):
        now = time.mktime((2026, 11, 6, 23, 0, 0, 0, 0, -1))
        t = chatplan.next_daily(22, 0, now=now)
        self.assertEqual(time.localtime(t).tm_mday, 7)


class SchedulerTest(unittest.TestCase):
    def test_add_fire_and_daily_repeat(self):
        QApplication.instance() or QApplication([])
        from chatdraw.scheduler import Scheduler
        with TemporaryDirectory() as d:
            clock = [1_000_000.0]
            s = Scheduler(_store(d), clock=lambda: clock[0])
            got = []
            s.fire.connect(got.append)
            s.add("海を描いて", after_min=10)
            s.add("森を描いて", daily=(21, 0))
            self.assertEqual(s.tick(), [])
            clock[0] += 601
            s.tick()
            self.assertEqual(got, ["海を描いて"])
            self.assertEqual(len(s.jobs()), 1)          # 一回きりは消え、毎日の物は残る
            clock[0] += 86400
            s.tick()
            self.assertIn("森を描いて", got)
            self.assertEqual(len(s.jobs()), 1)
            self.assertGreater(s.jobs()[0]["at"], clock[0])
            self.assertIn("毎日 21:00", s.summary())
            s.clear()
            self.assertEqual(s.summary(), "予約はありません")


class RefsTest(unittest.TestCase):
    def test_favorites(self):
        from chatdraw.refs import Favorites
        with TemporaryDirectory() as d:
            f = Favorites(_store(d))
            f.put("好きな水彩", "watercolor, soft colors")
            f.put("好きな水彩", "watercolor, pastel")   # 同じ名前は上書き
            self.assertEqual(len(f.all()), 1)
            text, hit = f.apply("好きな水彩で猫耳の少女")
            self.assertEqual(hit["name"], "好きな水彩")
            self.assertEqual(text, "猫耳の少女, watercolor, pastel")
            self.assertEqual(f.apply("森の騎士"), ("森の騎士", None))
            f.remove("好きな水彩")
            self.assertEqual(f.all(), [])

    def test_find_images(self):
        from PIL import Image
        from chatdraw.refs import find_images
        with TemporaryDirectory() as d:
            Image.new("RGB", (8, 8)).save(Path(d) / "beach_girl.png")
            Image.new("RGB", (8, 8)).save(Path(d) / "forest.png")
            (Path(d) / "forest.json").write_text('{"text": "森の騎士", "prompt": "knight, forest"}', encoding="utf-8")
            items = [{"path": "/x/a.png", "text": "海辺の少女", "prompt": "1girl, beach, ocean", "tags": []}]
            got = find_images("海 少女", items, [d])
            paths = [p for _s, p in got]
            self.assertIn("/x/a.png", paths)
            self.assertIn(str(Path(d) / "beach_girl.png"), paths)
            self.assertNotIn(str(Path(d) / "forest.png"), paths)
            self.assertEqual([p for _s, p in find_images("騎士", [], [d])], [str(Path(d) / "forest.png")])
            self.assertEqual(find_images("", items, [d]), [])

    def test_dialog_saves(self):
        QApplication.instance() or QApplication([])
        from chatdraw.refs import Favorites, FavoritesDialog
        with TemporaryDirectory() as d:
            used = []
            dlg = FavoritesDialog(Favorites(_store(d)), on_use=used.append)
            dlg.name.setText("厚塗りの作家")
            dlg.words.setText("painterly, rich lighting")
            dlg._save()
            self.assertEqual(dlg.list.count(), 1)
            dlg.list.setCurrentRow(0)
            dlg._use()
            self.assertEqual(used[0]["words"], "painterly, rich lighting")
            dlg._remove()
            self.assertEqual(dlg.list.count(), 0)


class LanguageTest(unittest.TestCase):
    def test_translate_menus(self):
        QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QMenu, QMenuBar
        from chatdraw import i18n
        bar = QMenuBar()
        f = QMenu("ファイル", bar)
        bar.addMenu(f)
        f.addAction("名前の無い項目")
        bar.addMenu("ヘルプ").addAction("使い方ツアー")
        self.assertEqual(i18n.translate_menus(bar, "日本語"), 0)
        self.assertEqual(i18n.translate_menus(bar, "English"), 3)
        self.assertEqual([a.text() for a in bar.actions()], ["File", "Help"])
        self.assertEqual(f.actions()[0].text(), "名前の無い項目")   # 表に無い言葉は日本語のまま
        self.assertEqual(i18n.t("設定", "English"), "Settings")

    def test_setting_exists(self):
        from chatdraw.settings import FIELDS
        self.assertIn("language", [f[0] for f in FIELDS])


class WordsTest(unittest.TestCase):
    def test_other_languages_are_translated(self):
        from chatdraw.engine import english_only, has_japanese
        self.assertTrue(has_japanese("고양이 소녀"))
        self.assertTrue(has_japanese("девочка"))
        self.assertFalse(has_japanese("café, girl"))
        self.assertEqual(english_only("고양이, cat girl"), "cat girl")

    def test_new_terms(self):
        from chatdraw.jaterms import tags_from
        self.assertIn("witch", tags_from("魔女の少女"))

    def test_presets_have_english_suffix(self):
        from chatdraw.aipanel import PRESETS, PROMPT_SUFFIX
        from chatdraw.engine import has_japanese
        names = [p[0] for p in PRESETS]
        self.assertGreaterEqual(len(names), 12)
        self.assertEqual(len(names), len(set(names)))
        for v in PROMPT_SUFFIX.values():
            self.assertFalse(has_japanese(v))
        # プリセットの名前が、チャットの加工の言い方と重ならない（「〜にして」で加工が動かない）
        for n in names:
            self.assertEqual([s for s in chatplan.parse(f"{n}にして").steps if s != "draw"], [], n)


class WindowPlanTest(unittest.TestCase):
    def _window(self):
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        app = QApplication.instance() or QApplication([])
        self.tmp = TemporaryDirectory()
        w = Window(Studio(FakeWords(), FakePainter(), Path(self.tmp.name)))
        return app, w

    def tearDown(self):
        from chatdraw.tests.test_chatdraw import sweep_windows
        sweep_windows()
        self.tmp.cleanup()

    def _settle(self, app, w, until, n=600):
        for _ in range(n):
            app.processEvents()
            if until():
                return True
            if w.thread:
                w.thread.wait(10)
            else:
                time.sleep(0.01)
        return False

    def test_export_from_chat(self):
        app, w = self._window()
        out = Path(self.tmp.name) / "export"
        w.chat_send(f"「{out}」に書き出して")
        self.assertTrue(self._settle(app, w, lambda: out.is_dir() and any(out.glob("*.png"))))

    def test_schedule_from_chat(self):
        app, w = self._window()
        w.scheduler.clear()
        try:
            w.chat_send("10分後に猫耳の少女を描いて")
            jobs = w.scheduler.jobs()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["text"], "猫耳の少女を描いて")
        finally:
            w.scheduler.clear()

    def test_loop_draws_n_times(self):
        app, w = self._window()
        n = len(w.images)
        w.chat_send("猫耳の少女を3回描いて")
        self.assertTrue(self._settle(app, w, lambda: len(w.images) >= n + 3 and not w._plan_queue, n=8000), len(w.images) - n)


if __name__ == "__main__":
    unittest.main()
