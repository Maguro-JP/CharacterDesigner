import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import zukan  # noqa: E402


class Zukan(unittest.TestCase):
    def test_only_passed_images_grouped_by_style(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "src", Path(d) / "out"
            for animal, style, ok in (("cat", "01-flat", True), ("dog", "01-flat", True), ("fox", "01-flat", False),
                                      ("cat", "02-paint", True)):
                p = src / "2026-10-19" / animal / f"{style}-7.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (60, 40), "gray").save(p)
                if ok:
                    p.with_name(p.name + ".pass").touch()
            sys.argv = ["zukan.py", str(src), str(out)]
            with redirect_stdout(io.StringIO()) as buf:
                zukan.main()
            self.assertIn("'01-flat': 2", buf.getvalue())
            self.assertTrue((out / "zukan-01-flat-s123.jpg").exists())
            readme = (out / "README.md").read_text()
            self.assertIn("cat, dog", readme)
            self.assertNotIn("fox", readme)


if __name__ == "__main__":
    unittest.main()
