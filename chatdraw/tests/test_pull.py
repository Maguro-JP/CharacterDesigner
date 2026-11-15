"""新しく描く頼みが、前に描いた絵や前の頼みに引っ張られないか。進みのポップアップと透過も、窓から押して確かめる。

偽の模型（diffusers の偽物と、渡った物を覚える描き手）で、2 回目の頼みに 1 回目の何か
（頼みの言葉、種、ラフにしたキャンバスの絵、参考画像、参考画像の部品、ライブラリーの好み）が渡っていないかを見る。
"""
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

from chatdraw import engine  # noqa: E402
from chatdraw.tests.test_drawbugs import fake_diffusers, fake_torch  # noqa: E402

SHOTS = os.environ.get("CD_SHOTS")   # 写しを撮る置き場（自分で見るとき）


class EnginePullTest(unittest.TestCase):
    """読んだ模型を使い回しても、1 回目の付け足しが 2 回目に残らない"""

    def run_two(self, repo="cagliostrolab/animagine-xl-4.0"):
        log = []
        mod = fake_diffusers(log)
        pipe_cls = mod.StableDiffusionXLPipeline
        pipe_cls.load_ip_adapter = lambda self, *a, **k: log.append(("ip", "load"))
        pipe_cls.set_ip_adapter_scale = lambda self, s: log.append(("ip", "scale", s))
        pipe_cls.unload_ip_adapter = lambda self: log.append(("ip", "unload"))
        with TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"diffusers": mod, "torch": fake_torch()}), \
                mock.patch.object(engine, "free_ram_gb", return_value=0.0), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"):
            painter = engine.Painter(repo, steps=28, guidance=5.0)
            st = engine.Studio(engine.Words(Path("")), painter, Path(d))
            st.way = "one"
            ref = Image.new("RGB", (64, 64), "red")
            st.draw("1girl, red scarf, snow", 11, size=(832, 1216), reference=ref)
            first = len(log)
            st.draw("1boy, knight, armor", 22, size=(832, 1216))
        calls = [x[2] for x in log if x[0] == "call"]
        return log, first, calls, painter

    def test_second_request_gets_nothing_from_first(self):
        log, first, calls, painter = self.run_two()
        a, b = calls[0], calls[-1]
        self.assertIn("ip_adapter_image", a)              # 1 回目は参考画像を渡した
        self.assertNotIn("ip_adapter_image", b)           # 2 回目には渡さない
        self.assertIn(("ip", "unload"), log[first:])      # 参考画像の部品を外してから描く
        self.assertFalse(painter._ref)
        self.assertNotIn("red scarf", b["prompt"])        # 前の頼みの言葉が残らない
        self.assertNotIn("snow", b["prompt"])
        self.assertIn("knight", b["prompt"])
        self.assertEqual(b["num_inference_steps"], a["num_inference_steps"])   # 工程と頼みの効きは変えない
        self.assertEqual(b["guidance_scale"], a["guidance_scale"])
        self.assertEqual(b.get("negative_prompt", ""), a.get("negative_prompt", ""))

    def test_sdxl_draws_at_trained_size(self):
        """SDXL は約 100 万画素で描き、頼んだ大きさに戻す（小さいキャンバスのまま渡すと崩れた）"""
        self.assertEqual(engine.native_size((832, 1216), "sdxl"), (832, 1216))
        w, h = engine.native_size((400, 600), "sdxl")
        self.assertGreater(w * h, 832 * 1216 * 0.85)
        w, h = engine.native_size((2000, 3000), "sdxl")
        self.assertLess(w * h, 832 * 1216 * 1.15)

    def test_card_scheduler(self):
        """札が Euler a を推す模型は、読んだあとに Euler a に替える"""
        from chatdraw.models import image_model
        for repo in ("cagliostrolab/animagine-xl-4.0", "Laxhar/noobai-XL-1.1", "OnomaAIResearch/Illustrious-xl-early-release-v0"):
            self.assertEqual(image_model(repo).scheduler, "euler_a", repo)
        self.assertFalse(image_model("Laxhar/noobai-XL-Vpred-1.0").scheduler)   # v-pred は札どおり Euler（v_prediction）


class CutTest(unittest.TestCase):
    def test_drop_props_without_parts_model(self):
        """部位分けの模型が無くても、切り抜きは落ちずにそのまま返る（前は透過全体が落ちた）"""
        from chatdraw import paths
        paths.use_tools_gen()
        try:
            import layers
        except Exception as e:   # noqa: BLE001  numpy などが無い機械では見ない
            self.skipTest(str(e))
        with TemporaryDirectory() as d:
            src = Path(d) / "a.png"
            Image.new("RGB", (32, 32), "white").save(src)
            cut = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
            fake_edit = mock.MagicMock()
            fake_edit.parts.side_effect = RuntimeError("部位分けの模型がありません")
            with mock.patch.dict(sys.modules, {"edit": fake_edit}):
                out = layers.drop_props(str(src), cut)
            self.assertIs(out, cut)


class WindowPullTest(unittest.TestCase):
    """窓から「描く」を押して、2 回目の頼みに 1 回目の物が渡らないことを見る"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords

        class Slow(FakePainter):
            def paint(self, prompt, seed, on_step=None, **kw):
                self.calls.append((prompt, seed))
                self.kws = getattr(self, "kws", []) + [kw]
                prev = kw.get("on_preview")
                for i in range(4):
                    time.sleep(0.15)
                    if on_step:
                        on_step(i + 1, 4)
                    if prev:
                        prev(Image.new("RGB", (64, 96), (40 * i, 120, 200)))
                return Image.new("RGB", (64, 96), "white")
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = TemporaryDirectory()
        cls.painter = Slow()
        cls.w = Window(engine.Studio(FakeWords(), cls.painter, Path(cls.tmp.name)))
        cls.w.resize(1400, 900)
        cls.w.show()
        cls.w.check_ai = lambda: {"torch": True, "image": True, "words": True, "reason": ""}
        cls.spin(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.w.dirty = False   # 閉じる前の保存の問いを出さない
        cls.w.close()
        cls.tmp.cleanup()

    @classmethod
    def spin(cls, s=0.3):
        end = time.time() + s
        while time.time() < end:
            cls.app.processEvents()

    def wait_done(self, limit=20.0, shot=None):
        end = time.time() + limit
        took = False
        while time.time() < end and self.w.thread is not None:
            self.spin(0.1)
            if shot and not took and self.w.progress_popup.thumb.isVisible():
                self.spin(0.3)
                self.w.grab().save(shot)
                took = True
        self.spin(0.3)
        self.assertIsNone(self.w.thread)

    def draw(self, text, shot=None):
        self.w.entry.setText(text)
        self.w.send()
        self.wait_done(shot=shot)

    def test_rough_then_new(self):
        w, p = self.w, self.painter
        w.ai_panel.seed_lock.setChecked(False)
        w.mode.setCurrentIndex(1)    # 利用者がラフからを選んだ 1 回目
        self.draw("赤いマフラーの女の子")
        self.assertIsNotNone(p.kws[-1].get("base"))
        self.assertEqual(w.mode.currentIndex(), 0)   # 描き終えたら新規に戻る
        self.draw("1boy, knight, armor")   # 偽の言葉の模型は日本語を決まった言葉に直すので、英語で頼む
        last = p.kws[-1]
        self.assertIsNone(last.get("base"))          # 前の絵を下描きにしない
        self.assertIsNone(last.get("reference"))
        self.assertNotIn("scarf", p.calls[-1][0])
        self.assertNotEqual(p.calls[-1][1], p.calls[-2][1])   # 種を固定していなければ種も変わる

    def test_taste_off_by_default(self):
        """ライブラリーの好みは、利用者が入れたときだけ頼みに足す"""
        w = self.w
        w.layout_store.remove("use_taste")
        with mock.patch.object(type(w.library), "profile", return_value={"tags": ["old_tag"], "avoid": ["old_avoid"]}):
            self.assertNotIn("old_tag", w.ai_panel.style_tags())
            w._apply_avoid()
            self.assertNotIn("old_avoid", getattr(w.studio.painter, "avoid", ""))

    def test_popup_shows_sheet_thumb_and_short_error(self):
        w = self.w
        pop = w.progress_popup
        w.panels["progress"][0].show()   # 進みの欄が見えていても、ポップアップは出す
        w.ai_panel.set_count(2)
        try:
            w.entry.setText("猫耳の少女 笑顔")
            w.send()
            seen = set()
            end = time.time() + 20
            shot = os.path.join(SHOTS, "popup-drawing.png") if SHOTS else None
            while time.time() < end and w.thread is not None:
                self.spin(0.1)
                if pop.isVisible():
                    seen.add(pop.title.text())
                if shot and pop.thumb.isVisible() and "2/2" in pop.title.text():
                    w.grab().save(shot)
                    shot = None
            self.spin(0.3)
        finally:
            w.ai_panel.set_count(1)
            w.panels["progress"][0].hide()
        self.assertTrue(any("1/2 枚目" in t for t in seen), seen)
        self.assertTrue(any("2/2 枚目" in t for t in seen), seen)
        self.assertTrue(pop.thumb.pixmap() is not None and not pop.thumb.pixmap().isNull())
        long = "描けませんでした: 模型のファイル model.safetensors が足りません（置き場 C:/LLM/hub を確かめてください）" * 2
        w.fail(long)
        self.spin(0.5)
        self.assertLessEqual(len(pop.title.text()), 20)
        self.assertTrue(pop.more.isVisible())
        self.assertFalse(pop.details.isVisible())     # 詳しい中身は折りたたむ
        pop.more.setChecked(True)
        self.spin(0.3)
        self.assertTrue(pop.details.isVisible())
        self.assertIn("C:/LLM/hub", pop.details.text())
        if SHOTS:
            w.grab().save(os.path.join(SHOTS, "popup-error.png"))
        pop.more.setChecked(False)

    def test_transparent_hides_below(self):
        """透過の結果は一番上に置き、下の絵を隠して透明の所を見せる。書き出す絵も透明のまま"""
        from PySide6.QtGui import QColor
        w = self.w
        c = w.canvas
        img = c.layers[0].image
        img.fill(QColor("#a0a8b8"))
        c.rebuild()
        before = len(c.layers)

        def fake_anime_cut(path):
            im = Image.open(path).convert("RGBA")
            im.putalpha(Image.new("L", im.size, 0))
            im.paste(Image.new("RGBA", (40, 60), (200, 120, 90, 255)), (im.width // 2 - 20, im.height // 2 - 30))
            return im
        fake_layers = mock.MagicMock()
        fake_layers.anime_cut.side_effect = fake_anime_cut
        with mock.patch.dict(sys.modules, {"layers": fake_layers}):
            w.make_transparent()
            end = time.time() + 15
            while time.time() < end and len(c.layers) == before:
                self.spin(0.1)
        self.spin(0.3)
        self.assertEqual(c.layers[-1].name, "透過")
        self.assertTrue(all(not lay.visible for lay in c.layers[:-1]))
        flat = c.flatten()
        self.assertEqual(flat.pixelColor(2, 2).alpha(), 0)
        self.assertEqual(flat.pixelColor(flat.width() // 2, flat.height() // 2).alpha(), 255)
        if SHOTS:
            w.grab().save(os.path.join(SHOTS, "transparent.png"))
        c.undo()


if __name__ == "__main__":
    unittest.main()
