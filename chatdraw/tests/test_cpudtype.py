"""bf16 の命令の無い CPU で、描く本体を float32 に替える試験（engine.cpu_upcast）。

Actions の 16GB の機械で、bf16 の命令の無い CPU に当たった回だけ SDXL の 1 歩が約 36 分になった。
偽の機械（RAM の量と bf16 の速さを差し替える）と、小さな本物の部品（torch の Conv2d）で、
足りる機械では本体と VAE が float32 になり、bf16 で入ってきた値でも描けること、bf16 の速い CPU と RAM の足りない機械では替えないことを見る。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw import engine  # noqa: E402

try:
    import torch
except ImportError:   # 描く部品の無い機械
    torch = None


@unittest.skipIf(torch is None, "torch がありません")
class CpuUpcastTest(unittest.TestCase):
    def pipe(self):
        class Pipe:
            pass
        p = Pipe()
        p.unet = torch.nn.Conv2d(4, 4, 3, padding=1).to(torch.bfloat16)
        p.vae = torch.nn.Conv2d(4, 3, 1).to(torch.bfloat16)
        p.text_encoder = torch.nn.Linear(8, 8).to(torch.bfloat16)
        return p

    def test_fits_on_16gb_for_sdxl(self):
        with mock.patch.object(engine, "total_ram_gb", return_value=16.7):   # Actions の ubuntu-latest
            self.assertTrue(engine.cpu_upcast_fits(6.9))
        with mock.patch.object(engine, "total_ram_gb", return_value=8.0):
            self.assertFalse(engine.cpu_upcast_fits(6.9))
        with mock.patch.object(engine, "total_ram_gb", return_value=16.7):   # 24GB 級の模型は入らない
            self.assertFalse(engine.cpu_upcast_fits(24.0))

    def test_slow_bf16_cpu_upcasts_denoiser_only(self):
        p, said = self.pipe(), []
        with mock.patch.object(engine, "bf16_fast", return_value=False), \
                mock.patch.object(torch.cuda, "is_available", return_value=False):
            self.assertTrue(engine.cpu_upcast(p, said.append))
        self.assertEqual(p.unet.weight.dtype, torch.float32)
        self.assertEqual(p.vae.weight.dtype, torch.float32)
        self.assertEqual(p.text_encoder.weight.dtype, torch.bfloat16)   # 文字の部品は bf16 のまま
        self.assertTrue(said and "float32" in said[0])   # 進みの欄に、どの形で描くかを出す
        out = p.unet(torch.randn(1, 4, 8, 8, dtype=torch.bfloat16))   # bf16 の値が入っても落ちない
        self.assertEqual(out.dtype, torch.float32)

    def test_fast_bf16_cpu_keeps_bf16(self):
        p = self.pipe()
        with mock.patch.object(engine, "bf16_fast", return_value=True), \
                mock.patch.object(torch.cuda, "is_available", return_value=False):
            self.assertFalse(engine.cpu_upcast(p))
        self.assertEqual(p.unet.weight.dtype, torch.bfloat16)


if __name__ == "__main__":
    unittest.main()
