"""保存先に絵だけを置く試験。頼み・種は PNG に埋め、大きな記録はアプリのデータの置き場（records）に置く。
保存先に絵の数だけ .json が並ぶと、利用者には中身の分からないゴミに見えた"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock


class NoJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out, self.home = root / "out", root / "home"
        self.env = mock.patch.dict(os.environ, {"CD_HOME": str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _draw(self) -> Path:
        """描いた後と同じ道（Studio._save と _inspect）で絵を残す"""
        from PIL import Image
        from chatdraw.engine import Studio
        fake = SimpleNamespace(out=self.out, last_check=None)
        meta = {"text": "赤い髪の魔法使い", "prompt": "1girl, red hair", "seed": 1234, "model": "m"}
        path = Studio._save(fake, Image.new("RGB", (16, 16), "white"), 1234, meta)
        with mock.patch("chatdraw.handcheck.check", return_value={"readable": True, "bad": [], "hands": []}):
            Studio._inspect(fake, path, lambda _s: None)
        return path

    def test_no_json_in_output(self):
        path = self._draw()
        self.assertEqual([p.name for p in self.out.iterdir()], [path.name])   # 保存先には絵だけ
        from chatdraw import finishers
        self.assertTrue((finishers.record_dir(path) / "check.json").exists())
        self.assertTrue(str(finishers.record_dir(path)).startswith(str(self.home)))
        self.assertEqual(finishers.read_record(path, "check.json")["readable"], True)

    def test_prompt_and_seed_from_png(self):
        from chatdraw import finishers
        from chatdraw.library import Library
        path = self._draw()
        meta = finishers.sidecar(path)
        self.assertEqual((meta["text"], meta["seed"]), ("赤い髪の魔法使い", 1234))
        lib = Library(self.home / "library")
        item = lib.add_work(str(path))
        self.assertEqual((item["text"], item["seed"]), ("赤い髪の魔法使い", 1234))

    def test_old_json_still_read(self):
        from PIL import Image
        from chatdraw import finishers
        self.out.mkdir(parents=True)
        p = self.out / "old.png"
        Image.new("RGB", (8, 8)).save(p)
        p.with_suffix(".json").write_text(json.dumps({"text": "前の版", "seed": 7}), encoding="utf-8")
        p.with_suffix(".check.json").write_text(json.dumps({"readable": False}), encoding="utf-8")
        self.assertEqual(finishers.sidecar(p)["seed"], 7)
        self.assertEqual(finishers.read_record(p, "check.json"), {"readable": False})
        self.assertTrue(p.with_suffix(".json").exists())   # 利用者のデータなので消さない

    def test_trash_moves_records(self):
        from chatdraw import finishers
        from chatdraw.trash import Trash
        path = self._draw()
        rd = finishers.record_dir(path)
        t = Trash(self.home / "trash")
        key = t.put([str(path)])
        self.assertFalse(path.exists() or rd.exists())
        t.restore(key)
        self.assertTrue(path.exists() and (rd / "check.json").exists())
        self.assertEqual(finishers.sidecar(path)["seed"], 1234)
        key = t.put([str(path)])
        t.purge(key)
        self.assertFalse(rd.exists())


if __name__ == "__main__":
    unittest.main()
