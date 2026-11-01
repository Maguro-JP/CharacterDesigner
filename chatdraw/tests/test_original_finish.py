"""このリポジトリで作ってきた仕上げ（tools/gen の retouch・inking・atmosphere・materials）と、
キャラクターデザインの流れ（設定資料集・三面図・表情差分）を、アプリから使えるか。絵の模型は偽物に替えて流れだけを確かめる"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from chatdraw import finishers, omakase  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402

SCIPY = importlib.util.find_spec("scipy") is not None
SKIMAGE = importlib.util.find_spec("skimage") is not None


def figure(size=(160, 200), specks=True) -> Image.Image:
    """白い地に主線の人型と、線から離れた黒い粒（AI の描き残しに当たる崩れ）"""
    im = Image.new("RGB", size, (250, 248, 245))
    d = ImageDraw.Draw(im)
    d.ellipse((50, 20, 110, 80), fill=(240, 205, 180), outline=(20, 20, 20), width=3)
    d.rectangle((45, 85, 115, 180), fill=(90, 120, 200), outline=(20, 20, 20), width=3)
    if specks:
        for x, y in ((15, 20), (140, 30), (20, 150), (140, 170), (12, 100)):
            d.ellipse((x, y, x + 3, y + 3), fill=(10, 10, 10))
    return im


def box_mask(size, box) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle(box, fill=255)
    return m


def outside_same(a, b, mask) -> bool:
    keep = Image.new("RGB", a.size)
    inv = mask.point(lambda v: 0 if v >= 128 else 255)
    return ImageChops.difference(Image.composite(a, keep, inv), Image.composite(b, keep, inv)).getbbox() is None


class OwnFinishers(unittest.TestCase):
    def test_registered_with_tooltips(self):
        names = {f["name"] for f in finishers.available()}
        for n in ("retouch", "retouch_full", "ink", "air_holy", "air_komorebi", "air_haze", "mat_metal", "mat_gem", "mat_slime"):
            self.assertIn(n, names)
            f = finishers.REGISTRY[n]
            self.assertTrue(f.tip and f.label)
            self.assertNotIn(f.tip, f.label)   # 説明はボタンの中に書かず、ツールチップに出す

    def test_auto_finish_only_shape_keeping(self):
        self.assertIn("retouch", omakase.AUTO_FINISH)
        for n in ("retouch_full", "ink", "air_holy", "mat_metal"):   # 形や見た目を変えうる物はおまかせで掛けない
            self.assertNotIn(n, omakase.AUTO_FINISH)
        self.assertEqual(omakase.auto_finish([dict(name="retouch", ready=True), dict(name="ink", ready=True)]), ["retouch"])
        self.assertNotIn("deburr", finishers.RETOUCH_SAFE)   # 顔の細い線に掛かりうる工程はおまかせに入れない
        self.assertIn("sharpen", finishers.RETOUCH_SAFE)

    @unittest.skipUnless(SCIPY, "scipy が無い")
    def test_repair_returns_only_new_flaw_pixels(self):
        import numpy as np
        a = np.asarray(figure(specks=False)).astype(float)
        b = a.copy()
        b[150:153, 10:13] = 5      # 直しで出来た黒い粒（崩れ）
        b[100:110, 60:70] += 3     # 直しで良くした所（崩れではない）
        out = finishers.repair(a, b)
        self.assertTrue((out[150:153, 10:13] == a[150:153, 10:13]).all())   # 崩れの所だけ元に戻す
        self.assertTrue((out[100:110, 60:70] == b[100:110, 60:70]).all())   # ほかの直しは残す
        self.assertLessEqual(finishers.flaws(out), finishers.flaws(a))

    def test_missing_script_reports_reason(self):
        with TemporaryDirectory() as d, mock.patch.object(finishers, "_gen_dir", lambda: Path(d)):
            row = next(f for f in finishers.available() if f["name"] == "retouch")
            self.assertFalse(row["ready"])
            self.assertIn("retouch.py", row["reason"])
            with self.assertRaises(finishers.Unavailable):
                finishers.run("retouch", figure())

    @unittest.skipUnless(SCIPY, "scipy が無い")
    def test_retouch_removes_specks_without_new_flaws(self):
        im = figure()
        a = __import__("numpy").asarray(im).astype(float)
        out = finishers.run("retouch", im)
        b = __import__("numpy").asarray(out).astype(float)
        self.assertEqual(out.size, im.size)
        self.assertLessEqual(finishers.flaws(b), finishers.flaws(a))
        rt = finishers._gen("retouch")
        self.assertLess(rt.specks(b), rt.specks(a))   # 線から離れた黒い粒が減った
        self.assertEqual(rt.line_broken(a, b), "")     # 主線は切れていない
        self.assertTrue(finishers.LAST_REPORT["steps"])

    @unittest.skipUnless(SCIPY, "scipy が無い")
    def test_mask_keeps_outside_for_every_own_tool(self):
        im = figure()
        mask = box_mask(im.size, (40, 15, 120, 90))
        names = ["retouch", "air_holy", "air_haze", "mat_metal", "mat_gem"] + (["retouch_full", "ink"] if SKIMAGE else [])
        for n in names:
            out = finishers.run(n, im, mask)
            self.assertEqual(out.size, im.size, n)
            self.assertTrue(outside_same(im, out, mask), n)   # 囲みの外は 1 画素も変えない

    def test_atmosphere_changes_look(self):
        im = figure(specks=False)
        out = finishers.run("air_holy", im)
        self.assertIsNotNone(ImageChops.difference(im, out).getbbox())


class CharaDesign(unittest.TestCase):
    def test_save_turnaround_expressions_sheet(self):
        from chatdraw import charadesign
        with TemporaryDirectory() as d:
            c = charadesign.save_character("Akari", "1girl, red hair, green eyes", figure(), outfit="school uniform", home=d)
            self.assertEqual(c["id"], "akari")
            self.assertTrue((Path(d) / c["images"]["color"]).exists())
            self.assertTrue(c["palette"])
            self.assertEqual(charadesign.slug("Akari", home=d), "akari-2")   # 同じ名前でも上書きしない
            self.assertEqual([x["id"] for x in charadesign.characters(home=d)], ["akari"])
            plan = charadesign.turnaround_plan("akari", home=d)
            self.assertEqual([p["view"] for p in plan], ["front", "side", "back"])
            self.assertTrue(all("red hair" in p["prompt"] and "school uniform" in p["prompt"] for p in plan))
            self.assertIn("back view", plan[2]["prompt"])
            painter = FakePainter()
            turn = charadesign.draw_turnaround(painter, "akari", 3, home=d)
            self.assertEqual(set(turn), {"front", "side", "back"})
            base = figure()
            mask = charadesign.face_mask(base, [(50, 20, 110, 80)])
            seen = []
            orig = painter.redraw

            def redraw(prompt, seed, image, m, **kw):
                seen.append(prompt)
                return orig(prompt, seed, image, m, **kw)
            painter.redraw = redraw
            expr = charadesign.draw_expressions(painter, "akari", base, mask, 0, ["smile", "angry"], home=d)
            self.assertEqual(set(expr), {"smile", "angry"})
            self.assertTrue(any("smile" in p for p in seen) and any("angry" in p for p in seen))
            from chatdraw.charadesign import bible
            for rel in expr.values():   # 表情差分は顔の囲みの外を変えない（保存は JPEG なので、元の絵と同じ縮め方で比べる）
                got = Image.open(Path(d) / rel).convert("RGB")
                self.assertEqual(got.size, base.size)
            with self.assertRaises(charadesign.NotReady):
                charadesign.draw_expressions(painter, "akari", base, Image.new("L", base.size, 0), home=d)
            sheet = charadesign.write_sheet("akari", home=d)
            html = sheet.read_text(encoding="utf-8")
            self.assertIn("Akari", html)
            self.assertGreaterEqual(html.count("<img"), 6)   # 色の手本・三面図 3 枚・表情 2 枚
            self.assertTrue(bible(home=d).BIBLE.is_relative_to(Path(d)))   # リポジトリの bible/ には書かない

    def test_expressions_keep_outside_face(self):
        from chatdraw import charadesign
        from chatdraw.finishers import keep_outside
        base = figure()
        mask = charadesign.face_mask(base, [(50, 20, 110, 80)])
        res = FakePainter().redraw("smile", 1, base, mask)
        self.assertTrue(outside_same(base, keep_outside(base, res, mask), mask))

    def test_needs_painter(self):
        from chatdraw import charadesign
        with TemporaryDirectory() as d:
            charadesign.save_character("b", "1boy", figure(), home=d)
            with self.assertRaises(charadesign.NotReady):
                charadesign.draw_turnaround(None, "b", home=d)


@unittest.skipUnless(importlib.util.find_spec("PySide6") is not None, "PySide6 が無い")
class CharaMenu(unittest.TestCase):
    def test_menu_and_save(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        QApplication.instance() or QApplication([])
        with TemporaryDirectory() as d, mock.patch("chatdraw.paths.HOME", Path(d)):
            w = Window(Studio(FakeWords(), FakePainter(), Path(d) / "out"))
            titles = [a.text() for a in w.menuBar().actions()]
            self.assertIn("キャラクターデザイン", titles)
            w._fill_chara_menu()
            acts = {a.text(): a for a in w.chara_menu.actions()}
            self.assertIn("描いた人物を設定資料に保存…", acts)
            self.assertFalse(acts["三面図を描く"].isEnabled())   # 保存した人物が無いうちは押せない
            self.assertTrue(all(a.toolTip() for a in acts.values() if a.text()))
            w.last_text = "red hair girl"
            ident = w.chara_save("Hana")
            self.assertEqual(ident, "hana")
            self.assertTrue((Path(d) / "bible" / "characters" / "hana.json").exists())
            w._fill_chara_menu()
            acts = {a.text(): a for a in w.chara_menu.actions()}
            self.assertTrue(acts["三面図を描く"].isEnabled())
            w.close()


if __name__ == "__main__":
    unittest.main()
