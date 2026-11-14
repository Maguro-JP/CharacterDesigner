"""担当編集者（chatdraw/director.py）: サボりの検品と工程の記録が、アプリの経路で効くこと"""
import glob
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFilter

from chatdraw.tests.test_chatdraw import FakePainter, FakeWords

ROOT = Path(__file__).resolve().parents[2]


def good_picture(size=(256, 384)):
    """見本の絵。無ければ線と塗りのある絵を作る"""
    fs = sorted(glob.glob(str(ROOT / "library/samples/people/*.png")) + glob.glob(str(ROOT / "library/samples/people/*.jpg")))
    if fs:
        return Image.open(fs[0]).convert("RGB").resize(size)
    im = Image.new("RGB", size, "#f4efe6")
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.ellipse((20 + i * 9, 30 + i * 13, 120 + i * 9, 150 + i * 13), fill=(200 - i * 9, 120 + i * 5, 90), outline="black", width=2)
    return im


class SlackPainter(FakePainter):
    """初めは色だけの絵を返し、そのあとまともな絵を返す偽の模型"""

    def __init__(self, lazy=1):
        super().__init__()
        self.lazy = lazy

    def paint(self, prompt, seed, on_step=None, **kw):
        self.calls.append((prompt, seed))
        if on_step:
            on_step(1, 1)
        if len(self.calls) <= self.lazy:
            return Image.new("RGB", (256, 384), "#d9a0a0")
        return good_picture()


class SlackCheckTest(unittest.TestCase):
    def test_lazy_pictures_are_caught(self):
        from chatdraw import director
        good = good_picture()
        self.assertEqual(director.slack(good)["bad"], [])
        lazy = {"単色": Image.new("RGB", (256, 384), "#c88"),
                "ぼかし": good.filter(ImageFilter.GaussianBlur(12)),
                "グラデーション": Image.linear_gradient("L").resize((256, 384)).convert("RGB"),
                "ノイズ": Image.merge("RGB", [Image.effect_noise((256, 384), 80) for _ in range(3)])}
        for name, im in lazy.items():
            self.assertTrue(director.slack(im)["bad"], name)
        mask = Image.new("L", good.size, 0)
        ImageDraw.Draw(mask).rectangle((50, 50, 150, 150), fill=255)
        self.assertIn("直していない: 頼んだ所が元の絵とほぼ同じ", director.slack(good, good, mask)["bad"])
        moved = good.copy()
        moved.paste((0, 0, 0), (0, 300, 256, 384))
        self.assertIn("頼んだ所の外が変わった", director.slack(moved, good, mask)["bad"])

    def test_no_person(self):
        from chatdraw import director
        self.assertEqual(director.no_person("1girl, red scarf", {"readable": True, "read": {"cat": 0.9}}), ["人を頼んだのに人がいない"])
        self.assertEqual(director.no_person("1girl", {"readable": True, "read": {"1girl": 0.9}}), [])
        self.assertEqual(director.no_person("cat", {"readable": True, "read": {}}), [])

    def test_thresholds_on_library(self):
        """境目: library の絵（すべて絵になっている）は 1 枚も落とさない"""
        from chatdraw import director
        fs = [f for f in glob.glob(str(ROOT / "library/**/*.*"), recursive=True)
              if f.endswith((".jpg", ".png")) and ".parts" not in f and ("/feedback/" in f or "/samples/" in f)]
        wrong = []
        for f in fs:
            try:
                im = Image.open(f).convert("RGB")
            except Exception:
                continue
            if director.slack(im)["bad"]:
                wrong.append(f)
        self.assertEqual(wrong, [])


def meta_of(path):
    from chatdraw.finishers import KEY
    return json.loads(Image.open(path).text[KEY])


def run_window(w, app, cond, n=600):
    for _ in range(n):
        app.processEvents()
        if cond():
            return True
        w.thread and w.thread.wait(10)
        time.sleep(0.01)
    return False


class AppPathTest(unittest.TestCase):
    def draw(self, painter):
        from chatdraw.app import Window
        from chatdraw.engine import Studio
        from chatdraw.tests.test_editing import app
        a = app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        studio = Studio(FakeWords(), painter, Path(d.name))
        studio.REDRAW_TRIES = 4
        w = Window(studio)
        w.entry.setText("1girl, red scarf")
        w.send()
        run_window(w, a, lambda: w.images and not w.thread and not w.activity.background)
        self.addCleanup(lambda: (setattr(w, "closing_checked", True), w.close()))
        return w, studio

    def test_lazy_is_recorded_not_redrawn(self):
        """色だけの絵は知らせて記録するだけ。描き直しには繋げない（描く流れは 1 回で終える）"""
        p = SlackPainter(lazy=99)
        w, studio = self.draw(p)
        meta = meta_of(w.images[0])
        rec = meta["director"]
        st = {s["name"]: s for s in rec["stages"]}
        self.assertEqual(st["描き直す"]["tries"], 0)
        self.assertIn("絵になっていない", st["検品"]["result"])
        self.assertIn("red scarf", st["描く"]["sent"][0]["prompt"])   # 模型に渡した言葉を工程ごとに残す
        self.assertTrue(all("sec" in s and "done_when" in s for s in rec["stages"]))
        log = "\n".join(w.activity.editor_log)
        self.assertIn("記録だけ", log)
        self.assertNotIn("担当編集者: 描き直す", log)
        self.assertIn("担当編集者: 仕上げ", w.activity.editor.text())

    def test_good_passes_first(self):
        p = SlackPainter(lazy=0)
        w, studio = self.draw(p)
        self.assertEqual(len(p.calls), 1)
        self.assertNotIn("担当編集者: 描き直す", "\n".join(w.activity.editor_log))


def _tiny():
    from chatdraw.tests.test_finish_quality import TINY, tiny_ready
    return TINY if tiny_ready() else None


@unittest.skipUnless(_tiny(), "試験用の小さな SDXL が取れません")
class RealModelTest(unittest.TestCase):
    def test_tiny_model_through_director(self):
        """小さな本物の模型で描いても、担当編集者が工程を記録すること"""
        from chatdraw.engine import Painter, Studio
        with TemporaryDirectory() as d:
            st = Studio(FakeWords(), Painter(_tiny(), steps=2, size=(256, 256)), Path(d))
            st.REDRAW_TRIES = 2
            lines = []
            _prompt, path = st.draw("1girl, red scarf", 1, on_status=lines.append, size=(256, 256))
            rec = meta_of(path)["director"]
            print("tiny:", [(s["name"], s["tries"], s["result"]) for s in rec["stages"]],
                  meta_of(path)["redraws"])
            self.assertGreaterEqual({s["name"]: s for s in rec["stages"]}["描く"]["tries"], 1)
            self.assertTrue(any(l.startswith("担当編集者:") for l in lines))


if __name__ == "__main__":
    unittest.main()
