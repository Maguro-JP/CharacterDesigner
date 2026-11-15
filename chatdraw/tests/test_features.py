"""タイムラプスの書き出しと再生、SNS 連携のオン・オフ、音声入力のキー、3D に進む入口"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def figure() -> Image.Image:
    im = Image.new("RGB", (120, 160), "white")
    ImageDraw.Draw(im).ellipse((30, 20, 90, 150), fill=(200, 80, 80))
    return im


class TimelapseTest(unittest.TestCase):
    def test_gif_export_and_in_app_player(self):
        from chatdraw.timelapse import PlayerDialog, Recorder, TimelapseDialog
        app()
        rec = Recorder()
        for i in range(5):
            im = figure()
            ImageDraw.Draw(im).line((0, i * 10, 120, i * 10), fill="black", width=3)
            rec.add(im)
        rec.add(im)   # 同じ写しは足さない
        self.assertEqual(len(rec.frames), 5)
        with TemporaryDirectory() as d:
            gif = Path(d) / "t.gif"
            self.assertEqual(rec.export(gif), 5)
            with Image.open(gif) as g:
                self.assertEqual(g.n_frames, 5)
            dlg = PlayerDialog(gif)
            self.assertTrue(dlg.movie.isValid())
            self.assertGreater(dlg.movie.frameCount(), 1)
            dlg.close()
            tl = TimelapseDialog(rec)
            self.assertEqual(tl.slider.maximum(), 4)
            tl.close()

    def test_video_without_encoder_writes_webp(self):
        """MP4 を書く部品が無い環境でも、動画の代わりに動く WebP を書き、ボタンは押せる形のまま理由をツールチップに出す"""
        from chatdraw import timelapse
        rec = timelapse.Recorder()
        rec.add(figure())
        rec.add(figure().rotate(90))
        with mock.patch.object(timelapse, "video_backend", return_value="webp"), TemporaryDirectory() as d:
            n, out = rec.export_video(Path(d) / "t.mp4")
            self.assertEqual(out.suffix, ".webp")
            self.assertGreater(Image.open(out).n_frames, 1)
            app()
            dlg = timelapse.TimelapseDialog(rec)
            self.assertTrue(dlg.video.isEnabled())
            self.assertIn("WebP", dlg.video.toolTip())
            dlg.close()


class FakeSettings(dict):
    pass


class ShareTest(unittest.TestCase):
    def test_off_blocks_post_and_on_opens_compose(self):
        from PySide6.QtGui import QDesktopServices
        from chatdraw import share
        app()
        win = mock.Mock(settings=FakeSettings(sns="オフ"))
        with mock.patch.object(QDesktopServices, "openUrl") as opened:
            share.post(win, "Bluesky", "x.png", "猫")
            opened.assert_not_called()
            win.copy_image.assert_not_called()
            win.settings["sns"] = "Misskey"
            share.post(win, "Misskey", "x.png", "猫")
            win.copy_image.assert_called_once_with("x.png")
            self.assertIn("misskey.io/share?text=", opened.call_args[0][0].toString())
        self.assertIn("%E7%8C%AB", share.compose_url("X（Twitter）", "猫"))


class VoiceTest(unittest.TestCase):
    def test_sends_win_h(self):
        from chatdraw import voice
        user32 = mock.Mock()
        self.assertTrue(voice.start(user32))
        keys = [c.args[:3] for c in user32.keybd_event.call_args_list]
        self.assertEqual(keys, [(0x5B, 0, 0), (0x48, 0, 0), (0x48, 0, 2), (0x5B, 0, 2)])
        with mock.patch.object(voice.sys, "platform", "linux"):
            self.assertFalse(voice.start())


class To3DTest(unittest.TestCase):
    def test_build_relief_model(self):
        from chatdraw import to3d
        with TemporaryDirectory() as d:
            src = Path(d) / "chara.png"
            figure().save(src)
            obj = to3d.build(src, grid=32)
            self.assertEqual(obj.parent.name, "chara-3d")
            text = obj.read_text(encoding="utf-8")
            zs = [float(l.split()[3]) for l in text.splitlines() if l.startswith("v ")]
            self.assertGreater(max(zs), 0.1)        # 内側は厚い
            self.assertAlmostEqual(min(abs(z) for z in zs), 0.0, places=3)   # 縁は薄い
            self.assertTrue(any(l.startswith("f ") for l in text.splitlines()))
            self.assertTrue((obj.parent / "color.png").exists() and (obj.parent / "model.mtl").exists())
            # 背景（白）は面にしない: 面の数は人物のマスの 2 倍（表と裏）
            mask = to3d.cutout(Image.open(src)).resize((24, 32), Image.NEAREST)
            cells = sum(1 for p in mask.tobytes() if p)
            self.assertEqual(sum(1 for l in text.splitlines() if l.startswith("f ")), cells * 2)

    def test_dialog_without_blender_offers_download(self):
        from PySide6.QtGui import QDesktopServices
        from chatdraw import to3d
        app()
        with TemporaryDirectory() as d, mock.patch.object(to3d, "find_blender", return_value=None), \
                mock.patch.object(QDesktopServices, "openUrl") as opened:
            src = Path(d) / "c.png"
            figure().save(src)
            dlg = to3d.To3DDialog(str(src))
            self.assertEqual(dlg.go_button.text(), "Blender を取りに行く")
            dlg.make_button.click()
            self.assertTrue((Path(d) / "c-3d" / "model.obj").exists())
            dlg.go_button.click()
            self.assertEqual(opened.call_args[0][0].toString(), to3d.BLENDER_URL)
            dlg.close()


    def test_rigged_character_runs_in_background(self):
        """「骨付きの 3D キャラを作る」を押すと、裏で作って画面は固まらず、終わると写しと .vrm が出る"""
        import time
        from PySide6.QtGui import QDesktopServices
        from chatdraw import to3d
        qa = app()
        with TemporaryDirectory() as d, mock.patch.object(QDesktopServices, "openUrl") as opened:
            src = Path(d) / "c.png"
            sheet = Image.new("RGB", (360, 160), "white")
            for i in range(3):
                sheet.paste(figure(), (i * 120, 0))
            sheet.save(src)
            dlg = to3d.To3DDialog(str(src))
            t0 = time.time()
            dlg.rig_button.click()
            self.assertLess(time.time() - t0, 1.0)              # 押した手は 1 秒以内に戻る（裏で作る）
            self.assertFalse(dlg.rig_button.isEnabled())       # 作っている間は押し直せない
            self.assertIn("作っています", dlg.status.text())
            for _ in range(6000):
                qa.processEvents()
                if dlg.rig_button.isEnabled():
                    break
                time.sleep(0.02)
            self.assertIn("作りました", dlg.status.text())
            self.assertTrue(Path(dlg.info["vrm"]).exists() and Path(dlg.info["glb"]).exists())
            self.assertTrue(Path(dlg.info["sheet"]).exists())
            self.assertTrue(opened.called)
            dlg.close()


    def test_chara_menu_entry_opens_3d(self):
        """キャラデザのメニューの「3D キャラを作る…」から、選んだ絵で 3D に進む画面が開く"""
        from PySide6.QtWidgets import QFileDialog
        from chatdraw.app import Window
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords, Studio
        app()
        with TemporaryDirectory() as d:
            src = Path(d) / "c.png"
            figure().save(src)
            w = Window(Studio(FakeWords(), FakePainter(), Path(d)))
            w.chara_menu.aboutToShow.emit()
            act = next(a for a in w.chara_menu.actions() if a.text() == "3D キャラを作る…")
            self.assertTrue(act.toolTip())
            with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(src), "")), \
                    mock.patch.object(w, "open_3d") as opened:
                w.canvas.layers.clear() if hasattr(w.canvas.layers, "clear") else None
                act.trigger()
            self.assertEqual(opened.call_args[0][0], str(src))
            w.close()


if __name__ == "__main__":
    unittest.main()
