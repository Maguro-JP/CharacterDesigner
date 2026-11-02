"""履歴とライブラリーの絵から、描いた設定（模型・頼み・禁止ワード・種・大きさ・日時）を見る入口の試験"""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image  # noqa: E402
from chatdraw import drawinfo, finishers  # noqa: E402
from chatdraw.tests.test_panels import done, fresh  # noqa: E402
from chatdraw.tests.test_uifix import app, draw, spin  # noqa: E402


def values(path):
    return dict(drawinfo.rows(path))


class RowsTest(unittest.TestCase):
    def test_embedded_record(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "20261102-153012-42.png"
            Image.new("RGB", (64, 96), "white").save(p)
            finishers.embed(p, {"model": "no/such-model", "prompt": "1girl, knight", "text": "騎士",
                                "negative": "lowres, hat", "seed": 42, "size": [832, 1216]})
            v = values(p)
            self.assertEqual(v["模型"], "no/such-model")
            self.assertEqual(v["頼み（模型に渡した言葉）"], "1girl, knight")
            self.assertEqual(v["禁止ワード"], "lowres, hat")
            self.assertEqual(v["種"], "42")
            self.assertEqual(v["大きさ"], "64 × 96")   # 絵の実際の大きさ
            self.assertEqual(v["描いた日時"], "2026-11-02 15:30:12")   # 名前から読む

    def test_old_json_and_missing(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "old.png"
            Image.new("RGB", (32, 32)).save(p)
            p.with_suffix(".json").write_text(json.dumps({"text": "猫", "seed": 0, "model": "x/y"}), encoding="utf-8")
            v = values(p)
            self.assertEqual(v["頼み（模型に渡した言葉）"], "猫")
            self.assertEqual(v["種"], "0")   # 0 の種を「記録なし」にしない
            self.assertEqual(v["禁止ワード"], drawinfo.MISSING)
            self.assertEqual(v["描いた日時"], drawinfo.MISSING)
            q = Path(d) / "none.png"
            Image.new("RGB", (8, 8)).save(q)
            v = values(q)
            for k in ("模型", "頼み（模型に渡した言葉）", "禁止ワード", "種", "描いた日時"):
                self.assertEqual(v[k], drawinfo.MISSING, k)
            self.assertEqual([k for k, _ in drawinfo.rows(q)], list(drawinfo.LABELS))

    def test_two_stage_model(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "a.png"
            Image.new("RGB", (8, 8)).save(p)
            finishers.embed(p, {"model": "r/render", "compose_model": "c/comp"})
            self.assertEqual(values(p)["模型"], "構図: c/comp / 仕上げ: r/render")


class MenuTest(unittest.TestCase):
    def test_history_and_library_open_info(self):
        from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            draw(w)   # 本物と同じ経路（Studio._save）で描いて保存した絵
            path = w.history.item(0).data(0x0100)
            meta = finishers.embedded(path)
            self.assertIn("drawn", meta)   # 描いた日時を絵に埋めた
            lib = w.library_panel.works
            menus = [w._history_menu(w.history.visualItemRect(w.history.item(0)).center(), run=False),
                     w.library_panel._menu(lib, lib.visualItemRect(lib.item(0)).center(), run=False)]
            for m in menus:
                act = next(a for a in m.actions() if a.text() == "描いた設定を見る…")
                act.trigger()
                spin()
                dlg = w._draw_info
                box = dlg.findChild(QPlainTextEdit)
                text = box.toPlainText()
                self.assertIn("模型: ", text)
                self.assertIn("種: " + str(meta["seed"]), text)
                self.assertIn("描いた日時: " + meta["drawn"], text)
                self.assertTrue(box.isReadOnly())
                next(b for b in dlg.findChildren(QPushButton) if b.text() == "コピー").click()
                self.assertEqual(QApplication.clipboard().text(), text)
                dlg.close()
            app()
            done(w)


if __name__ == "__main__":
    unittest.main()
