"""自分の作風の入口: ★ の保存、学習用の書き出し（絵と説明の .txt）、LoRA を重ねる・外す"""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))


class FakePipe:
    def __init__(self):
        self.calls = []

    def load_lora_weights(self, folder, weight_name, adapter_name):
        self.calls.append(("load", weight_name))

    def set_adapters(self, names, adapter_weights):
        self.calls.append(("set", adapter_weights[0]))

    def unload_lora_weights(self):
        self.calls.append(("unload",))


class OwnStyleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        from chatdraw import paths
        self.patches = [mock.patch.object(paths, "data_home", lambda: self.d / "data"),
                        mock.patch.object(paths, "LLM_HOME", self.d / "LLM")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_favorite_persists(self):
        from chatdraw import ownstyle
        self.assertFalse(ownstyle.is_favorite("a.png"))
        self.assertTrue(ownstyle.toggle("a.png"))
        self.assertEqual(json.loads((self.d / "data" / "favorites.json").read_text(encoding="utf-8")), ["a.png"])
        self.assertFalse(ownstyle.toggle("a.png"))
        self.assertEqual(ownstyle.favorites(), [])

    def test_collect_writes_image_and_caption(self):
        from PIL import Image
        from chatdraw import ownstyle
        a, b = self.d / "a.png", self.d / "b.png"
        Image.new("RGB", (8, 8)).save(a)
        Image.new("RGB", (8, 8)).save(b)
        b.with_suffix(".json").write_text(json.dumps({"prompt": "1girl, red hair"}), encoding="utf-8")
        for p in (b, a, self.d / "gone.png"):
            ownstyle.set_favorite(str(p))
        tagger = lambda path: {"smile": 0.5, "1girl": 0.9} if path.endswith("a.png") else {}
        res = ownstyle.collect(tagger=tagger)
        out = Path(res["dir"])
        self.assertTrue(out.is_relative_to(self.d / "data" / "datasets"))
        self.assertEqual(len(res["images"]), 2)
        self.assertEqual(res["missing"], [str(self.d / "gone.png")])
        caps = sorted(p.read_text(encoding="utf-8") for p in out.glob("*.txt"))
        self.assertEqual(caps, ["1girl, red hair", "1girl, smile"])

    def test_lora_list_and_apply(self):
        from chatdraw import ownstyle
        self.assertEqual(ownstyle.loras(), [])
        (self.d / "LLM" / "lora").mkdir(parents=True)
        f = self.d / "LLM" / "lora" / "mine.safetensors"
        f.write_bytes(b"x")
        self.assertEqual(ownstyle.loras(), [f])
        pipe, state = FakePipe(), {}
        self.assertIsNone(ownstyle.apply(pipe, str(f), 0.7, state))
        self.assertIsNone(ownstyle.apply(pipe, str(f), 0.5, state))   # 2 度目は読まず、強さだけ替える
        self.assertIsNone(ownstyle.apply(pipe, "", 0.5, state))
        self.assertEqual(pipe.calls, [("load", "mine.safetensors"), ("set", 0.7), ("set", 0.5), ("unload",)])
        self.assertIn("重ねられません", ownstyle.apply(object(), str(f), 1.0, {}))

    def test_lora_dropdown_defaults_to_none(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw import ownstyle
        app = QApplication.instance() or QApplication([])
        (self.d / "LLM" / "lora").mkdir(parents=True)
        (self.d / "LLM" / "lora" / "mine.safetensors").write_bytes(b"x")
        from chatdraw.app import Window as ChatDraw
        from types import SimpleNamespace
        store = {}
        w = SimpleNamespace(layout_store=mock.Mock(value=lambda k, d=None: store.get(k, d), setValue=store.__setitem__))
        w._lora_changed = lambda: ChatDraw._lora_changed(w)
        from PySide6.QtWidgets import QVBoxLayout, QWidget
        holder = QWidget()
        w.ai_panel = SimpleNamespace(sections={"模型": SimpleNamespace(body=QVBoxLayout(holder))})
        ChatDraw._lora_row(w)
        self.assertEqual(w.lora_pick.currentData(), "")
        self.assertEqual(w.lora_pick.count(), 2)
        w.studio = mock.Mock()
        w.lora_pick.setCurrentIndex(1)
        self.assertEqual(store["lora"], str(ownstyle.lora_dir() / "mine.safetensors"))
        self.assertEqual(w.studio.painter.lora_scale, 0.8)
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
