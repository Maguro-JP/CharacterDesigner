import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))


@unittest.skipUnless(importlib.util.find_spec("imageio_ffmpeg"), "imageio-ffmpeg が無い（sh tools/gen/setup.sh で入る）")
class VideoIO(unittest.TestCase):
    def test_write_then_read_keeps_frames_and_rate(self):
        from PIL import Image
        import imgproc
        cuts = [Image.new("RGBA", (64, 48), (i * 30, 0, 0, 255)) for i in range(5)]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "a.webm"
            imgproc.write_video(cuts, out, 10)
            frames, fps = imgproc.read_video(str(out))
        self.assertEqual(len(frames), 5)
        self.assertEqual(frames[0].size, (64, 48))
        self.assertAlmostEqual(fps, 10, delta=0.5)


if __name__ == "__main__":
    unittest.main()
