"""描く前のメモリの予算（chatdraw/membudget.py）が、どの RAM と VRAM の数字でも予算を超えない置き方と大きさを選ぶか。

torch と diffusers は偽物に替え、空いている RAM と VRAM の数字だけを変える。選んだ計画の段階ごとの山が予算の中にあるか、
収まらないときは読む前に止めるか、GPU に収まる模型を RAM が少ないだけで部品の出し入れに替えないか（前の誤り）、
模型が同時に 2 つ載らないか、見張りが近づいた・危ないを見分けて止めるか、拡大が区画に分けても同じ絵を返すかを見る。
"""
import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw import engine, membudget as mb  # noqa: E402
from chatdraw.tests.test_drawbugs import fake_diffusers, fake_torch  # noqa: E402

RAMS = (2, 4, 6, 8, 12, 16, 24, 32, 64, 128)
VRAMS = (0, 2, 4, 6, 8, 12, 16, 24, 48)
MODELS = (("sd15", 2.0), ("sdxl", 6.9), ("flux2", 16.0), ("zimage", 20.0), ("qwen", 57.0))
SIZES = ((512, 768), (832, 1216), (1024, 1024), (1536, 1536))


class ChooseTest(unittest.TestCase):
    def test_never_over_budget(self):
        """どの数字の組でも、選んだ計画の全段階の山が予算の中。収まらなければ ok=False で理由と軽い代わりを持つ"""
        n = ok = 0
        for fam, gb in MODELS:
            for ram in RAMS:
                for vram in VRAMS:
                    for size in SIZES:
                        b = mb.budget(ram, vram)
                        plan = mb.choose(gb, size, fam, b, cuda=vram > 0)
                        n += 1
                        with self.subTest(fam=fam, ram=ram, vram=vram, size=size):
                            if plan.ok:
                                ok += 1
                                self.assertLessEqual(plan.ram_peak(), b.ram)
                                self.assertLessEqual(plan.vram_peak(), b.vram + 1e-9)
                                self.assertLessEqual(plan.size[0] * plan.size[1], size[0] * size[1])
                                if vram == 0:
                                    self.assertEqual(plan.placement, "cpu")
                            else:
                                self.assertIn("描く前に止めました", plan.reason)
                                self.assertIn("軽い代わり", plan.lighter)
        self.assertGreater(ok, 0)
        self.assertLess(ok, n)   # 収まらない組もある（その組は止める）

    def test_gpu_fits_but_ram_low_stays_on_gpu(self):
        """前の誤り: GPU に収まる模型でも、空いている RAM が少ないと部品の出し入れに替え、かえって RAM を多く使った"""
        b = mb.budget(6.0, 24.0)
        plan = mb.choose(6.9, (832, 1216), "sdxl", b, cuda=True)
        self.assertTrue(plan.ok)
        self.assertEqual(plan.placement, "cuda")
        model = mb.peaks(6.9, (832, 1216), "sdxl", "model", False, False, True)
        cuda = mb.peaks(6.9, (832, 1216), "sdxl", "cuda", False, False, True)
        self.assertGreater(max(r for r, _ in model.values()), max(r for r, _ in cuda.values()))   # 出し入れのほうが RAM を使う

    def test_lighter_settings_before_smaller_size(self):
        """品質を変えない軽さ（注意の分割、VAE の分割）を先に使い、大きさは最後に下げる"""
        b = mb.budget(64.0, 9.5)
        plan = mb.choose(6.9, (832, 1216), "sdxl", b, cuda=True)
        self.assertTrue(plan.ok)
        self.assertEqual(tuple(plan.size), (832, 1216))
        tight = mb.choose(6.9, (1536, 1536), "sdxl", mb.budget(8.0, 0.0), cuda=False)
        if tight.ok and tuple(tight.size) != (1536, 1536):
            self.assertTrue(tight.slicing and tight.tiling and not tight.preview)

    def test_loaded_plan_keeps_placement(self):
        plan = mb.choose(6.9, (832, 1216), "sdxl", mb.budget(4.0, 4.0), cuda=True, loaded_as="sequential")
        self.assertEqual(plan.placement, "sequential")


def run_paint(repo, ram, vram, cuda=True, size=(832, 1216)):
    log = []
    with mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch(cuda, vram),
                                       "bitsandbytes": types.ModuleType("bitsandbytes")}), \
            mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"), \
            mock.patch.object(engine, "free_ram_gb", return_value=ram):
        p = engine.Painter(repo, steps=2)
        notes = []
        p.on_note = notes.append
        err = None
        try:
            p.paint("1girl", 1, size=size)
        except Exception as e:   # noqa: BLE001
            err = e
    return p, log, notes, err


class PainterBudgetTest(unittest.TestCase):
    def test_painter_gpu_with_low_ram(self):
        """偽の GPU 24GB、RAM の空き 6GB の SDXL は、全部を GPU に（GPU へ直に読む）。部品の出し入れに替えない"""
        p, log, notes, err = run_paint("cagliostrolab/animagine-xl-4.0", 6.0, 24.0)
        self.assertIsNone(err)
        self.assertEqual(p.placed, "cuda")
        self.assertNotIn(("place", "model"), log)
        self.assertEqual(next(x for x in log if x[0] == "load")[4].get("device_map"), "cuda")
        self.assertFalse(p.low_memory)

    def test_over_budget_stops_before_loading(self):
        p, log, notes, err = run_paint("cagliostrolab/animagine-xl-4.0", 3.0, 0.0, cuda=False)
        self.assertIsInstance(err, mb.OverBudget)
        self.assertFalse([x for x in log if x[0] == "load"], "止める前に模型を読んだ")
        self.assertIn("軽い代わり", engine.explain(err))

    def test_small_budget_draws_smaller_and_returns_size(self):
        """予算に合わせて小さく描いたときも、頼んだ大きさに戻す（キャンバスの大きさは変えない）"""
        p, log, notes, err = run_paint("cagliostrolab/animagine-xl-4.0", 14.0, 0.0, cuda=False, size=(1536, 1536))
        self.assertIsNone(err)
        call = next(x for x in log if x[0] == "call")[2]
        plan = p.plan
        self.assertEqual((call["width"], call["height"]), tuple(plan.size))
        self.assertLessEqual(plan.ram_peak(), mb.budget(14.0, 0.0).ram)

    def test_grid_of_painter_runs(self):
        """本物と同じ経路（Painter.paint）で、数字を変えても予算を超える計画で描かない"""
        for ram in (4, 8, 16, 32):
            for vram in (0, 4, 8, 24):
                with self.subTest(ram=ram, vram=vram):
                    p, log, notes, err = run_paint("cagliostrolab/animagine-xl-4.0", float(ram), float(vram), cuda=vram > 0)
                    if err is None:
                        # 少し超えるだけなら一番軽い設定で描く（engine.Painter.OVER_OK）。大きく超える計画では描かない
                        b = mb.budget(float(ram), float(vram))
                        k = 1.0 if p.plan.ok else engine.Painter.OVER_OK
                        self.assertLessEqual(p.plan.ram_peak(), b.ram * k)
                        self.assertLessEqual(p.plan.vram_peak(), b.vram * k + 1e-9)
                    else:
                        self.assertIsInstance(err, mb.OverBudget)

    def test_redraw_scale_follows_budget(self):
        p = engine.Painter("cagliostrolab/animagine-xl-4.0")
        with mock.patch.dict(sys.modules, {"torch": fake_torch(False, 0)}):
            self.assertEqual(p.redraw_scale((832, 1216), mb.budget(64.0, 0.0)), 1.5)
            k = p.redraw_scale((2048, 2048), mb.budget(15.0, 0.0))
            self.assertLess(k, 1.5)
            with self.assertRaises(mb.OverBudget):
                p.redraw_scale((4096, 4096), mb.budget(9.0, 0.0))


class OneModelTest(unittest.TestCase):
    def test_loading_one_unloads_others(self):
        downs = []
        mb.exclusive("a", lambda: downs.append("a"))
        mb.exclusive("b", lambda: downs.append("b"))
        self.assertEqual(downs, ["a"])
        mb.exclusive("upscale", lambda: downs.append("upscale"))
        self.assertEqual(downs, ["a", "b"])
        self.assertEqual(mb.loaded_names(), ["upscale"])
        mb.released("upscale")
        self.assertEqual(mb.loaded_names(), [])

    def test_painter_load_unloads_other_painter(self):
        log = []
        with mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch()}), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"), \
                mock.patch.object(engine, "free_ram_gb", return_value=0.0):
            a = engine.Painter("cagliostrolab/animagine-xl-4.0")
            b = engine.Painter("Laxhar/noobai-XL-1.1")
            a.load()
            self.assertTrue(a.loaded())
            b.load()
            self.assertFalse(a.loaded(), "前の模型を降ろさずに次を読んだ")
            self.assertTrue(b.loaded())
            b.unload()
        self.assertEqual(mb.loaded_names(), [])


class WatchTest(unittest.TestCase):
    def test_levels(self):
        start = mb.Budget(8.0, 0.0, 10.0, 0.0)   # 空き 10GB、余裕 2GB
        seq = iter([(9.0, 0), (2.5, 0), (5.0, 0), (0.5, 0)])
        w = mb.Watch(start, sample=lambda: next(seq))
        self.assertEqual(w.poll(), "ok")
        self.assertEqual(w.poll(), "near")
        self.assertEqual(w.poll(), "near")    # 一度上がった段は下げない
        self.assertEqual(w.poll(), "danger")

    def test_vram_is_watched(self):
        w = mb.Watch(mb.Budget(80, 16, 100, 20), sample=lambda: (90.0, 1.0))
        self.assertEqual(w.poll(), "danger")

    def test_danger_stops_before_decode_and_keeps_partial(self):
        """危ないところまで来たら、VAE の復号に進まずに止め、途中の絵を残す。メモリ不足の描き直しはしない"""
        log = []
        with TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch()}), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"), \
                mock.patch.object(engine, "free_ram_gb", return_value=0.0), \
                mock.patch.object(mb.Watch, "level", "danger", create=True), \
                mock.patch.object(mb.Watch, "__init__", lambda self, *a, **k: None), \
                mock.patch.object(mb.Watch, "__enter__", lambda self: self), \
                mock.patch.object(mb.Watch, "__exit__", lambda self, *a: False):
            p = engine.Painter("cagliostrolab/animagine-xl-4.0", steps=2)
            p.partial_dir = Path(d)
            with self.assertRaises(mb.MemoryDanger) as got:
                p.paint("1girl", 1)
            self.assertIn("落ちる前に止めました", engine.explain(got.exception))
            self.assertEqual(len([x for x in log if x[0] == "call"]), 1, "止めたあとに描き直した")

    def test_near_lightens(self):
        log = []
        notes = []
        with mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch()}), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"), \
                mock.patch.object(engine, "free_ram_gb", return_value=0.0), \
                mock.patch.object(mb.Watch, "level", "near", create=True), \
                mock.patch.object(mb.Watch, "__init__", lambda self, *a, **k: None), \
                mock.patch.object(mb.Watch, "__enter__", lambda self: self), \
                mock.patch.object(mb.Watch, "__exit__", lambda self, *a: False):
            p = engine.Painter("cagliostrolab/animagine-xl-4.0", steps=2)
            p.on_note = notes.append
            with mock.patch.object(p, "lighten", wraps=p.lighten) as light:
                p.paint("1girl", 1)
            self.assertTrue(any(c.kwargs.get("tiling") for c in light.call_args_list))
        self.assertTrue(any("予算に近づいた" in n for n in notes), notes)


class StagesTest(unittest.TestCase):
    def test_paint_records_stages(self):
        """描くたびに、読み込み・描く本体の秒と RAM の山が残る。2 枚目は読んだ模型を使い回す（読み込み 0 秒）"""
        log = []
        with mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch()}), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"), \
                mock.patch.object(engine, "free_ram_gb", return_value=0.0):
            p = engine.Painter("cagliostrolab/animagine-xl-4.0", steps=2)
            p.paint("1girl", 1)
            names = [r[0] for r in p.stages.rows]
            self.assertEqual(names[0], "読み込み")
            self.assertTrue(any(n.startswith("描く本体") for n in names), names)
            p.paint("1girl", 2)
            self.assertIn("使い回す", p.stages.rows[0][0])
            self.assertEqual(len([x for x in log if x[0] == "load"]), 1, "2 枚目で模型を読み直した")
            self.assertIn("秒", p.stages.table())


class UpscaleTilesTest(unittest.TestCase):
    def test_tiles_give_same_picture_and_unload_painter(self):
        try:
            import numpy as np
            import torch
        except ImportError:
            self.skipTest("torch が無い")
        from PIL import Image
        from chatdraw import upscale

        class Net(torch.nn.Module):   # 4 倍に広げるだけの偽の模型（区画の継ぎ目が出ないかを見る）
            def __init__(self):
                super().__init__()
                self.w = torch.nn.Parameter(torch.zeros(1))

            def forward(self, x):
                return torch.nn.functional.interpolate(x, scale_factor=4, mode="nearest") + self.w

        downs = []
        mb.exclusive(("painter", 1), lambda: downs.append("painter"))
        rng = np.random.default_rng(0)
        img = Image.fromarray(rng.integers(0, 255, (100, 140, 3), dtype=np.uint8))
        with mock.patch.object(upscale, "_NET", [Net()]):
            a = upscale.x4(img, tile=256)
            b = upscale.x4(img, tile=32)
            self.assertEqual(downs, ["painter"], "拡大の前に描く模型を降ろしていない")
            upscale.unload()
        self.assertEqual(a.size, (560, 400))
        self.assertEqual(np.asarray(a).tobytes(), np.asarray(b).tobytes())
        self.assertEqual(mb.tile_for(1.0, 0.0, False), 128)
        self.assertEqual(mb.tile_for(64.0, 0.0, False), 256)


if __name__ == "__main__":
    unittest.main()
