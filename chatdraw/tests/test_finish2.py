"""加工のメニュー（メニューバーの「加工」）から、ディテール追加・画風・拡大・綺麗にするを押して最後まで動くか。

- ディテール追加は、前は足した明暗が SSIM の混ぜ戻しで半分以下になり、見本で変わりの平均が 0.79（0〜255）しかなく効いて見えなかった
- 画風は右クリックにしか無かった。加工のメニューからも選べる
- 拡大の言葉は、何倍か・どれくらいかかるか・元の絵がどうなるかを書く
- まとめて綺麗にするは、工程ごとに部位分け（CPU で 1 回 30〜40 秒）を測り直していた。元の絵の 1 回で足りる
- 綺麗にするの検品は、暗い平らな塗りが 6 揺れて明るさ 90 を越えただけで線が消えたと数え、塗りを元に戻していた
本物の部位分け・手の模型と、試験用の小さな SDXL で流す（無ければ飛ばす）
"""
import importlib.util
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

from PIL import Image, ImageDraw  # noqa: E402

from chatdraw import finishers  # noqa: E402

SAMPLE = ROOT / "library" / "daily" / "2026-10-13" / "05-yukionna.png"
HAVE = all(importlib.util.find_spec(m) is not None for m in ("PySide6", "numpy", "scipy", "skimage"))


def window(d: Path, painter=None):
    from chatdraw.app import Window
    from chatdraw.engine import Studio
    from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
    from chatdraw.tests.test_editing import app
    qapp = app()
    w = Window(Studio(FakeWords(), painter or FakePainter(), d))
    w.settings.set("output_dir", str(d / "out"))
    return qapp, w


def menu_action(w, sid: str):
    w._fill_finish_menu()
    for sub in w.finish_menu.actions():
        if sub.menu() is None:
            continue
        for a in sub.menu().actions():
            if a.objectName() == "menu-" + sid:
                return sub.text(), a
    raise AssertionError(f"加工のメニューに {sid} がありません")


def wait_done(qapp, w, n_layers: int, limit: float = 600):
    t = time.time()
    while time.time() - t < limit:
        qapp.processEvents()
        if w.thread is None and len(w.canvas.layers) > n_layers:
            return time.time() - t
        time.sleep(0.02)
    raise AssertionError("加工が終わりませんでした")


@unittest.skipUnless(HAVE, "PySide6・numpy・scipy・scikit-image が要ります")
class FinishMenuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.src = Image.open(SAMPLE).convert("RGB")
        self.src.save(self.d / "a.png")

    def tearDown(self):
        self.tmp.cleanup()

    def test_menu_has_groups_and_style(self):
        from chatdraw import restyle
        qapp, w = window(self.d)
        try:
            self.assertIn("加工", [a.text() for a in w.menuBar().actions()])
            w._fill_finish_menu()
            subs = {a.text(): a.menu() for a in w.finish_menu.actions() if a.menu() is not None}
            for g in ("綺麗にする", "まとめて", "ディテール", "拡大", "画風"):
                self.assertIn(g, subs)
            styles = [a.text() for a in subs["画風"].actions()]
            self.assertEqual(styles, [s[1] for s in restyle.STYLES])
            self.assertTrue(all(a.toolTip() for m in subs.values() for a in m.actions()))
        finally:
            w.dirty = False
            w.close()

    def test_upscale_words(self):
        qapp, w = window(self.d)
        try:
            tips = [menu_action(w, sid)[1].toolTip() for sid in ("app:upscale2x", "fin:upscale_anime")]
            tips.append(w.ai_panel.upscale_button.toolTip())
            for t in tips:
                if "torch" in t:   # 部品が無い環境では理由が出る
                    continue
                self.assertIn("2 倍", t)
                self.assertIn("目安", t)
                self.assertIn("置き換", t)
        finally:
            w.dirty = False
            w.close()

    def test_detail_from_menu_is_visible_and_keeps_face(self):
        import numpy as np
        from chatdraw import facefeat
        qapp, w = window(self.d)
        try:
            w.edit_image(str(self.d / "a.png"))
            n = len(w.canvas.layers)
            group, act = menu_action(w, "fin:detail")
            self.assertEqual(group, "ディテール")
            self.assertTrue(act.isEnabled(), act.toolTip())
            from chatdraw.app import qimage_to_pil
            before = np.asarray(qimage_to_pil(w.canvas.flatten()).convert("RGB"), float)
            act.trigger()
            sec = wait_done(qapp, w, n)
            self.assertEqual(w.canvas.layers[-1].name, "エフェクト: ディテール追加")
            after = np.asarray(qimage_to_pil(w.canvas.flatten()).convert("RGB"), float)
            diff = float(np.abs(after - before).mean())
            q = finishers.LAST_QC
            print(f"\nディテール追加（加工のメニュー）: {sec:.1f} 秒、変わりの平均 {diff:.2f}、検品 {q.get('verify', {}).get('ssim')}", file=sys.stderr)
            self.assertGreater(diff, 1.2)   # 前は 0.79
            self.assertFalse(q.get("rejected"))
            fr = q.get("features") or {}
            if fr.get("measured"):
                after_d = fr.get("after") or {}
                self.assertLessEqual(after_d.get("eye", 0), facefeat.EYE_COLOR)
                self.assertLessEqual(after_d.get("move", 0), facefeat.EYE_MOVE)
        finally:
            w.dirty = False
            w.close()

    def test_detail_mask_outside_is_untouched(self):
        m = Image.new("L", self.src.size, 0)
        ImageDraw.Draw(m).rectangle((100, 300, 400, 600), fill=255)
        out = finishers.run("detail", self.src, m)
        outside = Image.new("L", self.src.size, 255)
        ImageDraw.Draw(outside).rectangle((100 - finishers.PAD, 300 - finishers.PAD, 400 + finishers.PAD, 600 + finishers.PAD), fill=0)
        import numpy as np
        o, s, k = np.asarray(out), np.asarray(self.src), np.asarray(outside) > 0
        self.assertEqual(int((o[k] != s[k]).any(1).sum()), 0)
        inside = (o[300:600, 100:400] != s[300:600, 100:400]).any(2).sum()
        self.assertGreater(int(inside), 1000)

    def test_tidy_from_menu_segments_once(self):
        from chatdraw import facefeat
        edit = finishers._gen("edit")
        calls = []
        real = edit.parts

        def counted(p):
            calls.append(p)
            return real(p)
        facefeat._SEG.clear()
        finishers._FACES.clear()
        finishers._SEGS.clear()
        finishers._HANDS.clear()
        qapp, w = window(self.d)
        try:
            w.edit_image(str(self.d / "a.png"))
            n = len(w.canvas.layers)
            group, act = menu_action(w, "combo:tidy")
            self.assertEqual(group, "まとめて")
            with mock.patch.object(edit, "parts", counted):
                act.trigger()
                sec = wait_done(qapp, w, n)
            broken = sum(q.get("broken") or 0 for q in finishers.LAST_CHAIN)
            back = sum(len((q.get("features") or {}).get("back") or []) for q in finishers.LAST_CHAIN)
            print(f"\nまとめて綺麗にする（加工のメニュー）: {sec:.1f} 秒、部位分け {len(calls)} 回、崩れた区画 {broken}、"
                  f"目・髪を戻した所 {back}", file=sys.stderr)
            if facefeat.ready():
                self.assertEqual(len(calls), 1)   # 前は工程ごとに 2 回
            self.assertEqual(w.canvas.layers[-1].name, "綺麗にした絵")
            self.assertFalse(any(q.get("rejected") for q in finishers.LAST_CHAIN))
        finally:
            w.dirty = False
            w.close()

    def test_dark_fill_jitter_is_not_lost_line(self):
        import numpy as np
        a = np.full((64, 64, 3), 89.0)
        b = a + 4.0   # 塗りのむらを均した揺れ（CLEAN_CAP 以下）で明るさ 90 を越えた
        _bad, why = finishers.breakage(a, b)
        self.assertEqual(why["line"], 0)
        c = a.copy()
        c[:, :] = 200.0   # 本当に線が消えた
        _bad, why = finishers.breakage(a, c)
        self.assertGreater(why["line"], 0)


def _tiny():
    from chatdraw.tests import test_finish_quality as q
    return q.tiny_painter() if q.tiny_ready() else None


@unittest.skipUnless(HAVE, "PySide6・numpy・scipy・scikit-image が要ります")
class StyleFromMenuTest(unittest.TestCase):
    def test_style_from_finish_menu_goes_on_top(self):
        from chatdraw import restyle
        painter = _tiny()
        if painter is None:
            self.skipTest("試験用の小さな SDXL が取れません")
        finishers.use_painter(painter)
        with TemporaryDirectory() as d, \
                mock.patch.object(restyle, "check", lambda a, b: dict(drift=0.0, line_kept=1.0, why="")), \
                mock.patch.object(restyle, "WORK_SIDE", 48):
            d = Path(d)
            Image.open(SAMPLE).convert("RGB").resize((32, 48), Image.LANCZOS).save(d / "a.png")
            qapp, w = window(d, painter)
            try:
                w.edit_image(str(d / "a.png"))
                n = len(w.canvas.layers)
                kind, label = restyle.STYLES[0][0], restyle.STYLES[0][1]
                group, act = menu_action(w, f"fin:style_{kind}")
                self.assertEqual(group, "画風")
                self.assertTrue(act.isEnabled(), act.toolTip())
                act.trigger()
                wait_done(qapp, w, n)
                self.assertEqual(w.canvas.layers[-1].name, f"画風: {label}")
                self.assertEqual(w.canvas.current, len(w.canvas.layers) - 1)
            finally:
                finishers.use_painter(None)
                w.dirty = False
                w.close()


if __name__ == "__main__":
    unittest.main()
