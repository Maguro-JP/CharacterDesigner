"""ロゴ・マークとスタンプ（chatdraw/logo.py）。絵の模型は偽物で流れを、模型の要らない処理は本物で画素と大きさを確かめる"""
import json
import os
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw import logo  # noqa: E402


def mark(size=(400, 300)):
    """白い地に、青い丸と、丸の中の白い穴（地と同じ色だが外とつながらない）"""
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.ellipse((100, 50, 300, 250), fill=(30, 60, 200))
    d.ellipse((180, 130, 220, 170), fill="white")
    return im


class FakePainter:
    model = "fake"

    def __init__(self):
        self.calls, self.avoid = [], "nsfw"

    def ready(self):
        return True

    def paint(self, prompt, seed, size=None, **kw):
        self.calls.append(dict(prompt=prompt, seed=seed, avoid=self.avoid, size=size))
        return mark()


class LogoTest(unittest.TestCase):
    def test_prompt_is_english_and_bans_text(self):
        prompt, avoid = logo.logo_prompt("ねこ屋", "かわいい 猫", "青と白")
        self.assertNotRegex(prompt, r"[぀-ヿ一-鿿]")              # 日本語を模型に渡さない
        for w in ("cute", "cat", "blue", "white", "no text"):
            self.assertIn(w, prompt)
        for w in ("text", "letters", "photo", "detailed background"):
            self.assertIn(w, avoid)

    def test_draw_logo_flow(self):
        p = FakePainter()
        im = logo.draw_logo(p, "Cat Shop", "cute", "blue", seed=3)
        self.assertEqual(p.calls[0]["seed"], 3)
        self.assertIn("garbled text", p.calls[0]["avoid"])
        self.assertTrue(p.calls[0]["avoid"].startswith("nsfw"))     # 前からの描かない物も残す
        self.assertEqual(p.avoid, "nsfw")                          # 描いたあとは元に戻す
        self.assertEqual(im.mode, "RGBA")

    def test_background_removed_but_inner_white_kept(self):
        im = logo.remove_background(mark())
        a = im.getchannel("A")
        self.assertEqual(a.getpixel((5, 5)), 0)
        self.assertEqual(a.getpixel((200, 80)), 255)
        self.assertEqual(a.getpixel((200, 150)), 255)              # 丸の中の白い穴は外とつながらないので残る

    def test_square_wide_colors_mono(self):
        cut = logo.remove_background(mark())
        sq = logo.square(cut, 512, 32)
        self.assertEqual(sq.size, (512, 512))
        box = sq.getchannel("A").getbbox()
        self.assertGreaterEqual(min(box[0], box[1]), 31)            # 余白を残す
        self.assertEqual(max(box[2], box[3]), 512 - 32)
        wd = logo.wide(cut, "CAT", size=(800, 300))
        self.assertEqual(wd.size, (800, 300))
        right = wd.crop((300, 0, 800, 300))
        dark = [p for p in right.getdata() if p[3] > 128 and p[0] < 100]
        self.assertTrue(dark, "右側に文字が書かれていない")
        few = logo.reduce_colors(sq, 3)
        self.assertLessEqual(len({p[:3] for p in few.getdata() if p[3]}), 3)
        self.assertEqual({p[3] for p in few.getdata()} - {0, 255}, set())
        mo = logo.mono(sq)
        self.assertEqual({p for p in mo.getdata()} - {(0, 0, 0, 0), (0, 0, 0, 255)}, set())
        self.assertTrue(mo.getchannel("A").getbbox())

    def test_svg_and_export(self):
        with TemporaryDirectory() as d:
            files = logo.export_logo(logo.remove_background(mark()), d, text="CAT")
            names = {f.name for f in files}
            for n in ("logo-square.png", "logo-wide.png", "logo-square-mono.png", "logo-square-colors.svg"):
                self.assertIn(n, names)
            svg = (Path(d) / "logo-square-colors.svg").read_text(encoding="utf-8")
            self.assertTrue(svg.startswith("<svg") and "<path" in svg)
            with Image.open(Path(d) / "logo-square.png") as im:
                self.assertEqual(im.mode, "RGBA")


class StampTest(unittest.TestCase):
    def test_line_stamp_shape(self):
        st = logo.stamp(mark(), "line")
        self.assertEqual(st.size, (370, 320))
        self.assertEqual(st.getpixel((0, 0))[3], 0)
        box = st.getchannel("A").getbbox()
        self.assertTrue(box[0] >= 10 and box[1] >= 10 and box[2] <= 360 and box[3] <= 310)   # 10 画素の余白
        edge = st.getpixel((box[0] + (box[2] - box[0]) // 2, box[1] + 1))
        self.assertGreater(min(edge[:3]), 200)                     # いちばん外は白い縁取り

    def test_telegram_side_is_512(self):
        self.assertEqual(logo.stamp(mark(), "telegram").size, (512, 512))

    def test_export_many_with_zip(self):
        with TemporaryDirectory() as d:
            srcs = []
            for i in range(3):
                p = Path(d) / f"e{i}.png"
                mark().save(p)
                srcs.append(p)
            out = logo.export_stamps(srcs, Path(d) / "out", "line", stem="chara")
            names = sorted(p.name for p in out)
            self.assertEqual(names, ["01.png", "02.png", "03.png", "chara-line.zip", "main.png", "tab.png"])
            self.assertEqual(Image.open(Path(d) / "out" / "main.png").size, (240, 240))
            self.assertEqual(Image.open(Path(d) / "out" / "tab.png").size, (96, 74))
            for p in out:
                self.assertLessEqual(p.stat().st_size, logo.MAX_BYTES)
            with zipfile.ZipFile(Path(d) / "out" / "chara-line.zip") as z:
                self.assertEqual(len(z.namelist()), 5)

    def test_expressions_from_bible(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "bible" / "characters").mkdir(parents=True)
            (root / "img").mkdir()
            for k in ("expr-smile", "expr-angry"):
                mark().save(root / "img" / f"{k}.png")
            (root / "bible" / "characters" / "a.json").write_text(json.dumps(
                {"id": "a", "images": {"color": "img/c.png", "expr-smile": "img/expr-smile.png", "expr-angry": "img/expr-angry.png"}}))
            self.assertEqual([p.name for p in logo.expressions("a", home=root)], ["expr-angry.png", "expr-smile.png"])


class IconTest(unittest.TestCase):
    def test_make_ico(self):
        with TemporaryDirectory() as d:
            png = Path(d) / "app.png"
            logo.remove_background(mark()).save(png)
            ico = logo.make_ico(png, Path(d) / "app.ico")
            im = Image.open(ico)
            self.assertEqual(im.format, "ICO")
            self.assertIn((256, 256), im.info["sizes"])
            self.assertIn((16, 16), im.info["sizes"])

    def test_draw_one_logo_candidates(self):
        from chatdraw import draw_one
        with TemporaryDirectory() as d:
            done = draw_one.logo_candidates({"mode": "logo", "name": "CharacterDesigner", "seeds": [1, 2], "size": [256, 256]},
                                            Path(d), painter=FakePainter())
            self.assertEqual([x["file"] for x in done], ["icon-s1.png", "icon-s2.png"])
            self.assertEqual(Image.open(Path(d) / "icon-s1.png").size, (1024, 1024))
            self.assertIn("avoid", json.loads((Path(d) / "request.json").read_text(encoding="utf-8")))


def good_icon(size=512):
    """通るアイコン: 黒の無地の地に、赤い太い丸と白い太い棒（2 色、真ん中、余白あり）"""
    im = Image.new("RGB", (size, size), logo.ICON_COLORS["black"])
    d = ImageDraw.Draw(im)
    k = size / 512
    d.ellipse((150 * k, 150 * k, 362 * k, 362 * k), fill=logo.ICON_COLORS["red"])
    d.rectangle((236 * k, 200 * k, 276 * k, 312 * k), fill=logo.ICON_COLORS["white"])
    return im


class IconPainter(FakePainter):
    """1 枚目は紫のグラデーションの地（落ちる）、2 枚目からは通るアイコンを返す"""

    def paint(self, prompt, seed, size=None, **kw):
        self.calls.append(dict(prompt=prompt, seed=seed, avoid=self.avoid, size=size))
        if len(self.calls) == 1:
            im = Image.new("RGB", (512, 512))
            im.putdata([(120 + x // 4, 40, 200 - y // 4) for y in range(512) for x in range(512)])
            return im
        return good_icon()


class IconTest(unittest.TestCase):
    def test_prompt_has_intent_palette_and_bans(self):
        prompt, avoid = logo.icon_prompt("black-red-white")
        self.assertNotRegex(prompt, r"[぀-ヿ一-鿿]")
        self.assertIn("draws and finishes anime characters", prompt)   # 意図
        self.assertIn("one single bold symbol", prompt)                # 1 つの象徴
        self.assertIn("red and white", prompt)                          # 色の組
        self.assertIn("flat black background", prompt)
        self.assertIn("retro-futuristic sci-fi", prompt)
        for w in ("gradient background", "fine details", "photo", "text", "purple", "pink", "rounded square tile"):
            self.assertIn(w, avoid)
        for pal in logo.ICON_PALETTES.values():                         # 色は好みの白・黒・赤・オレンジから 2〜3 色
            cols = [pal["ground"]] + pal["ink"]
            self.assertTrue(2 <= len(cols) <= 3 and set(cols) <= {"white", "black", "red", "orange"})

    def test_check_passes_good_icon(self):
        res = logo.icon_check(good_icon(), "black-red-white")
        self.assertTrue(res["ok"], res["faults"])
        self.assertEqual(res["colors"], 2)
        self.assertGreaterEqual(res["small_iou"], 0.7)

    def test_check_fails_gradient_ground(self):
        im = Image.new("RGB", (256, 256))
        im.putdata([(x, 40, 255 - y) for y in range(256) for x in range(256)])
        ImageDraw.Draw(im).ellipse((80, 80, 176, 176), fill="white")
        res = logo.icon_check(im, "black-red-white")
        self.assertFalse(res["ok"])
        self.assertIn("地が無地でない（グラデーションか模様）", res["faults"])

    def test_check_fails_off_center_too_many_colors_and_fine_detail(self):
        im = Image.new("RGB", (512, 512), logo.ICON_COLORS["black"])
        ImageDraw.Draw(im).ellipse((300, 300, 500, 500), fill=logo.ICON_COLORS["red"])
        self.assertIn("中心から外れている", logo.icon_check(im)["faults"])
        im = good_icon()
        d = ImageDraw.Draw(im)
        d.rectangle((60, 400, 160, 470), fill=(40, 200, 60))
        d.rectangle((352, 400, 452, 470), fill=(60, 60, 230))
        f = logo.icon_check(im)["faults"]
        self.assertIn("色の組に無い色がある", f)
        im = Image.new("RGB", (512, 512), logo.ICON_COLORS["black"])
        d = ImageDraw.Draw(im)
        for x in range(120, 392, 6):                                    # 細い線の描き込み（16 画素で消える）
            d.line((x, 120, x, 392), fill=logo.ICON_COLORS["white"], width=1)
        f = logo.icon_check(im)["faults"]
        self.assertTrue({"16 画素に縮めると形が崩れる", "細かい描き込みが多い"} & set(f), f)

    def test_draw_icon_redraws_until_pass(self):
        p = IconPainter()
        im, res, seed, failed = logo.draw_icon(p, "black-red-white", seed=5, tries=3)
        self.assertTrue(res["ok"])
        self.assertEqual([c["seed"] for c in p.calls], [5, 1005])       # 落ちた 1 枚目のあと、種を変えて描き直す
        self.assertEqual(len(failed), 1)
        self.assertEqual(p.avoid, "nsfw")

    def test_draw_one_icon_kind(self):
        from chatdraw import draw_one
        with TemporaryDirectory() as d:
            done = draw_one.logo_candidates({"mode": "logo", "kind": "icon", "palettes": ["black-red-white"], "seeds": [3],
                                             "size": [512, 512]}, Path(d), painter=IconPainter())
            self.assertEqual(done[0]["file"], "icon-black-red-white-head-nib-s1003.png")
            self.assertTrue((Path(d) / done[0]["file"]).exists())
            req = json.loads((Path(d) / "request.json").read_text(encoding="utf-8"))
            self.assertTrue(req["done"][0]["check"]["ok"])


try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 が無い")
class AppTest(unittest.TestCase):
    """アプリのメニューから押して、裏の糸で最後まで書き出すか"""

    def _window(self, d):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakeWords
        app = QApplication.instance() or QApplication([])
        w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
        w._logo_folder = lambda kind: Path(d) / kind
        return app, w

    def _wait(self, app, w):
        for _ in range(500):
            app.processEvents()
            if getattr(w, "logo_out", None) and not w.thread:
                break
            w.thread and w.thread.wait(10)
        if w.thread:
            w.thread.wait(5000)

    def test_menu_next_to_character_design(self):
        with TemporaryDirectory() as d:
            app, w = self._window(d)
            titles = [a.text() for a in w.menuBar().actions()]
            self.assertEqual(titles[titles.index("キャラクターデザイン") + 1], "ロゴ・スタンプ")
            acts = [a for a in w.logo_menu.actions() if a.text()]
            self.assertEqual(len(acts), len(logo.menu_items(w)))
            self.assertTrue(all(a.toolTip() for a in acts))          # 説明はツールチップ
            from PySide6.QtWidgets import QMenu
            m = w._fill_logo_menu(QMenu())                            # 右クリックにも同じ項目を足せる
            self.assertEqual([a.text() for a in m.actions()], [a.text() for a in acts])
            w.close()

    def test_logo_make_runs_through(self):
        with TemporaryDirectory() as d:
            app, w = self._window(d)
            w.logo_make("CAT", "cute", "blue")
            self._wait(app, w)
            names = {Path(p).name for p in w.logo_out}
            self.assertIn("logo-wide.png", names)
            self.assertTrue((Path(d) / "logo" / "logo-square.png").exists())
            w.close()

    def test_stamp_from_canvas_runs_through(self):
        with TemporaryDirectory() as d:
            app, w = self._window(d)
            mark().save(Path(d) / "m.png")
            w.canvas.show_image(str(Path(d) / "m.png"))
            w.stamp_from_canvas("line")
            self._wait(app, w)
            self.assertEqual(Image.open(Path(d) / "stamp" / "01.png").size, (370, 320))
            w.close()


if __name__ == "__main__":
    unittest.main()
