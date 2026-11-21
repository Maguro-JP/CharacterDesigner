"""工程に分けて、AI が筆を動かして描く（chatdraw/phases.py、chatdraw/strokes.py）を確かめる。

- 工程は人の描き方の順で 15 あり、模型が描くのは下絵だけ（崩れたときの描き直しも 1 回だけ）。あとは筆の線を置いて描く
- 各工程は検品 1 回・直し 1 回で必ず終わる（0.5.20 で「検品を通るまで直す」にしたら終わらなくなった）
- 進みの欄は「工程 i/N 名前」を出し、最後の工程まで 100% にしない（前は 1 工程目の下絵の i/n で帯が満ち、完了に見えた）
- 本物と同じ経路を、試験用の小さな SDXL で通す
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw import phases, strokes  # noqa: E402
from chatdraw.engine import Stopped, Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402

HAND = {"readable": True, "bad": ["手 1: 指が 6 本"], "hands": [{"box": [10, 10, 30, 30], "bad": ["指が 6 本"], "seen": True}],
        "feet": [], "faces": []}
CLEAN_HAND = {"readable": True, "bad": [], "hands": [], "feet": [], "faces": []}
NAMES = ["下絵", "アタリ", "構図", "体の線", "顔の線", "髪の線", "服の線", "線画の清書", "下塗り", "影 1 段目", "影 2 段目", "光",
         "目", "髪の艶", "仕上げ"]


def figure(size=(96, 144)):
    """頭（肌と髪）と服の体のある、簡単な人の形の絵（筆の線と部位が取れるように）"""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", size, (250, 250, 250))
    d = ImageDraw.Draw(im)
    d.rectangle([w * .3, h * .3, w * .7, h * .95], fill=(60, 80, 160), outline=(20, 20, 40))   # 服
    d.rectangle([w * .3, h * .62, w * .7, h * .95], fill=(40, 55, 120))                         # 服の影
    d.ellipse([w * .32, h * .05, w * .68, h * .32], fill=(236, 204, 186), outline=(30, 20, 20))  # 顔
    d.pieslice([w * .3, h * .03, w * .7, h * .3], 180, 360, fill=(120, 70, 40))                  # 髪
    d.ellipse([w * .4, h * .18, w * .45, h * .22], fill=(20, 20, 60))                            # 目
    d.ellipse([w * .55, h * .18, w * .6, h * .22], fill=(20, 20, 60))
    return im


class Painter(FakePainter):
    steps = 20

    def __init__(self):
        super().__init__()
        self.log = []
        self.unloaded = 0

    def paint(self, prompt, seed, on_step=None, **kw):
        self.log.append(("paint", prompt, seed))
        if on_step:
            for i in range(1, 5):
                on_step(i, 4)
        return figure()

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        self.log.append(("redraw", prompt, seed))
        return image

    def unload(self):
        self.unloaded += 1


def checks(always_bad: bool):
    """always_bad: どの検品も毎回崩れを返す（直しても消えない）。False: 1 回目だけ崩れを返す"""
    seen = {"request": 0, "body": 0, "hands": 0, "pose": 0}

    class C:
        @staticmethod
        def request(image, prompt):
            seen["request"] += 1
            bad = always_bad or seen["request"] == 1
            return {"readable": True, "missing": ["red scarf"] if bad else [], "extra": [], "people": [], "body": []}

        @staticmethod
        def body(image, prompt, tags=None):
            seen["body"] += 1
            return {"readable": True, "bad": ["余分な腕"] if always_bad else [], "avoid": []}

        @staticmethod
        def pose(image):
            seen["pose"] += 1
            return {"readable": True, "bad": ["骨の長さの比が外れている"] if always_bad else [], "map": image}

        @staticmethod
        def hands(image, prompt):
            seen["hands"] += 1
            return dict(HAND) if (always_bad or seen["hands"] == 1) else dict(CLEAN_HAND)
    return C, seen


class PhasesTest(unittest.TestCase):
    def run_phases(self, always_bad, painter=None):
        painter = painter or Painter()
        C, seen = checks(always_bad)
        said, frames = [], []
        with TemporaryDirectory() as d:
            got = phases.draw(painter, "1girl, red scarf", 5, (96, 144), Path(d) / "k", say=said.append, checks=C,
                              on_preview=frames.append)
            files = sorted(p.name for p in (Path(d) / "k").iterdir())
        return got, painter, seen, said, files, frames

    def test_phases_follow_human_order(self):
        self.assertEqual([p[0] for p in phases.PHASES], NAMES)
        got, painter, seen, said, files, frames = self.run_phases(always_bad=True)
        self.assertEqual([r["phase"] for r in got["phases"]], NAMES)
        self.assertIn("phases.json", files)
        self.assertIn("01-下絵.png", files)
        self.assertIn("15-仕上げ.png", files)

    def test_model_draws_only_the_reference_and_brush_does_the_rest(self):
        got, painter, seen, said, files, frames = self.run_phases(always_bad=True)
        # 下絵 1 回 + 崩れたときの描き直し 1 回だけ。模型での描き直し（redraw）はしない
        self.assertEqual([x[0] for x in painter.log], ["paint", "paint"])
        self.assertGreaterEqual(painter.unloaded, 1)   # 下絵のあとに模型を降ろす
        lines = sum(r["strokes"] for r in got["phases"])
        self.assertGreater(lines, 50)   # 筆の線を置いている
        for name in ("線画の清書", "下塗り"):
            self.assertGreater(next(r for r in got["phases"] if r["phase"] == name)["strokes"], 0, name)
        self.assertGreaterEqual(len(frames), 20)   # 筆を置く途中の絵が出ている（キャンバスに重なり、タイムラプスに残る）

    def test_one_check_and_one_fix_each(self):
        got, painter, seen, *_ = self.run_phases(always_bad=True)
        self.assertEqual(seen["request"], 2)   # 下絵の検品と、描き直したあとの 1 回
        self.assertEqual(seen["pose"], 1)
        self.assertLessEqual(seen["hands"], 2)   # 仕上げの検品と、直したあとの 1 回
        self.assertTrue(got["left"])   # 崩れが残っても終わる（残った崩れを返す）

    def test_clean_after_first_fix(self):
        got, painter, seen, *_ = self.run_phases(always_bad=False)
        self.assertTrue(got["checked"])
        self.assertEqual(sum(1 for x in painter.log if x[0] == "paint"), 2)

    def test_no_words_added(self):
        """模型に渡す言葉は頼みの訳だけ"""
        got, painter, *_ = self.run_phases(always_bad=True)
        self.assertEqual({x[1] for x in painter.log}, {"1girl, red scarf"})
        for r in got["phases"]:
            for w in r["words"]:
                self.assertEqual(w, "1girl, red scarf")

    def test_each_phase_is_light_and_reports_progress(self):
        got, painter, seen, said, files, frames = self.run_phases(always_bad=False)
        heads = [s for s in said if s.startswith("工程 ")]
        for i, name in enumerate(NAMES, 1):
            self.assertTrue(any(s.startswith(f"工程 {i}/{len(NAMES)}「{name}」") for s in heads), name)
        self.assertTrue(any("（" in s and "/4）" in s for s in heads))   # 下絵の進みも工程の見出しの中で出る
        self.assertFalse(any(s.startswith("描いています（") for s in said))   # 帯を満たして完了に見せた知らせは出さない
        for r in got["phases"][1:]:
            self.assertLess(r["seconds"], 10, r["phase"])
            self.assertIn("rss_mb", r)

    def test_memory_is_freed_each_phase(self):
        import gc
        n = [0]
        real = gc.collect

        def counted(*a):
            n[0] += 1
            return real(*a)
        with mock.patch.object(gc, "collect", counted):
            self.run_phases(always_bad=False)
        self.assertGreaterEqual(n[0], len(NAMES))

    def test_stop_between_phases(self):
        painter = Painter()
        C, _ = checks(always_bad=True)
        orig = C.pose

        def pose(image):
            painter.stop = True   # アタリの検品のあとに止める
            return orig(image)
        C.pose = staticmethod(pose)
        with TemporaryDirectory() as d, self.assertRaises(Stopped):
            phases.draw(painter, "1girl", 1, (96, 144), Path(d) / "k", checks=C)

    def test_plain_white_reference_still_finishes(self):
        painter = FakePainter()   # 真っ白の下絵（線も部位も無い）でも最後の工程まで通る
        C, _ = checks(always_bad=True)
        with TemporaryDirectory() as d:
            got = phases.draw(painter, "1girl", 1, (64, 96), Path(d) / "k", checks=C)
        self.assertEqual(len(got["phases"]), len(NAMES))

    def test_studio_way_phases(self):
        with TemporaryDirectory() as d:
            painter = Painter()
            s = Studio(FakeWords(), painter, Path(d))
            s.way = "phases"
            said = []
            prompt, path = s.draw("赤いマフラーの子", 7, said.append)
            self.assertEqual(prompt, "1girl, red scarf")   # 背景や構図の言葉を足さない
            self.assertTrue(path.exists())
            self.assertEqual([r["phase"] for r in s.last_phases], NAMES)
            s.way = "one"
            s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertIsNone(s.last_phases)


class StrokesTest(unittest.TestCase):
    def test_parts_and_lines_from_reference(self):
        p = strokes.plan(figure((192, 288)))
        self.assertIn("肌", p.parts)
        self.assertIn("服", p.parts)
        self.assertGreater(len(strokes.trace(p.edges)), 5)
        self.assertGreater(len(strokes.runs(p.parts["服"])), 5)

    def test_paper_places_strokes(self):
        paper = strokes.Paper((100, 100), 2.0)
        paper.stroke([(5, 5), (40, 40)], (255, 0, 0), 2)
        self.assertEqual(paper.strokes, 1)
        self.assertEqual(paper.layer.getpixel((50, 50))[3], 255)
        self.assertEqual(paper.layer.getpixel((95, 5))[3], 0)


class ActivityPhaseTest(unittest.TestCase):
    """進みの欄は工程の番号と名前を出し、1 工程目の終わりで完了に見せない"""

    def test_phase_progress(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from chatdraw.activity import ActivityPanel
        p = ActivityPanel()
        p.begin("x", "描く")
        p.status("工程 1/15「下絵」 下絵（4/4）", 4, 4)
        self.assertIn("工程 1/15", p.state.text())
        self.assertIn("下絵", p.state.text())
        self.assertLess(p.bar.value(), p.bar.maximum() * 0.1)   # 下絵を描き終えても全体の 1/15 まで
        p.status("工程 1/15「下絵」 済み: 崩れは見つかりませんでした")
        p.status("工程 8/15「線画の清書」 主線に筆を置いています（10/20）", 10, 20)
        self.assertIn("工程 8/15　線画の清書", p.state.text())
        self.assertTrue(0.45 < p.bar.value() / p.bar.maximum() < 0.55)
        p.status("工程 15/15「仕上げ」 直し（5/5）", 5, 5)
        self.assertLess(p.bar.value(), p.bar.maximum())   # 描き終えて end が呼ばれるまで満たさない


def tiny_ready():
    import importlib.util
    if importlib.util.find_spec("torch") is None or importlib.util.find_spec("diffusers") is None:
        return False
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(TINY, local_files_only=True)
        return True
    except Exception:   # noqa: BLE001
        return False


TINY = "hf-internal-testing/tiny-stable-diffusion-xl-pipe"
if (ROOT / ".cache" / "gen" / "hf").is_dir():
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))


@unittest.skipUnless(tiny_ready(), "試験用の小さな SDXL が手元にありません")
class TinyModelPhasesTest(unittest.TestCase):
    """本物と同じ経路（Studio.draw → phases.draw → Painter.paint）を、試験用の小さな SDXL で小さな大きさのまま通す"""

    def test_real_path_with_tiny_model(self):
        from chatdraw import engine, models
        from chatdraw.models import FILES, ImageModel
        tiny = ImageModel(TINY, "試験用の小さな SDXL", "", "", 0.1, 2, 5.0, files=FILES["bin"], family="sdxl", score=0)
        C, _ = checks(always_bad=False)
        with mock.patch.object(models, "IMAGES", models.IMAGES + (tiny,)), \
                mock.patch.dict(os.environ, {"CD_NATIVE_SIZE": "off"}), \
                mock.patch.object(phases, "Checks", C), TemporaryDirectory() as d:
            self.assertEqual(engine.native_size((96, 128), "sdxl"), (96, 128))
            painter = engine.Painter(TINY, 2, guidance=5.0)
            s = Studio(FakeWords(), painter, Path(d))
            s.way = "phases"
            s.size = (96, 128)
            said, frames = [], []
            with mock.patch.object(phases, "draw", lambda *a, **k: _real(*a, **dict(k, checks=C))):
                prompt, path = s.draw("赤いマフラーの子", 3, said.append, size=(96, 128), on_preview=frames.append)
            self.assertTrue(path.exists())
            self.assertEqual([r["phase"] for r in s.last_phases], NAMES)
            self.assertGreater(len(frames), 10)
            self.assertTrue(any(m.startswith("工程 1/15「下絵」") and "/2）" in m for m in said), said[:12])
            self.assertIsNone(painter._pipe)   # 下絵のあとに模型を降ろした


_real = phases.draw


class PhaseLayersTest(unittest.TestCase):
    def test_phase_images_are_hidden_layers_below(self):
        from PIL import Image
        from chatdraw.app import Window
        from chatdraw.tests.test_editing import app
        qapp = app()
        with TemporaryDirectory() as d:
            d = Path(d)
            w = Window(Studio(FakeWords(), Painter(), d))
            try:
                rows = []
                for i, name in enumerate([p[0] for p in phases.PHASES[:5]], 1):
                    p = d / f"{i}.png"
                    Image.new("RGB", (64, 64), (i * 40, 0, 0)).save(p)
                    rows.append({"phase": name, "image": str(p), "found": ["崩れ"], "fixed": True, "after": [], "seconds": 1.0})
                final = d / "final.png"
                Image.new("RGB", (64, 64), "white").save(final)
                w.mode.setCurrentIndex(0)
                w.job_kind = "draw"
                w.studio.last_phases = rows
                w.images.append("x")
                w.place(str(final))
                w._put_phases()
                qapp.processEvents()
                c = w.canvas
                names = [l.name for l in c.layers]
                self.assertEqual(names[:5], [f"工程 {i}: {p[0]}" for i, p in enumerate(phases.PHASES[:5], 1)])
                self.assertFalse(any(l.visible for l in c.layers[:5]))
                self.assertEqual(c.current, len(c.layers) - 1)   # 描いた絵が一番上で選ばれたまま
            finally:
                w.dirty = False
                w.close()


class BrokenChecksTest(unittest.TestCase):
    """検品の部品が例外を出しても、描く流れは落ちずに最後の工程まで描き、検品できなかったと残す（0.5.30 で 1 工程目のあとに落ちた）"""

    def test_all_phases_drawn_when_checks_raise(self):
        class Boom:
            @staticmethod
            def request(image, prompt):
                raise RuntimeError("部品が無い")
            body = pose = hands = request

        with TemporaryDirectory() as d:
            p = Painter()
            got = phases.draw(p, "red hair, 1girl", 1, (64, 64), Path(d), checks=Boom)
            self.assertEqual(len(got["phases"]), len(phases.PHASES))
            self.assertFalse(got["checked"])
            self.assertIsNotNone(got["image"])


class CountLimitTest(unittest.TestCase):
    """枚数の欄は数字だけで、8 枚や 9 枚で勝手に止めない"""

    def test_count_spin_has_no_small_cap(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        w = Window(Studio(FakeWords(), FakePainter(), Path(d.name)))
        try:
            spin = w.ai_panel.count_spin
            self.assertEqual(spin.suffix(), "")
            spin.setValue(25)
            self.assertEqual(spin.value(), 25)
        finally:
            w.close()
