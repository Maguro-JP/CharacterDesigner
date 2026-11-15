"""映り込みの矛盾の検品（chatdraw/mirrorcheck.py）と、「検品する」の赤ペンの印までの経路。
絵は試験の中で組む（人の形の図を左に置き、右に反転して暗くした写しを置く）。写しの色・部位・向きを変えて、食い違いを返すかを見る"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageOps  # noqa: E402

from chatdraw import mirrorcheck, qcmanual  # noqa: E402

BG = (235, 235, 225)


def figure(d, ox, body=(200, 40, 40), arm=True):
    d.ellipse([ox + 30, 40, ox + 70, 80], fill=(240, 200, 170), outline=(0, 0, 0), width=2)
    d.rectangle([ox + 25, 85, ox + 75, 170], fill=body, outline=(0, 0, 0), width=2)
    d.polygon([(ox + 20, 90), (ox + 5, 120), (ox + 15, 125)], fill=(30, 30, 160))
    if arm:
        d.rectangle([ox + 75, 90, ox + 110, 100], fill=(240, 200, 170), outline=(0, 0, 0), width=2)
    d.rectangle([ox + 30, 170, ox + 45, 230], fill=(50, 50, 50))
    d.rectangle([ox + 55, 170, ox + 70, 200], fill=(90, 60, 20))


def scene(kind="same", vertical=False):
    """左（上）に元の図、右（下）に鏡の写し。写しはガラスの色を 25% 混ぜて暗くする"""
    one = Image.new("RGB", (200, 260), BG)
    figure(ImageDraw.Draw(one), 20)
    copy = Image.new("RGB", (200, 260), BG)
    figure(ImageDraw.Draw(copy), 20, body=(40, 160, 40) if kind == "color" else (200, 40, 40), arm=kind != "arm")
    if kind != "straight":
        copy = ImageOps.flip(copy) if vertical else ImageOps.mirror(copy)
    copy = Image.blend(copy, Image.new("RGB", copy.size, (150, 170, 200)), 0.25)
    im = Image.new("RGB", (200, 520) if vertical else (400, 260), BG)
    im.paste(one, (0, 0))
    im.paste(copy, (0, 260) if vertical else (200, 0))
    return im


def words(res):
    return [b for f in res["flaws"] for b in f["bad"]]


class MirrorCheckTest(unittest.TestCase):
    def test_no_tag_says_nothing(self):
        """映り込みのタグが無い絵では何も言わない（左右に同じ物を並べた絵を、鏡と読まない）"""
        self.assertEqual(mirrorcheck.check(scene("color"), {"1girl": 0.9}), {"gated": [], "flaws": []})

    def test_same_reflection_is_clean(self):
        """暗く色の寄った、正しく反転した映りは崩れにしない"""
        res = mirrorcheck.check(scene("same"), {"mirror": 0.8})
        self.assertGreaterEqual(res["found"], mirrorcheck.LEAST_PAIRS)
        self.assertEqual(res["flaws"], [])

    def test_color_differs(self):
        res = mirrorcheck.check(scene("color"), {"mirror": 0.8})
        self.assertIn("矛盾: 鏡の中の色が違う", words(res))
        box = next(f["box"] for f in res["flaws"] if "色" in f["bad"][0])
        self.assertGreaterEqual(box[0], 200)   # 印は映りの側（右）に付く

    def test_missing_part(self):
        res = mirrorcheck.check(scene("arm"), {"mirror": 0.8})
        self.assertTrue(any("物が足りない" in w for w in words(res)), words(res))

    def test_not_flipped(self):
        res = mirrorcheck.check(scene("straight"), {"mirror": 0.8})
        self.assertTrue(any("向きが違う" in w for w in words(res)), words(res))

    def test_water_is_vertical(self):
        """水面は上下に反転して映る"""
        self.assertEqual(mirrorcheck.check(scene("same", True), {"reflective water": 0.7})["flaws"], [])
        res = mirrorcheck.check(scene("color", True), {"reflective water": 0.7})
        self.assertIn("矛盾: 水面の中の色が違う", words(res))

    def test_unpaired_is_not_clean(self):
        """タグはあるのに元の物と映りの組が見つからない絵は、崩れが無いことにせず「比べていない」と返す"""
        im = Image.new("RGB", (300, 200), BG)
        # 左右にも上下にも対称でない形 1 つ（対称な形は、自分の半分どうしを組にする。そのときは映りも元も同じなので崩れは出ない）
        ImageDraw.Draw(im).polygon([(20, 30), (140, 60), (60, 180), (40, 90)], fill=(200, 40, 40), outline=(0, 0, 0), width=3)
        res = mirrorcheck.check(im, {"mirror": 0.8})
        self.assertIn("比べていない", res.get("reason", ""))
        self.assertTrue(any(m.startswith("映り込み") for m in qcmanual.missed({"mirror": res})))

    def test_flaws_become_redpen_marks(self):
        """qcmanual.flaws が映り込みの矛盾を枠と言葉にする（「検品する」が赤ペンの印にする物）"""
        res = {"hands": [], "feet": [], "faces": [], "mirror": mirrorcheck.check(scene("color"), {"mirror": 0.8})}
        marks = qcmanual.flaws(res, (10, 0))
        self.assertTrue(marks and marks[0][1].startswith("矛盾: 鏡の中の"))
        self.assertGreaterEqual(marks[0][0][0], 210)


@unittest.skipUnless((ROOT / ".cache" / "simple" / "lib" / "PySide6").is_dir(), "PySide6 が無い")
class MirrorFromWindowTest(unittest.TestCase):
    """編集のメニューの「検品する」を押すと、映り込みの矛盾が赤ペンの印になる。
    手・足・顔の模型は偽に差し替え、映り込みの検品（mirrorcheck）は本物を通す"""

    def test_inspect_menu_marks_mirror(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("CD_CHECK", "off")
        from tempfile import TemporaryDirectory
        from PySide6.QtTest import QTest
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg, wait_idle
        from chatdraw.tests.test_editing import app
        qapp = app()
        old = qcmanual.inspect
        with TemporaryDirectory() as d:
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            try:
                src = Path(d) / "m.png"
                scene("color").save(src)
                w.resize(1200, 800)
                w.show()
                w.canvas.replace_with_image(str(src))
                QTest.qWait(50)
                w.notify = lambda *a, **k: None
                qcmanual.inspect = lambda img: {"readable": True, "bad": [], "hands": [], "feet": [], "faces": [],
                                                "face": {"readable": True}, "mirror": mirrorcheck.check(img, {"mirror": 0.8})}
                acts = [a for a in w.menuBar().actions() if a.text() == "編集"][0].menu().actions()
                [a for a in acts if a.text() == "検品する"][0].trigger()
                wait_idle(qapp, w, 60)
                wait_bg(qapp, w)
                texts = list(w.canvas.redpen.texts)
            finally:
                qcmanual.inspect = old
                w.closing_checked = True
                w.close()
        self.assertTrue(any("矛盾: 鏡の中の色が違う" in t for t in texts), texts)

if __name__ == "__main__":
    unittest.main()
