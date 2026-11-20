"""描く処理（engine・phases・pausekeep など）は、画面の部品（PySide6）が無い所でも動く。
Actions の phase-bench は画面の部品を入れずに描くので、描く処理の中で PySide6 を読むと 1 枚も描けずに落ちた（0.5.30 の favmodels、0.5.34 の pausekeep）"""
import builtins
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class NoQt:
    def __enter__(self):
        self.real = builtins.__import__

        def imp(name, *a, **k):
            if name.split(".")[0] == "PySide6":
                raise ImportError("描く処理が PySide6 を読んだ: " + name)
            return self.real(name, *a, **k)
        builtins.__import__ = imp
        return self

    def __exit__(self, *exc):
        builtins.__import__ = self.real


class HeadlessTest(unittest.TestCase):
    def test_pausekeep_root_without_qt(self):
        with NoQt():
            from chatdraw import pausekeep
            self.assertEqual(pausekeep.root().name, "paused")

    def test_precise_without_qt(self):
        with NoQt():
            from chatdraw import favmodels
            favmodels.precise("single", "a")

    def test_phases_draw_without_qt(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow が無い")

        class Painter:
            abilities = (True, True)
            steps = 4
            model = "fake"
            stop = False

            def paint(self, prompt, seed, on_step=None, size=None, **kw):
                return Image.new("RGB", size or (64, 64), (200, 120, 120))

            def redraw(self, prompt, seed, image, mask, **kw):
                return image

            def refine(self, prompt, seed, image, strength=0.5, **kw):
                return image

        class Checks:
            @staticmethod
            def request(image, prompt):
                return {"readable": True, "missing": [], "extra": [], "people": [], "body": []}

            @staticmethod
            def body(image, prompt, tags=None):
                return {"readable": True, "bad": [], "avoid": []}

            @staticmethod
            def pose(image):
                return {"readable": True, "bad": [], "points": 17}

            @staticmethod
            def hands(image, prompt):
                return {"readable": True, "bad": [], "hands": [], "feet": [], "faces": []}

        with NoQt(), TemporaryDirectory() as d:
            from chatdraw import pausekeep, phases
            pausekeep.ROOT = Path(d) / "paused"
            try:
                got = phases.draw(Painter(), "1girl", 1, (64, 64), Path(d) / "k", checks=Checks)
            finally:
                pausekeep.ROOT = None
            self.assertTrue(got["phases"])


if __name__ == "__main__":
    unittest.main()
