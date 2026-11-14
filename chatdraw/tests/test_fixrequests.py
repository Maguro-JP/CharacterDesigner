"""修正依頼と、模型を使わない整える・揃える・消すを、窓から押して通す（偽の模型）。
- 修正依頼を選ぶと、赤ペンの印の指示の欄に書いて確定し、1 回だけ直す。模型には用意した言葉と強さが渡る
- 自分の指示を一覧に足すと、右クリックと AI の欄の両方に出る
- 道具の結果は一番上の新しいレイヤーに置き、囲みの外は変えず、元に戻すで戻せる
CD_SHOTS に置き場を書くと、窓の写しを撮る（見えるか・幅が潰れていないかを目で見るため）"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, wait_bg, wait_idle  # noqa: E402
from chatdraw.tests.test_editing import app, figure  # noqa: E402


def _find(menu, text):
    for a in menu.actions():
        if a.text() == text:
            return a
        if a.menu():
            got = _find(a.menu(), text)
            if got:
                return got
    return None


class EditToolsUnitTest(unittest.TestCase):
    def test_despeckle_removes_dots_keeps_line(self):
        from chatdraw import edittools
        img = Image.new("RGB", (80, 80), "white")
        d = ImageDraw.Draw(img)
        d.line((5, 40, 75, 40), fill="black", width=3)
        for p in ((10, 10), (60, 15), (30, 65)):
            img.putpixel(p, (0, 0, 0))
        out = edittools.despeckle(img)
        self.assertEqual(edittools.despeckle.last_count, 3)
        self.assertEqual(out.getpixel((10, 10)), (255, 255, 255))
        self.assertEqual(out.getpixel((40, 40)), (0, 0, 0))   # 線は残す

    def test_smooth_changes_only_inside(self):
        from chatdraw import edittools
        img = Image.new("RGB", (80, 80), "white")
        d = ImageDraw.Draw(img)
        d.line([(5 + 2 * i, 40 + (3 if i % 2 else -3)) for i in range(36)], fill="black", width=2)
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rectangle((0, 0, 39, 79), fill=255)
        out = edittools.smooth_lines(img, mask)
        self.assertGreater(edittools.changed_pixels(img, out), 0)
        self.assertEqual(img.crop((40, 0, 80, 80)).tobytes(), out.crop((40, 0, 80, 80)).tobytes())

    def test_align_matches_size_and_height(self):
        from chatdraw import edittools
        img = Image.new("RGB", (120, 80), "white")
        d = ImageDraw.Draw(img)
        d.ellipse((10, 20, 30, 40), fill="black")      # 基準: 20x20、中心の高さ 30
        d.ellipse((80, 40, 92, 52), fill="black")      # 小さく低い
        m1 = Image.new("L", img.size, 0)
        ImageDraw.Draw(m1).rectangle((8, 18, 32, 42), fill=255)
        m2 = Image.new("L", img.size, 0)
        ImageDraw.Draw(m2).rectangle((78, 38, 94, 54), fill=255)
        out = edittools.align(img, [m1, m2])
        dark = out.convert("L").point(lambda v: 255 if v < 100 else 0).crop((60, 0, 120, 80)).getbbox()
        h = dark[3] - dark[1]
        cy = (dark[1] + dark[3]) / 2
        self.assertGreater(h, 17)
        self.assertLess(abs(cy - 30), 3)


class FixRequestWindowTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.old_home = os.environ.get("CD_HOME")
        os.environ["CD_HOME"] = str(self.d / "home")   # 自分の指示は試験の置き場に書く
        self.painter = FakePainter()
        self.w = Window(Studio(FakeWords(), self.painter, self.d))
        self.w.settings.set("output_dir", str(self.d / "out"))
        src = self.d / "a.png"
        figure().save(src)
        self.w.resize(1200, 800)
        self.w.show()
        self.w.canvas.replace_with_image(str(src))
        QTest.qWait(50)
        self.w.tool_actions["redpen"].trigger()

    def tearDown(self):
        self.w.closing_checked = True
        self.w.close()
        if self.old_home is None:
            os.environ.pop("CD_HOME", None)
        else:
            os.environ["CD_HOME"] = self.old_home
        self.tmp.cleanup()

    def mark(self, dx=0):
        c = self.w.canvas
        vp = c.viewport()
        start = c.mapFromScene(c.sceneRect().center()) + QPoint(-30 + dx, -30)
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
        for i in range(1, 16):
            QTest.mouseMove(vp, start + QPoint(4 * i, 4 * i))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 60))
        QTest.qWait(20)
        QTest.keyClick(self.w.note_edit, Qt.Key_Escape)   # 指示は欄に書かず、修正依頼から選ぶ

    def shot(self, name, widget=None):
        out = os.environ.get("CD_SHOTS")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (widget or self.w).grab().save(str(Path(out) / name))

    def test_request_from_right_click_writes_note_and_fixes_once(self):
        from chatdraw import fixrequests
        self.mark()
        self.menu = self.w.build_canvas_menu(None)   # メニューを持っておかないと、中の項目が消える
        act = _find(self.menu, "指を 5 本に")
        self.assertIsNotNone(act)
        calls = []
        real = self.painter.redraw
        self.painter.redraw = lambda prompt, *a, **k: (calls.append((prompt, k.get("strength"))), real(prompt, *a, **k))[1]
        act.trigger()
        self.assertEqual(self.w.canvas.redpen.texts[0], "指を 5 本に")   # 指示の欄に書いて確定した（直したあとは印を片付ける）
        wait_idle(self.qapp, self.w, 60)
        wait_bg(self.qapp, self.w)
        req = fixrequests.lookup("指を 5 本に")
        self.assertTrue(calls, "直しが走っていない")
        self.assertIn(req["prompt"], calls[0][0])                        # 用意した言葉が模型に渡る
        self.assertNotIn("指を", calls[0][0])                            # 日本語のまま渡さない
        self.assertAlmostEqual(calls[0][1], req["strength"])
        self.assertEqual(len([c for c in calls if req["prompt"] in c[0]]), 1)   # 1 回だけ

    def test_user_request_appears_in_both_menus(self):
        from chatdraw import fixmenu, fixrequests
        fixrequests.add_user("袖を短く")
        self.menu = self.w.build_canvas_menu(None)
        self.assertIsNotNone(_find(self.menu, "袖を短く"))
        menu = self.w.ai_panel.fixreq_menu   # AI の欄の「直す」の「修正依頼」
        menu.aboutToShow.emit()
        self.assertIsNotNone(_find(menu, "袖を短く"))
        self.assertIn(fixrequests.USER_PART, fixrequests.parts())
        self.assertTrue(fixmenu.TOOLS)

    def test_tools_put_top_layer_and_undo(self):
        from chatdraw.app import qimage_to_pil
        c = self.w.canvas
        before = qimage_to_pil(c.flatten()).convert("RGB")
        self.mark()
        n = len(c.layers)
        self.menu = self.w.build_canvas_menu(None)
        act = _find(self.menu, "囲んだ物を消す")
        act.trigger()
        QTest.qWait(20)
        self.assertEqual(len(c.layers), n + 1)
        self.assertEqual(c.current, len(c.layers) - 1)
        after = qimage_to_pil(c.flatten()).convert("RGB")
        mask = self.w._region_mask().resize(before.size).point(lambda v: 255 if v > 127 else 0)
        from PIL import ImageChops
        diff = ImageChops.difference(before, after).convert("L").point(lambda v: 255 if v else 0)
        self.assertIsNotNone(diff.getbbox())
        self.assertIsNone(ImageChops.subtract(diff, mask).getbbox())   # 囲みの外は 1 画素も変えない
        self.shot("canvas-after-erase.png")
        self.w.tool_actions["pen"].trigger()   # 赤ペンの道具の間の元に戻すは、印を先に外す（canvas.undo）
        c.undo()
        self.assertEqual(len(c.layers), n)
        self.assertEqual(qimage_to_pil(c.flatten()).convert("RGB").tobytes(), before.tobytes())

    def test_panel_buttons_visible(self):
        from PySide6.QtWidgets import QPushButton
        btns = {b.text(): b for b in self.w.findChildren(QPushButton)}
        for name in ("修正依頼", "整える・揃える・消す"):
            self.assertIn(name, btns)
        self.shot("window.png")
        self.menu = self.w.build_canvas_menu(None)
        self.shot("menu.png", self.menu)
        from PySide6.QtWidgets import QTabWidget
        panel = self.w.ai_panel
        tabs = next(t for t in panel.findChildren(QTabWidget) if any(t.tabText(i) == "直す・仕上げ" for i in range(t.count())))
        tabs.setCurrentIndex(next(i for i in range(tabs.count()) if tabs.tabText(i) == "直す・仕上げ"))
        QTest.qWait(30)
        for name in ("修正依頼", "整える・揃える・消す"):
            b = btns[name]
            self.assertTrue(b.isVisible(), name)
            self.assertGreater(b.width(), b.fontMetrics().horizontalAdvance(name), name)   # 文字が切れない幅
        self.shot("ai-fix-tab.png", panel)
        panel.fixreq_menu.aboutToShow.emit()
        self.shot("fixreq-menu.png", panel.fixreq_menu)
        hands = next(a.menu() for a in panel.fixreq_menu.actions() if a.text() == "手・指")
        self.shot("fixreq-hands.png", hands)
        self.assertIsNotNone(_find(hands, "指を 5 本に"))
