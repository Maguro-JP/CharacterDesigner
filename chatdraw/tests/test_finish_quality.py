"""綺麗にする加工が元の絵を崩さないか、拡大のあとでも速いか、画風の加工が本物の経路で動くか。

- 綺麗にするの前と後を、本物の絵（library の見本）で SSIM・主線の重なり・顔の変わりで測る
- 線から離れた粒を消す工程は、顔の目・口の小さな線も消していた。顔は元の画素のまま残す
- 粒を消す工程の中央値を粒の画素だけで取る形にし、絵全体に掛けた前と同じ値で速くなったことを確かめる
- 画風の加工は、試験用の小さな SDXL と小さな ControlNet で本当に描かせ、一番上の新しいレイヤーに置かれるまで通す
"""
import math
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from chatdraw import finishers  # noqa: E402

SAMPLE = ROOT / "library" / "daily" / "2026-10-13" / "05-yukionna.png"
TINY = "hf-internal-testing/tiny-stable-diffusion-xl-pipe"


def has(*mods):
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in mods)


@unittest.skipUnless(has("numpy", "scipy", "skimage"), "numpy・scipy・scikit-image が要ります")
class CleanKeepsOriginalTest(unittest.TestCase):
    def test_levels_is_not_in_clean(self):
        # 明るさの幅は描き手の決めた色を変える（拡大のあとの絵で色が平均 10.7 変わった）ので、綺麗にするに入れない
        self.assertNotIn("levels", finishers.RETOUCH_SAFE)
        self.assertNotIn("levels", finishers.RETOUCH_FULL)

    def test_heal_median_only_at_specks_is_same_and_faster(self):
        import numpy as np
        from scipy.ndimage import median_filter
        rt = finishers._gen("retouch")
        a = np.asarray(Image.open(SAMPLE).convert("RGB").resize((1024, 1536), Image.LANCZOS)).astype(float)
        t = time.time()
        b = rt.heal(a)
        new = time.time() - t
        t = time.time()
        fill = np.stack([median_filter(a[..., c], size=9) for c in range(3)], -1)   # 前の掛け方（絵全体の中央値）
        old = time.time() - t
        d = (b != a).any(2)
        self.assertTrue(d.any())
        self.assertEqual(float(np.abs(b[d] - fill[d]).max()), 0.0)   # 前と同じ値
        self.assertLess(new, old, (new, old))

    def test_face_is_kept_and_too_much_change_is_mixed_back(self):
        src = Image.open(SAMPLE).convert("RGB")
        face = Image.new("L", src.size, 0)
        face.paste(255, (200, 100, 300, 200))
        dark = src.point(lambda v: min(255, v + 120))   # 線を消すほど明るくした絵
        with mock.patch.object(finishers, "face_keep", lambda im: face):
            out, q = finishers.soften(src, dark)
        self.assertTrue(q["face"])
        self.assertEqual(out.crop((210, 110, 290, 190)).tobytes(), src.crop((210, 110, 290, 190)).tobytes())
        # 明るくしすぎた絵も、主線の周りは変わりが上限までに抑えられ、形の変わった区画は元の絵に戻る
        import numpy as np
        d = np.abs(np.asarray(out, float) - np.asarray(src, float)).max(2)
        self.assertLess(d.mean(), 120 * 0.5)
        self.assertGreater(q["reverted"] + q["capped"], 0)

    def test_limit_caps_lines_and_reverts_changed_shape(self):
        import numpy as np
        src = Image.open(SAMPLE).convert("RGB")
        a = np.asarray(src).astype(float)
        b = a.copy()
        b[100:164, 100:164] = 255 - b[100:164, 100:164]   # 形を壊した所
        out, n = finishers.limit(src, Image.fromarray(b.astype("uint8")))
        o = np.asarray(out).astype(float)
        self.assertGreater(n["reverted"], 0)
        self.assertLess(np.abs(o[100:164, 100:164] - a[100:164, 100:164]).mean(), 20)
        line = finishers._gen("cleanup").line_mask(a)
        self.assertLessEqual(np.abs(o - a).max(2)[line].max(), finishers.LINE_DELTA + 1)

    def test_changed_or_unreadable_hand_goes_back_to_original(self):
        from chatdraw import handcheck
        src = Image.open(SAMPLE).convert("RGB")
        out = src.point(lambda v: 255 - v)

        class Hands:
            def _litert(self):
                pass

            def best_crop(self, im, box, ang):
                return im.crop(box)

            def measure(self, crop):
                dark = sum(crop.convert("L").getdata()) / (crop.width * crop.height) < 128
                return ({"palm": 1.0, "thumb": 1.0 if dark else 1.3, "fingers": {"count": 5}}, [], None)
        with mock.patch.object(handcheck, "_hands", lambda: Hands()), \
                mock.patch.object(handcheck, "ensure_models", lambda fetch=True: True), \
                mock.patch.object(handcheck, "find_hands", lambda h, im: ["10,10,60,60:0", "100,100,150,150:0"]):
            got, n = finishers.hand_guard(src, out)
        self.assertEqual(n["hands_back"], 2)   # 指の長さの比が変わった手は、元の画素に戻す
        self.assertEqual(got.crop((10, 10, 60, 60)).tobytes(), src.crop((10, 10, 60, 60)).tobytes())
        self.assertEqual(got.crop((200, 200, 250, 250)).tobytes(), out.crop((200, 200, 250, 250)).tobytes())

    def test_face_box_is_kept_with_soft_edge_when_no_parts_model(self):
        from chatdraw import handcheck
        src = Image.open(SAMPLE).convert("RGB")
        out = src.point(lambda v: max(0, v - 10))
        with mock.patch.object(finishers, "face_keep", lambda im: None), \
                mock.patch.object(handcheck, "_face", lambda im, asked: {"box": [200, 100, 296, 196]}), \
                mock.patch.object(finishers, "hand_guard", lambda a, b: (b, {})):
            got, q = finishers.soften(src, out)
        self.assertTrue(q["face"])
        self.assertEqual(got.crop((220, 120, 276, 176)).tobytes(), src.crop((220, 120, 276, 176)).tobytes())   # 枠の中は元のまま
        row = [got.getpixel((x, 148))[0] - out.getpixel((x, 148))[0] for x in range(180, 205)]
        self.assertTrue(len(set(row)) > 2, row)   # 縁はぼかして移る（一気に変わる継ぎ目にしない）

    def test_real_clean_stays_close_to_original(self):
        src = Image.open(SAMPLE).convert("RGB")
        for name in ("clean", "retouch", "retouch_full"):
            out = finishers.run(name, src)
            s = finishers.scores(src, out)
            self.assertGreaterEqual(s["ssim"], finishers.VERIFY_SSIM, (name, s))
            self.assertGreaterEqual(s["line"], finishers.VERIFY_LINE, (name, s))
            self.assertLess(s["color"], 3.0, (name, s))
            self.assertIn("verify", finishers.LAST_QC)

    def test_upscaled_clean_stays_close(self):
        src = Image.open(SAMPLE).convert("RGB")
        big = src.resize((src.width * 2, src.height * 2), Image.LANCZOS)
        out = finishers.run("retouch", big)
        s = finishers.scores(big, out)
        self.assertGreaterEqual(s["ssim"], finishers.VERIFY_SSIM, s)
        self.assertGreaterEqual(s["line"], finishers.VERIFY_LINE, s)


class CleanBeforeUpscaleTest(unittest.TestCase):
    def test_clean_moves_before_upscale(self):
        from chatdraw import chatplan
        self.assertEqual(chatplan.clean_first(["draw", "upscale", "finisher:retouch", "transparent"]),
                         ["draw", "finisher:retouch", "upscale", "transparent"])
        self.assertEqual(chatplan.clean_first(["upscale", "finisher:air_holy"]), ["upscale", "finisher:air_holy"])


def tiny_painter():
    """試験用の小さな SDXL と、その UNet から作った小さな線の ControlNet（重みは乱数。絵の出来は見ない）"""
    from diffusers import ControlNetModel, StableDiffusionXLPipeline
    from chatdraw import restyle
    # 手元にあれば通信しない（通信の揺れで試験が落ちていた）。ほかの試験が HF_HOME を替えても見つかるよう、既定の置き場を先に見る
    import glob
    import os
    local = sorted(glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--" + TINY.replace("/", "--") + "/snapshots/*/")))
    pipe = StableDiffusionXLPipeline.from_pretrained(local[-1] if local else TINY)
    restyle._CACHE.clear()
    restyle._CACHE["controlnet"] = ControlNetModel.from_unet(
        pipe.unet, conditioning_embedding_out_channels=(16,) * (int(math.log2(pipe.vae_scale_factor)) + 1))

    class Tiny:
        model = TINY
        steps = 2
        guidance = 5.0
        stop = False
        avoid = ""

        def load(self):
            return pipe

        def ready(self):
            return True

        def paint(self, *a, **k):
            return Image.new("RGB", (64, 64), "white")
    return Tiny()


def tiny_ready():
    if not has("torch", "diffusers"):
        return False
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(TINY)
        return True
    except Exception:
        return False


class RestylePostTest(unittest.TestCase):
    """描いたあとの処理（模型を使わない）。白黒の画風は色が残らず、ドット絵は格子がそろい色が減る"""
    def setUp(self):
        import numpy as np
        rng = np.random.default_rng(0)
        self.img = Image.fromarray(rng.integers(0, 255, (96, 64, 3), dtype=np.uint8), "RGB")

    def test_monochrome_styles_have_no_color(self):
        import numpy as np
        from chatdraw import restyle
        for kind in ("pencil", "sumie", "manga"):
            a = np.asarray(restyle.post(kind, self.img)).astype(int)
            self.assertEqual(int(np.abs(a[..., 0] - a[..., 1]).max()), 0, kind)

    def test_pixel_is_grid_and_few_colors(self):
        from chatdraw import restyle
        out = restyle.post("pixel", self.img)
        self.assertEqual(out.size, self.img.size)
        self.assertLessEqual(len(out.getcolors(1 << 16)), restyle.PIXEL_COLORS)

    def test_color_styles_pass_through(self):
        from chatdraw import restyle
        self.assertIs(restyle.post("gouache", self.img), self.img)

    def test_every_style_has_words_and_strength(self):
        from chatdraw import restyle
        for kind, label, tip, words, s, *_ in restyle.STYLES:
            self.assertTrue(words and tip and label)
            self.assertTrue(0 < s <= 0.7, kind)
        self.assertLessEqual(set(restyle.EXTRA), {k[0] for k in restyle.STYLES})


@unittest.skipUnless(tiny_ready(), "試験用の小さな SDXL が取れません")
class RestyleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.painter = tiny_painter()

    def setUp(self):
        finishers.use_painter(self.painter)
        self.src = Image.open(SAMPLE).convert("RGB").resize((32, 48), Image.LANCZOS)

    def tearDown(self):
        finishers.use_painter(None)

    def test_styles_are_registered_in_menu_group(self):
        from chatdraw import restyle, shortcuts
        names = [f"style_{s[0]}" for s in restyle.STYLES]
        self.assertEqual(len(names), 13)
        for n in names:
            self.assertEqual(finishers.REGISTRY[n].group, "style")
            self.assertTrue(finishers.REGISTRY[n].ready())
        self.assertIn("style", dict(shortcuts.GROUPS))

    def test_restyle_draws_with_tiny_model(self):
        from chatdraw import restyle
        with mock.patch.object(restyle, "check", lambda a, b: dict(drift=0.0, line_kept=1.0, why="")):
            out = finishers.run("style_anime", self.src)
        self.assertEqual(out.size, self.src.size)
        self.assertEqual(restyle.LAST["strength"], restyle.STYLES[0][4])

    def test_broken_result_lowers_strength_then_stops(self):
        from chatdraw import restyle
        calls = []

        def bad(a, b):
            calls.append(1)
            return dict(drift=0.5, line_kept=0.1, why="形が変わりすぎる（0.500）")
        with mock.patch.object(restyle, "check", bad):
            with self.assertRaises(finishers.Unavailable):
                finishers.run("style_watercolor", self.src)
        self.assertEqual(len(calls), len(restyle.STRENGTH_STEPS))
        got = [t["strength"] for t in restyle.LAST["tries"]]
        self.assertEqual(got, sorted(got, reverse=True))   # 強さを下げて描き直した

    def test_app_puts_style_on_top_layer(self):
        from chatdraw import restyle
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakeWords
        from chatdraw.tests.test_editing import app
        qapp = app()
        with TemporaryDirectory() as d, \
                mock.patch.object(restyle, "check", lambda a, b: dict(drift=0.0, line_kept=1.0, why="")), \
                mock.patch.object(restyle, "WORK_SIDE", 48):   # キャンバスは広いので、小さな模型で描く大きさを絞る（試験の時間とメモリ）
            d = Path(d)
            w = Window(Studio(FakeWords(), self.painter, d))
            old = w.settings.store.value("result_place")
            w.settings.set("result_place", "上のレイヤー")
            w.settings.set("output_dir", str(d / "out"))
            self.src.save(d / "a.png")
            w.edit_image(str(d / "a.png"))
            n = len(w.canvas.layers)
            # 右クリックの加工と同じ入口（shortcuts.builtins が呼ぶ物）
            from chatdraw import shortcuts
            try:
                for kind, label, *_ in restyle.STYLES:   # 13 の画風を全部、右クリックの項目から押す
                    item = [s for s in shortcuts.builtins(w) if s.id == f"fin:style_{kind}"][0]
                    self.assertTrue(item.ready, item.reason)
                    item.run()
                    for _ in range(6000):
                        qapp.processEvents()
                        if len(w.canvas.layers) > n:
                            break
                        time.sleep(0.01)
                    self.assertEqual(w.canvas.layers[-1].name, f"画風: {label}")
                    self.assertEqual(w.canvas.current, len(w.canvas.layers) - 1)
                    n = len(w.canvas.layers)
            finally:
                if old is None:
                    w.settings.store.remove("result_place")
                else:
                    w.settings.set("result_place", old)
                w.dirty = False
                w.close()

    def test_right_click_style_menu_and_mark_only(self):
        """キャンバスの右クリックに「画風の変更」があり、画風が全部並ぶ。赤ペンの印の右クリックからは、その囲みの中だけに掛かる"""
        import numpy as np
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtTest import QTest
        from chatdraw import restyle
        from chatdraw.app import Window, qimage_to_pil
        from chatdraw.engine import Studio
        from chatdraw.tests.test_chatdraw import FakeWords
        from chatdraw.tests.test_editing import app
        qapp = app()

        def sub(menu, title):
            subs = {a.text(): a.menu() for a in menu.actions() if a.menu() is not None}
            self.assertIn(title, subs)
            return subs[title]

        def wait_layer(w, n):
            for _ in range(6000):
                qapp.processEvents()
                if len(w.canvas.layers) > n:
                    return
                time.sleep(0.01)
            self.fail("画風のレイヤーが置かれません")
        with TemporaryDirectory() as d, \
                mock.patch.object(restyle, "check", lambda a, b: dict(drift=0.0, line_kept=1.0, why="")), \
                mock.patch.object(restyle, "WORK_SIDE", 48):
            d = Path(d)
            w = Window(Studio(FakeWords(), self.painter, d))
            old = w.settings.store.value("result_place")
            w.settings.set("result_place", "上のレイヤー")
            w.settings.set("output_dir", str(d / "out"))
            try:
                Image.open(SAMPLE).convert("RGB").resize((160, 240)).save(d / "a.png")
                w.resize(1200, 800)
                w.show()
                w.canvas.replace_with_image(str(d / "a.png"))
                QTest.qWait(50)
                c = w.canvas
                # キャンバスの右クリック: 「画風の変更」の中に、見本の画風と今ある画風が全部並ぶ
                top = w.build_canvas_menu()   # 親のメニューを持っておく（消えると中の小さなメニューも消える）
                m = sub(top, "画風の変更")
                labels = [a.text() for a in m.actions()]
                for want in ("線画", "鉛筆画", "色鉛筆画", "水彩", "墨絵", "ガッシュ画", "アルコールマーカー画",
                             "モノクロ漫画風", "フィギュア風", "ドット絵", "アニメの塗り", "厚塗り", "セル画"):
                    self.assertIn(want, labels)
                self.assertTrue(all(a.toolTip() for a in m.actions()))   # 説明はボタンの中でなくツールチップ
                # 赤ペンで囲み、印の番号の丸の上で右クリックする
                w.tool_actions["redpen"].trigger()
                vp = c.viewport()
                start = c.mapFromScene(c.sceneRect().center()) + QPoint(-20, -20)
                QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
                for i in range(1, 11):
                    QTest.mouseMove(vp, start + QPoint(4 * i, 4 * i))
                QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(40, 40))
                QTest.qWait(20)
                w.note_edit.setText("画風")
                QTest.keyClick(w.note_edit, Qt.Key_Return)
                self.assertEqual(len(c.redpen.marks), 1)
                r = 13 / max(0.05, c.zoom())
                dot = c.redpen.marks[0][0] + QPointF(-r, -r)
                gpos = vp.mapToGlobal(c.mapFromScene(dot))
                mask = np.asarray(qimage_to_pil(c.redpen.masks()[0]).convert("L")) > 0
                before = np.asarray(qimage_to_pil(c.flatten()).convert("RGB")).astype(int)
                n = len(c.layers)
                top2 = w.build_canvas_menu(gpos)
                item = next(a for a in sub(top2, "印 1 の中の画風の変更").actions() if a.text() == "ドット絵")
                self.assertTrue(item.isEnabled())
                item.trigger()
                wait_layer(w, n)
                self.assertEqual(c.layers[-1].name, "画風: ドット絵")
                after = np.asarray(qimage_to_pil(c.flatten()).convert("RGB")).astype(int)
                self.assertEqual(int(np.abs(after - before)[~mask].max()), 0)   # 囲みの外は 1 画素も変えない
                self.assertGreater(int(np.abs(after - before)[mask].max()), 0)  # 囲みの中は描き替わった
            finally:
                if old is None:
                    w.settings.store.remove("result_place")
                else:
                    w.settings.set("result_place", old)
                w.dirty = False
                w.closing_checked = True
                w.close()


if __name__ == "__main__":
    unittest.main()
