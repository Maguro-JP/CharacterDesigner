"""描く場所の使い分け（tools/gen/device.py）。torch を作り物に差し替え、GPU の無い環境でも選び方を確かめる"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import device  # noqa: E402


def fake_torch(cuda=False, mps=False, vram_gb=24):
    props = SimpleNamespace(total_memory=vram_gb * 1024 ** 3)
    return SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda, get_device_properties=lambda i: props),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
        float16="float16", bfloat16="bfloat16", set_num_threads=lambda n: None)


class FakePipe:
    def __init__(self):
        self.calls = []

    def to(self, where):
        self.calls.append(("to", where))

    def enable_model_cpu_offload(self):
        self.calls.append(("offload",))

    def enable_attention_slicing(self):
        self.calls.append(("slicing",))


class DeviceTest(unittest.TestCase):
    def setUp(self):
        device._CHOSEN = None
        self.old = os.environ.pop("CD_DEVICE", None)

    def tearDown(self):
        device._CHOSEN = None
        if self.old is not None:
            os.environ["CD_DEVICE"] = self.old

    def test_order_cuda_then_mps_then_cpu(self):
        self.assertEqual(device.name(fake_torch(cuda=True, mps=True)), "cuda")
        device._CHOSEN = None
        self.assertEqual(device.name(fake_torch(mps=True)), "mps")
        device._CHOSEN = None
        self.assertEqual(device.name(fake_torch()), "cpu")

    def test_env_choice_falls_back_when_missing(self):
        os.environ["CD_DEVICE"] = "cuda"
        self.assertEqual(device.name(fake_torch()), "cpu")
        device._CHOSEN = None
        os.environ["CD_DEVICE"] = "cpu"
        self.assertEqual(device.name(fake_torch(cuda=True)), "cpu")
        del os.environ["CD_DEVICE"]

    def test_dtype(self):
        t = fake_torch(cuda=True)
        self.assertEqual(device.dtype(t), "float16")
        device._CHOSEN = None
        self.assertEqual(device.dtype(fake_torch()), "bfloat16")

    def test_place(self):
        p = FakePipe()
        device.place(p, fake_torch())
        self.assertEqual(p.calls, [])                       # CPU は今までどおり何もしない
        device._CHOSEN = None
        p = FakePipe()
        device.place(p, fake_torch(cuda=True, vram_gb=24))
        self.assertEqual(p.calls, [("to", "cuda")])
        device._CHOSEN = None
        p = FakePipe()
        device.place(p, fake_torch(cuda=True, vram_gb=8))  # メモリが少ない GPU は使う部品だけを載せる
        self.assertEqual(p.calls, [("offload",)])
        device._CHOSEN = None
        p = FakePipe()
        device.place(p, fake_torch(mps=True))
        self.assertEqual(p.calls, [("to", "mps"), ("slicing",)])


if __name__ == "__main__":
    unittest.main()
