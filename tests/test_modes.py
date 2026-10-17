"""描く仕事のモードの門。人物の設計が要るモードは、設計がそろうか人の参考資料があるまで始めない。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import bible  # noqa: E402
import modes  # noqa: E402


class ModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = bible.BIBLE
        bible.BIBLE = Path(self.tmp.name)
        bible.new_character("a", "A", "adult woman", "coat")
        bible.new_character("b", "B", "adult man", "coat")

    def tearDown(self):
        bible.BIBLE = self.old
        self.tmp.cleanup()

    def _ready(self, ident):
        c = bible.load("characters", ident)
        c.update(eyes={"tags": "x"}, expressions=[{"id": "neutral"}], images={"turnaround": "t", "expressions": "e"})
        bible.save("characters", c)

    def test_five_modes(self):
        self.assertEqual(set(modes.MODES), {"CharacterDesigner", "Illustrator", "Background", "Composite", "Ensemble"})

    def test_illustrator_needs_design_or_reference(self):
        self.assertFalse(modes.check("Illustrator", ["a"])["ok"])
        self._ready("a")
        self.assertTrue(modes.check("Illustrator", ["a"])["ok"])
        ref = Path(self.tmp.name) / "r.png"
        ref.write_bytes(b"x")
        self.assertTrue(modes.check("Illustrator", ["b"], str(ref))["ok"])

    def test_ensemble_needs_two_ready_characters(self):
        self._ready("a")
        self.assertFalse(modes.check("Ensemble", ["a"])["ok"])
        self.assertFalse(modes.check("Ensemble", ["a", "b"])["ok"])
        self._ready("b")
        self.assertTrue(modes.check("Ensemble", ["a", "b"])["ok"])

    def test_design_and_background_have_no_gate(self):
        self.assertTrue(modes.check("CharacterDesigner", ["a"])["ok"])
        self.assertTrue(modes.check("Background")["ok"])

    def test_plan_fills_character(self):
        p = modes.plan("CharacterDesigner", ["a"])
        self.assertTrue(any("turnaround a" in s["command"] for s in p["steps"]))
