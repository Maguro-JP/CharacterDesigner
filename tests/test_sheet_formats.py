"""設定画集の版（styles/sheet-formats/*.json）とテーマ（styles/sheet-themes/*.json）が読めること、
版とテーマを組み合わせて出せること、印の無い区画からはみ出さないこと、中身の無い区画を作らないこと、
各版が魅せる手（端で切る・重ねる・顔の大写し・名前の上に人物）を少なくとも1つ使うこと"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import charsheet  # noqa: E402

# 書き出しは Chromium（Playwright）で行う。入っていない環境では書き出しの試験だけを飛ばす
needs_browser = unittest.skipIf(importlib.util.find_spec("playwright") is None, "playwright が無い")

NAMES = [p.stem for p in sorted((ROOT / "styles" / "sheet-formats").glob("*.json"))]
THEMES = [p.stem for p in sorted((ROOT / "styles" / "sheet-themes").glob("*.json"))]


class SheetFormatsTest(unittest.TestCase):
    def _inside(self, r):
        W, H = r["size"]
        for _, _, d, free in r["drawn"]:
            if free:   # bleed / overlap の印のある区画は、端で切れたり隣に重なったりしてよい
                continue
            self.assertTrue(d[0] >= 0 and d[1] >= 0 and d[2] <= W and d[3] <= H, d)

    def test_formats_list_has_one_default(self):
        fs = charsheet.formats()
        self.assertGreaterEqual(len(fs), 5)
        self.assertEqual(sum(f["default"] for f in fs), 1)
        self.assertEqual(fs[0]["name"], "classic")

    def test_format_grid_is_12_columns(self):
        for name in NAMES:
            with self.subTest(name=name):
                fm = charsheet.load_format(name)
                self.assertTrue(fm["name"] == name and fm["purpose"] and fm["ratio"])
                rows = [r.split() for r in fm["areas"]]
                self.assertTrue(all(len(r) == 12 for r in rows) and len(fm["rows"]) == len(rows))
                named = {a for r in rows for a in r}
                for pn in fm["panels"]:
                    self.assertIn(pn["area"], named, pn)

    @needs_browser
    def test_sample_renders_without_overflow(self):
        from PIL import Image
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                out = Path(td) / f"{name}.png"
                r = charsheet.sheet_format("sheep-girl", name, str(out))
                self.assertTrue(out.exists())
                self.assertEqual(r["outside_panel"], 0, r["over"])
                self.assertEqual(r["empty"], [])
                self.assertEqual(Image.open(out).size, tuple(r["size"]))
                self._inside(r)

    def test_unknown_format_fails(self):
        with self.assertRaises(SystemExit):
            charsheet.load_format("no-such-format")

    def test_themes_load_and_one_default(self):
        ts = charsheet.themes()
        self.assertGreaterEqual(len(ts), 4)
        self.assertEqual(sum(bool(t.get("default")) for t in ts), 1)
        for t in ts:
            th = charsheet.load_theme(t["name"])
            for k in ("page", "card", "ink", "sub", "accent"):
                self.assertIn(k, th["colors"], (t["name"], k))
            # 地・文字・補助・差し色（と表情の台）に絞る。色が増えるほど、主役の絵の色と競った
            self.assertLessEqual(len(set(th["colors"].values())), 6, t["name"])

    @needs_browser
    def test_theme_and_format_combine_without_overflow(self):
        for theme in THEMES:
            for name in ("overview", "social"):
                with self.subTest(theme=theme, name=name), tempfile.TemporaryDirectory() as td:
                    r = charsheet.sheet_format("sheep-girl", name, str(Path(td) / "s.png"), theme=theme)
                    self.assertTrue(r["theme"] == theme and r["outside_panel"] == 0 and r["empty"] == [])
                    self._inside(r)

    def test_theme_choice_order(self):
        c = {"theme": "washi", "look": "knight"}
        self.assertEqual(charsheet.pick_theme(c, "neon"), "neon")          # 指定が先
        self.assertEqual(charsheet.pick_theme(c), "washi")                 # 次にキャラクターの指定
        self.assertEqual(charsheet.pick_theme({"look": "x"}), "studio")   # 無ければ既定

    def test_suggest_puts_matching_theme_first(self):
        c = {"look": "1girl", "outfit": "silver plate armor, red cape",
             "items": [{"name": "ランタン", "tags": "holding lantern"}]}
        self.assertEqual(charsheet.suggest_themes(c)[0][0], "heraldry")

    def test_unknown_theme_fails(self):
        with self.assertRaises(SystemExit):
            charsheet.load_theme("no-such-theme")

    def test_each_format_uses_a_bold_device(self):
        # 区画からはみ出さない決まりだけでは、主役が台紙に収まった平板な版になった
        for name in NAMES:
            with self.subTest(name=name):
                fm = charsheet.load_format(name)
                marks = [k for pn in fm["panels"] for k in ("bleed", "overlap", "watermark", "huge") if pn.get(k)]
                marks += ["tight" for pn in fm["panels"] if pn.get("crop") == "tight"]
                self.assertTrue(marks, name)


if __name__ == "__main__":
    unittest.main()
