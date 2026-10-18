"""手の模型か読み込む部品が無い環境で、検品が例外の文字列ではなく「読めない」の印を返すことの試験。
部品（ai-edge-litert）が模型の取得と同じ分岐でしか入らず、模型が無いまま batch のどの絵にも ModuleNotFoundError が出た"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import hands  # noqa: E402


class Unavailable(unittest.TestCase):
    def test_missing_package(self):
        with mock.patch.dict(sys.modules, {"ai_edge_litert": None, "ai_edge_litert.interpreter": None}):
            with self.assertRaises(hands.Unavailable) as c:
                hands._litert()
        self.assertIn("ai-edge-litert", str(c.exception))

    def test_missing_model(self):
        with self.assertRaises(hands.Unavailable) as c:
            hands._model(Path("/nonexistent/hand_detector.tflite"))
        self.assertIn("hand_detector.tflite", str(c.exception))

    def test_setup_checks_package_apart_from_model(self):
        src = (Path(__file__).resolve().parents[1] / "tools" / "gen" / "setup.py").read_text(encoding="utf-8")
        self.assertIn('if not (LIB / "ai_edge_litert").exists():', src)


if __name__ == "__main__":
    unittest.main()
