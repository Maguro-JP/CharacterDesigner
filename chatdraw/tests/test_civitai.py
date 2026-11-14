"""Civitai から探して取る（chatdraw/civitai.py、chatdraw/civitaipanel.py）の試験。

回線を使わず、Civitai の返りの形をした偽の返りで見る。本物の API での確かめは CD_CIVITAI_LIVE=1 のときだけ流す
（小さな LoRA を 1 つ取る）。
"""
import io
import json
import os
import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw import civitai  # noqa: E402


def safetensors_bytes() -> bytes:
    head = json.dumps({"__metadata__": {}}).encode()
    return struct.pack("<Q", len(head)) + head


def api_item(i=1, kind="LORA", name="lineart.safetensors", base="SDXL 1.0", scan="Success", nsfw=1):
    return {"id": i, "name": f"Item {i}", "type": kind, "allowCommercialUse": ["Image"], "creator": {"username": "u"},
            "stats": {"downloadCount": 10},
            "modelVersions": [{"id": 100 + i, "name": "v1", "baseModel": base, "trainedWords": ["lineart"],
                               "files": [{"name": name, "sizeKB": 1, "primary": True, "pickleScanResult": scan,
                                          "virusScanResult": scan, "downloadUrl": f"https://civitai.com/api/download/models/{100 + i}"}],
                               "images": [{"url": "https://image.civitai.com/x/abc/orig", "nsfwLevel": nsfw, "type": "image"}]}]}


class Resp(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class CivitaiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()
        self.llm = mock.patch("chatdraw.paths.LLM_HOME", Path(self.tmp.name))
        self.llm.start()

    def tearDown(self):
        self.env.stop()
        self.llm.stop()
        self.tmp.cleanup()

    def test_parse_keeps_only_safe_files_and_all_ages_samples(self):
        items = civitai.parse({"items": [api_item(1), api_item(2, scan="Danger"), api_item(3, name="x.ckpt"), api_item(4, nsfw=8)]})
        self.assertEqual([i.safe for i in items], [True, False, False, True])
        self.assertEqual(items[0].images, ["https://image.civitai.com/x/abc/width=320"])   # 縮めた見本の道
        self.assertEqual(items[3].images, [])   # 全年齢向けでない見本は出さない
        self.assertEqual(items[0].family, "sdxl")
        self.assertEqual(items[0].words, ["lineart"])

    def test_search_sends_agent_and_filters(self):
        seen = []

        def opener(req, timeout=0):
            seen.append(req)
            return Resp(json.dumps({"items": [api_item()]}).encode())
        got = civitai.search("lineart", "LORA", opener=opener)
        self.assertEqual(len(got), 1)
        self.assertIn("nsfw=false", seen[0].full_url)
        self.assertIn("types=LORA", seen[0].full_url)
        self.assertEqual(seen[0].get_header("User-agent"), civitai.AGENT)

    def test_fetch_places_lora_and_meta_and_uses_key(self):
        it = civitai.parse({"items": [api_item()]})[0]
        urls = []

        def opener(req, timeout=0):
            urls.append(req.full_url)
            return Resp(safetensors_bytes())
        p = civitai.fetch(it, key="abc", opener=opener)
        self.assertEqual(p, Path(self.tmp.name) / "lora" / "lineart.safetensors")
        self.assertIn("token=abc", urls[0])
        meta = json.loads(p.with_suffix(".civitai.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["words"], ["lineart"])
        from chatdraw import ownstyle
        self.assertIn(p, ownstyle.loras())   # すぐ LoRA の一覧に出る

    def test_fetch_checkpoint_goes_to_manual_and_rejects_html(self):
        it = civitai.parse({"items": [api_item(kind="Checkpoint", name="m.safetensors")]})[0]
        with self.assertRaises(ValueError):
            civitai.fetch(it, opener=lambda req, timeout=0: Resp(b"<html>login</html>"))
        self.assertFalse((Path(self.tmp.name) / "manual" / "m.safetensors").exists())
        p = civitai.fetch(it, opener=lambda req, timeout=0: Resp(safetensors_bytes()))
        self.assertEqual(p.parent.name, "manual")

    def test_unsafe_is_not_fetched(self):
        it = civitai.parse({"items": [api_item(scan="Danger")]})[0]
        with self.assertRaises(ValueError):
            civitai.fetch(it, opener=lambda req, timeout=0: Resp(safetensors_bytes()))

    @unittest.skipUnless(os.environ.get("CD_CIVITAI_LIVE"), "本物の Civitai に繋ぐのは CD_CIVITAI_LIVE=1 のときだけ")
    def test_live_search_and_small_lora(self):
        items = [i for i in civitai.search("lineart", "LORA", limit=20) if i.safe]
        self.assertTrue(items)
        small = min(items, key=lambda i: i.size_mb)
        p = civitai.fetch(small)
        self.assertGreater(p.stat().st_size, 1000)


class DialogTest(unittest.TestCase):
    def test_search_show_samples_and_fetch_from_window(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtCore import QBuffer, QByteArray
        from chatdraw.tests.test_aitabs import app, window
        from chatdraw import civitaipanel
        app()
        img = QImage(160, 240, QImage.Format_RGB32)
        img.fill(QColor("#8ab"))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        png = bytes(ba)
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CD_HOME": d}), \
                mock.patch("chatdraw.paths.LLM_HOME", Path(d)):
            items = civitai.parse({"items": [api_item(1), api_item(2, name="b.safetensors"), api_item(3, scan="Danger")]})

            def fake_fetch(it, key, progress=None):
                p = civitai.dest_for(it)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(safetensors_bytes())
                return p
            store = QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat)
            dlg = civitaipanel.CivitaiDialog(store, None, search=lambda q, k: items, fetch=fake_fetch, get=lambda url: png)
            dlg.show()
            dlg.query.setText("lineart")
            dlg.go.click()
            for _ in range(200):
                app().processEvents()
                if dlg.list.count() == 3 and not dlg.list.item(0).icon().isNull():
                    break
                __import__("time").sleep(0.02)
            self.assertEqual(dlg.list.count(), 3)
            self.assertFalse(dlg.list.item(0).icon().isNull())   # 見本の絵が付く
            dlg.list.setCurrentRow(2)
            self.assertFalse(dlg.take.isEnabled())               # 検査を通っていない物は取れない
            dlg.list.setCurrentRow(0)
            self.assertTrue(dlg.take.isEnabled())
            dlg.key.setText("k123")
            dlg.take.click()
            for _ in range(200):
                app().processEvents()
                if dlg.got is not None:
                    break
                __import__("time").sleep(0.02)
            self.assertEqual(dlg.got.name, "lineart.safetensors")
            self.assertEqual(store.value(civitaipanel.KEY), "k123")
            out = os.environ.get("CD_SNAP_DIR")
            if out:
                dlg.list.setCurrentRow(0)
                app().processEvents()
                dlg.grab().save(str(Path(out) / "civitai-dialog.png"))
            dlg.close()
            # 窓から: 取ったあと LoRA の欄に出る
            w = window(d)
            with mock.patch.object(civitaipanel.CivitaiDialog, "exec", lambda self: setattr(self, "got", Path(d) / "lora" / "lineart.safetensors")):
                w.open_civitai()
            self.assertGreaterEqual(w.lora_pick.findData(str(Path(d) / "lora" / "lineart.safetensors")), 0)
            w.close()


if __name__ == "__main__":
    unittest.main()
