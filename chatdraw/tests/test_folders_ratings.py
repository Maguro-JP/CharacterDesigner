"""ディレクトリを開くメニュー、模型の点（目録と自分の点）とタグの絞り込み、自分の点とタグの保存"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))


class FakeSettings:
    def __init__(self, out):
        self.out = out

    def get(self, key):
        return str(self.out) if key == "output_dir" else ""


class FoldersTest(unittest.TestCase):
    def test_menu_opens_each_folder_and_creates_missing(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QApplication, QMenu
        from chatdraw import folders, paths
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d, mock.patch.object(paths, "HOME", Path(d) / "data"), \
                mock.patch.object(paths, "LLM_HOME", Path(d) / "LLM"), \
                mock.patch.dict(os.environ, {"CD_HOME": str(Path(d) / "data")}), \
                mock.patch.object(QDesktopServices, "openUrl", return_value=True) as opened:
            menu = QMenu()
            folders.fill_menu(menu, FakeSettings(Path(d) / "pics"))
            self.assertEqual([a.text() for a in menu.actions()],
                             ["描いた絵", "自動保存の作業ファイル", "模型の置き場", "手で置く模型", "資料", "設定と記録"])
            want = [Path(d) / "pics", Path(d) / "data" / "autosave", Path(d) / "LLM", Path(d) / "LLM" / "manual",
                    Path(d) / "data" / "library", Path(d) / "data"]
            self.assertFalse((Path(d) / "pics").exists())
            for a, p in zip(menu.actions(), want):
                a.trigger()
                self.assertTrue(p.is_dir(), p)                                       # 無ければ作ってから開く
                self.assertEqual(Path(opened.call_args[0][0].toLocalFile()), p)
            self.assertEqual(opened.call_count, 6)


class RatingsTest(unittest.TestCase):
    def test_combine_sort_tags_and_persist(self):
        from chatdraw import models, ratings
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}):
            a = models.ImageModel("a/a", "A", "", "", 1, 20, 5, score=85, tags=("アニメ", "商用可"))
            b = models.ImageModel("b/b", "B", "", "", 1, 20, 5, score=0, tags=("リアル",))
            c = models.ImageModel("c/c", "C", "", "", 1, 20, 5, score=50, tags=("アニメ",))
            self.assertEqual(ratings.rating_text(b), "未確認")
            self.assertEqual(ratings.rating_text(a), "85 点")
            self.assertEqual([m.name for m in sorted([b, c, a], key=ratings.sort_key)], ["A", "C", "B"])
            ratings.set_user_rating("b/b", 95)                                      # 自分の点が目録の点より先
            self.assertEqual(ratings.rating(b), 95)
            self.assertEqual([m.name for m in sorted([b, c, a], key=ratings.sort_key)], ["B", "A", "C"])
            ratings.set_user_tags("c/c", ["厚塗り", " ", "厚塗り"])
            self.assertEqual(ratings.tags(c), ["アニメ", "厚塗り"])
            self.assertTrue((Path(d) / "model_prefs.json").exists())                # ファイルに残る
            self.assertEqual(ratings.user_rating("b/b"), 95)
            self.assertEqual(ratings.user_tags("c/c"), ["厚塗り"])
            self.assertEqual([m.name for m in models.pick([a, b, c], tags=["アニメ"])], ["A", "C"])
            self.assertEqual([m.name for m in models.pick([a, b, c], tags=["アニメ", "厚塗り"])], ["C"])
            ratings.set_user_rating("b/b", 0)                                       # 0 で目録の点に戻す
            self.assertEqual(ratings.rating_text(b), "未確認")

    def test_catalog_has_tags_and_default_sort_is_rating(self):
        from chatdraw import models
        self.assertTrue(all(m.tags for m in models.IMAGES))
        self.assertEqual(next(iter(models.SORTS)), "点の高い順")

    def test_manager_tag_filter_and_rating_row(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication, QInputDialog, QLabel
        from chatdraw import manager, models
        from chatdraw.settings import Settings
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}), \
                mock.patch.object(manager, "HUB", Path(d) / "hub"), mock.patch.object(manager, "GGUF", Path(d) / "g"), \
                mock.patch.object(manager, "OWN_LLM", Path(d) / "none"):
            dlg = manager.ModelManager(Settings(QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat)))

            def cards():
                return [w for w in (dlg.list.itemAt(i).widget() for i in range(dlg.list.count()))
                        if w and w.objectName() == "card" and "Hugging Face:" in w.toolTip()]

            def title(c):
                return c.findChildren(QLabel)[0].text()
            self.assertEqual(title(cards()[0]), max(models.IMAGES, key=lambda m: m.score).name)   # 既定は点の高い順
            dlg.set_tags(["GPU向き"])
            self.assertEqual(len(cards()), len([m for m in models.IMAGES if "GPU向き" in m.tags]))
            dlg.set_tags([])
            m = next(x for x in models.IMAGES if x.score == 0)
            with mock.patch.object(QInputDialog, "getInt", return_value=(99, True)):
                dlg.ask_rating(m)
            self.assertEqual(title(cards()[0]), m.name)
            self.assertIn("99 点", " ".join(lb.text() for lb in cards()[0].findChildren(QLabel)))
            with mock.patch.object(QInputDialog, "getText", return_value=("好き、細い線", True)):
                dlg.ask_tags(m)
            dlg.set_tags(["好き"])
            self.assertEqual([title(c) for c in cards()], [m.name])


if __name__ == "__main__":
    unittest.main()
