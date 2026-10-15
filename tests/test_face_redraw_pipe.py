"""顔の描き直し（imgproc.face_redraw）は、渡した模型で描き直し、別の模型を読み込まない。
模型の読み直しは冷えた状態で 552 秒かかった（docs/ROADMAP.md の 0.55 の 12）。描く模型は偽物を渡す"""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))

try:
    import torch  # noqa: F401
    HAS_TORCH = True
except ImportError:   # 画像生成の部品（.cache/gen/lib）が無い環境では飛ばす
    HAS_TORCH = False


class FakePipe:
    def __init__(self):
        self.calls = []
        self.unet = type("U", (), {"encoder_hid_proj": None})()   # 手本を読む部品は付いていない

    def __call__(self, **kw):
        self.calls.append(kw)

        class R:
            images = [Image.new("RGB", (1024, 1024), (255, 0, 0))]
        return R()


@unittest.skipUnless(HAS_TORCH, "torch が無い")
class FaceRedrawPipeTest(unittest.TestCase):
    def test_uses_given_pipe_without_loading(self):
        import demi
        import design
        import imgproc
        old = (demi.img2img, design.encode_xl)
        demi.img2img = lambda: self.fail("別の模型を読み込んだ")
        design.encode_xl = lambda pipe, p, n: (None, None, None, None)
        try:
            pipe = FakePipe()
            im = Image.new("RGB", (200, 300), (0, 0, 255))
            out = imgproc.face_redraw(im, (50, 20, 150, 120), "1girl", pipe=pipe, steps=12, guidance=2.0)
        finally:
            demi.img2img, design.encode_xl = old
        self.assertEqual(len(pipe.calls), 1)
        self.assertEqual(pipe.calls[0]["num_inference_steps"], 12)
        self.assertEqual(pipe.calls[0]["guidance_scale"], 2.0)
        self.assertEqual(out.getpixel((100, 70))[0], 255)      # 枠の真ん中は描き直した色
        self.assertEqual(out.getpixel((5, 5)), (0, 0, 255))     # 枠の外は元のまま


if __name__ == "__main__":
    unittest.main()
