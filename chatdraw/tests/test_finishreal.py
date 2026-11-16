"""加工が本当に効くか・壊さないか（finish-verify で本物の模型の絵に掛けて見つけた所の試験）。

- 綺麗にするは、ざらつきのある塗りを目で分かるだけ均し、主線は残す（前は 1 画素 6 までに抑え、混ぜ戻して 0 画素だった）
- 検品の対象でない加工（清書・空気感）に「部品が無いので測っていません」と嘘の知らせを出さない
- 変わった画素の数を知らせる（変わらなかったのに「綺麗にしました」とだけ出さない）
- 画風の加工は、目が消えた・動いた絵を崩れとして強さを下げる
"""
from __future__ import annotations

import importlib.util
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from chatdraw import finishers

HAVE = all(importlib.util.find_spec(m) for m in ("numpy", "scipy"))


def grainy():
    """平らな塗り 2 色に細かいざらつきを載せ、太い主線を引いた絵"""
    import numpy as np
    rng = np.random.default_rng(0)
    a = np.zeros((160, 120, 3), np.float32)
    a[:, :60] = (210, 180, 170)
    a[:, 60:] = (120, 150, 200)
    a += rng.normal(0, 7, a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    d.line((20, 20, 100, 140), fill=(20, 20, 30), width=4)
    d.ellipse((30, 40, 90, 100), outline=(25, 20, 20), width=3)
    return im


@unittest.skipUnless(HAVE, "numpy・scipy が要ります")
class CleanWorksTest(unittest.TestCase):
    def test_clean_visibly_smooths_grain_and_keeps_lines(self):
        import numpy as np
        src = grainy()
        out = finishers._clean_apply(src)
        a, b = np.asarray(src).astype(int), np.asarray(out).astype(int)
        changed = (np.abs(a - b).max(2) > finishers.CHANGE_SEEN).mean()
        self.assertGreater(changed, 0.05)   # 前の作りは 0.3% ほどしか変えなかった
        # 塗りのざらつき（平らな所の揺れ）が減る
        flat = (slice(5, 15), slice(5, 15))
        self.assertLess(b[flat].std((0, 1)).mean(), a[flat].std((0, 1)).mean() * 0.5)
        s = finishers.scores(src, out)
        self.assertGreaterEqual(s["line"], finishers.VERIFY_LINE, s)

    def test_clean_through_run_is_not_mixed_back_to_nothing(self):
        import numpy as np
        src = grainy()
        with mock.patch.object(finishers, "face_keep", lambda im: None), \
                mock.patch.object(finishers, "face_box_keep", lambda im: None):
            out = finishers.run("clean", src)
        a, b = np.asarray(src).astype(int), np.asarray(out).astype(int)
        self.assertGreater((np.abs(a - b).max(2) > finishers.CHANGE_SEEN).mean(), 0.05, finishers.LAST_QC)


class NoteTest(unittest.TestCase):
    def test_unmeasured_group_gives_no_false_numpy_note(self):
        self.assertEqual(finishers.qc_note({"name": "ink"}), "")
        self.assertIn("numpy", finishers.qc_note({"name": "clean", "label": "x", "measured": False}))

    @unittest.skipUnless(HAVE, "numpy が要ります")
    def test_change_note_counts_pixels(self):
        a = Image.new("RGB", (100, 100), (100, 100, 100))
        self.assertIn("ほとんど変わっていません", finishers.change_note(a, a.copy()))
        b = a.copy()
        b.paste((200, 0, 0), (0, 0, 50, 100))
        note = finishers.change_note(a, b)
        self.assertIn("5000 画素", note)
        self.assertNotIn("ほとんど", note)
        self.assertEqual(finishers.change_note(a, a.resize((200, 200))), "")


@unittest.skipUnless(HAVE, "numpy・scipy が要ります")
class RestyleFaceTest(unittest.TestCase):
    def test_vanished_or_moved_eyes_are_broken(self):
        import numpy as np
        from chatdraw import facefeat, restyle
        a = Image.new("RGB", (64, 64), (200, 200, 200))
        f0 = dict(measured=True, face_box=(10, 10, 50, 50), eye=np.float32([50, 50, 80]), eyes=[(0.3, 0.4), (0.7, 0.4)])
        moved = dict(f0, eyes=[(0.3, 0.65), (0.7, 0.4)])
        with mock.patch.object(facefeat, "ready", lambda: True):
            with mock.patch.object(facefeat, "features", side_effect=[f0, dict(measured=True)]):
                self.assertEqual(restyle.face_broken(a, a)["why"], "顔が消える")
            with mock.patch.object(facefeat, "features", side_effect=[f0, moved]):
                self.assertIn("目の位置が崩れる", restyle.face_broken(a, a)["why"])
            with mock.patch.object(facefeat, "features", side_effect=[f0, f0]):
                self.assertEqual(restyle.face_broken(a, a)["why"], "")
        with mock.patch.object(facefeat, "ready", lambda: False):
            self.assertEqual(restyle.face_broken(a, a), {})

    def test_more_strength_steps_before_refusing(self):
        from chatdraw import restyle
        self.assertGreaterEqual(len(restyle.STRENGTH_STEPS), 5)
        self.assertLessEqual(min(restyle.STRENGTH_STEPS), 0.25)


@unittest.skipUnless(HAVE, "numpy が要ります")
class VerifyStatsTest(unittest.TestCase):
    def test_transparency_counts_as_change(self):
        from chatdraw import finish_verify
        a = Image.new("RGB", (40, 40), (255, 255, 255))
        b = a.convert("RGBA")
        b.putalpha(0)
        self.assertEqual(finish_verify.stats(a, b)["changed"], 1600)
        m = Image.new("L", (40, 40), 0)
        m.paste(255, (0, 0, 20, 40))
        self.assertEqual(finish_verify.stats(a, a, m)["outside_changed"], 0)


if __name__ == "__main__":
    unittest.main()
